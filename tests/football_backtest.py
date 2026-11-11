"""Tune college football's preseason prior and margin damping.   python -m tests.football_backtest [season]

Replays a season week by week: fit on every earlier game (prior from the season before),
predict the week's games. Compares prior strength (games), carry-over share, and damping
of lopsided margins.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from football import config, run, teams


def replay(season: int, settings: dict) -> pd.DataFrame:
    tm, g, _ = run.load(season)
    tm_p, g_p, _ = run.load(season - 1)
    g = g.sort_values("date")
    days = sorted(g.date.unique())
    # one checkpoint per week: Sundays are rarely game days, so cut on Mondays
    cuts = sorted({d for d in days if pd.Timestamp(d).weekday() in (1,)} | {days[len(days) // 3]})
    weeks = pd.to_datetime(g.date).dt.to_period("W-MON")
    rows = []
    for wk in sorted(weeks.unique())[1:]:
        test = g[weeks == wk]
        train = g[weeks < wk]
        if test.empty:
            continue
        as_of = pd.to_datetime(test.date).min().date()
        for name, (k, keep, cap) in settings.items():
            prior = teams.last_season_prior(g_p, tm_p, keep=keep, cap=cap) if keep else {}
            m = teams.fit(train, tm, prior, as_of=as_of, prior_games=k, cap=cap)
            m["sd"] = config.MARGIN_SD
            for x in test.itertuples():
                p = teams.predict(m, x.home_id, x.away_id, bool(x.neutral))
                if not p:
                    continue
                a = x.home_pts - x.away_pts
                both_d1 = x.home_id in m["idx"] and x.away_id in m["idx"] and "NON_D1" not in (x.home_id, x.away_id)
                rows.append({"setting": name, "game": x.game_id, "week": str(wk), "early": len(train) < 600,
                             "err": a - p["margin"], "right": (p["margin"] > 0) == (a > 0),
                             "brier": (p["home_win"] - (a > 0)) ** 2})
    return pd.DataFrame(rows)


def main(season: int = 2025):
    settings = {"none": (0.25, 0.0, None)}
    for k in (1, 3, 6):
        for keep in (0.5, 0.7, 0.9):
            settings[f"{k} games, keep {keep:.0%}"] = (k, keep, None)
    for cap in (21, 28, 35):
        settings[f"3 games, keep 70%, damp past {cap}"] = (3, 0.7, cap)
    df = replay(season, settings)
    for label, part in (("all weeks", df), ("first ~4 weeks", df[df.early]), ("later weeks", df[~df.early])):
        s = part.groupby("setting").agg(n=("err", "size"), mae=("err", lambda e: e.abs().mean()),
                                        acc=("right", "mean"), brier=("brier", "mean")).sort_values("mae")
        print(f"\n== {season}, {label}: {part.game.nunique()} games ==")
        print(s.round(3).head(10).to_string())


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2025)
