"""Position groups: who is on the roster, how experienced and big they are, who produces, and how each group
compares with the rest of the conference.

Built from ESPN rosters (position, class, size) and per-player box-score lines. The feed has no snap counts, so
production is credited by what is counted: passes, carries, catches, tackles, sacks, pass breakups, interceptions.
Offensive linemen have no counting stats, so that group shows size and experience only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GROUPS = {"QB": "Quarterbacks", "RB": "Running backs", "WR": "Receivers", "OL": "Offensive line",
          "DL": "Defensive line", "LB": "Linebackers", "DB": "Defensive backs"}
POS = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "WR", "OL": "OL", "OT": "OL", "OG": "OL", "C": "OL",
       "G": "OL", "T": "OL", "DL": "DL", "DE": "DL", "DT": "DL", "NT": "DL", "EDGE": "DL", "LB": "LB", "ILB": "LB",
       "OLB": "LB", "MLB": "LB", "DB": "DB", "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "SAF": "DB"}
SENIOR = {"SR", "GR", "5TH"}


def _metric(g: str, x: pd.DataFrame, games: float) -> float | None:
    """A group's production per team game, from the players in it."""
    if x.empty or games <= 0:
        return None
    s = lambda c: float(x[c].sum()) if c in x else 0.0
    if g == "QB":
        att = s("pass_att")
        return (s("pass_yds") + 20 * s("pass_td") - 45 * s("pass_int")) / att if att >= 20 else None   # adjusted yards per attempt
    if g == "RB":
        car = s("rush_car")
        return s("rush_yds") / car if car >= 20 else None
    if g == "WR":
        return s("rec_yds") / games
    if g == "DL":
        return (3 * s("sacks") + 1.5 * s("tfl") + 0.5 * s("hur")) / games
    if g == "LB":
        return (s("tkl") + 2 * s("tfl") + 2 * s("sacks")) / games
    if g == "DB":
        return (3 * (s("pd") + 2 * s("def_int"))) / games
    return None


LABEL = {"QB": "adjusted yards per pass attempt", "RB": "yards per carry", "WR": "receiving yards per game",
         "DL": "pressure score per game (sacks, TFL, hurries)", "LB": "tackle impact per game",
         "DB": "pass-defense score per game (PD, INT)"}


def _line(g: str, r) -> str:
    v = lambda c: 0.0 if pd.isna(r.get(c)) else float(r.get(c))
    f = lambda c: int(v(c))
    if g == "QB":
        return f"{f('pass_cmp')}/{f('pass_att')}, {f('pass_yds')} yds, {f('pass_td')} TD, {f('pass_int')} INT"
    if g == "RB":
        return f"{f('rush_car')} car, {f('rush_yds')} yds, {f('rush_td')} TD"
    if g == "WR":
        return f"{f('rec')} rec, {f('rec_yds')} yds, {f('rec_td')} TD"
    return f"{f('tkl')} tkl, {f('tfl')} TFL, {v('sacks'):g} sacks, {f('pd')} PD, {f('def_int')} INT"


SORT = {"QB": "pass_att", "RB": "rush_car", "WR": "rec_yds", "DL": "sacks", "LB": "tkl", "DB": "tkl"}


def build(roster: pd.DataFrame, players: pd.DataFrame, games: pd.DataFrame, teams: pd.DataFrame) -> dict | None:
    if roster is None or not len(roster):
        return None
    r = roster.copy()
    r["g"] = r.pos.astype(str).str.upper().map(POS)
    r = r[r.g.notna()]
    r["senior"] = r["class"].astype(str).str.upper().isin(SENIOR)
    r["w"] = pd.to_numeric(r.weight, errors="coerce")
    if players is not None and len(players):
        num = [c for c in players.columns if c not in ("game_id", "team_id", "player_id", "name", "punt_avg")]
        season = players.groupby(["team_id", "player_id"], as_index=False).agg({**{c: "sum" for c in num}, "name": "last"})
        p = season.merge(r[["team_id", "player_id", "g"]], on=["team_id", "player_id"], how="left")
        gp = pd.concat([games.home_id, games.away_id]).value_counts()
    else:
        p, gp = pd.DataFrame(), pd.Series(dtype=float)
    conf = dict(zip(teams.team_id, teams.conf))
    out = {}
    for tid, rt in r.groupby("team_id"):
        d = {}
        for g in GROUPS:
            x = rt[rt.g == g]
            if x.empty:
                continue
            row = {"n": int(len(x)), "seniors": int(x.senior.sum()), "wt": None if x.w.isna().all() else round(float(x.w.mean()))}
            if len(p):
                px = p[(p.team_id == tid) & (p.g == g)]
                row["metric"] = _metric(g, px, float(gp.get(tid, 0)))
                if g in SORT and len(px):
                    top = px.sort_values(SORT[g], ascending=False).head(3)
                    row["top"] = [{"name": t["name"], "line": _line(g, t)} for _, t in top.iterrows()]
            d[g] = row
        out[tid] = d
    # conference comparison for each measurable group
    for g in GROUPS:
        vals = {t: d[g]["metric"] for t, d in out.items() if g in d and d[g].get("metric") is not None}
        if len(vals) < 20:
            continue
        sd = float(np.std(list(vals.values()))) or 1.0
        for t, v in vals.items():
            peers = [vals[u] for u in vals if conf.get(u) == conf.get(t)]
            rank = 1 + sum(1 for q in peers if q > v)
            out[t][g].update({"metric": round(v, 2), "conf_rank": rank, "conf_n": len(peers),
                              "z": round((v - float(np.mean(peers))) / sd, 2), "nat_rank": 1 + sum(1 for q in vals.values() if q > v)})
    for t in out:
        for g in out[t]:
            if out[t][g].get("metric") is not None and "z" not in out[t][g]:
                out[t][g]["metric"] = None
    return {"groups": GROUPS, "labels": LABEL, "teams": out}
