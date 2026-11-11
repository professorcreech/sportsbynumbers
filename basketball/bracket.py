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


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * np.arcsin(np.sqrt(a))


def team_homes() -> dict:
    p = config.DATA_DIR / "history" / "team_homes.csv"
    if not p.exists():
        return {}
    h = pd.read_csv(p, dtype={"team_id": str}).dropna(subset=["lat"])
    return {t: (la, lo) for t, la, lo in zip(h.team_id, h.lat, h.lon)}


def home_arenas() -> dict:
    """Each school's most-used home arena in the latest season on file."""
    files = sorted((config.DATA_DIR / "history").glob("scores_*.csv.gz"))
    if not files:
        return {}
    s = pd.read_csv(files[-1], dtype={"home_id": str}, usecols=["home_id", "neutral", "venue"])
    s = s[~s.neutral.astype(bool)].dropna(subset=["venue"])
    top = s.groupby(["home_id", "venue"]).size().rename("n").reset_index().sort_values("n").drop_duplicates("home_id", keep="last")
    return {t: _arena(v) for t, v in zip(top.home_id, top.venue)}


def _arena(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v).lower())


# Bracket positions (in SEED_ORDER) that make up each first-weekend pod, keyed by the pod's top seed
PODS = {1: range(0, 4), 4: range(4, 8), 3: range(8, 12), 2: range(12, 16)}


def build_bracket(field: pd.DataFrame, sites: dict | None = None, homes: dict | None = None,
                  arenas: dict | None = None) -> dict:
    """Place the field the way the committee does.

    Seed lines 1-4 pick, in S-curve order, the nearest region and first-weekend site still open
    (each site hosts two pods). Lines 5-16 snake across regions for balance. Lines with more
    than four teams send their lowest-ranked teams into opening-round games.
    Returns regions (4 x 16 slots in SEED_ORDER; a slot is [team] or [team, team]), region and
    pod sites, opening-game sites, and the Final Four pairing."""
    homes = homes or {}
    f = field.sort_values(["seed", "avg_seed"]).reset_index(drop=True)
    reg_names = list(sites["regional"]) if sites else ["Region 1", "Region 2", "Region 3", "Region 4"]
    regions = [{s: None for s in range(1, 17)} for _ in range(4)]
    pod_site = [{} for _ in range(4)]
    site_load = {k: 0 for k in (sites or {}).get("first", {})}
    top_overall = []

    def dist(team, coord):
        h = homes.get(team)
        return haversine(h[0], h[1], coord[0], coord[1]) if h and coord else 0.0

    for seed, line in f.groupby("seed", sort=True):
        line = list(line.team_id)
        k = max(len(line) - 4, 0)
        direct, playin = line[: 4 - k], line[4 - k:]
        slots = [[t] for t in direct] + [[playin[2 * i], playin[2 * i + 1]] for i in range(k)]
        if seed <= 4 and sites and homes:
            free = [0, 1, 2, 3]
            for slot in slots:
                t = slot[0]
                r = min(free, key=lambda r: dist(t, sites["regional"][reg_names[r]]))
                free.remove(r)
                regions[r][seed] = slot
                own = (arenas or {}).get(t)
                def home_floor(x):
                    v = _arena(sites.get("venues", {}).get(x, ""))
                    return bool(own and v and (v in own or own in v))
                allowed = [x for x in site_load if site_load[x] < 2 and not home_floor(x)]
                site = min(allowed or [x for x in site_load if site_load[x] < 2], key=lambda x: dist(t, sites["first"][x]))
                site_load[site] += 1
                pod_site[r][seed] = site
                if seed == 1:
                    top_overall.append(r)
        else:
            order = [0, 1, 2, 3] if seed % 2 else [3, 2, 1, 0]  # S-curve snake
            for r, slot in zip(order, slots):
                regions[r][seed] = slot
            if seed == 1:
                top_overall = order[:]
    # Opening games go to the nearer opening site, at most half the games at each
    opening = {}
    if sites:
        cap = {x: 0 for x in sites["opening"]}
        games = [slot for reg in regions for slot in reg.values() if slot and len(slot) == 2]
        per_site = int(np.ceil(len(games) / max(len(cap), 1)))
        for slot in games:
            options = [x for x in cap if cap[x] < per_site] or list(cap)
            x = min(options, key=lambda x: dist(slot[0], sites["opening"][x]) + dist(slot[1], sites["opening"][x]))
            cap[x] += 1
            opening[tuple(slot)] = x
    # Final Four: region of the No. 1 overall seed meets the region of the No. 4 overall seed
    semis = [(top_overall[0], top_overall[3]), (top_overall[1], top_overall[2])] if len(top_overall) == 4 else [(0, 3), (1, 2)]
    return {"regions": [[regions[r][s] for s in SEED_ORDER] for r in range(4)], "region_names": reg_names,
            "pod_site": pod_site, "opening_site": opening, "semis": semis}


