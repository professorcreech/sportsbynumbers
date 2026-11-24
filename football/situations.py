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


# ---- Play-call tendencies by down (run/pass rate by field position and yards to go; direction where the feed has it)
TEND = [
    ("t1a", "1st down, backed up (own 1–10)"), ("t1b", "1st down, own territory (own 11–39)"),
    ("t1c", "1st down, midfield (40–60)"), ("t1d", "1st down, opponent territory (opp 21–39)"),
    ("t1e", "1st down, red zone (inside the 20)"),
    ("t2s", "2nd & short (1–3)"), ("t2m", "2nd & medium (4–6)"), ("t2l", "2nd & long (7+)"),
    ("t3a", "3rd & 1"), ("t3b", "3rd & 2–3"), ("t3c", "3rd & 4–6"), ("t3d", "3rd & 7–10"), ("t3e", "3rd & 11+"),
]
K_T = 25.0
FOURTH_T = [("f1", "4th & 1"), ("f2", "4th & 2–3"), ("f3", "4th & 4–7"), ("f4", "4th & 8+")]
ZONES = [("own", "in own territory (own 49 or deeper)"), ("mid", "between midfield and the opponent’s 36"), ("fg", "inside the opponent’s 35")]


def _tmasks(s: pd.DataFrame) -> dict:
    d, dist, y = s.down, s.distance, s.ytg
    return {
        "t1a": (d == 1) & (y >= 90), "t1b": (d == 1) & y.between(61, 89), "t1c": (d == 1) & y.between(40, 60),
        "t1d": (d == 1) & y.between(21, 39), "t1e": (d == 1) & (y <= 20),
        "t2s": (d == 2) & (dist <= 3), "t2m": (d == 2) & dist.between(4, 6), "t2l": (d == 2) & (dist >= 7),
        "t3a": (d == 3) & (dist <= 1), "t3b": (d == 3) & dist.between(2, 3), "t3c": (d == 3) & dist.between(4, 6),
        "t3d": (d == 3) & dist.between(7, 10), "t3e": (d == 3) & (dist >= 11),
    }


def _tend_counts(p: pd.DataFrame) -> pd.DataFrame:
    s = p[p.scrim & p.distance.notna() & p.ytg.notna()]
    rows = []
    for key, mask in _tmasks(s).items():
        x = s[mask]
        base = pd.DataFrame({"n": x.w, "pass": x.pass_ * x.w, "succ": x.success * x.w, "yds": x.yards.clip(-10, 40) * x.w})
        for role, team in (("off", x.offense), ("def", x.defense)):
            rows.append(base.assign(team=team.to_numpy(), role=role, sit=key))
    return pd.concat(rows).groupby(["team", "role", "sit"], as_index=False).sum(numeric_only=True)


def _fourth_t_counts(p: pd.DataFrame) -> pd.DataFrame:
    f = p[(p.down == 4) & p.distance.notna() & p.ytg.notna()].copy()
    f["kind"] = np.select([f.scrim, f.type.eq("Punt"), f.type.str.startswith("Field Goal") | f.type.str.startswith("Blocked Field Goal")],
                          ["go", "punt", "fg"], "")
    f = f[f.kind != ""]
    f["zone"] = np.select([f.ytg >= 50, f.ytg >= 36], ["own", "mid"], "fg")
    f["band"] = np.select([f.distance <= 1, f.distance <= 3, f.distance <= 7], ["f1", "f2", "f3"], "f4")
    out = f.groupby(["offense", "band", "zone"]).apply(
        lambda g: pd.Series({"n": g.w.sum(), "go": (g.w * (g.kind == "go")).sum(), "punt": (g.w * (g.kind == "punt")).sum(),
                             "fg": (g.w * (g.kind == "fg")).sum()}), include_groups=False).reset_index()
    return out.rename(columns={"offense": "team"})


