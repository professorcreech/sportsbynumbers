"""Which extra factors improve predictions?   SBN_LEAGUE=ncaam|nba python -m tests.factors [season]

Step 1 (baseline): replay a season from opening night to the final. Each morning the
production model refits on everything played so far and predicts that day's games.

Step 2 (factors): for each candidate, compute a per-game feature from information available
before tip-off, then ask whether it explains what the baseline missed:
    actual margin - predicted margin = beta * feature + noise
beta is fit on the first half of the season and judged on the second half (and the other way
round), so a factor only "works" if it helps on games it wasn't fit to.
"""
from __future__ import annotations

import sys
import time
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

from basketball import bracket as B, config, preseason as P, run, teams

OUT = config.DATA_DIR / "factors"


# --------------------------------------------------------------------------- baseline

def baseline(season: int, half_life: float | None = None, label: str = "base") -> pd.DataFrame:
    path = OUT / f"walkforward_{season}_{label}.csv"
    if path.exists():
        return pd.read_csv(path, dtype={"game_id": str, "home_id": str, "away_id": str})
    OUT.mkdir(parents=True, exist_ok=True)
    tm, games, box, *_ = run.load(season)
    games = games[games.completed.astype(bool)].sort_values("date")
    prior, _ = P.build_prior(season, None, box)
    saved = config.TEAM_HALF_LIFE_DAYS
    if half_life:
        config.TEAM_HALF_LIFE_DAYS = half_life
    rows, t0 = [], time.time()
    try:
        for day in sorted(games.date.unique())[1:]:
            tr, te = games[games.date < day], games[games.date == day]
            m = teams.fit(tr, box[box.game_id.isin(tr.game_id)], tm, prior, as_of=date.fromisoformat(day),
                          prior_games=config.PRESEASON_GAMES)
            idx = m["idx"]
            for g in te.itertuples():
                p = teams.predict(m, g.home_id, g.away_id, bool(g.neutral))
                if not p:
                    continue
                hi, ai = idx.get(g.home_id, idx.get("NON_D1")), idx.get(g.away_id, idx.get("NON_D1"))
                rows.append({"game_id": g.game_id, "date": day, "home_id": g.home_id, "away_id": g.away_id,
                             "neutral": bool(g.neutral), "pred": p["margin"], "poss": p["poss"], "p_home": p["home_win"],
                             "sd": m["sd"], "actual": g.home_pts - g.away_pts,
                             "net_home": m["O"][hi] - m["D"][hi], "net_away": m["O"][ai] - m["D"][ai],
                             "tempo_home": m["T"][hi], "tempo_away": m["T"][ai]})
    finally:
        config.TEAM_HALF_LIFE_DAYS = saved
    df = pd.DataFrame(rows)
    df["resid"] = df.actual - df.pred
    df.to_csv(path, index=False)
    print(f"baseline {label}: {len(df)} games in {time.time() - t0:.0f}s")
    return df