def simulate(br: dict, meta: dict, strength_sd: dict, n_sims: int = 20000, seed: int = 7,
             seed_of: dict | None = None, sites: dict | None = None, homes: dict | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    bracket = br["regions"]
    ids = sorted({t for reg in bracket for slot in reg for t in slot})
    pos = {t: i for i, t in enumerate(ids)}
    m = meta["model"]
    mpos = {t: i for i, t in enumerate(m["ids"])}
    known = np.array([t in mpos for t in ids])
    ix = np.array([mpos.get(t, 0) for t in ids])
    O, D, T = np.array(m["O"])[ix], np.array(m["D"])[ix], np.array(m["T"])[ix]
    seed_of = seed_of or {}
    for i, t in enumerate(ids):  # teams we couldn't match play at their seed line's average strength
        if not known[i]:
            same = [j for j, u in enumerate(ids) if known[j] and seed_of.get(u) == seed_of.get(t)] or list(np.flatnonzero(known))
            O[i], D[i], T[i] = O[same].mean(), D[same].mean(), T[same].mean()
    sd = np.array([strength_sd.get(t, strength_sd.get("*", 6.0)) for t in ids])
    shift = rng.normal(0, 1, (n_sims, len(ids))) * sd
    Os, Ds = O + shift / 2, D - shift / 2
    sims = np.arange(n_sims)
    reach = np.zeros((len(ids), len(ROUNDS)))

    # log(1 + miles) from each team's campus to each site; unknown homes count as a typical trip
    homes = homes or {}
    site_xy = {}
    for group in ("opening", "first", "regional", "final"):
        site_xy.update((sites or {}).get(group, {}))
    site_ix = {name: j for j, name in enumerate(site_xy)}
    logd = np.full((len(ids), max(len(site_xy), 1)), np.log1p(600.0))
    for i, t in enumerate(ids):
        if t in homes:
            for name, j in site_ix.items():
                logd[i, j] = np.log1p(haversine(homes[t][0], homes[t][1], *site_xy[name]))
    k_dist = config.TOURNEY_LOG_DISTANCE if site_xy else 0.0

    def play(a, b, site=None):
        poss = meta["tau"] + T[a] + T[b]
        eff = (Os[sims, a] + Ds[sims, b]) - (Os[sims, b] + Ds[sims, a])
        margin = poss * eff / 100
        if site in site_ix:
            j = site_ix[site]
            margin = margin + k_dist * (logd[a, j] - logd[b, j])
        return np.where(rng.random(n_sims) < norm.cdf(margin / meta["sd"]), a, b)

    final_site = next(iter((sites or {}).get("final", {})), None)
    champs = []
    for r, reg in enumerate(bracket):
        alive = []
        for slot in reg:
            if len(slot) == 1:
                w = np.full(n_sims, pos[slot[0]])
            else:
                a, b = pos[slot[0]], pos[slot[1]]
                w = play(np.full(n_sims, a), np.full(n_sims, b), br["opening_site"].get(tuple(slot)))
            alive.append(w)
        for w in alive:
            np.add.at(reach[:, 1], w, 1)
        # Which first-weekend site each bracket position plays at
        pos_site = {}
        for top, rng_ in PODS.items():
            for p_ in rng_:
                pos_site[p_] = br["pod_site"][r].get(top)
        region_site = br["region_names"][r]
        rnd, width = 2, 1
        while len(alive) > 1:
            nxt = []
            for i in range(0, len(alive), 2):
                site = pos_site.get(i * width) if rnd <= 3 else region_site
                nxt.append(play(alive[i], alive[i + 1], site))
            alive, width = nxt, width * 2
            for w in alive:
                np.add.at(reach[:, rnd], w, 1)
            rnd += 1
        champs.append(alive[0])
    (r1, r4), (r2, r3) = br["semis"]
    f1, f2 = play(champs[r1], champs[r4], final_site), play(champs[r2], champs[r3], final_site)
    for w in (f1, f2):
        np.add.at(reach[:, 6], w, 1)
    np.add.at(reach[:, 7], play(f1, f2, final_site), 1)
    reach[:, 0] = n_sims
    return pd.DataFrame(reach / n_sims, index=ids, columns=ROUNDS)


def strength_sd_for(teams_json: list[dict], days_left: int) -> dict:
    """How far each team's true tournament-day strength may be from today's rating."""
    sd = float(np.sqrt(config.BRACKET_FINAL_SD ** 2 + config.BRACKET_DRIFT_PER_100_DAYS ** 2 * max(days_left, 0) / 100))
    return {"*": sd} | {t["id"]: sd for t in teams_json}


def tournament_record() -> dict:
    """Context only (it doesn't move the odds): each program's results against expectations in
    its last four tournaments, from tests/tournament_factors.py."""
    p = config.DATA_DIR / "history" / "tournament_record.csv"
    if not p.exists():
        return {}
    r = pd.read_csv(p, dtype={"team_id": str})
    return {t: {"games": int(g), "wins": int(w), "vs_exp": round(float(v), 1)} for t, g, w, v in zip(r.team_id, r.games, r.wins, r.vs_exp)}


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
    field["team_id"] = field.team_id.where(field.team_id.notna(), "BM:" + field.team)
    season = config.season_for(date.today())
    sites = config.TOURNEY_SITES.get(season)
    homes = team_homes()
    br = build_bracket(field, sites, homes, home_arenas())
    days_left = (config.selection_sunday(season) - date.today()).days
    odds = simulate(br, meta, strength_sd_for(teams_json, days_left), n_sims,
                    seed_of=dict(zip(field.team_id, field.seed)), sites=sites, homes=homes)
    region_of, site_of = {}, {}
    for r, reg in enumerate(br["regions"]):
        for i, slot in enumerate(reg):
            top = next(k for k, v in PODS.items() if i in v)
            for t in slot:
                region_of[t] = r
                site_of[t] = br["pod_site"][r].get(top)
    rec = tournament_record()
    f = field.set_index("team_id")
    rows = []
    for tid, o in odds.iterrows():
        h = homes.get(tid)
        fs = (sites or {}).get("first", {}).get(site_of.get(tid))
        rows.append({"id": tid, "team": f.at[tid, "team"], "seed": int(f.at[tid, "seed"]), "avg_seed": f.at[tid, "avg_seed"],
                     "brackets": None if pd.isna(f.at[tid, "brackets"]) else int(f.at[tid, "brackets"]),
                     "region": region_of[tid] + 1, "site": site_of.get(tid),
                     "miles": None if not (h and fs) else int(round(haversine(h[0], h[1], *fs))),
                     "opening": any(tid in sl and len(sl) == 2 for reg in br["regions"] for sl in reg),
                     "record": rec.get(tid), "odds": [round(float(x), 4) for x in o.to_numpy()]})
    out = {"source": "Bracket Matrix", "url": "http://www.bracketmatrix.com/", "label": info["label"],
           "latest_bracket": info["latest_bracket"], "n_brackets": info["n_brackets"], "field_size": len(field),
           "rounds": ROUNDS, "sims": n_sims, "days_to_selection": days_left, "unmatched": missing,
           "region_names": br["region_names"], "distance_coef": config.TOURNEY_LOG_DISTANCE if sites else None,
           "teams": sorted(rows, key=lambda r: -r["odds"][-1])}
    (site_dir / "bracket.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"bracket: {len(field)} teams simulated {n_sims:,} times; favorite "
          f"{out['teams'][0]['team']} {out['teams'][0]['odds'][-1]:.1%}")
    return out


if __name__ == "__main__":
    run()