def _dir_counts(p: pd.DataFrame) -> pd.DataFrame:
    """Direction and depth shares among plays whose text carried them (mostly NFL)."""
    for c in ("rdir", "rgap", "pdepth", "pdir", "gun"):
        if c not in p:
            p[c] = "" if c != "gun" else False
    for c in ("rdir", "rgap", "pdepth", "pdir"):
        p[c] = p[c].fillna("")
    s = p[p.scrim & p.distance.notna()]
    r = s[s.rush & (s.rdir != "")]
    q = s[s.pass_ & ~s.sack & (s.pdir != "")]
    rows = []
    for ctx, rm, qm in (("all", r.distance >= 0, q.distance >= 0), ("short", r.distance <= 3, q.distance <= 3),
                        ("late", (r.down >= 3), (q.down >= 3))):
        rr, qq = r[rm], q[qm]
        rows.append(pd.DataFrame({"team": rr.offense, "ctx": ctx, "k": "r_" + rr.rdir, "w": rr.w}))
        rows.append(pd.DataFrame({"team": rr.offense, "ctx": ctx, "k": "g_" + rr.rgap, "w": rr.w}))
        rows.append(pd.DataFrame({"team": qq.offense, "ctx": ctx, "k": "p_" + qq.pdir, "w": qq.w}))
        rows.append(pd.DataFrame({"team": qq.offense, "ctx": ctx, "k": "d_" + qq.pdepth.replace("", "unk"), "w": qq.w}))
        rows.append(pd.DataFrame({"team": rr.offense, "ctx": ctx, "k": "r_n", "w": rr.w}))
        rows.append(pd.DataFrame({"team": qq.offense, "ctx": ctx, "k": "p_n", "w": qq.w}))
    return pd.concat(rows).groupby(["team", "ctx", "k"], as_index=False).w.sum()


