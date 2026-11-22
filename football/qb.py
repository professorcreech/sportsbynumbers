"""Starting-quarterback availability (NFL only).

tests/qb_absence_live.py (2025 and 2026 box scores, replayed predictions, the usual starter taken as the attempts leader
BEFORE each game, no hindsight): when a team's starter throws fewer than 5 passes, the team lands below the ratings'
prediction by 3.6 points in the NFL (+/-1.4; 3.1 when the absence continues from the week before, 4.4 when it is new) and
2.3 in college (+/-0.6). Using hindsight to pick the starter overstates the NFL effect at 6.4.
College football has no injury report in ESPN's feed, and "he missed the previous game" is worth only -1.0 (+/-0.6) without
hindsight, so nothing is applied there. In the NFL the pregame injury report is used: a usual starter listed Out, Doubtful or
Injured Reserve moves that team's margin by REPORTED_OUT. Questionable is left alone. The usual starter is the quarterback
with the most pass attempts this season (at least 30).
"""
from __future__ import annotations

import json

import pandas as pd

from . import config

REPORTED_OUT = -3.5                                # NFL injury report: Out / Doubtful / Injured Reserve
OUT_STATUS = {"out", "doubtful", "injured reserve"}


def adjustments(players: pd.DataFrame, games: pd.DataFrame, schedule: list[dict], injuries: dict | None = None) -> dict:
    """{game_id: {team_id: {"name", "why", "shift"}}} for upcoming games where a team's usual starter is probably out."""
    if not config.IS_NFL or players is None or not len(players) or not len(games):
        return {}
    p = players[players.pass_att.fillna(0) > 0].astype({"team_id": str, "player_id": str, "game_id": str})
    tot = p.groupby(["team_id", "player_id"]).agg(att=("pass_att", "sum"), name=("name", "last")).reset_index()
    lead = tot.sort_values("att").drop_duplicates("team_id", keep="last")
    lead = lead[lead.att >= 30].set_index("team_id")
    out = {}
    for s in schedule:
        row = {}
        for tid in (str(s["home_id"]), str(s["away_id"])):
            if tid not in lead.index:
                continue
            pid, name = lead.at[tid, "player_id"], lead.at[tid, "name"]
            why, shift = None, 0.0
            for r in ((injuries or {}).get(str(s["game_id"]), {}).get(tid) or []):
                if str(r.get("id")) == pid and str(r.get("status", "")).lower() in OUT_STATUS:
                    why, shift = f"{name} is listed {r['status']}", REPORTED_OUT
            if why:
                row[tid] = {"name": name, "why": why, "shift": shift}
        if row:
            out[str(s["game_id"])] = row
    return out
