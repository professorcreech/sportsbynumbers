"""Preseason team ratings built from last season.

Two ingredients, both measured in points per 100 possessions relative to an average team:

  Program:  how the team played last season, with its games weighted toward the end of the
            season (half-life in days), or only its final N games.
  Roster:   the players on this season's roster, each carrying his own rating from last
            season to wherever he plays now (transfers included). A returning rating is
            projected forward with a rule learned from the data:
                expected rating this year = alpha + beta * rating last year
            fit separately for players who stayed and players who transferred. Newcomers
            (freshmen, players new to Division I) get the average newcomer rating.
            Team offense = sum over the roster of (projected minutes / 40) * offense rating,
            with projected minutes scaled to 200 per team; defense the same way.

The two are blended with weights from a regression of each team's full-season rating on
both ingredients, and the regression's leftover spread sets how much the prior is worth
in games. All of this is refit from two past seasons, so nothing here is hand-tuned.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config, players, run, teams

CACHE = "player_ratings.csv"


# ---------------------------------------------------------------------------- program

def program_strength(games, box, tm, half_life: float | None, last_n: int | None = None) -> pd.DataFrame:
    """Each team's offense/defense offsets from a fit of one season, weighted toward its end."""
    g = games[games.completed.astype(bool)] if "completed" in games else games
    if last_n:
        long = pd.concat([g[["game_id", "date", "home_id"]].rename(columns={"home_id": "t"}),
                          g[["game_id", "date", "away_id"]].rename(columns={"away_id": "t"})])
        long = long.sort_values("date").groupby("t").tail(last_n)
        g = g[g.game_id.isin(set(long.game_id))]
    saved = config.TEAM_HALF_LIFE_DAYS, config.TEAM_PRIOR_GAMES
    config.TEAM_HALF_LIFE_DAYS = half_life or 1e9
    config.TEAM_PRIOR_GAMES = 0.5
    try:
        m = teams.fit(g, box[box.game_id.isin(g.game_id)], tm, {})
    finally:
        config.TEAM_HALF_LIFE_DAYS, config.TEAM_PRIOR_GAMES = saved
    return pd.DataFrame({"team_id": list(m["idx"]), "o": m["O"], "d": m["D"]}).assign(net=lambda d: d.o - d.d)


# ---------------------------------------------------------------------------- players

def player_season(season: int, tune: bool = True) -> pd.DataFrame:
    """Player ratings for a finished season (cached next to that season's data)."""
    path = config.DATA_DIR / str(season) / CACHE
    if path.exists():
        return pd.read_csv(path, dtype={"player_id": str, "team_id": str})
    tm, games, box, stints, *_ = run.load(season)
    stints = stints.astype({"home_players": str, "away_players": str})
    lam = players.tune_lambda(stints, box) if tune else config.PLAYER_LAMBDA
    p = players.fit(stints, box, lam)
    keep = ["player_id", "name", "team_id", "gp", "min", "poss", "off", "def", "total"]
    p = p[keep].assign(mpg=lambda d: d["min"] / d.gp.clip(lower=1))
    p.to_csv(path, index=False)
    return p


def rosters_from_box(box: pd.DataFrame) -> pd.DataFrame:
    """Who played for whom in a season (used to test on past seasons, whose rosters ESPN no longer lists)."""
    return box.groupby("player_id").team_id.agg(lambda s: s.mode().iat[0]).rename("team_id").reset_index()


@dataclass
class Carry:
    """How last season's player rating projects to this season."""
    alpha: dict = field(default_factory=lambda: {"stay": 0.0, "moved": 0.0})
    beta: dict = field(default_factory=lambda: {"stay": 0.7, "moved": 0.6})
    newcomer_off: float = -1.0
    newcomer_def: float = -0.5
    newcomer_mpg: float = 10.0
    min_poss: float = 300.0  # last-season possessions needed to count as a known player