def build(plays: pd.DataFrame | None, games: pd.DataFrame, plays_prev: pd.DataFrame | None = None,
          games_prev: pd.DataFrame | None = None, teams_in: set | None = None) -> dict | None:
    if plays is None or not len(plays) or not len(games):
        return None
    parts = [(plays, games, 1.0)]
    if plays_prev is not None and len(plays_prev) and games_prev is not None and len(games_prev):
        parts.append((plays_prev, games_prev, PRIOR_SEASON_WEIGHT))
    counts, fourth, tcs, f4t, dcs = [], [], [], [], []
    for pl, gm, w in parts:
        if teams_in:   # only games between rated teams, so the league baseline is the league being scouted
            gm = gm[gm.home_id.isin(teams_in) & gm.away_id.isin(teams_in)]
        pp = _prepare(pl, gm, w)
        counts.append(_counts(pp))
        fourth.append(_fourth_counts(pp))
        tcs.append(_tend_counts(pp)); f4t.append(_fourth_t_counts(pp)); dcs.append(_dir_counts(pp))
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


    tc = pd.concat(tcs).groupby(["team", "role", "sit"], as_index=False).sum(numeric_only=True)
    tl = {}
    for sit, grp in tc[tc.role == "off"].groupby("sit"):
        a = grp.sum(numeric_only=True)
        tl[sit] = {"pass": a["pass"] / a.n, "succ": a.succ / a.n, "yds": a.yds / a.n}
    tidx = tc.set_index(["team", "role", "sit"])
    ft = pd.concat(f4t).groupby(["team", "band", "zone"], as_index=False).sum(numeric_only=True)
    fl = {}
    for (b, z), grp in ft.groupby(["band", "zone"]):
        a = grp.sum(numeric_only=True)
        fl[b + z] = {"go": a.go / a.n, "punt": a.punt / a.n, "fg": a.fg / a.n, "n": float(a.n)}
    dc = pd.concat(dcs).groupby(["team", "ctx", "k"], as_index=False).w.sum()
    didx = dc.set_index(["team", "ctx", "k"]).w
    dleague = dc.groupby(["ctx", "k"]).w.sum()

    def shr(num, den, base, k):
        return (num + k * base) / (den + k)

    def tend_for(t):
        out = {}
        for sit, _ in TEND:
            L = tl.get(sit)
            if not L:
                continue
            o = tidx.loc[(t, "off", sit)] if (t, "off", sit) in tidx.index else None
            e = tidx.loc[(t, "def", sit)] if (t, "def", sit) in tidx.index else None
            n, nd = (float(o.n) if o is not None else 0.0), (float(e.n) if e is not None else 0.0)
            out[sit] = {"n": round(n), "pass": round(float(shr(o["pass"] if o is not None else 0, n, L["pass"], K_T)), 3),
                        "succ": round(float(shr(o.succ if o is not None else 0, n, L["succ"], K_T)), 3),
                        "yds": round(float(shr(o.yds if o is not None else 0, n, L["yds"], K_T)), 2),
                        "d_n": round(nd), "d_pass": round(float(shr(e["pass"] if e is not None else 0, nd, L["pass"], K_T)), 3)}
        f = {}
        for b, _ in FOURTH_T:
            for z, _ in ZONES:
                key = b + z
                L = fl.get(key)
                r = ft[(ft.team == t) & (ft.band == b) & (ft.zone == z)]
                n = float(r.n.iloc[0]) if len(r) else 0.0
                if L and n > 0:
                    g = lambda c: float(r[c].iloc[0]) if len(r) else 0.0
                    f[key] = {"n": round(n, 1), "go": round(float(shr(g("go"), n, L["go"], K_FOURTH)), 3),
                              "punt": round(float(shr(g("punt"), n, L["punt"], K_FOURTH)), 3),
                              "fg": round(float(shr(g("fg"), n, L["fg"], K_FOURTH)), 3)}
        out["fourth"] = f
        dr = {}
        for ctx in ("all", "short", "late"):
            rn, pn = float(didx.get((t, ctx, "r_n"), 0.0)), float(didx.get((t, ctx, "p_n"), 0.0))
            blk = {"run_n": round(rn), "pass_n": round(pn)}
            for k, den in (("r_left", rn), ("r_middle", rn), ("r_right", rn), ("g_end", rn), ("g_tackle", rn), ("g_guard", rn), ("g_middle", rn),
                           ("p_left", pn), ("p_middle", pn), ("p_right", pn), ("d_short", pn), ("d_deep", pn)):
                blk[k] = round(float(didx.get((t, ctx, k), 0.0)) / den, 3) if den else None
            dr[ctx] = blk
        out["dir"] = dr
        return out

    def dir_league():
        res = {}
        for ctx in ("all", "short", "late"):
            rn, pn = float(dleague.get((ctx, "r_n"), 0.0)), float(dleague.get((ctx, "p_n"), 0.0))
            res[ctx] = {"run_n": round(rn), "pass_n": round(pn)}
            for k, den in (("r_left", rn), ("r_middle", rn), ("r_right", rn), ("p_left", pn), ("p_middle", pn), ("p_right", pn),
                           ("d_short", pn), ("d_deep", pn)):
                res[ctx][k] = round(float(dleague.get((ctx, k), 0.0)) / den, 3) if den else None
        return res

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
        d["tend"] = tend_for(t)
        teams[t] = d
    out_league = {k: {a: (None if b is None else round(float(b), 3)) for a, b in v.items()} for k, v in league.items()}
    out_l4 = {k: {a: round(float(b), 3) for a, b in v.items()} for k, v in lg4.items()}
    return {"situations": SITUATIONS, "fourth": FOURTH, "league": out_league, "league_fourth": out_l4, "teams": teams,
            "tend": TEND, "fourth_t": FOURTH_T, "zones": ZONES, "league_tend": {k: {a: round(float(b), 3) for a, b in v.items()} for k, v in tl.items()},
            "league_f4": {k: {a: round(float(b), 3) for a, b in v.items()} for k, v in fl.items()}, "league_dir": dir_league()}
