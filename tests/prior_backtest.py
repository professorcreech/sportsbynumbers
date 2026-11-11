"""How much does last season help predict this season's early games?

Walk forward through the season: for each day, fit ratings on every earlier game and
predict that day's games. Repeat with last season's ratings weighted from "almost
nothing" to "nothing but last season", and with different amounts of regression
toward average.

    python -m tests.prior_backtest
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from basketball import config, run, teams


def main(season: int = 2027, first_test_day: str | None = None):
    tm, games, box, _, prior, _ = run.load(season)
    games = games[games.completed.astype(bool)].sort_values("date")
    config.TEAM_PRIOR_REGRESS = 1.0
    raw_prior = teams.prior_from_last_season(prior, tm.team_id.tolist())  # unregressed last-season net

    days = sorted(games.date.unique())
    test_days = [d for d in days if d >= (first_test_day or days[3])]
    settings = [("none", 0.25, 0.0)] + [(f"{k:g} games, keep {r:.0%}", k, r)
                                         for k in (1, 2, 4, 8, 16) for r in (0.4, 0.6, 0.8, 1.0)]
    settings += [("last season only, keep 60%", 1e6, 0.6), ("last season only, keep 80%", 1e6, 0.8)]

    rows = []
    for d in test_days:
        train, test = games[games.date < d], games[games.date == d]
        if train.empty or test.empty:
            continue
        for name, k, keep in settings:
            config.TEAM_PRIOR_GAMES = k
            pn = {t: keep * v for t, v in raw_prior.items()}
            m = teams.fit(train, box[box.game_id.isin(train.game_id)], tm, pn, as_of=pd.Timestamp(d).date())
            m["sd"] = config.MARGIN_SD  # same win-probability spread for every setting
            for g in test.itertuples():
                p = teams.predict(m, g.home_id, g.away_id, bool(g.neutral))
                if not p:
                    continue
                actual = g.home_pts - g.away_pts
                rows.append({"setting": name, "k": k, "keep": keep, "game": g.game_id, "day": d,
                             "err": actual - p["margin"], "right": (p["margin"] > 0) == (actual > 0),
                             "brier": (p["home_win"] - (actual > 0)) ** 2})
    df = pd.DataFrame(rows)
    summary = df.groupby("setting").agg(k=("k", "first"), keep=("keep", "first"), n=("err", "size"),
                                        mae=("err", lambda e: e.abs().mean()), rmse=("err", lambda e: np.sqrt((e ** 2).mean())),
                                        acc=("right", "mean"), brier=("brier", "mean")).sort_values("mae")
    # Paired comparison with the best setting, so differences come with a standard error
    best = summary.index[0]
    base = df[df.setting == best].set_index("game").err.abs()
    se = {}
    for s in summary.index:
        diff = df[df.setting == s].set_index("game").err.abs() - base
        se[s] = f"{diff.mean():+.2f} ± {diff.std(ddof=1) / np.sqrt(len(diff)):.2f}"
    summary["mae_vs_best"] = pd.Series(se)
    pd.set_option("display.width", 200)
    print(f"test games: {df.game.nunique()} on {len(test_days)} days ({test_days[0]} to {test_days[-1]})")
    print(summary.round(3).to_string())
    return df, summary


if __name__ == "__main__":
    main()