def fit_carry(prev: pd.DataFrame, cur: pd.DataFrame, min_poss: float = 300.0) -> Carry:
    """Learn the carry-over rule from two consecutive seasons of player ratings."""
    c = Carry(min_poss=min_poss)
    j = prev.merge(cur, on="player_id", suffixes=("_p", "_c"))
    j = j[(j.poss_p >= min_poss) & (j.poss_c >= min_poss)]
    j["group"] = np.where(j.team_id_p == j.team_id_c, "stay", "moved")
    for grp, g in j.groupby("group"):
        # One slope and intercept per group, fit on total rating
        w = np.sqrt(np.minimum(g.poss_p, g.poss_c)).to_numpy()
        X = np.c_[np.ones(len(g)), g.total_p]
        coef = np.linalg.lstsq(X * w[:, None], g.total_c.to_numpy() * w, rcond=None)[0]
        c.beta[grp] = float(coef[1])
        c.alpha[grp] = float(coef[0])
    new = cur[~cur.player_id.isin(prev.player_id) & (cur.poss >= 50)]
    if len(new):
        c.newcomer_off = float(np.average(new.off, weights=new.poss))
        c.newcomer_def = float(np.average(new["def"], weights=new.poss))
        c.newcomer_mpg = float(np.average(new.mpg, weights=new.gp))
    c.counts = j.group.value_counts().to_dict()
    return c


def roster_strength(prev: pd.DataFrame, roster: pd.DataFrame, carry: Carry) -> pd.DataFrame:
    """Team offense/defense offsets implied by this season's roster and last season's ratings.

    Returns d as points *allowed* above average (the team model's convention)."""
    p = roster[["player_id", "team_id"]].merge(
        prev[["player_id", "team_id", "poss", "off", "def", "mpg"]].rename(columns={"team_id": "prev_team"}),
        on="player_id", how="left")
    known = p.poss >= carry.min_poss
    grp = np.where(p.prev_team == p.team_id, "stay", "moved")
    beta = np.where(grp == "stay", carry.beta["stay"], carry.beta["moved"])
    alpha = np.where(grp == "stay", carry.alpha["stay"], carry.alpha["moved"])
    # Split the projected intercept evenly between ends
    p["off_hat"] = np.where(known, alpha / 2 + beta * p.off, carry.newcomer_off)
    p["def_hat"] = np.where(known, alpha / 2 + beta * p["def"], carry.newcomer_def)
    # Partially known players (few possessions) blend toward newcomer values
    part = (~known) & (p.poss > 0)
    wgt = (p.poss / carry.min_poss).clip(0, 1)
    p.loc[part, "off_hat"] = wgt[part] * (beta[part] * p.off[part]) + (1 - wgt[part]) * carry.newcomer_off
    p.loc[part, "def_hat"] = wgt[part] * (beta[part] * p["def"][part]) + (1 - wgt[part]) * carry.newcomer_def
    p["mpg_hat"] = np.where(p.mpg.notna(), p.mpg, carry.newcomer_mpg)
    out = []
    for tid, g in p.groupby("team_id"):
        g = g.sort_values("mpg_hat", ascending=False)
        m = g.mpg_hat.to_numpy(float)
        # Minutes are capped at 36 and scaled so the team plays 200
        for _ in range(5):
            m = np.minimum(m * 200 / max(m.sum(), 1e-9), 36.0)
        share = m / 40
        out.append({"team_id": tid, "o": float(share @ g.off_hat), "d": float(-(share @ g.def_hat)),
                    "returning_min": float(m[(g.prev_team == tid).to_numpy()].sum() / 200)})
    return pd.DataFrame(out).assign(net=lambda d: d.o - d.d)


# ---------------------------------------------------------------------------- blend

@dataclass
class Blend:
    w_program: float = 0.6
    w_roster: float = 0.0
    games: float = 4.0          # prior strength in games of ~68 possessions
    non_d1: tuple = (-12.0, 12.0)


