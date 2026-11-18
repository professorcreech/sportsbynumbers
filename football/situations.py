"""Down-and-distance, score and fourth-down habits for every team, offense and defense.

Built from play-by-play. For each situation it measures how often a team passes, how often it succeeds
(gains half the yards to go on 1st down, 70% on 2nd, all of them on 3rd/4th), how often a play is explosive
(a run of 12+ yards or a pass of 16+), and on 3rd down how often it converts. The same measures are taken
for what each defense allows. Each rate is pulled toward the league rate in the same situation (a team has
only a few dozen plays in most of them) and last season's plays count at partial weight.

Not available from ESPN's play-by-play: formations, play-action, blitzes, coverage and personnel. Nothing
here claims to know them; sacks are the only pressure signal.

The play clock in these files is stale within a drive, so tempo is not measured.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

RUSH = {"Rush", "Rushing Touchdown", "Two Point Rush"}
PASS = {"Pass Reception", "Pass Incompletion", "Passing Touchdown", "Sack", "Interception", "Pass Interception Return",
        "Interception Return Touchdown", "Pass Completion", "Two Point Pass"}
PRIOR_SEASON_WEIGHT = 0.25 if config.IS_NFL else 0.5
K = 30.0          # pseudo-plays of league-average behavior
K_CONV = 20.0
K_FOURTH = 8.0

SITUATIONS = [
    ("d1", "1st down"), ("d2s", "2nd & short (1–3)"), ("d2m", "2nd & medium (4–6)"), ("d2l", "2nd & long (7+)"),
    ("d3s", "3rd & short (1–3)"), ("d3m", "3rd & medium (4–6)"), ("d3l", "3rd & long (7+)"),
    ("rz", "Red zone (inside the 20)"), ("gl", "Goal to go (inside the 5)"),
    ("chase", "Trailing by 9+, second half"), ("protect", "Leading by 9+, second half"),
]
FOURTH = [("short", "4th & 1–3, at the opponent’s 55 or closer"), ("mid", "4th & 4–7, at the opponent’s 45 or closer")]


def _prepare(plays: pd.DataFrame, games: pd.DataFrame, weight: float) -> pd.DataFrame:
    g = games[["game_id", "home_id", "away_id"]].drop_duplicates("game_id")
    p = plays.merge(g, on="game_id", how="inner")
    p["_ord"] = np.arange(len(p))
    p = p.sort_values(["game_id", "_ord"], kind="stable")
    after = p.home_score - p.away_score
    p["m_home"] = after.groupby(p.game_id).shift(1).fillna(0)      # score margin before the play
    is_home = p.offense == p.home_id
    p["margin"] = np.where(is_home, p.m_home, -p.m_home)            # from the offense's side
    p["defense"] = np.where(is_home, p.away_id, p.home_id)
    p["rush"] = p.type.isin(RUSH)
    p["pass_"] = p.type.isin(PASS)
    p["scrim"] = (p.rush | p.pass_) & p.down.between(1, 4)
    p["sack"] = p.type.eq("Sack")
    need = np.select([p.down == 1, p.down == 2], [0.5 * p.distance, 0.7 * p.distance], p.distance)
    p["success"] = p.yards >= need
    p["conv"] = p.yards >= p.distance
    p["expl"] = np.where(p.rush, p.yards >= 12, p.yards >= 16)
    p["w"] = weight
    return p


def _masks(s: pd.DataFrame) -> dict:
    d, dist = s.down, s.distance
    second_half = s.period >= 3
    return {
        "d1": d == 1,
        "d2s": (d == 2) & (dist <= 3), "d2m": (d == 2) & dist.between(4, 6), "d2l": (d == 2) & (dist >= 7),
        "d3s": (d == 3) & (dist <= 3), "d3m": (d == 3) & dist.between(4, 6), "d3l": (d == 3) & (dist >= 7),
        "rz": s.ytg <= 20, "gl": s.ytg <= 5,
        "chase": second_half & (s.margin <= -9), "protect": second_half & (s.margin >= 9),
    }


def _counts(p: pd.DataFrame) -> pd.DataFrame:
    """Weighted counts per team, role (offense, or the defense facing those plays) and situation."""
    s = p[p.scrim & p.distance.notna() & p.ytg.notna()]
    rows = []
    for key, mask in _masks(s).items():
        x = s[mask]
        w = x.w
        cols = {"n": w, "pass": x.pass_ * w, "succ": x.success * w, "expl": x.expl * w, "conv": ((x.down >= 3) & x.conv) * w,
                "conv_n": ((x.down >= 3) * w)}
        base = pd.DataFrame(cols)
        for role, team in (("off", x.offense), ("def", x.defense)):
            rows.append(base.assign(team=team.to_numpy(), role=role, sit=key))
    return pd.concat(rows).groupby(["team", "role", "sit"], as_index=False).sum(numeric_only=True)


def _fourth_counts(p: pd.DataFrame) -> pd.DataFrame:
    f = p[(p.down == 4) & p.distance.notna() & p.ytg.notna()].copy()
    f["kind"] = np.select([f.scrim, f.type.eq("Punt"), f.type.str.startswith("Field Goal") | f.type.str.startswith("Blocked Field Goal")],
                          ["go", "punt", "fg"], "")
    f = f[f.kind != ""]
    short = (f.distance <= 3) & f.ytg.between(3, 55)
    mid = f.distance.between(4, 7) & (f.ytg <= 45)
    rows = []
    for key, m in (("short", short), ("mid", mid)):
        x = f[m]
        rows.append(pd.DataFrame({"team": x.offense, "sit": key, "n": x.w, "go": (x.kind == "go") * x.w,
                                  "made": ((x.kind == "go") & x.conv) * x.w}))
    return pd.concat(rows).groupby(["team", "sit"], as_index=False).sum(numeric_only=True)


def build(plays: pd.DataFrame | None, games: pd.DataFrame, plays_prev: pd.DataFrame | None = None,
          games_prev: pd.DataFrame | None = None, teams_in: set | None = None) -> dict | None:
    if plays is None or not len(plays) or not len(games):
        return None
    parts = [(plays, games, 1.0)]
    if plays_prev is not None and len(plays_prev) and games_prev is not None and len(games_prev):
        parts.append((plays_prev, games_prev, PRIOR_SEASON_WEIGHT))
    counts, fourth = [], []
    for pl, gm, w in parts:
        if teams_in:   # only games between rated teams, so the league baseline is the league being scouted
            gm = gm[gm.home_id.isin(teams_in) & gm.away_id.isin(teams_in)]
        pp = _prepare(pl, gm, w)
        counts.append(_counts(pp))
        fourth.append(_fourth_counts(pp))
    c = pd.concat(counts).groupby(["team", "role", "sit"], as_index=False).sum(numeric_only=True)
    f4 = pd.concat(fourth).groupby(["team", "sit"], as_index=False).sum(numeric_only=True)

    league = {}
    for sit, grp in c[c.role == "off"].groupby("sit"):
        t = grp.sum(numeric_only=True)
        league[sit] = {"n": float(t.n), "pass": t["pass"] / t.n, "succ": t.succ / t.n, "expl": t.expl / t.n,
                       "conv": t.conv / t.conv_n if (t.conv_n > 0 and sit.startswith("d3")) else None}
    lg4 = {}
    for sit, grp in f4.groupby("sit"):
        t = grp.sum(numeric_only=True)
        lg4[sit] = {"go": t.go / max(t.n, 1e-9), "made": t.made / max(t.go, 1e-9), "n": float(t.n)}

    def shrink(num, den, base, k):
        return (num + k * base) / (den + k)

    teams = {}
    idx = c.set_index(["team", "role", "sit"])
    ids = sorted(set(c.team) & (teams_in or set(c.team)))
    for t in ids:
        d = {}
        for sit, _ in SITUATIONS:
            L = league.get(sit)
            if not L:
                continue
            o = idx.loc[(t, "off", sit)] if (t, "off", sit) in idx.index else None
            e = idx.loc[(t, "def", sit)] if (t, "def", sit) in idx.index else None
            n_o, n_d = (o.n if o is not None else 0.0), (e.n if e is not None else 0.0)
            row = {"n": round(float(n_o), 1),
                   "pass": shrink(o["pass"] if o is not None else 0, n_o, L["pass"], K),
                   "succ": shrink(o.succ if o is not None else 0, n_o, L["succ"], K),
                   "expl": shrink(o.expl if o is not None else 0, n_o, L["expl"], K),
                   "d_n": round(float(n_d), 1),
                   "d_succ": shrink(e.succ if e is not None else 0, n_d, L["succ"], K),
                   "d_expl": shrink(e.expl if e is not None else 0, n_d, L["expl"], K)}
            if L["conv"] is not None and sit.startswith("d3"):
                row["conv"] = shrink(o.conv if o is not None else 0, o.conv_n if o is not None else 0, L["conv"], K_CONV)
                row["d_conv"] = shrink(e.conv if e is not None else 0, e.conv_n if e is not None else 0, L["conv"], K_CONV)
            d[sit] = {k: (round(float(v), 3) if isinstance(v, (float, np.floating)) else v) for k, v in row.items()}
        fo = {}
        for sit, _ in FOURTH:
            L = lg4.get(sit)
            r = f4[(f4.team == t) & (f4.sit == sit)]
            n = float(r.n.iloc[0]) if len(r) else 0.0
            go = float(r.go.iloc[0]) if len(r) else 0.0
            if L:
                fo[sit] = {"n": round(n, 1), "go": round(shrink(go, n, L["go"], K_FOURTH), 3)}
        d["fourth"] = fo
        teams[t] = d
    out_league = {k: {a: (None if b is None else round(float(b), 3)) for a, b in v.items()} for k, v in league.items()}
    out_l4 = {k: {a: round(float(b), 3) for a, b in v.items()} for k, v in lg4.items()}
    return {"situations": SITUATIONS, "fourth": FOURTH, "league": out_league, "league_fourth": out_l4, "teams": teams}
