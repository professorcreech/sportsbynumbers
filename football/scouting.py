"""Season stat profiles for every college football team, offense and defense, with national ranks.

Raw season averages from ESPN play-by-play (not adjusted for opponents; the team ratings
handle strength of schedule).

Definitions
  Success: a play that gains at least 50% of the yards to go on 1st down, 70% on 2nd,
           100% on 3rd or 4th (the standard football analytics definition).
  Explosive: a run of 12+ yards or a pass of 16+ yards.
  Pass plays include sacks and interceptions; runs include rushing touchdowns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RUSH = {"Rush", "Rushing Touchdown", "Two Point Rush"}
PASS = {"Pass Reception", "Pass Incompletion", "Passing Touchdown", "Sack", "Interception", "Pass Interception Return",
        "Interception Return Touchdown", "Pass Completion", "Two Point Pass"}

STATS = [  # key, label, side, higher_is_better
    ("ypp", "Yards per play", "off", True), ("success", "Success rate", "off", True), ("explosive", "Explosive play rate", "off", True),
    ("rush_ypc", "Yards per rush", "off", True), ("rush_success", "Rush success rate", "off", True),
    ("pass_ypa", "Yards per dropback", "off", True), ("pass_success", "Pass success rate", "off", True),
    ("pass_rate", "Pass rate", "off", None), ("early_pass_rate", "Early-down pass rate", "off", None),
    ("third_conv", "3rd-down conversion", "off", True), ("sack_rate", "Sacks taken per dropback", "off", False),
    ("rz_td", "Red-zone TD rate", "off", True), ("ppd", "Points per drive", "off", True), ("to_drive", "Turnovers per drive", "off", False),
    ("plays_pg", "Plays per game", "off", None), ("fourth_go", "4th-down go rate", "off", None),
    ("d_ypp", "Yards per play allowed", "def", False), ("d_success", "Success rate allowed", "def", False),
    ("d_explosive", "Explosive plays allowed", "def", False), ("d_rush_ypc", "Yards per rush allowed", "def", False),
    ("d_rush_success", "Rush success allowed", "def", False), ("d_pass_ypa", "Yards per dropback allowed", "def", False),
    ("d_pass_success", "Pass success allowed", "def", False), ("d_third_conv", "3rd-down conversion allowed", "def", False),
    ("d_sack_rate", "Sack rate", "def", True), ("d_rz_td", "Red-zone TD rate allowed", "def", False),
    ("d_ppd", "Points per drive allowed", "def", False), ("d_to_drive", "Takeaways per drive", "def", True),
]


def _side(plays: pd.DataFrame, drives: pd.DataFrame, key: str) -> pd.DataFrame:
    """Per-team aggregates with plays grouped by `key` (offense or defense)."""
    p = plays
    g = p.groupby(key)
    sc = p[p.scrim]
    gs = sc.groupby(key)
    out = pd.DataFrame({
        "ypp": gs.yards.mean(), "success": gs.success.mean(), "explosive": gs.explosive.mean(),
        "rush_ypc": sc[sc.rush].groupby(key).yards.mean(), "rush_success": sc[sc.rush].groupby(key).success.mean(),
        "pass_ypa": sc[sc.pass_].groupby(key).yards.mean(), "pass_success": sc[sc.pass_].groupby(key).success.mean(),
        "pass_rate": gs.pass_.mean(),
        "early_pass_rate": sc[sc.down.isin([1, 2])].groupby(key).pass_.mean(),
        "third_conv": sc[sc.down == 3].groupby(key).converted.mean(),
        "sack_rate": sc[sc.pass_].groupby(key).sack.mean(),
        "fourth_go": p[p.down == 4].groupby(key).go.mean(),
        "plays_pg": gs.size() / g.game_id.nunique(),
    })
    d = drives[drives.plays > 0]
    dk = "offense" if key == "offense" else "defense"
    gd = d.groupby(dk)
    out["ppd"] = gd.pts_off.mean()
    out["to_drive"] = gd.to.mean()
    rz = d[d.reached_rz]
    out["rz_td"] = rz.groupby(dk).td.mean()
    return out


def team_profiles(plays: pd.DataFrame, drives: pd.DataFrame, teams: set) -> dict:
    p = plays.copy()
    p["rush"] = p.type.isin(RUSH)
    p["pass_"] = p.type.isin(PASS)
    p["scrim"] = (p.rush | p.pass_) & p.down.between(1, 4)
    p["sack"] = p.type.eq("Sack")
    need = np.select([p.down == 1, p.down == 2], [0.5 * p.distance, 0.7 * p.distance], p.distance)
    p["success"] = p.yards >= need
    p["converted"] = p.yards >= p.distance
    p["explosive"] = np.where(p.rush, p.yards >= 12, p.yards >= 16)
    p["go"] = p.rush | p.pass_
    # defense of each play = the other team in that game
    teams_in_game = pd.concat([p[["game_id", "offense"]]]).drop_duplicates()
    opp = teams_in_game.merge(teams_in_game, on="game_id")
    opp = opp[opp.offense_x != opp.offense_y].rename(columns={"offense_x": "offense", "offense_y": "defense"})
    p = p.merge(opp, on=["game_id", "offense"], how="left")

    d = drives.copy()
    d["to"] = d.result.astype(str).str.contains("INT|FUMBLE", regex=True)
    d["td"] = d.pts_off >= 6
    rz_drives = p[p.ytg.le(20) & p.scrim].groupby(["game_id", "drive"]).size().rename("rz").reset_index()
    d = d.merge(rz_drives, on=["game_id", "drive"], how="left")
    d["reached_rz"] = d.rz.notna()

    off = _side(p, d, "offense")
    dfn = _side(p, d, "defense").add_prefix("d_")
    out = off.join(dfn, how="outer")
    out["d_to_drive"] = out["d_to_drive"]
    out["games"] = p.groupby("offense").game_id.nunique()
    out = out[out.index.isin(teams)]

    league, ranks = {}, {}
    for key, label, side, better in STATS:
        if key not in out:
            continue
        col = out[key]
        league[key] = {"mean": round(float(col.mean()), 4), "sd": round(float(col.std()), 4), "label": label,
                       "side": side, "better": better}
        if better is not None:
            ranks[key] = col.rank(ascending=not better, method="min")
    teams_out = {}
    for tid, row in out.iterrows():
        dct = {"games": int(row.games) if not pd.isna(row.games) else 0}
        for key in league:
            v = row.get(key)
            dct[key] = None if pd.isna(v) else round(float(v), 4)
            if key in ranks and not pd.isna(ranks[key].get(tid)):
                dct[key + "_rk"] = int(ranks[key][tid])
        teams_out[str(tid)] = dct
    return {"league": league, "n_teams": int(len(out)), "teams": teams_out}
