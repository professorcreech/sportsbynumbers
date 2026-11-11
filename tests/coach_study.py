"""Does the head coach add predictive power beyond last season's results?

    python -m tests.coach_study

For every D-I team-season 2013-2026, the season's margin rating (opponent-adjusted points per
game) is compared with what last season predicts (a league-wide regression). The question is
whether the leftover -- a team beating or missing its expectation -- is predictable from:

  * the coach's trailing 5-year record of beating expectations (at any school), and
  * a coaching change (does a new coach shift the team, or weaken last season's carry-over?).

And separately for March: does a coach's record of beating his team's rating in past NCAA
tournaments predict his next tournament?

All tests are leave-one-season-out: weights are fit on the other seasons and scored on the
held-out one, so a factor only "works" if it helps in seasons it never saw.
Needs data/basketball/history/coaches.csv (Action input "coaches: 2012 2026").
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from basketball import config
from tests.tournament_factors import season_ratings, TOURNEY

HIST = config.DATA_DIR / "history"


def ratings() -> pd.DataFrame:
    rows = []
    for s in range(2012, 2027):
        p = HIST / f"scores_{s}.csv.gz"
        if not p.exists():
            continue
        g = pd.read_csv(p, dtype={"home_id": str, "away_id": str})
        g = g[(g.home_pts + g.away_pts) > 0]
        counts = pd.concat([g.home_id, g.away_id]).value_counts()
        d1 = set(counts[counts >= 10].index)
        g = g[g.home_id.isin(d1) & g.away_id.isin(d1)]
        R, _, _ = season_ratings(g)
        rows += [{"season": s, "team_id": t, "R": r, "games": int(counts[t])} for t, r in R.items()]
    return pd.DataFrame(rows)


def coach_table() -> pd.DataFrame:
    c = pd.read_csv(HIST / "coaches.csv", dtype={"team_id": str, "coach_id": str})
    n = c.groupby(["season", "team_id"]).coach_id.transform("size")
    c = c[n == 1]  # skip mid-season changes (interim seasons) -- ambiguous credit
    c = c[c.groupby(["season", "coach_id"]).team_id.transform("size") == 1]  # one coach listed at two schools
    return c[["season", "team_id", "coach_id", "coach_name"]]


def loso(df: pd.DataFrame, y: str, cols: list[str]) -> tuple[float, float, np.ndarray]:
    """RMSE of y with and without cols, each season predicted from a fit on the others."""
    base, adj, betas = [], [], []
    for s in sorted(df.season.unique()):
        tr, te = df[df.season != s], df[df.season == s]
        X = np.c_[np.ones(len(tr)), tr[cols].to_numpy(float)]
        b = np.linalg.lstsq(X, tr[y].to_numpy(float), rcond=None)[0]
        betas.append(b[1:])
        b0 = tr[y].mean()
        base += list((te[y] - b0) ** 2)
        adj += list((te[y] - np.c_[np.ones(len(te)), te[cols].to_numpy(float)] @ b) ** 2)
    return float(np.sqrt(np.mean(base))), float(np.sqrt(np.mean(adj))), np.array(betas)


def per_season(df, y, cols):
    """How many held-out seasons the factor improved."""
    wins = 0
    seasons = sorted(df.season.unique())
    for s in seasons:
        tr, te = df[df.season != s], df[df.season == s]
        X = np.c_[np.ones(len(tr)), tr[cols].to_numpy(float)]
        b = np.linalg.lstsq(X, tr[y].to_numpy(float), rcond=None)[0]
        e0 = ((te[y] - tr[y].mean()) ** 2).mean()
        e1 = ((te[y] - np.c_[np.ones(len(te)), te[cols].to_numpy(float)] @ b) ** 2).mean()
        wins += e1 < e0
    return wins, len(seasons)


def main():
    R = ratings()
    prev = R.assign(season=R.season + 1).rename(columns={"R": "R_prev"})[["season", "team_id", "R_prev"]]
    df = R.merge(prev, on=["season", "team_id"])
    # Expectation from last season alone, fit across all seasons (the coach factors are judged
    # on what this misses). Leave-one-season-out so no season sees its own fit.
    df["expect"] = np.nan
    for s in df.season.unique():
        tr = df[df.season != s]
        b = np.polyfit(tr.R_prev, tr.R, 1)
        df.loc[df.season == s, "expect"] = np.polyval(b, df.loc[df.season == s, "R_prev"])
    df["surprise"] = df.R - df.expect
    b = np.polyfit(df.R_prev, df.R, 1)
    print(f"{len(df)} team-seasons. Last season carries {b[0]:.2f} of its rating; "
          f"spread of this season's rating {df.R.std():.2f}, of the surprise {df.surprise.std():.2f} pts/game")

    c = coach_table()
    df = df.merge(c, on=["season", "team_id"], how="left")
    prevc = c.assign(season=c.season + 1).rename(columns={"coach_id": "coach_prev"})[["season", "team_id", "coach_prev"]]
    df = df.merge(prevc, on=["season", "team_id"], how="left")
    known = df.coach_id.notna() & df.coach_prev.notna()
    df["new_coach"] = (known & (df.coach_id != df.coach_prev)).astype(float)
    print(f"Coach known both years for {known.sum()} team-seasons; {int(df.new_coach.sum())} coaching changes")

    # Coach track record: shrunk mean surprise over his previous 5 seasons (any school)
    hist = df.dropna(subset=["coach_id"])[["season", "coach_id", "surprise"]]
    def track(row, k=5, shrink=2.0):
        h = hist[(hist.coach_id == row.coach_id) & (hist.season < row.season) & (hist.season >= row.season - k)]
        return pd.Series({"track": h.surprise.sum() / (len(h) + shrink), "track_n": len(h)})
    tr = df[df.coach_id.notna()].apply(track, axis=1)
    df = df.join(tr)
    df["track"] = df.track.fillna(0.0)
    df["new_x_prev"] = df.new_coach * df.R_prev
    # A coach's record only adds information when he earned it somewhere else: with the same
    # coach at the same school, last season's rating already contains his effect.
    df["moved_track"] = df.new_coach * df.track

    d = df[known & (df.season >= 2015)].copy()  # at least 2 earlier seasons of surprises exist
    print(f"\nTest set: {len(d)} team-seasons, {d.season.nunique()} seasons (2015-2026)\n")
    print(f"{'factor':42s}{'RMSE without':>13s}{'with':>8s}{'gain':>7s}{'beta (mean ± sd over folds)':>30s}{'seasons helped':>16s}")
    tests = {
        "Coach 5-year record vs. expectation": ["track"],
        "  (coaches with 3+ seasons of record)": ["track"],
        "Coaching change (level shift)": ["new_coach"],
        "Coaching change x last season (carry-over)": ["new_coach", "new_x_prev"],
        "New coach's record from his old school": ["moved_track"],
        "Coaching change + new coach's record": ["new_coach", "new_x_prev", "moved_track"],
    }
    out = {}
    for name, cols in tests.items():
        dd = d[d.track_n >= 3] if "3+" in name else d
        r0, r1, betas = loso(dd, "surprise", cols)
        w, n = per_season(dd, "surprise", cols)
        bm = ", ".join(f"{m:+.2f}±{s:.2f}" for m, s in zip(betas.mean(0), betas.std(0)))
        print(f"{name:42s}{r0:13.3f}{r1:8.3f}{r0 - r1:+7.3f}{bm:>30s}{f'{w}/{n}':>16s}")
        out[name] = (r0, r1, w, n)

    # How big is a coach "effect" in points? Correlation of consecutive-season surprises for the
    # same coach vs. the same program after the coach left.
    same = d[(d.track_n >= 1) & (d.new_coach == 0)]
    print(f"\nCorrelation of surprise with coach's record: same coach, same school r = "
          f"{np.corrcoef(same.track, same.surprise)[0, 1]:.3f} (n={len(same)})")
    moved = d[(d.track_n >= 1) & (d.new_coach == 1)]
    if len(moved) > 30:
        print(f"  coach new to this school (record earned elsewhere) r = "
              f"{np.corrcoef(moved.track, moved.surprise)[0, 1]:.3f} (n={len(moved)})")
    nc = d[d.new_coach == 1]
    print(f"Teams with a new coach: mean surprise {nc.surprise.mean():+.2f} (n={len(nc)}), "
          f"carry of last season {np.polyfit(nc.R_prev, nc.R, 1)[0]:.2f} vs {np.polyfit(d[d.new_coach == 0].R_prev, d[d.new_coach == 0].R, 1)[0]:.2f} with the same coach")

    tournament(c)
    df.to_csv(config.DATA_DIR / "factors" / "coach_study.csv", index=False)
    return out


def tournament(c: pd.DataFrame):
    """Coach's past NCAA tournament residuals (vs. team rating) -> this tournament."""
    t = pd.read_csv(HIST / "tournament_games.csv", dtype={"a": str, "b": str})
    ca = c.rename(columns={"team_id": "a", "coach_id": "coach_a"})[["season", "a", "coach_a"]]
    cb = c.rename(columns={"team_id": "b", "coach_id": "coach_b"})[["season", "b", "coach_b"]]
    t = t.merge(ca, on=["season", "a"], how="left").merge(cb, on=["season", "b"], how="left")
    long = pd.concat([t[["season", "coach_a", "resid"]].rename(columns={"coach_a": "coach"}),
                      t[["season", "coach_b", "resid"]].rename(columns={"coach_b": "coach"}).assign(resid=lambda x: -x.resid)]).dropna()
    def rep(coach, season, k=5, shrink=6.0):
        if pd.isna(coach):
            return 0.0, 0
        h = long[(long.coach == coach) & (long.season < season) & (long.season >= season - k)]
        return h.resid.sum() / (len(h) + shrink), len(h)
    ra = [rep(r.coach_a, r.season) for r in t.itertuples()]
    rb = [rep(r.coach_b, r.season) for r in t.itertuples()]
    t["rep"] = [x[0] - y[0] for x, y in zip(ra, rb)]
    t["rep_n"] = [x[1] + y[1] for x, y in zip(ra, rb)]
    d = t[t.season >= 2014]
    r0, r1, betas = loso(d.assign(y=d.resid), "y", ["rep"])
    w, n = per_season(d.assign(y=d.resid), "y", ["rep"])
    x = d.rep.to_numpy(); y = d.resid.to_numpy()
    beta = (x @ y) / (x @ x); se = np.sqrt(np.sum((y - beta * x) ** 2) / (len(x) - 1) / (x @ x))
    print(f"\nNCAA tournament, coach's past-5-year tournament record ({len(d)} games, {d.season.nunique()} tournaments):")
    print(f"  beta {beta:+.2f} (t = {beta / se:.1f}); held-out RMSE {r0:.3f} -> {r1:.3f}; helped {w}/{n} tournaments")


if __name__ == "__main__":
    main()
