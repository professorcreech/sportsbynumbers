"""Re-tune the football team model over several seasons (weekly refits, prior from the season before).

   python -m tests.tune_football [college|nfl] [season ...]

One setting changes at a time from the production values; a change is only worth making if it helps in most seasons.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from football import config, run, teams

BASE = dict(k=config.PRIOR_GAMES, keep=config.PRIOR_KEEP, hl=config.HALF_LIFE_DAYS, cap=None)
GRID = {"k": [1.5, 2, 4.5, 6, 9], "keep": [0.6, 0.7, 0.8, 1.0], "hl": [45, 75, 180, 365], "cap": [21, 28, 35]}


def replay(season: int, settings: dict) -> pd.DataFrame:
    tm, g, _ = run.load(season)
    tm_p, g_p, _ = run.load(season - 1)
    g = g.sort_values("date")
    weeks = pd.to_datetime(g.date).dt.to_period("W-MON")
    priors = {}
    rows = []
    for wk in sorted(weeks.unique())[1:]:
        test, train = g[weeks == wk], g[weeks < wk]
        if test.empty or len(train) < 20:
            continue
        as_of = pd.to_datetime(test.date).min().date()
        for name, s in settings.items():
            key = (s["keep"], s["cap"])
            if key not in priors:
                priors[key] = teams.last_season_prior(g_p, tm_p, keep=s["keep"], cap=s["cap"])
            m = teams.fit(train, tm, priors[key], as_of=as_of, prior_games=s["k"], half_life=s["hl"], cap=s["cap"])
            for x in test.itertuples():
                p = teams.predict(m, x.home_id, x.away_id, bool(x.neutral))
                if p:
                    rows.append({"setting": name, "season": season, "margin": p["margin"], "actual": x.home_pts - x.away_pts})
    return pd.DataFrame(rows)


def main():
    args = sys.argv[1:]
    if args and args[0] in ("college", "nfl"):
        args = args[1:]
    seasons = [int(a) for a in args] or [2022, 2023, 2024, 2025, 2026]
    settings = {"production": BASE}
    for k, vals in GRID.items():
        for v in vals:
            if v != BASE[k]:
                settings[f"{k}={v}"] = {**BASE, k: v}
    df = pd.concat([replay(s, settings) for s in seasons], ignore_index=True)
    sd = config.MARGIN_SD
    from scipy.stats import norm
    df["err"] = (df.actual - df.margin).abs()
    df["right"] = (df.margin > 0) == (df.actual > 0)
    df["brier"] = (norm.cdf(df.margin / sd) - (df.actual > 0)) ** 2
    t = df.groupby(["setting", "season"]).agg(mae=("err", "mean"), brier=("brier", "mean"), acc=("right", "mean")).reset_index()
    base = t[t.setting == "production"].set_index("season")
    out = []
    for name, x in t.groupby("setting"):
        x = x.set_index("season")
        out.append({"setting": name, "mae": x.mae.mean() - base.mae.mean(), "brier": x.brier.mean() - base.brier.mean(),
                    "acc": x.acc.mean() - base.acc.mean(), "seasons_better_mae": int((x.mae < base.mae).sum()), "of": len(x)})
    r = pd.DataFrame(out).sort_values("brier")
    print(f"baseline mean: mae {base.mae.mean():.3f} brier {base.brier.mean():.4f} acc {base.acc.mean():.3f}  ({len(df) // len(settings)} games/setting)")
    print(r.round(4).to_string(index=False))
    for s in (11, 12, 13, 14, 15, 16, 17):
        b = (norm.cdf(df[df.setting == "production"].margin / s) - (df[df.setting == "production"].actual > 0)) ** 2
        print(f"margin sd {s}: brier {b.mean():.4f}")


if __name__ == "__main__":
    main()