def calibrate(target: pd.DataFrame, program: pd.DataFrame, roster: pd.DataFrame | None, s2: float) -> Blend:
    """Regress full-season ratings on the ingredients; leftover spread sets prior strength.

    target, program, roster: team_id, o, d. s2: the team model's variance per possession."""
    t = target.merge(program, on="team_id", suffixes=("", "_p"))
    cols = ["_p"]
    if roster is not None:
        t = t.merge(roster.rename(columns={"o": "o_r", "d": "d_r", "net": "net_r"}), on="team_id")
        cols.append("_r")
    # Stack offense and defense rows; one weight per ingredient shared by both ends
    y = np.r_[t.o, t.d]
    X = np.c_[np.r_[t.o_p, t.d_p]] if roster is None else np.c_[np.r_[t.o_p, t.d_p], np.r_[t.o_r, t.d_r]]
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    tau2 = max(float(np.var(resid)) - float(target.get("se2", pd.Series([0.0])).mean()), 1.0)
    b = Blend(w_program=float(coef[0]), w_roster=float(coef[1]) if roster is not None else 0.0)
    b.games = float(s2 / tau2 / 68.0)
    b.tau = float(np.sqrt(tau2))
    return b


def combine(program: pd.DataFrame, roster: pd.DataFrame | None, blend: Blend) -> dict:
    """Prior offsets per team: {team_id: (o, d)}, including the pooled non-Division I team."""
    p = program.set_index("team_id")
    r = roster.set_index("team_id") if roster is not None else None
    out = {}
    for t in p.index.union(r.index if r is not None else []):
        o = d = 0.0
        if t in p.index:
            o += blend.w_program * p.at[t, "o"]; d += blend.w_program * p.at[t, "d"]
        if r is not None and t in r.index:
            o += blend.w_roster * r.at[t, "o"]; d += blend.w_roster * r.at[t, "d"]
        out[t] = (o, d)
    if "NON_D1" in p.index:  # non-D-I opponents carry last season's pooled rating as is
        out["NON_D1"] = (p.at["NON_D1", "o"], p.at["NON_D1", "d"])
    else:
        out["NON_D1"] = blend.non_d1
    return out


def build_prior(season: int, rosters: pd.DataFrame | None, box_cur: pd.DataFrame) -> tuple[dict, dict]:
    """Production prior for a season, from the season before. Returns (prior, info)."""
    prev = season - 1
    if not (config.DATA_DIR / str(prev) / "games").exists():
        return {}, {"source": "none"}
    tm_p, g_p, b_p, *_ = run.load(prev)
    prog = program_strength(g_p, b_p, tm_p, None)
    prev_pl = player_season(prev)
    carry = Carry()
    if (config.DATA_DIR / str(prev - 1) / "games").exists():
        carry = fit_carry(player_season(prev - 1), prev_pl)
    roster_src = rosters[["player_id", "team_id"]] if rosters is not None and len(rosters) else rosters_from_box(box_cur)
    roster = roster_strength(prev_pl, roster_src, carry)
    blend = Blend(w_program=config.PRESEASON_W_PROGRAM, w_roster=config.PRESEASON_W_ROSTER,
                  games=config.PRESEASON_GAMES)
    info = {"source": f"{prev - 1}-{str(prev)[2:]} season + current rosters", "games": blend.games,
            "player_proj": player_projection(prev_pl, roster_src, carry),
            "w_program": blend.w_program, "w_roster": blend.w_roster,
            "carry": {k: round(v, 2) for k, v in carry.beta.items()},
            "returning": dict(zip(roster.team_id, roster.returning_min.round(3)))}
    return combine(prog, roster, blend), info


def player_projection(prev: pd.DataFrame, roster: pd.DataFrame, carry: Carry) -> dict:
    """{player_id: (off, def)} expected this season from last season's rating (known players only)."""
    p = roster[["player_id", "team_id"]].merge(
        prev[["player_id", "team_id", "poss", "off", "def"]].rename(columns={"team_id": "prev_team"}), on="player_id")
    p = p[p.poss >= carry.min_poss]
    stay = (p.prev_team == p.team_id).to_numpy()
    beta = np.where(stay, carry.beta["stay"], carry.beta["moved"])
    alpha = np.where(stay, carry.alpha["stay"], carry.alpha["moved"])
    return {pid: (a / 2 + b * o, a / 2 + b * d) for pid, a, b, o, d in zip(p.player_id, alpha, beta, p.off, p["def"])}
