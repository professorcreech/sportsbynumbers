"""Should win probabilities include uncertainty in the team ratings?

   python -m tests.uncertainty football 2022 2023 2024 2025 2026      (SBN_LEAGUE=nfl for the NFL)
   python -m tests.uncertainty basketball 2025 2026 2027              (SBN_LEAGUE=nba for the NBA)

Weekly refits (prior from the season before). For every game it saves the margin, the model's own spread and each
team's rating standard error, then scores win probabilities with the live spread against spreads that add the ratings'
uncertainty in quadrature. Lower Brier and log loss are better; the result has to hold in most seasons.
"""
from __future__ import annotations

import sys
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm


def football(season):
    from football import run, teams
    tm, g, _ = run.load(season)
    prior = run.prior_for(season)
    g = g.sort_values("date")
    weeks = pd.to_datetime(g.date).dt.to_period("W-MON")
    rows = []
    for wk in sorted(weeks.unique())[1:]:
        test, train = g[weeks == wk], g[weeks < wk]
        if test.empty or len(train) < 20:
            continue
        m = teams.fit(train, tm, prior, as_of=pd.to_datetime(test.date).min().date() - timedelta(days=1))
        se = dict(zip(m["table"].team_id, m["table"].net_se))
        for x in test.itertuples():
            p = teams.predict(m, x.home_id, x.away_id, bool(x.neutral))
            if p:
                rows.append({"season": season, "n_train": len(train), "margin": p["margin"], "sd": m["sd"],
                             "se": float(np.hypot(se.get(x.home_id, 6), se.get(x.away_id, 6))), "actual": x.home_pts - x.away_pts, "conf": bool(getattr(x, "conference_game", False)), "neutral": bool(x.neutral)})
    return pd.DataFrame(rows)


def basketball(season):
    from basketball import run, teams
    tm, g, box, _, prior, _ = run.load(season)
    g = g[g.completed.astype(str).str.lower().eq("true")].sort_values("date")
    pn = teams.prior_from_last_season(prior, tm.team_id.tolist()) if prior is not None else {}
    weeks = pd.to_datetime(g.date).dt.to_period("W-MON")
    rows = []
    for wk in sorted(weeks.unique())[1:]:
        test, train = g[weeks == wk], g[weeks < wk]
        if test.empty or len(train) < 20:
            continue
        m = teams.fit(train, box[box.game_id.isin(train.game_id)], tm, pn, as_of=pd.to_datetime(test.date).min().date() - timedelta(days=1))
        se = dict(zip(m["table"].team_id, m["table"].net_se))
        for x in test.itertuples():
            p = teams.predict(m, x.home_id, x.away_id, bool(x.neutral))
            if p:
                rows.append({"season": season, "n_train": len(train), "margin": p["margin"], "sd": m["sd"],
                             "se": float(np.hypot(se.get(x.home_id, 3), se.get(x.away_id, 3)) * p["poss"] / 100), "actual": x.home_pts - x.away_pts, "conf": bool(getattr(x, "conference_game", False)), "neutral": bool(x.neutral)})
    return pd.DataFrame(rows)


def score(df, label, sd):
    p = np.clip(norm.cdf(df.margin / sd), 1e-4, 1 - 1e-4)
    w = df.actual > 0
    return {"variant": label, "brier": ((p - w) ** 2).mean(), "logloss": -(np.where(w, np.log(p), np.log(1 - p))).mean()}


def main():
    kind, seasons = sys.argv[1], [int(s) for s in sys.argv[2:]]
    df = pd.concat([(football if kind == "football" else basketball)(s) for s in seasons], ignore_index=True)
    df = df[df.actual != 0]
    rows = []
    for season, d in list(df.groupby("season")) + [("ALL", df)]:
        base = score(d, "live spread", d.sd)
        for lab, sd in (("live spread", d.sd), ("+ rating uncertainty", np.sqrt(d.sd ** 2 + d.se ** 2)),
                        ("x1.05", d.sd * 1.05), ("x1.10", d.sd * 1.10), ("x1.15", d.sd * 1.15),
                        ("x1.10 + uncertainty", np.sqrt((d.sd * 1.10) ** 2 + d.se ** 2)),
                        ("full-season sd, + uncertainty", np.sqrt(d.sd.median() ** 2 + d.se ** 2))):
            s = score(d, lab, sd)
            rows.append({"season": season, **s, "d_brier": s["brier"] - base["brier"], "d_logloss": s["logloss"] - base["logloss"], "n": len(d)})
    out = pd.DataFrame(rows)
    print(out.round(4).to_string(index=False))
    early = df[df.n_train < (600 if kind == "football" else 1500)]
    print("\nearly in the season only:", len(early), "games")
    for lab, sd in (("live spread", early.sd), ("+ rating uncertainty", np.sqrt(early.sd ** 2 + early.se ** 2))):
        print(score(early, lab, sd))


if __name__ == "__main__":
    main()
