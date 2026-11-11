"""Player impact ratings (Bayesian regularized plus-minus) and lineup tables.

Every stint gives two observations: home offense vs away defense, and the reverse.

    100 * points / possessions - mu = sum(Off[5 offensive players])
                                     + sum(Def[5 defensive players]) + h * H/2 + error

Def here is points *allowed* above average, so we report -Def as the defensive rating
(positive = better). With hundreds of thousands of stints but heavy collinearity between
teammates, plain regression is unstable, so each player gets a normal prior:

    Off[p] ~ N(box_off[p], 1/lambda),   Def[p] ~ N(box_def[p], 1/lambda)

box_off / box_def come from a box-score model that is itself fit to a first pass of the
plus-minus regression, so the prior learns which box stats predict on-court impact. The
posterior mean is

    beta = prior + (X'WX + lambda I)^-1 X'W (y - X prior)

which keeps low-minute players near what their box score suggests and lets high-minute
players' on-court results dominate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import cg

from . import config

OFF_STATS = ["pts", "fga", "fta", "tpm", "ast", "tov", "oreb"]
DEF_STATS = ["stl", "blk", "dreb", "pf"]


def _design(stints: pd.DataFrame, pidx: dict):
    """Sparse design: columns [Off players | Def players | home]."""
    n = len(pidx)
    rows, cols, vals = [], [], []
    y, w, h = [], [], []
    r = 0
    for st in stints.itertuples(index=False):
        hp, ap = st.home_players.split(), st.away_players.split()
        hflag = 0.0 if st.neutral else 1.0
        for off, de, pts, sign in ((hp, ap, st.home_pts, 1), (ap, hp, st.away_pts, -1)):
            for p in off:
                rows.append(r); cols.append(pidx[p]); vals.append(1.0)
            for p in de:
                rows.append(r); cols.append(n + pidx[p]); vals.append(1.0)
            rows.append(r); cols.append(2 * n); vals.append(sign * hflag / 2)
            y.append(100.0 * pts / st.poss)
            w.append(st.poss)
            r += 1
    X = sparse.csr_matrix((vals, (rows, cols)), shape=(r, 2 * n + 1))
    return X, np.array(y), np.array(w)


def _posterior(X, y, w, prior, lam):
    W = sparse.diags(w)
    A = (X.T @ W @ X) + sparse.diags(np.r_[np.full(X.shape[1] - 1, lam), 1e-3])
    b = X.T @ (w * (y - X @ prior))
    delta, _ = cg(A, b, rtol=1e-8, maxiter=5000)
    return prior + delta


def box_rates(box: pd.DataFrame) -> pd.DataFrame:
    agg = box.groupby("player_id").agg(
        name=("name", "last"), team_id=("team_id", "last"), pos=("pos", "last"), gp=("game_id", "nunique"),
        min=("min", "sum"), **{s: (s, "sum") for s in set(OFF_STATS + DEF_STATS) | {"fgm", "ftm", "tpa"}})
    m = agg["min"].clip(lower=1)
    for s in set(OFF_STATS + DEF_STATS):
        agg[s + "_40"] = agg[s] * 40 / m
    agg["ts"] = agg.pts / (2 * (agg.fga + 0.44 * agg.fta)).replace(0, np.nan)
    return agg


MIN_STINTS_PER_GAME = 8  # fewer means the feed lacked substitutions for that game


def usable(stints: pd.DataFrame) -> pd.DataFrame:
    """Drop games whose lineup data is too sparse to trust (see parse.parse_stints)."""
    n = stints.groupby("game_id").game_id.transform("size")
    return stints[(n >= MIN_STINTS_PER_GAME) & (stints.poss > 0)]


def _core(stints: pd.DataFrame, box: pd.DataFrame, lam: float):
    stints = usable(stints)
    players = sorted({p for col in ("home_players", "away_players") for s in stints[col].astype(str) for p in s.split()})
    pidx = {p: i for i, p in enumerate(players)}
    n = len(players)
    X, y, w = _design(stints, pidx)
    mu = np.average(y, weights=w)
    y = y - mu

    # Pass 1: shrink toward zero, then learn a box-score prior from it
    first = _posterior(X, y, w, np.zeros(2 * n + 1), lam)
    rates = box_rates(box).reindex(players)
    poss_on = np.asarray(abs(X[:, :n]).T @ w).ravel()  # offensive possessions played
    prior = np.zeros(2 * n + 1)
    for cols, part in ((OFF_STATS, slice(0, n)), (DEF_STATS, slice(n, 2 * n))):
        F = rates[[c + "_40" for c in cols]].fillna(0).to_numpy()
        F = np.c_[np.ones(len(F)), F]
        sw = np.sqrt(poss_on)
        coef = np.linalg.lstsq(F * sw[:, None], first[part] * sw, rcond=None)[0]
        prior[part] = F @ coef
        prior[part] -= np.average(prior[part], weights=poss_on + 1)  # average player = 0

    # Pass 2: full posterior with the informed prior
    beta = _posterior(X, y, w, prior, lam)
    return beta, prior, pidx, mu, poss_on, rates


def tune_lambda(stints: pd.DataFrame, box: pd.DataFrame, grid=(250, 500, 1000, 2000, 4000, 8000, 16000)) -> float:
    """Pick the ridge strength that best predicts scoring in held-out games (1 in 5)."""
    stints = usable(stints)
    games = stints.game_id.astype(str).unique()
    test_ids = set(games[np.arange(len(games)) % 5 == 0])
    is_test = stints.game_id.astype(str).isin(test_ids)
    train, test = stints[~is_test], stints[is_test & (stints.poss > 0)]
    best, best_err = None, np.inf
    for lam in grid:
        beta, _, pidx, mu, _, _ = _core(train, box, lam)
        n = len(pidx)
        known = test[test.home_players.map(lambda s: all(p in pidx for p in s.split()))
                     & test.away_players.map(lambda s: all(p in pidx for p in s.split()))]
        X, y, w = _design(known, pidx)
        err = np.average((y - mu - X @ beta) ** 2, weights=w)
        print(f"  lambda {lam:>6}: held-out error {err:.2f}")
        if err < best_err:
            best, best_err = lam, err
    return float(best)


def fit(stints: pd.DataFrame, box: pd.DataFrame, lam: float | None = None) -> pd.DataFrame:
    stints = stints.astype({"home_players": str, "away_players": str})
    lam = lam or config.PLAYER_LAMBDA
    beta, prior, pidx, mu, poss_on, rates = _core(stints, box, lam)
    n = len(pidx)
    out = rates.copy()
    out["poss"] = poss_on
    out["off"] = beta[:n]
    out["def"] = -beta[n:2 * n]          # flip so positive = better defender
    out["total"] = out.off + out["def"]
    out["prior_off"] = prior[:n]
    out["prior_def"] = -prior[n:2 * n]
    out["impact"] = out.total * out.poss / max(out.poss.max(), 1)  # value scaled by playing time
    out.index.name = "player_id"
    out.attrs["lambda"] = lam
    return out.reset_index().sort_values("total", ascending=False)


def lineups(stints: pd.DataFrame, min_poss: float | None = None) -> pd.DataFrame:
    min_poss = config.LINEUP_MIN_POSS if min_poss is None else min_poss
    stints = usable(stints)
    rows = []
    for st in stints.itertuples(index=False):
        rows.append((st.home_id, st.home_players, st.home_pts, st.away_pts, st.poss))
        rows.append((st.away_id, st.away_players, st.away_pts, st.home_pts, st.poss))
    df = pd.DataFrame(rows, columns=["team_id", "players", "pts_for", "pts_against", "poss"])
    g = df.groupby(["team_id", "players"], as_index=False).sum()
    g = g[g.poss >= min_poss].copy()
    g["off"] = 100 * g.pts_for / g.poss
    g["def"] = 100 * g.pts_against / g.poss
    g["net"] = g.off - g["def"]
    g = g.sort_values(["team_id", "poss"], ascending=[True, False])
    return g.groupby("team_id").head(15)  # each team's most-used groups
