"""Do distance, road/neutral form, or tournament reputation predict NCAA tournament results
beyond team ratings?   python -m tests.tournament_factors

For each tournament since 2012 (no 2020): fit margin ratings on that season's games before
the tournament, predict every tournament game at a neutral site, and ask whether each
factor explains what the ratings missed. Validation holds out one tournament at a time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from basketball import config

HIST = config.DATA_DIR / "history"
TOURNEY = 22


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * np.arcsin(np.sqrt(a))


def season_ratings(g: pd.DataFrame, lam: float = 2.0):
    """Margin ratings: margin = H * home + R[home] - R[away]. Returns ratings, H, residuals per team-game."""
    ids = sorted(set(g.home_id) | set(g.away_id))
    idx = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    X = np.zeros((len(g), n + 1))
    X[np.arange(len(g)), g.home_id.map(idx)] = 1
    X[np.arange(len(g)), g.away_id.map(idx)] = -1
    X[:, n] = np.where(g.neutral.astype(bool), 0, 1)
    y = (g.home_pts - g.away_pts).to_numpy(float)
    A = X.T @ X + np.diag(np.r_[np.full(n, lam), 1e-6])
    coef = np.linalg.solve(A, X.T @ y)
    R = dict(zip(ids, coef[:n]))
    resid = y - X @ coef
    # Each team's residual from its own side, split by venue type
    rows = pd.DataFrame({"team": np.r_[g.home_id, g.away_id], "resid": np.r_[resid, -resid],
                         "venue": np.r_[np.where(g.neutral, "neutral", "home"), np.where(g.neutral, "neutral", "road")]})
    return R, coef[n], rows


def build() -> pd.DataFrame:
    places = pd.read_csv(HIST / "places.csv")
    homes = pd.read_csv(HIST / "team_homes.csv", dtype={"team_id": str}).set_index("team_id")
    out = []
    for season in range(2012, 2027):
        p = HIST / f"scores_{season}.csv.gz"
        if not p.exists():
            continue
        s = pd.read_csv(p, dtype={"home_id": str, "away_id": str})
        s = s[(s.home_pts + s.away_pts) > 0]
        t = s[pd.to_numeric(s.tourney_id, errors="coerce") == TOURNEY]
        if t.empty:
            continue
        start = t.date.min()
        reg = s[s.date < start]
        R, H, resid = season_ratings(reg)
        # Road/neutral form: mean residual away from home minus at home (per team)
        piv = resid.assign(away=resid.venue != "home").groupby(["team", "away"]).resid.agg(["mean", "size"]).unstack()
        split = (piv["mean"][True] - piv["mean"][False]).rename("split")
        n_away = piv["size"][True].rename("n_away")
        t = t.merge(places, on=["city", "state"], how="left")
        for g in t.itertuples():
            a, b = g.home_id, g.away_id  # ESPN's listed "home" is arbitrary at neutral tournament sites
            if a not in R or b not in R:
                continue
            da = haversine(homes.lat.get(a, np.nan), homes.lon.get(a, np.nan), g.lat, g.lon)
            db = haversine(homes.lat.get(b, np.nan), homes.lon.get(b, np.nan), g.lat, g.lon)
            out.append({"season": season, "date": g.date, "game_id": g.game_id, "a": a, "b": b,
                        "pred": R[a] - R[b], "actual": g.home_pts - g.away_pts,
                        "dist_a": da, "dist_b": db,
                        "split_a": split.get(a, np.nan), "split_b": split.get(b, np.nan),
                        "nsplit_a": n_away.get(a, 0), "nsplit_b": n_away.get(b, 0)})
    df = pd.DataFrame(out)
    df["resid"] = df.actual - df.pred
    # Reputation: each program's average residual in its previous 4 tournaments (shrunk by game count)
    long = pd.concat([df[["season", "a", "resid"]].rename(columns={"a": "team"}),
                      df[["season", "b", "resid"]].rename(columns={"b": "team"}).assign(resid=lambda d: -d.resid)])
    def rep(team, season, k=4, shrink=6.0):
        h = long[(long.team == team) & (long.season < season) & (long.season >= season - k - (1 if season - k <= 2020 < season else 0))]
        return h.resid.sum() / (len(h) + shrink), len(h)
    reps = {(t, s): rep(t, s) for t, s in set(zip(df.a, df.season)) | set(zip(df.b, df.season))}
    df["rep_a"] = [reps[(t, s)][0] for t, s in zip(df.a, df.season)]
    df["rep_b"] = [reps[(t, s)][0] for t, s in zip(df.b, df.season)]
    df["rep_n"] = [min(reps[(a, s)][1], reps[(b, s)][1]) for a, b, s in zip(df.a, df.b, df.season)]
    return df


def features(df: pd.DataFrame) -> dict:
    d = {}
    d["distance (per 500 mi, a minus b)"] = (df.dist_a - df.dist_b) / 500
    la, lb = np.log1p(df.dist_a.clip(lower=0)), np.log1p(df.dist_b.clip(lower=0))
    d["log distance (a minus b)"] = la - lb
    d["within 150 mi (a minus b)"] = (df.dist_a < 150).astype(float) - (df.dist_b < 150).astype(float)
    d["road/neutral form (a minus b)"] = df.split_a.fillna(0) - df.split_b.fillna(0)
    d["tournament reputation (a minus b)"] = df.rep_a - df.rep_b
    return d


def loso(df: pd.DataFrame, x: pd.Series) -> tuple[float, float]:
    """Leave-one-season-out: fit resid = beta * x on other seasons, predict held-out season.
    Returns (MAE improvement in points per game, share of seasons improved)."""
    gains, better = [], 0
    for s in sorted(df.season.unique()):
        tr, te = df.season != s, df.season == s
        xs, ys = x[tr].to_numpy(), df.resid[tr].to_numpy()
        ok = np.isfinite(xs)
        beta = (xs[ok] @ ys[ok]) / (xs[ok] @ xs[ok])
        xt = np.nan_to_num(x[te].to_numpy())
        base = np.abs(df.resid[te]).mean()
        adj = np.abs(df.resid[te] - beta * xt).mean()
        gains.append(base - adj)
        better += adj < base
    return float(np.mean(gains)), better / len(gains)


def main():
    df = build()
    print(f"tournament games: {len(df)} over {df.season.nunique()} tournaments; "
          f"ratings miss by {df.resid.abs().mean():.2f} points on average; "
          f"actual = {np.polyfit(df.pred, df.actual, 1)[0]:.2f} x predicted")
    ok = df.dist_a.notna() & df.dist_b.notna()
    print(f"games with both distances: {ok.sum()}; median distance {np.nanmedian(np.r_[df.dist_a, df.dist_b]):.0f} mi")
    print(f"\n{'factor':<38}{'coef':>8}{'± se':>8}{'t':>7}{'held-out gain':>15}{'seasons better':>16}")
    for name, x in features(df[ok].reset_index(drop=True)).items():
        d = df[ok].reset_index(drop=True)
        m = np.isfinite(x)
        xs, ys = x[m].to_numpy(), d.resid[m].to_numpy()
        beta = (xs @ ys) / (xs @ xs)
        se = np.sqrt(np.sum((ys - beta * xs) ** 2) / (len(xs) - 1) / (xs @ xs))
        gain, share = loso(d, x)
        print(f"{name:<38}{beta:>8.2f}{se:>8.2f}{beta / se:>7.1f}{gain:>+15.3f}{share:>16.0%}")
    # Reputation only where both teams have real history
    d = df[ok & (df.rep_n >= 3)].reset_index(drop=True)
    x = d.rep_a - d.rep_b
    beta = (x @ d.resid) / (x @ x); se = np.sqrt(np.sum((d.resid - beta * x) ** 2) / (len(x) - 1) / (x @ x))
    print(f"\nreputation, both teams with 3+ recent tournament games: n={len(d)}, coef {beta:.2f} ± {se:.2f}")
    # 2021 was played entirely in Indiana: check distance without it
    d = df[ok & (df.season != 2021)].reset_index(drop=True)
    x = (d.dist_a - d.dist_b) / 500
    beta = (x @ d.resid) / (x @ x); se = np.sqrt(np.sum((d.resid - beta * x) ** 2) / (len(x) - 1) / (x @ x))
    print(f"distance per 500 mi without 2021 bubble: coef {beta:.2f} ± {se:.2f}")
    df.to_csv(HIST / "tournament_games.csv", index=False)


if __name__ == "__main__":
    main()
