"""Opponent-adjusted team ratings and game predictions.

Model (one row per team per game, i.e. each offense facing each defense):

    100 * points / possessions = mu + O[offense] + D[defense] + h * H/2 + error

h is +1 when the offense is at home, -1 on the road, 0 at a neutral site, so H is the
full home-court swing in points per 100 possessions. O is points scored above average
against an average defense; D is points allowed above average (lower is better).

We solve it as Bayesian ridge regression: each team's O and D get a normal prior centered
on last season's rating (regressed toward average), and each game is weighted by its
possessions and by recency. Tempo gets the same treatment:

    possessions = tau + T[home] + T[away] + error
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config


def _solve(X, y, w, prior_mean, prior_prec):
    """Posterior mean of weighted ridge with a per-coefficient normal prior."""
    A = (X.T * w) @ X + np.diag(prior_prec)
    b = (X.T * w) @ (y - X @ prior_mean)
    return prior_mean + np.linalg.solve(A, b), A


def prior_from_last_season(prior_scores: pd.DataFrame | None, team_ids: list[str]) -> dict:
    """Net rating per 100 from last season's margins, regressed toward average."""
    if prior_scores is None or prior_scores.empty:
        return {}
    df = prior_scores.copy()
    df["home_id"], df["away_id"] = df.home_id.astype(str), df.away_id.astype(str)
    ids = sorted(set(df.home_id) | set(df.away_id))
    idx = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    X = np.zeros((len(df), n + 1))
    X[np.arange(len(df)), df.home_id.map(idx)] = 1
    X[np.arange(len(df)), df.away_id.map(idx)] = -1
    X[:, n] = np.where(df.neutral.astype(bool), 0, 1)
    y = (df.home_pts - df.away_pts).to_numpy(float) * 100 / 68.0  # per 100 at typical tempo
    coef, _ = _solve(X, y, np.ones(len(df)), np.zeros(n + 1), np.r_[np.full(n, 2.0), 0.01])
    net = coef[:n] - coef[:n].mean()
    return {t: config.TEAM_PRIOR_REGRESS * net[idx[t]] for t in ids if t in set(team_ids)}


