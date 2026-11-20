"""Replay last season: what the model would have predicted for every game, using only what came before it.

For each game day the ratings are refit on the games played before that day, starting from the same kind of
preseason prior the live model uses (last season's results, no rosters, injuries or coaching changes, none of which
were saved as they stood on each past day). The predictions are saved in data/<league>/replay.csv, in the ledger's
format, and the Record tab compares them with this season's live record.

  SBN_LEAGUE=nba python -m tools.replay        (also: ncaam [default], ncaaf/nfl via football engine: SBN_LEAGUE=nfl, ncaaf)
  python -m tools.replay --engine football     (college football)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

from tools.ledger import COLS, ROOT


def _games(path):
    frames = []
    for f in sorted(path.glob("*.csv")):
        if f.stat().st_size == 0:
            continue
        try:
            frames.append(pd.read_csv(f, dtype={"game_id": str, "home_id": str, "away_id": str}))
        except pd.errors.EmptyDataError:
            pass
    g = pd.concat(frames, ignore_index=True).drop_duplicates("game_id", keep="last")
    return g[g.completed.astype(str).str.lower().eq("true")].copy()


def _rows(g, day, league, pred_fn):
    out = []
    for r in g.itertuples():
        pr = pred_fn(r)
        if not pr:
            continue
        out.append({"game_id": r.game_id, "start": r.start, "home": r.home_id, "away": r.away_id,
                    "home_name": getattr(r, "home_name", ""), "away_name": getattr(r, "away_name", ""),
                    "neutral": int(bool(r.neutral)), "p_home": round(float(pr["home_win"]), 4), "margin": round(float(pr["margin"]), 2),
                    "snap": f"{day}T00:00Z", "home_pts": r.home_pts, "away_pts": r.away_pts,
                    "line_spread": getattr(r, "line_spread", np.nan)})
    return out


def basketball() -> tuple[str, pd.DataFrame]:
    from basketball import config, run, teams
    league = "nba" if config.IS_NBA else "basketball"
    season = config.season_for(date.today()) - 1
    tm, games, box, _, prior, _ = run.load(season)
    games = games[games.completed.astype(str).str.lower().eq("true")]
    prior_net = teams.prior_from_last_season(prior, tm.team_id.tolist()) if prior is not None else {}
    names = dict(zip(tm.team_id, tm.get("short", tm.get("name"))))
    games = games.assign(home_name=games.home_id.map(names), away_name=games.away_id.map(names))
    rows = []
    for day, today in games.groupby("date"):
        before = games[games.date < day]
        if len(before) < 20:
            continue
        m = teams.fit(before, box[box.game_id.isin(before.game_id)], tm, prior_net, as_of=pd.Timestamp(day).date() - timedelta(days=1))
        rows += _rows(today, day, league, lambda r: teams.predict(m, r.home_id, r.away_id, bool(r.neutral)))
    return league, pd.DataFrame(rows)


def football() -> tuple[str, pd.DataFrame]:
    from football import config, run, teams
    league = "nfl" if config.IS_NFL else "football"
    season = config.season_for(date.today()) - 1
    tm = pd.read_csv(config.DATA_DIR / str(season) / "teams.csv", dtype={"team_id": str})
    games = _games(config.DATA_DIR / str(season) / "games")
    prior = run.prior_for(season)
    games = games.assign(home_name=games.home_id.map(dict(zip(tm.team_id, tm.short))), away_name=games.away_id.map(dict(zip(tm.team_id, tm.short))))
    rows = []
    for day, today in games.groupby("date"):
        before = games[games.date < day]
        if len(before) < 20:
            continue
        m = teams.fit(before, tm, prior, as_of=pd.Timestamp(day).date() - timedelta(days=1))
        rows += _rows(today, day, league, lambda r: teams.predict(m, r.home_id, r.away_id, bool(r.neutral)))
    return league, pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["basketball", "football"], required=True)
    a = ap.parse_args()
    league, df = (basketball if a.engine == "basketball" else football)()
    df = df.reindex(columns=COLS)
    out = ROOT / "data" / league / "replay.csv"
    out.write_text(df.to_csv(index=False))
    ok = ((df.p_home > 0.5) == (df.home_pts > df.away_pts)).mean()
    print(f"replay {league}: {len(df)} games, {ok:.3f} picked right -> {out}")


if __name__ == "__main__":
    main()
