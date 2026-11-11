"""NCAA tournament odds from the Bracket Matrix consensus field.

1. Parse the latest Bracket Matrix snapshot: each projected team's seed line, average seed
   and number of brackets that include it.
2. Build a bracket: teams ordered by seed line, then average seed, placed into four regions
   on an S-curve (the committee's method). A line with more than four teams sends its
   lowest-ranked teams into opening-round games (2027 format: 76 teams, 12 opening games;
   the same code handles 68).
3. Simulate it many times. Each simulation first draws every team's strength around its
   current rating, with a spread that grows with the time left before the tournament
   (ratings move during a season), then plays every game at a neutral site.

    python -m basketball.bracket
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date

import lxml.html
import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config

MATRIX = config.DATA_DIR / "bracketmatrix" / "latest.html"
ROUNDS = ["Opening", "R64", "R32", "Sweet 16", "Elite 8", "Final 4", "Final", "Champion"]
# Standard bracket order of seeds within a region
SEED_ORDER = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15]

# Bracket Matrix names that don't match ESPN's directly
ALIASES = {
    "connecticut": "uconn", "mississippi": "ole miss", "central florida": "ucf",
    "north carolina state": "nc state", "st. mary's (ca)": "saint mary's", "saint mary's (ca)": "saint mary's",
    "southern california": "usc", "brigham young": "byu", "louisiana state": "lsu", "virginia commonwealth": "vcu",
    "texas christian": "tcu", "southern methodist": "smu", "nevada-las vegas": "unlv", "miami (fl)": "miami",
    "miami (fla.)": "miami", "miami (fla)": "miami", "mcneese state": "mcneese", "st. thomas (mn)": "st. thomas",
    "texas a&m-corpus christi": "texas a&m-cc", "mount st. mary's": "mount st. mary's", "loyola (il)": "loyola chicago",
    "loyola chicago": "loyola chicago", "nc-wilmington": "unc wilmington", "unc-wilmington": "unc wilmington", "college of charleston": "charleston",
    "florida atlantic": "fau", "florida gulf coast": "fgcu", "california baptist": "cal baptist", "massachusetts": "umass",
    "pennsylvania": "penn", "southern illinois-edwardsville": "siu edwardsville", "siu-edwardsville": "siu edwardsville",
    "texas-arlington": "ut arlington", "texas-san antonio": "utsa", "texas-el paso": "utep", "alabama-birmingham": "uab",
    "illinois-chicago": "uic", "wisconsin-milwaukee": "milwaukee", "wisconsin-green bay": "green bay",
    "arkansas-little rock": "little rock", "arkansas-pine bluff": "arkansas-pine bluff", "md.-eastern shore": "maryland eastern shore",
    "louisiana-lafayette": "louisiana", "louisiana-monroe": "ul monroe", "tennessee-martin": "ut martin",
    "southeast missouri state": "southeast missouri st", "fairleigh dickinson": "fdu", "saint francis (pa)": "saint francis",
    "st. francis (pa)": "saint francis", "detroit": "detroit mercy", "grambling state": "grambling", "seattle": "seattle u",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()
    s = s.replace("&amp;", "&").replace("’", "'")
    s = re.sub(r"\bstate\b", "st", s)
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bst\.", "st", s)
    s = s.replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9&' -]", "", s)).strip()


def parse_matrix(path=MATRIX) -> tuple[pd.DataFrame, dict]:
    doc = lxml.html.fromstring(path.read_bytes())
    rows = [[re.sub(r"\s+", " ", td.text_content()).strip() for td in tr.iter("td")] for tr in doc.iter("tr")]
    rows = [r for r in rows if any(r)]
    field = []
    for r in rows:
        if len(r) > 4 and r[0].isdigit() and re.fullmatch(r"\d+(\.\d+)?", r[3] or ""):
            field.append({"seed": int(r[0]), "team": r[1], "conf": r[2], "avg_seed": float(r[3]),
                          "brackets": int(r[4]) if r[4].isdigit() else None})
    # Header: label and the dates of contributing brackets
    label = next((c for r in rows[:3] for c in r if "MATRIX" in c.upper()), "")
    dates = [c for r in rows[:3] for c in r if re.fullmatch(r"\d{1,2}/\d{1,2}", c)]
    return pd.DataFrame(field), {"label": label.title(), "latest_bracket": max(dates, key=lambda d: tuple(map(int, d.split("/"))), default=None),
                                 "n_brackets": max((f["brackets"] or 0 for f in field), default=0)}


def match_teams(field: pd.DataFrame, teams: pd.DataFrame) -> pd.Series:
    """ESPN team_id for each Bracket Matrix name (NaN if not found)."""
    t = teams.copy()
    t["n_short"] = t["short"].map(_norm)
    t["n_name"] = t["name"].map(_norm)
    by_short = dict(zip(t.n_short, t.team_id))
    out = []
    for name in field.team:
        key = _norm(ALIASES.get(name.lower(), name))
        tid = by_short.get(key)
        if tid is None:  # "Duke" -> "Duke Blue Devils": display name starts with the school name
            cand = t[t.n_name.str.startswith(key + " ")]
            if len(cand) == 1:
                tid = cand.team_id.iat[0]
            elif len(cand) > 1:  # prefer the shortest remaining mascot
                tid = cand.loc[cand.n_name.str.len().idxmin(), "team_id"]
        out.append(tid)
    return pd.Series(out, index=field.index)


def build_bracket(field: pd.DataFrame) -> list[list]:
    """Four regions, each a list of 16 slots in SEED_ORDER; a slot is [team] or [team, team] (opening game)."""
    f = field.sort_values(["seed", "avg_seed"]).reset_index(drop=True)
    regions = [{s: [] for s in range(1, 17)} for _ in range(4)]
    for seed, line in f.groupby("seed", sort=True):
        line = list(line.team_id)
        k = max(len(line) - 4, 0)            # number of opening games on this line
        direct, playin = line[: 4 - k], line[4 - k:]
        slots = [[t] for t in direct] + [[playin[2 * i], playin[2 * i + 1]] for i in range(k)]
        order = [0, 1, 2, 3] if seed % 2 else [3, 2, 1, 0]  # S-curve snake
        for r, slot in zip(order, slots):
            regions[r][seed] = slot
    return [[regions[r][s] for s in SEED_ORDER] for r in range(4)]


def simulate(bracket: list[list], meta: dict, strength_sd: dict, n_sims: int = 20000, seed: int = 7,
             seed_of: dict | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ids = sorted({t for reg in bracket for slot in reg for t in slot})
    pos = {t: i for i, t in enumerate(ids)}
    m = meta["model"]
    mpos = {t: i for i, t in enumerate(m["ids"])}
    known = np.array([t in mpos for t in ids])
    ix = np.array([mpos.get(t, 0) for t in ids])
    O, D, T = np.array(m["O"])[ix], np.array(m["D"])[ix], np.array(m["T"])[ix]
    # Teams we couldn't match play at the average strength of their seed line
    seed_of = seed_of or {}
    for i, t in enumerate(ids):
        if not known[i]:
            same = [j for j, u in enumerate(ids) if known[j] and seed_of.get(u) == seed_of.get(t)]
            same = same or list(np.flatnonzero(known))
            O[i], D[i], T[i] = O[same].mean(), D[same].mean(), T[same].mean()
    sd = np.array([strength_sd.get(t, strength_sd.get("*", 6.0)) for t in ids])
    shift = rng.normal(0, 1, (n_sims, len(ids))) * sd      # each simulation's true-strength draw
    Os, Ds = O + shift / 2, D - shift / 2
    sims = np.arange(n_sims)
    reach = np.zeros((len(ids), len(ROUNDS)))

    def play(a, b):
        """a, b: arrays of team positions per simulation; neutral site."""
        poss = meta["tau"] + T[a] + T[b]
        eff = (Os[sims, a] + Ds[sims, b]) - (Os[sims, b] + Ds[sims, a])
        pa = norm.cdf(poss * eff / 100 / meta["sd"])
        return np.where(rng.random(n_sims) < pa, a, b)

    champs = []
    for reg in bracket:
        alive = []
        for slot in reg:
            if len(slot) == 1:
                w = np.full(n_sims, pos[slot[0]])
            else:
                a, b = pos[slot[0]], pos[slot[1]]
                reach[[a, b], 0] = n_sims
                w = play(np.full(n_sims, a), np.full(n_sims, b))
            alive.append(w)
        for w in alive:
            np.add.at(reach[:, 1], w, 1)
        rnd = 2
        while len(alive) > 1:
            alive = [play(alive[i], alive[i + 1]) for i in range(0, len(alive), 2)]
            for w in alive:
                np.add.at(reach[:, rnd], w, 1)
            rnd += 1
        champs.append(alive[0])
    # Final Four pairs region 1 with 4 and 2 with 3, keeping the top two overall seeds apart
    f1, f2 = play(champs[0], champs[3]), play(champs[1], champs[2])
    for w in (f1, f2):
        np.add.at(reach[:, 6], w, 1)
    np.add.at(reach[:, 7], play(f1, f2), 1)
    reach[:, 0] = n_sims  # everyone in the field starts in the opening round or with a bye into the 64
    return pd.DataFrame(reach / n_sims, index=ids, columns=ROUNDS)


def strength_sd_for(teams_json: list[dict], days_left: int) -> dict:
    """How far each team's true tournament-day strength may be from today's rating."""
    sd = float(np.sqrt(config.BRACKET_FINAL_SD ** 2 + config.BRACKET_DRIFT_PER_100_DAYS ** 2 * max(days_left, 0) / 100))
    return {"*": sd} | {t["id"]: sd for t in teams_json}


def run(site_dir=None, n_sims: int = 20000) -> dict | None:
    site_dir = site_dir or config.SITE_DATA_DIR
    if not MATRIX.exists():
        return None
    field, info = parse_matrix()
    teams_json = json.loads((site_dir / "teams.json").read_text())
    meta = json.loads((site_dir / "meta.json").read_text())
    tm = pd.DataFrame(teams_json).rename(columns={"id": "team_id"})
    field["team_id"] = match_teams(field, tm)
    missing = field[field.team_id.isna()].team.tolist()
    if missing:
        print(f"bracket: no ESPN match for {missing}")
    field["team_id"] = field.team_id.where(field.team_id.notna(), "BM:" + field.team)  # keep unmatched in the bracket
    bracket = build_bracket(field)
    season = config.season_for(date.today())
    sunday = config.selection_sunday(season)
    days_left = (sunday - date.today()).days
    odds = simulate(bracket, meta, strength_sd_for(teams_json, days_left), n_sims,
                    seed_of=dict(zip(field.team_id, field.seed)))
    region_of, slot_of = {}, {}
    for r, reg in enumerate(bracket):
        for s, slot in zip(SEED_ORDER, reg):
            for t in slot:
                region_of[t], slot_of[t] = r, s
    f = field.set_index("team_id")
    rows = []
    for tid, o in odds.iterrows():
        rows.append({"id": tid, "team": f.at[tid, "team"], "seed": int(f.at[tid, "seed"]), "avg_seed": f.at[tid, "avg_seed"],
                     "brackets": None if pd.isna(f.at[tid, "brackets"]) else int(f.at[tid, "brackets"]),
                     "region": region_of[tid] + 1, "opening": any(tid in sl and len(sl) == 2 for reg in bracket for sl in reg),
                     "odds": [round(float(x), 4) for x in o.to_numpy()]})
    out = {"source": "Bracket Matrix", "url": "http://www.bracketmatrix.com/", "label": info["label"],
           "latest_bracket": info["latest_bracket"], "n_brackets": info["n_brackets"], "field_size": len(field),
           "rounds": ROUNDS, "sims": n_sims, "days_to_selection": days_left, "unmatched": missing,
           "regions": [[[t for t in slot] for slot in reg] for reg in bracket], "teams": sorted(rows, key=lambda r: -r["odds"][-1])}
    (site_dir / "bracket.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"bracket: {len(field)} teams simulated {n_sims:,} times; favorite "
          f"{out['teams'][0]['team']} {out['teams'][0]['odds'][-1]:.1%}")
    return out


if __name__ == "__main__":
    run()
