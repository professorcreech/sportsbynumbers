"""Player availability, valued by what the missing players produce.

tests/availability_value.py (2025 and 2026 box scores, replayed predictions): a team's result runs below its
prediction in proportion to the offensive production (passing + rushing + receiving yards per game, from games
before this one) of the players who did not play: about 0.8 points per 100 yards in college (+/-0.2) and 0.6 in the
NFL (+/-0.5, too few games to be sure). Once that production is in the model the flat "starting quarterback is out" flag
adds nothing in college (-0.3 +/- 1.0): it is the player's output that matters, not his label. Lost defensive box-score
production showed no effect (box scores count defensive plays poorly), so defenders are not adjusted.

Known before kickoff two ways, used where each exists:
  * NFL: the injury report. Players listed Out, Doubtful or Injured Reserve with 3+ games and 40+ usual yards this season.
    0.6 points per 100 usual yards.
  * College (no injury report in ESPN's feed): players with 3+ games and 40+ usual yards who missed the team's previous game.
    Walk-forward test, both seasons: -0.5 (+/-0.22) points per 100 yards, -0.68 (+/-0.27) counting only players with 40+ usual yards (same sign in both
    seasons); applied at 0.5.
A team's total is capped so one long list cannot swamp the ratings.
"""
from __future__ import annotations

import pandas as pd

from . import config

MIN_GAMES = 3
MIN_YPG = 40         # only real contributors count: a box score lists just players with a stat, so a reserve who didn't touch the ball isn't "missing"
MIN_SHIFT = 0.3
OUT_STATUS = {"out", "doubtful", "injured reserve"}


def _usual(players: pd.DataFrame) -> pd.DataFrame:
    """Per player: games played this season, name, and offensive yards per game."""
    p = players.astype({"team_id": str, "player_id": str, "game_id": str}).copy()
    for c in ("pass_yds", "rush_yds", "rec_yds"):
        p[c] = p[c].fillna(0) if c in p else 0.0
    p["off"] = p.pass_yds + p.rush_yds + p.rec_yds
    g = p.groupby(["team_id", "player_id"]).agg(n=("game_id", "nunique"), off=("off", "sum"), name=("name", "last")).reset_index()
    g["ypg"] = g.off / g.n
    return g[(g.n >= MIN_GAMES) & (g.ypg >= MIN_YPG)]


def adjustments(players: pd.DataFrame, games: pd.DataFrame, schedule: list[dict], injuries: dict | None = None) -> dict:
    """{game_id: {team_id: {"shift", "who": [{"name", "ypg", "why"}]}}}; shift is points off that team's margin (negative)."""
    if players is None or not len(players) or not len(games):
        return {}
    usual = _usual(players).set_index(["team_id", "player_id"])
    pl = players.astype({"team_id": str, "player_id": str, "game_id": str})
    sizes = pl.groupby(["game_id", "team_id"]).size()
    present = {k: set(v) for k, v in pl.groupby(["game_id", "team_id"]).player_id}
    last = {}                         # team -> its previous game with a usable box score
    for r in games.astype({"game_id": str}).sort_values("date").itertuples():
        for tid in (str(r.home_id), str(r.away_id)):
            if sizes.get((r.game_id, tid), 0) >= 15:
                last[tid] = r.game_id
    out = {}
    for s in schedule:
        row = {}
        for tid in (str(s["home_id"]), str(s["away_id"])):
            who = []
            if config.IS_NFL:
                for r in ((injuries or {}).get(str(s["game_id"]), {}).get(tid) or []):
                    k = (tid, str(r.get("id")))
                    if str(r.get("status", "")).lower() in OUT_STATUS and k in usual.index and usual.at[k, "ypg"] > 0:
                        who.append({"name": usual.at[k, "name"], "ypg": float(usual.at[k, "ypg"]), "why": str(r["status"])})
            elif tid in last:
                here = present.get((last[tid], tid), set())
                for (t_, pid), u in usual[usual.index.get_level_values(0) == tid].iterrows():
                    if pid not in here and u.ypg > 0:
                        who.append({"name": u["name"], "ypg": float(u.ypg), "why": "missed last game"})
            per100, cap = (0.6, 6.0) if config.IS_NFL else (0.5, 4.0)   # points per 100 usual yards; cap on one team
            shift = -min(sum(w["ypg"] for w in who) * per100 / 100, cap)
            if shift <= -MIN_SHIFT:
                who.sort(key=lambda w: -w["ypg"])
                row[tid] = {"shift": round(shift, 1), "who": [{**w, "ypg": round(w["ypg"])} for w in who[:3]]}
        if row:
            out[str(s["game_id"])] = row
    return out