def metrics(df: pd.DataFrame, pred_col="pred", sd=None) -> dict:
    sd = df.sd if sd is None else sd
    p = norm.cdf(df[pred_col] / sd).clip(0.01, 0.99)
    y = (df.actual > 0).astype(float)
    return {"games": len(df), "mae": float((df.actual - df[pred_col]).abs().mean()),
            "correct": float(((df[pred_col] > 0) == (df.actual > 0)).mean()),
            "log_loss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())}


# --------------------------------------------------------------------------- evaluation

def evaluate(df: pd.DataFrame, feature: pd.Series, name: str, min_games: int = 200) -> dict:
    """Fit residual ~ beta * feature on one half of the season, judge on the other half, both ways."""
    d = df.assign(f=feature.values).dropna(subset=["f"])
    d = d[d.f != 0] if (d.f == 0).mean() > 0.5 else d  # sparse features: judge only games where they apply
    if len(d) < min_games:
        return {"factor": name, "games": len(d), "note": "too few games"}
    mid = d.date.sort_values().iloc[len(d) // 2]
    halves = [d[d.date < mid], d[d.date >= mid]]
    gains, ll_gains = [], []
    for fit_on, test_on in ((0, 1), (1, 0)):
        a, b = halves[fit_on], halves[test_on]
        beta = float((a.f * a.resid).sum() / (a.f ** 2).sum())
        adj = b.assign(pred2=b.pred + beta * b.f)
        m0, m1 = metrics(adj), metrics(adj, "pred2")
        gains.append(m0["mae"] - m1["mae"])
        ll_gains.append(m0["log_loss"] - m1["log_loss"])
    beta = float((d.f * d.resid).sum() / (d.f ** 2).sum())
    se = float(np.sqrt(((d.resid - beta * d.f) ** 2).sum() / (len(d) - 1) / (d.f ** 2).sum()))
    return {"factor": name, "games": len(d), "beta": beta, "t": beta / se,
            "mae_gain_h1": gains[1], "mae_gain_h2": gains[0], "ll_gain_h1": ll_gains[1], "ll_gain_h2": ll_gains[0],
            "consistent": all(g > 0 for g in gains + ll_gains)}


# --------------------------------------------------------------------------- features

def schedule_features(df: pd.DataFrame, season: int) -> dict:
    """Rest, travel and body clock, from each team's previous game (any opponent)."""
    tm, games, *_ = run.load(season)
    games = games[games.completed.astype(bool)]
    hist = config.DATA_DIR / "history" / f"scores_{season}.csv.gz"
    places = pd.read_csv(config.DATA_DIR / "history" / "places.csv") if (config.DATA_DIR / "history" / "places.csv").exists() else None
    homes = B.team_homes()
    venue = {}
    start = {}
    if hist.exists() and places is not None:
        h = pd.read_csv(hist, dtype={"game_id": str}).merge(places, on=["city", "state"], how="left")
        venue = {g: (la, lo) for g, la, lo in zip(h.game_id, h.lat, h.lon) if not np.isnan(la)}
        start = dict(zip(h.game_id, h.start))
    if "start" in games:
        start.update({g: s for g, s in zip(games.game_id, games.start) if isinstance(s, str)})
    long = pd.concat([games[["game_id", "date", "home_id"]].rename(columns={"home_id": "team"}),
                      games[["game_id", "date", "away_id"]].rename(columns={"away_id": "team"})]).sort_values("date")
    long["prev_date"] = long.groupby("team").date.shift(1)
    long["prev_game"] = long.groupby("team").game_id.shift(1)
    key = long.set_index(["game_id", "team"])
    home_of = dict(zip(games.game_id, games.home_id))
    out = {k: [] for k in ("rest", "b2b", "travel", "tz_shift", "early_body")}
    for g in df.itertuples():
        vals = {}
        for side, t in (("h", g.home_id), ("a", g.away_id)):
            try:
                r = key.loc[(g.game_id, t)]
            except KeyError:
                vals[side] = None
                continue
            rest = (pd.Timestamp(g.date) - pd.Timestamp(r.prev_date)).days if isinstance(r.prev_date, str) else 7
            here = venue.get(g.game_id) or (homes.get(g.home_id) if not g.neutral else None)
            there = None
            if isinstance(r.prev_game, str):  # previous game's site, or its home team's arena
                there = venue.get(r.prev_game) or homes.get(home_of.get(r.prev_game))
            dist = B.haversine(there[0], there[1], here[0], here[1]) if here and there else np.nan
            home_lon = homes.get(t, (0, np.nan))[1]
            tz_home = round(home_lon / 15) if not np.isnan(home_lon) else np.nan
            tz_here = round(here[1] / 15) if here else tz_home
            st = start.get(g.game_id)
            body = np.nan
            if isinstance(st, str) and len(st) >= 13 and not np.isnan(tz_home):
                body = (int(st[11:13]) + tz_home) % 24  # tip-off hour on the team's home clock
            vals[side] = (min(rest, 7), float(rest <= 1), np.log1p(dist) if not np.isnan(dist) else np.nan,
                          (tz_here - tz_home) if not np.isnan(tz_home) else np.nan, float(body < 13) if not np.isnan(body) else np.nan)
        for i, k in enumerate(out):
            h, a = vals.get("h"), vals.get("a")
            out[k].append(h[i] - a[i] if h is not None and a is not None else np.nan)
    return {k: pd.Series(v) for k, v in out.items()}


def form_features(df: pd.DataFrame) -> dict:
    """Hot/cold streaks and team-specific home court, from residuals of games already played."""
    long = pd.concat([pd.DataFrame({"i": df.index, "date": df.date, "team": df.home_id, "res": df.resid, "home": ~df.neutral}),
                      pd.DataFrame({"i": df.index, "date": df.date, "team": df.away_id, "res": -df.resid, "home": False})]).sort_values(["date", "i"])
    hot = {}
    hca = {}
    for t, g in long.groupby("team"):
        r = g.res.to_numpy()
        prev5 = pd.Series(r).shift(1).rolling(5, min_periods=3).mean().to_numpy()
        # home minus away residual so far, shrunk toward zero (10 games' worth of prior at 0)
        hr = pd.Series(np.where(g.home, r, np.nan)).shift(1).expanding().agg(lambda x: np.nansum(x)).to_numpy()
        hn = pd.Series(g.home.astype(float).to_numpy()).shift(1).expanding().sum().to_numpy()
        ar = pd.Series(np.where(~g.home, r, np.nan)).shift(1).expanding().agg(lambda x: np.nansum(x)).to_numpy()
        an = pd.Series((~g.home).astype(float).to_numpy()).shift(1).expanding().sum().to_numpy()
        team_hca = hr / (hn + 10) - ar / (an + 10)
        for i, p5, th in zip(g.i, prev5, team_hca):
            hot.setdefault(i, {})[t] = p5
            hca.setdefault(i, {})[t] = th
    hot_f = [hot[i].get(h, np.nan) - hot[i].get(a, np.nan) for i, h, a in zip(df.index, df.home_id, df.away_id)]
    hca_f = [hca[i].get(h, np.nan) if not n else 0.0 for i, h, n in zip(df.index, df.home_id, df.neutral)]
    return {"hot_last5": pd.Series(hot_f), "team_home_court": pd.Series(hca_f)}


def availability_feature(df: pd.DataFrame, season: int) -> pd.Series:
    """Rating points missing because rotation players sat out. Uses each player's full-season
    rating as his value and his minutes so far as his role (players with 10+ mpg so far)."""
    tm, games, box, *_ = run.load(season)
    pl = P.player_season(season).set_index("player_id")
    box = box.merge(games[["game_id", "date"]], on="game_id")
    box = box.sort_values("date")
    out = []
    played = {gid: set(g.player_id) for gid, g in box.groupby("game_id")}
    by_team = {t: g for t, g in box.groupby("team_id")}
    cache = {}
    for g in df.itertuples():
        miss = {}
        for t in (g.home_id, g.away_id):
            hist = by_team.get(t)
            if hist is None:
                miss[t] = np.nan
                continue
            before = hist[hist.date < g.date]
            if before.game_id.nunique() < 3:
                miss[t] = np.nan
                continue
            mpg = before.groupby("player_id")["min"].sum() / before.game_id.nunique()
            rot = mpg[mpg >= 10]
            out_now = [p for p in rot.index if p not in played.get(g.game_id, set())]
            miss[t] = sum(rot[p] / 40 * pl.total.get(p, 0.0) for p in out_now)  # points per 100 lost
        out.append((miss[g.home_id] - miss[g.away_id]) * g.poss / 100 if not np.isnan(miss[g.home_id]) and not np.isnan(miss[g.away_id]) else np.nan)
    return pd.Series(out)


def main(season: int = 2026):
    df = baseline(season)
    print(f"\n== {config.LEAGUE} {season}: baseline over {len(df)} games ==")
    print({k: round(v, 3) for k, v in metrics(df).items()})
    feats = {}
    feats.update(schedule_features(df, season))
    feats.update(form_features(df))
    feats["availability"] = -availability_feature(df, season)  # missing value hurts that team
    res = [evaluate(df, f, n) for n, f in feats.items()]
    # Recency: whole baseline reruns with other half-lives
    for hl in (20, 40, 90, 180):
        alt = baseline(season, hl, f"hl{hl}")
        m0, m1 = metrics(df.merge(alt[["game_id"]], on="game_id")), metrics(alt)
        res.append({"factor": f"recency half-life {hl}d (vs 60)", "games": len(alt), "mae_gain_h1": m0["mae"] - m1["mae"],
                    "ll_gain_h1": m0["log_loss"] - m1["log_loss"]})
    pd.set_option("display.width", 220)
    print(pd.DataFrame(res).round(4).to_string(index=False))
    pd.DataFrame(feats).assign(game_id=df.game_id).to_csv(OUT / f"features_{season}.csv", index=False)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)


def style_features(df: pd.DataFrame, season: int, cut: str = "2026-01-15") -> dict:
    """Matchup interactions from team profiles built on games before `cut` (applied after it)."""
    from basketball import scouting
    tm, games, box, *_ = run.load(season)
    early = games[games.date < cut]
    shots = run.load_shots(season)
    prof = scouting.team_profiles(early, box[box.game_id.isin(early.game_id)],
                                  shots[shots.game_id.isin(early.game_id)] if shots is not None else None, set(tm.team_id))
    L, T = prof["league"], prof["teams"]
    z = lambda t, k: (T.get(t, {}).get(k) - L[k]["mean"]) / L[k]["sd"] if T.get(t, {}).get(k) is not None and k in L else np.nan
    pairs = {"threes_vs_perimeter_D": ("three_rate", "d_three_pct", 1), "rim_vs_rim_protection": ("rim_rate", "d_rim_pct", 1),
             "glass_vs_defensive_rebounding": ("orb", "d_orb", 1), "turnover_prone_vs_pressure": ("tov", "d_tov", -1),
             "free_throws_vs_fouling": ("ftr", "d_ftr", 1)}
    out = {}
    late = df.date >= cut
    for name, (o, d, sign) in pairs.items():
        f = [sign * (z(h, o) * z(a, d) - z(a, o) * z(h, d)) if l else np.nan for h, a, l in zip(df.home_id, df.away_id, late)]
        out[name] = pd.Series(f)
    out["pace_mismatch_favorite"] = pd.Series(np.where(late, np.sign(df.pred) * (df.tempo_home - df.tempo_away), np.nan))
    return out


def market_test(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Model vs. the betting line on the same games, and the best blend (weights fit on the other half)."""
    tm, games, *_ = run.load(season)
    g = games.dropna(subset=["line_spread"])[["game_id", "line_spread"]]
    d = df.merge(g, on="game_id")
    d["market"] = -d.line_spread  # spread is quoted from the home side
    mid = d.date.sort_values().iloc[len(d) // 2]
    rows = []
    for name, col in (("model", "pred"), ("market", "market")):
        rows.append({"predictor": name, **metrics(d, col)})
    blends = []
    for fit_on, test_on in ((d[d.date < mid], d[d.date >= mid]), (d[d.date >= mid], d[d.date < mid])):
        X = np.c_[fit_on.pred, fit_on.market]
        w = np.linalg.lstsq(X, fit_on.actual, rcond=None)[0]
        t = test_on.assign(blend=w[0] * test_on.pred + w[1] * test_on.market)
        blends.append((t, w))
    t = pd.concat([b[0] for b in blends])
    rows.append({"predictor": f"blend (model weight {np.mean([b[1][0] for b in blends]):.2f}, market {np.mean([b[1][1] for b in blends]):.2f})", **metrics(t, "blend")})
    # where the model disagrees with the market by 3+ points: who was closer?
    big = d[(d.pred - d.market).abs() >= 3]
    rows.append({"predictor": f"disagreements of 3+ pts: model closer in {((big.actual - big.pred).abs() < (big.actual - big.market).abs()).mean():.0%} of {len(big)} games"})
    return pd.DataFrame(rows)


def halftime_test(df: pd.DataFrame, season: int) -> dict:
    """Is 'better after halftime' a stable team trait? Split-half reliability and predictive tests."""
    tm, games, *_ = run.load(season)
    g = games.dropna(subset=["home_periods", "away_periods"]).copy()
    def halves(s):
        x = [int(v) for v in str(s).split("|") if v.lstrip("-").isdigit()]
        n = 2 if not config.IS_NBA else 4
        if len(x) < n:
            return None, None
        return (sum(x[:n // 2]), sum(x[n // 2:n]))  # regulation halves only; overtime excluded
    hh = g.home_periods.map(halves); ah = g.away_periods.map(halves)
    g["h1"] = [a[0] - b[0] if a[0] is not None and b[0] is not None else np.nan for a, b in zip(hh, ah)]
    g["h2"] = [a[1] - b[1] if a[1] is not None and b[1] is not None else np.nan for a, b in zip(hh, ah)]
    g = g.dropna(subset=["h1", "h2"]).sort_values("date")
    long = pd.concat([pd.DataFrame({"team": g.home_id, "date": g.date, "game_id": g.game_id, "adj": g.h2 - g.h1}),
                      pd.DataFrame({"team": g.away_id, "date": g.date, "game_id": g.game_id, "adj": -(g.h2 - g.h1)})])
    long["n"] = long.groupby("team").cumcount()
    odd = long[long.n % 2 == 1].groupby("team").adj.mean(); even = long[long.n % 2 == 0].groupby("team").adj.mean()
    both = pd.concat([odd, even], axis=1, keys=["odd", "even"]).dropna()
    reliability = float(both.odd.corr(both.even))
    # Pregame: does a team's past 2nd-half-minus-1st-half edge predict the final margin beyond the ratings?
    long = long.sort_values(["date", "game_id"])
    long["past"] = long.groupby("team").adj.transform(lambda x: x.shift(1).expanding().mean())
    long["past_n"] = long.groupby("team").adj.transform(lambda x: x.shift(1).expanding().count())
    past = long.assign(past=long.past * long.past_n / (long.past_n + 10)).set_index(["game_id", "team"]).past  # shrunk
    f = [past.get((gid, h), np.nan) - past.get((gid, a), np.nan) for gid, h, a in zip(df.game_id, df.home_id, df.away_id)]
    pregame = evaluate(df, pd.Series(f), "second-half tendency (pregame)")
    # In-game: at halftime, does the tendency predict the 2nd half beyond ratings and the score?
    d = df.merge(g[["game_id", "h1", "h2"]], on="game_id")
    d["resid2"] = d.h2 - d.pred / 2  # second-half margin vs. half the pregame expectation
    f2 = pd.Series([past.get((gid, h), np.nan) - past.get((gid, a), np.nan) for gid, h, a in zip(d.game_id, d.home_id, d.away_id)])
    d2 = d.assign(resid=d.resid2, pred=d.pred / 2, actual=d.h2)
    ingame = evaluate(d2, f2, "second-half tendency (at halftime, 2nd-half margin)")
    # Does trailing at the half predict a better 2nd half (regression to the mean / adjustments)?
    slope = float(np.polyfit(d.h1 - d.pred / 2, d.h2 - d.pred / 2, 1)[0])
    return {"teams": len(both), "split_half_reliability": round(reliability, 3), "pregame": pregame, "in_game": ingame,
            "first_half_surprise_carryover": round(slope, 3)}
