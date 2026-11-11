"""Season stat profiles for every team, offense and defense, for matchup pages and scouting.

From box scores (four factors, assists, steals, blocks) and shot logs (rim / midrange / three).
These are raw season averages, not adjusted for opponents; the team ratings handle strength
of schedule. Each stat comes with its national rank (1 = best for that side of the ball).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

# name, label, side, higher_is_better (for the team whose stat it is)
STATS = [
    ("efg", "Effective FG%", "off", True), ("tov", "Turnover rate", "off", False), ("orb", "Off. rebound rate", "off", True),
    ("ftr", "Free-throw rate", "off", True), ("three_rate", "3PA share", "off", None), ("three_pct", "3P%", "off", True),
    ("two_pct", "2P%", "off", True), ("rim_rate", "Rim attempt share", "off", None), ("rim_pct", "Rim FG%", "off", True),
    ("mid_rate", "Midrange share", "off", None), ("mid_pct", "Midrange FG%", "off", True), ("ast_rate", "Assisted baskets", "off", None),
    ("d_efg", "Opp. effective FG%", "def", False), ("d_tov", "Opp. turnover rate", "def", True), ("d_orb", "Opp. off. rebound rate", "def", False),
    ("d_ftr", "Opp. free-throw rate", "def", False), ("d_three_rate", "Opp. 3PA share", "def", None), ("d_three_pct", "Opp. 3P%", "def", False),
    ("d_two_pct", "Opp. 2P%", "def", False), ("d_rim_rate", "Opp. rim attempt share", "def", False), ("d_rim_pct", "Opp. rim FG%", "def", False),
    ("d_mid_rate", "Opp. midrange share", "def", None), ("stl_rate", "Steal rate", "def", True), ("blk_rate", "Block rate", "def", True),
]


def team_profiles(games: pd.DataFrame, box: pd.DataFrame, shots: pd.DataFrame | None, teams: set) -> dict:
    g = games[games.completed.astype(bool)] if "completed" in games else games
    t = box.groupby(["game_id", "team_id"])[["fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "tov", "stl", "blk"]].sum().reset_index()
    t["poss"] = t.fga - t.oreb + t.tov + config.FT_SHARE * t.fta
    # attach the opponent's line to each team-game
    opp = t.rename(columns={c: "o_" + c for c in t.columns if c not in ("game_id",)})
    m = t.merge(opp, on="game_id")
    m = m[m.team_id != m.o_team_id]

    if shots is not None and len(shots):
        s = shots[shots.kind != "ft"].copy()
        s["zone"] = np.where(s.kind == "three", "three", np.where(s.kind.isin(["layup", "dunk", "tip"]), "rim", "mid"))
        z = s.groupby(["game_id", "team_id", "zone"]).agg(att=("made", "size"), made=("made", "sum")).unstack("zone", fill_value=0)
        z.columns = [f"{a}_{b}" for a, b in z.columns]
        z = z.reset_index()
        for c in ("att_rim", "att_mid", "att_three", "made_rim", "made_mid"):
            if c not in z:
                z[c] = 0
        m = m.merge(z, on=["game_id", "team_id"], how="left")
        zo = z.rename(columns={c: "o_" + c for c in z.columns if c not in ("game_id",)})
        m = m.merge(zo, left_on=["game_id", "o_team_id"], right_on=["game_id", "o_team_id"], how="left")

    agg = m.groupby("team_id").sum(numeric_only=True)
    n_games = m.groupby("team_id").size()
    out = pd.DataFrame(index=agg.index)
    a = agg
    div = lambda x, y: x / y.replace(0, np.nan)
    out["efg"] = div(a.fgm + 0.5 * a.tpm, a.fga)
    out["tov"] = div(a.tov, a.poss)
    out["orb"] = div(a.oreb, a.oreb + a.o_dreb)
    out["ftr"] = div(a.fta, a.fga)
    out["three_rate"] = div(a.tpa, a.fga)
    out["three_pct"] = div(a.tpm, a.tpa)
    out["two_pct"] = div(a.fgm - a.tpm, a.fga - a.tpa)
    out["ast_rate"] = div(a.ast, a.fgm)
    out["d_efg"] = div(a.o_fgm + 0.5 * a.o_tpm, a.o_fga)
    out["d_tov"] = div(a.o_tov, a.o_poss)
    out["d_orb"] = div(a.o_oreb, a.o_oreb + a.dreb)
    out["d_ftr"] = div(a.o_fta, a.o_fga)
    out["d_three_rate"] = div(a.o_tpa, a.o_fga)
    out["d_three_pct"] = div(a.o_tpm, a.o_tpa)
    out["d_two_pct"] = div(a.o_fgm - a.o_tpm, a.o_fga - a.o_tpa)
    out["stl_rate"] = div(a.stl, a.o_poss)
    out["blk_rate"] = div(a.blk, a.o_fga - a.o_tpa)
    if "att_rim" in a:
        sh = a.att_rim + a.att_mid + a.att_three
        out["rim_rate"], out["rim_pct"] = div(a.att_rim, sh), div(a.made_rim, a.att_rim)
        out["mid_rate"], out["mid_pct"] = div(a.att_mid, sh), div(a.made_mid, a.att_mid)
        osh = a.o_att_rim + a.o_att_mid + a.o_att_three
        out["d_rim_rate"], out["d_rim_pct"] = div(a.o_att_rim, osh), div(a.o_made_rim, a.o_att_rim)
        out["d_mid_rate"] = div(a.o_att_mid, osh)
    out["games"] = n_games
    out = out[out.index.isin(teams)]

    league, ranks = {}, {}
    for key, label, side, better in STATS:
        if key not in out:
            continue
        col = out[key]
        league[key] = {"mean": round(float(col.mean()), 4), "sd": round(float(col.std()), 4), "label": label, "side": side,
                       "better": better}
        if better is not None:
            ranks[key] = col.rank(ascending=not better, method="min")
    teams_out = {}
    for tid, row in out.iterrows():
        d = {"games": int(row.games)}
        for key in league:
            v = row.get(key)
            d[key] = None if pd.isna(v) else round(float(v), 4)
            if key in ranks and not pd.isna(ranks[key].get(tid)):
                d[key + "_rk"] = int(ranks[key][tid])
        teams_out[tid] = d
    return {"league": league, "n_teams": int(len(out)), "teams": teams_out}