def fit(games: pd.DataFrame, box: pd.DataFrame, teams: pd.DataFrame,
        prior_net: dict | None = None, as_of: date | None = None) -> dict:
    """Return ratings table plus everything needed to predict a game."""
    d1 = set(teams.team_id.astype(str))
    g = games.copy()
    for c in ("home_id", "away_id"):
        g[c] = g[c].astype(str).where(g[c].astype(str).isin(d1), "NON_D1")  # pool non-D-I opponents

    # Possessions per game from team box totals (FGA - OREB + TO + 0.475 FTA, averaged over both teams)
    tb = box.groupby(["game_id", "team_id"])[["fga", "oreb", "tov", "fta"]].sum()
    tb["poss"] = tb.fga - tb.oreb + tb.tov + 0.475 * tb.fta
    poss = tb.groupby("game_id").poss.mean()
    if "poss" not in g:  # real data: possessions from box totals; the simulator supplies its own
        g["poss"] = g.game_id.astype(str).map(poss.rename(lambda x: str(x)))
    g["poss"] = g.poss.where(g.poss > 40, np.nan).fillna(poss.median() if len(poss) else 68.0)

    ids = sorted(set(g.home_id) | set(g.away_id) | d1)
    idx = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    as_of = as_of or pd.to_datetime(g.date).max().date()
    age = (pd.Timestamp(as_of) - pd.to_datetime(g.date)).dt.days.clip(lower=0).to_numpy()
    recency = 0.5 ** (age / config.TEAM_HALF_LIFE_DAYS)

    # Efficiency: two rows per game
    rows = len(g) * 2
    X = np.zeros((rows, 2 * n + 1))
    y = np.zeros(rows)
    w = np.zeros(rows)
    hflag = np.where(g.neutral.astype(bool), 0.0, 1.0)
    for k, (off, de, pts, sign) in enumerate([("home_id", "away_id", "home_pts", 1), ("away_id", "home_id", "away_pts", -1)]):
        r = np.arange(len(g)) + k * len(g)
        X[r, g[off].map(idx)] = 1
        X[r, n + g[de].map(idx)] = 1
        X[r, 2 * n] = sign * hflag / 2
        y[r] = 100 * g[pts].to_numpy(float) / g.poss.to_numpy()
        w[r] = g.poss.to_numpy() * recency
    mu = np.average(y, weights=w)
    prior_net = prior_net or {}
    prior_mean = np.zeros(2 * n + 1)
    for t, net in prior_net.items():
        if t in idx:
            prior_mean[idx[t]], prior_mean[n + idx[t]] = net / 2, -net / 2
    # Row weights are possessions, so the prior is worth TEAM_PRIOR_GAMES games of ~68 possessions.
    prec = config.TEAM_PRIOR_GAMES * 68.0
    # Home court gets its own prior: early in the season, when strong teams host weak ones,
    # the data can't separate "good team" from "home floor". Each game carries ~68 * 2 * 0.25 = 34
    # units of information about H, so the prior is worth HCA_PRIOR_GAMES games.
    prior_mean[2 * n] = config.HCA_PRIOR
    prior_prec = np.r_[np.full(2 * n, prec), config.HCA_PRIOR_GAMES * 34.0]
    coef, A = _solve(X, y - mu, w, prior_mean, prior_prec)
    O, D, hca = coef[:n], coef[n:2 * n], coef[2 * n]

    # Error variance of a row is s2 / weight; posterior covariance is s2 * A^-1
    resid = (y - mu) - X @ coef
    s2 = float(np.sum(w * resid ** 2) / max(len(y) - 2 * n, 1))
    cov = np.linalg.inv(A) * s2

    # Tempo
    Xt = np.zeros((len(g), n))
    Xt[np.arange(len(g)), g.home_id.map(idx)] = 1
    Xt[np.arange(len(g)), g.away_id.map(idx)] = 1
    tau = g.poss.mean()
    T, _ = _solve(Xt, g.poss.to_numpy() - tau, recency, np.zeros(n), np.full(n, 2.0))

    # Margin noise from how well ratings explain past games (inflated for out-of-sample use)
    pm = predict_margin_raw(g.home_id.map(idx).to_numpy(), g.away_id.map(idx).to_numpy(), hflag, O, D, T, mu, tau, hca)
    actual = (g.home_pts - g.away_pts).to_numpy(float)
    sd = float(np.sqrt(np.average((actual - pm) ** 2, weights=recency)) * 1.08) if len(g) > 200 else config.MARGIN_SD

    team_meta = teams.set_index(teams.team_id.astype(str))
    rec = {}
    for side, pts_for, pts_ag in (("home_id", "home_pts", "away_pts"), ("away_id", "away_pts", "home_pts")):
        for t, a, b in zip(g[side], g[pts_for], g[pts_ag]):
            w_, l_ = rec.get(t, (0, 0))
            rec[t] = (w_ + (a > b), l_ + (a < b))
    out = []
    for t in ids:
        if t not in team_meta.index:
            continue
        i = idx[t]
        se = float(np.sqrt(max(cov[i, i] + cov[n + i, n + i] - 2 * cov[i, n + i], 0)))
        m = team_meta.loc[t]
        out.append({"team_id": t, "name": m["name"], "short": m.get("short", m["name"]), "abbr": m.get("abbr", ""),
                    "conf": m.get("conf", "") if isinstance(m.get("conf", ""), str) else "",
                    "color": str(m.get("color", "888888")),
                    "adj_o": mu + O[i], "adj_d": mu + D[i], "net": O[i] - D[i], "net_se": se,
                    "tempo": tau + 2 * T[i], "wins": rec.get(t, (0, 0))[0], "losses": rec.get(t, (0, 0))[1],
                    "prior_net": prior_net.get(t)})
    table = pd.DataFrame(out).sort_values("net", ascending=False).reset_index(drop=True)
    table["rank"] = np.arange(1, len(table) + 1)
    return {"table": table, "idx": idx, "O": O, "D": D, "T": T, "mu": mu, "tau": tau, "hca": hca, "sd": sd}


def predict_margin_raw(hi, ai, hflag, O, D, T, mu, tau, hca):
    poss = tau + T[hi] + T[ai]
    home = mu + O[hi] + D[ai] + hflag * hca / 2
    away = mu + O[ai] + D[hi] - hflag * hca / 2
    return poss * (home - away) / 100


def predict(model: dict, home_id: str, away_id: str, neutral: bool = False) -> dict:
    idx = model["idx"]
    hi, ai = idx.get(str(home_id), idx.get("NON_D1")), idx.get(str(away_id), idx.get("NON_D1"))
    if hi is None or ai is None:
        return {}
    h = 0.0 if neutral else 1.0
    O, D, T = model["O"], model["D"], model["T"]
    poss = model["tau"] + T[hi] + T[ai]
    hs = poss * (model["mu"] + O[hi] + D[ai] + h * model["hca"] / 2) / 100
    as_ = poss * (model["mu"] + O[ai] + D[hi] - h * model["hca"] / 2) / 100
    return {"home_score": hs, "away_score": as_, "poss": poss, "margin": hs - as_,
            "home_win": float(norm.cdf((hs - as_) / model["sd"]))}
