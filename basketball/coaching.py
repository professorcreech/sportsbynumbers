"""Coaching changes in the college preseason prior.

tests/coach_study.py (4,212 team-seasons, 2015-2026, leave-one-season-out) found:
  * same coach, same school: his track record adds nothing -- last season already contains it;
  * new coach: the team lands lower than last season predicts, last season carries less, and the
    new coach's record of beating expectations at his previous school carries over.
Those three terms improved all 12 held-out seasons. Checked against the production prior
(program + roster) on 2025-26, the effects kept their direction and size. Weights below are per
100 possessions, between the historical fit and the production check.

College only (ESPN's NBA coach records are not wired in). Coaches are refreshed weekly.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import config

HIST = config.DATA_DIR / "history"
FILE = HIST / "coaches.csv"
NEW_COACH_SHIFT = -2.0     # net rating, per 100 possessions
NEW_COACH_CARRY = -0.10    # x the prior's own net rating: last season counts less
NEW_COACH_RECORD = 1.5     # x his shrunk mean surprise (points per game) over 5 seasons elsewhere


def _season_ratings(g: pd.DataFrame, lam: float = 2.0) -> dict:
    ids = sorted(set(g.home_id) | set(g.away_id))
    idx = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    X = np.zeros((len(g), n + 1))
    X[np.arange(len(g)), g.home_id.map(idx)] = 1
    X[np.arange(len(g)), g.away_id.map(idx)] = -1
    X[:, n] = np.where(g.neutral.astype(bool), 0, 1)
    y = (g.home_pts - g.away_pts).to_numpy(float)
    coef = np.linalg.solve(X.T @ X + np.diag(np.r_[np.full(n, lam), 1e-6]), X.T @ y)
    return dict(zip(ids, coef[:n]))


def surprises(last: int) -> pd.DataFrame:
    """season, team_id, surprise: rating minus what the season before predicted (points per game)."""
    rows = []
    for s in range(2012, last + 1):
        p = HIST / f"scores_{s}.csv.gz"
        if not p.exists():
            continue
        g = pd.read_csv(p, dtype={"home_id": str, "away_id": str})
        g = g[(g.home_pts + g.away_pts) > 0]
        counts = pd.concat([g.home_id, g.away_id]).value_counts()
        d1 = set(counts[counts >= 10].index)
        R = _season_ratings(g[g.home_id.isin(d1) & g.away_id.isin(d1)])
        rows += [{"season": s, "team_id": t, "R": r} for t, r in R.items()]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    prev = df.assign(season=df.season + 1).rename(columns={"R": "R_prev"})
    df = df.merge(prev, on=["season", "team_id"])
    b = np.polyfit(df.R_prev, df.R, 1)
    return df.assign(surprise=df.R - np.polyval(b, df.R_prev))[["season", "team_id", "surprise"]]


def refresh(season: int, team_ids: list[str], max_age_days: float = 7) -> pd.DataFrame:
    """Coaches table, fetching this season's coaches if missing or older than a week."""
    from tools.coaches import team_coaches, coach_name
    c = pd.read_csv(FILE, dtype={"team_id": str, "coach_id": str}) if FILE.exists() else pd.DataFrame(
        columns=["season", "team_id", "coach_id", "coach_name", "fetched"])
    if "fetched" not in c:
        c["fetched"] = np.nan
    cur = c[c.season == season]
    stale = cur.empty or (time.time() - pd.to_numeric(cur.fetched, errors="coerce").min()) > max_age_days * 86400
    if stale:
        ids = [t for t in team_ids if t != "NON_D1"]
        with ThreadPoolExecutor(8) as pool:
            rows = [r for rs in pool.map(lambda t: team_coaches(season, t), ids) for r in rs]
        new = pd.DataFrame(rows)
        if len(new):
            known = dict(zip(c.coach_id, c.coach_name))
            missing = new[~new.coach_id.isin(known)].drop_duplicates("coach_id")
            with ThreadPoolExecutor(8) as pool:
                known.update(zip(missing.coach_id, pool.map(coach_name, missing.ref)))
            new = new.assign(coach_name=new.coach_id.map(known), fetched=int(time.time())).drop(columns="ref")
            c = pd.concat([c[c.season != season], new], ignore_index=True)
            c.to_csv(FILE, index=False)
            print(f"coaches: {len(new)} for {season}")
    return c


def adjust(prior: dict, season: int, team_ids: list[str]) -> tuple[dict, dict]:
    """Shift each team's (o, d) prior for a coaching change. Returns (prior, {team_id: note})."""
    try:
        c = refresh(season, team_ids)
    except Exception as e:  # a feed problem should never block the ratings
        print(f"coaches: skipped ({e})")
        return prior, {}
    n = c.groupby(["season", "team_id"]).coach_id.transform("size")
    c = c[n == 1]
    # ESPN occasionally lists one coach at two schools in a season; credit neither
    c = c[c.groupby(["season", "coach_id"]).team_id.transform("size") == 1]
    now = c[c.season == season].set_index("team_id")
    before = c[c.season == season - 1].set_index("team_id")
    sur = surprises(season - 1)
    hist = sur.merge(c[["season", "team_id", "coach_id"]], on=["season", "team_id"])
    out, notes = dict(prior), {}
    for t, (o, d) in prior.items():
        if t not in now.index or t not in before.index or now.coach_id[t] == before.coach_id[t]:
            continue
        coach = now.coach_id[t]
        h = hist[(hist.coach_id == coach) & (hist.season < season) & (hist.season >= season - 5)]
        record = h.surprise.sum() / (len(h) + 2.0)
        delta = NEW_COACH_SHIFT + NEW_COACH_CARRY * (o - d) + NEW_COACH_RECORD * record
        out[t] = (o + delta / 2, d - delta / 2)
        notes[t] = {"coach": now.coach_name[t], "prev": before.coach_name[t], "seasons": int(len(h)),
                    "record": round(float(record), 2), "delta": round(float(delta), 2)}
    print(f"coaches: {len(notes)} new head coaches adjusted in the preseason prior")
    return out, notes
