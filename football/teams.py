"""Opponent-adjusted college football ratings and predictions.

One row per team per game (each offense against each defense):

    points scored = mu + O[offense] + D[defense] + h * H/2 + error

O is points scored above average against an average Division I defense; D is points
allowed above average (lower is better). Net = O - D is the expected margin against an
average Division I team on a neutral field. h is +1 for the home offense, -1 on the road,
0 at a neutral site, so H is the full home-field swing in points.

Bayesian ridge: each team's O and D get a normal prior centered on last season's rating,
games are weighted by recency, and optionally lopsided margins are damped so a 70-0 win
over a weak opponent doesn't count as 70 points of evidence.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config


def damp(home_pts, away_pts, cap: float | None):
    """Shrink margins beyond `cap` by half, keeping the total; None leaves scores as they are."""
    h, a = np.asarray(home_pts, float), np.asarray(away_pts, float)
    if not cap:
        return h, a
    m = h - a
    m2 = np.sign(m) * np.where(np.abs(m) > cap, cap + 0.5 * (np.abs(m) - cap), np.abs(m))
    t = h + a
    return (t + m2) / 2, (t - m2) / 2


def fit(games: pd.DataFrame, teams: pd.DataFrame, prior: dict | None = None, as_of: date | None = None,
        prior_games: float | None = None, half_life: float | None = None, cap: float | None = None) -> dict:
    """prior: {team_id: (O offset, D offset)} or {team_id: net}."""
    d1 = set(teams.team_id.astype(str))
    g = games.copy()
    for c in ("home_id", "away_id"):
        g[c] = g[c].astype(str).where(g[c].astype(str).isin(d1), "NON_D1")
    ids = sorted(set(g.home_id) | set(g.away_id) | d1)
    idx = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    as_of = as_of or pd.to_datetime(g.date).max().date()
    age = (pd.Timestamp(as_of) - pd.to_datetime(g.date)).dt.days.clip(lower=0).to_numpy()
    rec = 0.5 ** (age / (half_life or config.HALF_LIFE_DAYS))
    hp, ap = damp(g.home_pts, g.away_pts, cap)
    hflag = np.where(g.neutral.astype(bool), 0.0, 1.0)

    X = np.zeros((2 * len(g), 2 * n + 1))
    y = np.r_[hp, ap]
    r1, r2 = np.arange(len(g)), np.arange(len(g)) + len(g)
    X[r1, g.home_id.map(idx)] = 1; X[r1, n + g.away_id.map(idx)] = 1; X[r1, 2 * n] = hflag / 2
    X[r2, g.away_id.map(idx)] = 1; X[r2, n + g.home_id.map(idx)] = 1; X[r2, 2 * n] = -hflag / 2
    w = np.r_[rec, rec]
    mu = float(np.average(y, weights=w)) if len(y) else 28.0

    pm = np.zeros(2 * n + 1)
    for t, v in (prior or {}).items():
        if t in idx:
            o, d = (v if isinstance(v, (tuple, list)) else (v / 2, -v / 2))
            pm[idx[t]], pm[n + idx[t]] = o, d
    pm[2 * n] = config.HFA_PRIOR
    k = config.PRIOR_GAMES if prior_games is None else prior_games
    prec = np.r_[np.full(2 * n, k), config.HFA_PRIOR_GAMES * 0.5]  # each game is one row per side
    A = (X.T * w) @ X + np.diag(prec)
    b = (X.T * w) @ (y - mu - X @ pm)
    coef = pm + np.linalg.solve(A, b)
    O, D, H = coef[:n], coef[n:2 * n], coef[2 * n]

    # Margin spread from how far games landed from their fitted margins (actual, undamped scores)
    hi, ai = g.home_id.map(idx).to_numpy(), g.away_id.map(idx).to_numpy()
    pred = (O[hi] + D[ai] + hflag * H / 2) - (O[ai] + D[hi] - hflag * H / 2)
    act = (g.home_pts - g.away_pts).to_numpy(float)
    sd = float(np.sqrt(np.average((act - pred) ** 2, weights=rec)) * 1.08) if len(g) > 300 else config.MARGIN_SD
    resid = (y - mu) - X @ coef
    s2 = float(np.sum(w * resid ** 2) / max(len(y) - 2 * n, 1))
    cov = np.linalg.inv(A) * s2

    meta = teams.set_index(teams.team_id.astype(str))
    rec_wl = {}
    for side, pf, pa in (("home_id", "home_pts", "away_pts"), ("away_id", "away_pts", "home_pts")):
        for t, a, bb in zip(g[side], g[pf], g[pa]):
            w_, l_ = rec_wl.get(t, (0, 0))
            rec_wl[t] = (w_ + (a > bb), l_ + (a < bb))
    rows = []
    for t in ids:
        if t not in meta.index:
            continue
        i = idx[t]
        m = meta.loc[t]
        se = float(np.sqrt(max(cov[i, i] + cov[n + i, n + i] - 2 * cov[i, n + i], 0)))
        pv = (prior or {}).get(t)
        pnet = None if pv is None else (pv[0] - pv[1] if isinstance(pv, (tuple, list)) else pv)
        rows.append({"team_id": t, "name": m["name"], "short": m.get("short", m["name"]), "abbr": m.get("abbr", ""),
                     "conf": m.get("conf", "") if isinstance(m.get("conf", ""), str) else "",
                     "div": m.get("div", ""), "color": str(m.get("color", "888888")),
                     "off": mu + O[i], "dfn": mu + D[i], "net": O[i] - D[i], "net_se": se,
                     "wins": rec_wl.get(t, (0, 0))[0], "losses": rec_wl.get(t, (0, 0))[1], "pre": pnet})
    table = pd.DataFrame(rows).sort_values("net", ascending=False).reset_index(drop=True)
    table["rank"] = np.arange(1, len(table) + 1)
    return {"table": table, "idx": idx, "O": O, "D": D, "mu": mu, "hfa": float(H), "sd": sd}


def predict(m: dict, home: str, away: str, neutral: bool = False) -> dict:
    idx = m["idx"]
    hi, ai = idx.get(str(home), idx.get("NON_D1")), idx.get(str(away), idx.get("NON_D1"))
    if hi is None or ai is None:
        return {}
    h = 0.0 if neutral else 1.0
    hs = m["mu"] + m["O"][hi] + m["D"][ai] + h * m["hfa"] / 2
    as_ = m["mu"] + m["O"][ai] + m["D"][hi] - h * m["hfa"] / 2
    return {"home_score": hs, "away_score": as_, "margin": hs - as_, "home_win": float(norm.cdf((hs - as_) / m["sd"]))}


def last_season_prior(games: pd.DataFrame, teams: pd.DataFrame, keep: float | None = None, cap=None) -> dict:
    """Last season's final O/D offsets, multiplied by `keep` (regression toward average)."""
    keep = config.PRIOR_KEEP if keep is None else keep
    m = fit(games, teams, {}, prior_games=0.25, half_life=1e9, cap=cap)
    out = {t: (keep * m["O"][i], keep * m["D"][i]) for t, i in m["idx"].items()}
    if "NON_D1" in m["idx"]:  # non-Division I opponents keep their full (very negative) rating
        i = m["idx"]["NON_D1"]
        out["NON_D1"] = (m["O"][i], m["D"][i])
    return out
