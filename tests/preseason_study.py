"""Which preseason prior predicts best?  python -m tests.preseason_study

Uses 2024-25 to build a preseason prior for 2025-26, calibrates it against 2025-26's
full-season ratings, then replays 2025-26 day by day (fit on earlier games, predict
the day's games) for each candidate prior.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from basketball import config, preseason as P, run, teams

PREV, CUR = 2025, 2026


def walk_forward(games, box, tm, priors: dict, start: str, end: str, step: int = 2):
    """priors: name -> (prior dict, games, fade half-life or None). Returns per-game errors."""
    games = games[games.completed.astype(bool)].sort_values("date")
    days = [d for d in sorted(games.date.unique()) if start <= d <= end][::step]
    rows = []
    for d in days:
        train, test = games[games.date < d], games[games.date == d]
        if train.empty:
            continue
        tb = box[box.game_id.isin(train.game_id)]
        for name, (prior, k, fade) in priors.items():
            m = teams.fit(train, tb, tm, prior, as_of=pd.Timestamp(d).date(), prior_games=k, prior_half_life=fade)
            m["sd"] = config.MARGIN_SD
            for g in test.itertuples():
                p = teams.predict(m, g.home_id, g.away_id, bool(g.neutral))
                if p:
                    a = g.home_pts - g.away_pts
                    rows.append({"prior": name, "game": g.game_id, "day": d, "err": a - p["margin"],
                                 "right": (p["margin"] > 0) == (a > 0), "brier": (p["home_win"] - (a > 0)) ** 2})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, label: str) -> pd.DataFrame:
    s = df.groupby("prior").agg(n=("err", "size"), mae=("err", lambda e: e.abs().mean()),
                                acc=("right", "mean"), brier=("brier", "mean")).sort_values("mae")
    base = df[df.prior == "current"].set_index("game").err.abs()
    s["vs_current"] = [f"{(df[df.prior == p].set_index('game').err.abs() - base).mean():+.2f} ± "
                       f"{(df[df.prior == p].set_index('game').err.abs() - base).std() / np.sqrt(len(base)):.2f}"
                       for p in s.index]
    print(f"\n== {label}: {df.game.nunique()} games ==")
    print(s.round(3).to_string())
    return s


def main():
    t0 = time.time()
    tm_p, g_p, b_p, _, prior_scores_p, _ = run.load(PREV)
    tm, g, b, *_ = run.load(CUR)
    prev_pl, cur_pl = P.player_season(PREV), P.player_season(CUR)

    carry = P.fit_carry(prev_pl, cur_pl)
    print("carry-over:", {k: round(v, 2) for k, v in carry.beta.items()}, "intercepts",
          {k: round(v, 2) for k, v in carry.alpha.items()}, "pairs", carry.counts,
          f"newcomer off {carry.newcomer_off:.2f} def {carry.newcomer_def:.2f} mpg {carry.newcomer_mpg:.1f}")

    # Target: how good each team really was over the full 2025-26 season
    full = teams.fit(g[g.completed.astype(bool)], b, tm, {}, prior_games=0.5)
    config.TEAM_HALF_LIFE_DAYS = 60
    target = pd.DataFrame({"team_id": list(full["idx"]), "o": full["O"], "d": full["D"]})
    se = full["table"].set_index("team_id").net_se
    target["se2"] = target.team_id.map(se ** 2 / 2).fillna(se.median() ** 2 / 2)
    s2 = full["s2"]

    programs = {f"program {h}": P.program_strength(g_p, b_p, tm_p, h) for h in (None, 90, 60, 30)}
    programs["program last 15"] = P.program_strength(g_p, b_p, tm_p, None, last_n=15)
    roster = P.roster_strength(prev_pl, P.rosters_from_box(b), carry)

    priors = {}
    # The current production prior is built from the previous season's margins
    config.TEAM_PRIOR_REGRESS = 0.6
    priors["current"] = (teams.prior_from_last_season(g_p, tm.team_id.tolist()), 4.0, None)
    priors["none"] = ({}, 0.25, None)

    print("\ncalibration against 2025-26 full-season ratings (R2 of offense/defense offsets):")
    for name, prog in programs.items():
        for use_roster in (False, True):
            bl = P.calibrate(target, prog, roster if use_roster else None, s2)
            t = target.merge(prog, on="team_id", suffixes=("", "_p"))
            key = name + (" + roster" if use_roster else "")
            pri = P.combine(prog, roster if use_roster else None, bl)
            yhat = np.r_[[pri.get(x, (0, 0))[0] for x in t.team_id], [pri.get(x, (0, 0))[1] for x in t.team_id]]
            y = np.r_[t.o, t.d]
            r2 = 1 - np.var(y - yhat) / np.var(y)
            print(f"  {key:<28} w_program {bl.w_program:.2f}  w_roster {bl.w_roster:.2f}  "
                  f"R2 {r2:.3f}  spread left {bl.tau:.1f}  worth {bl.games:.1f} games")
            priors[key] = (pri, bl.games, None)

    df = walk_forward(g, b, tm, priors, "2025-11-05", "2025-12-31")
    summarize(df, "Nov-Dec 2025 (mostly nonconference)")
    df.to_csv(config.DATA_DIR / "preseason_study_novdec.csv", index=False)
    print(f"\ndone in {time.time() - t0:.0f}s")


if __name__ == "__main__" and not __import__("sys").argv[1:]:
    main()


def fade_and_current():
    """1) Should the prior fade by mid-season?  2) How much should the roster count this season?"""
    tm_p, g_p, b_p, *_ = run.load(PREV)
    tm, g, b, *_ = run.load(CUR)
    prev_pl, cur_pl = P.player_season(PREV), P.player_season(CUR)
    carry = P.fit_carry(prev_pl, cur_pl)
    prog = P.program_strength(g_p, b_p, tm_p, None)
    roster = P.roster_strength(prev_pl, P.rosters_from_box(b), carry)
    full = teams.fit(g[g.completed.astype(bool)], b, tm, {}, prior_games=0.5)
    target = pd.DataFrame({"team_id": list(full["idx"]), "o": full["O"], "d": full["D"]})
    bl = P.calibrate(target, prog, roster, full["s2"])
    pri = P.combine(prog, roster, bl)
    fades = {f"fade {h}d": (pri, bl.games, h) for h in (15, 30, 45, 60)}
    fades["no fade"] = (pri, bl.games, None)
    fades["current"] = fades["no fade"]
    df = walk_forward(g, b, tm, fades, "2026-01-02", "2026-03-08", step=3)
    summarize(df, "Jan-early Mar 2026, prior fade (half-life from Nov 1)")

    # This season: roster from current rosters, player ratings from the complete 2025-26 season
    tm3, g3, b3, _, _, ros3 = run.load(2027)
    prog3 = P.program_strength(g, b, tm, None)
    carry3 = P.fit_carry(prev_pl, cur_pl)
    roster3 = P.roster_strength(cur_pl, ros3[["player_id", "team_id"]], carry3)
    config.TEAM_PRIOR_REGRESS = 0.6
    cand = {"current": (teams.prior_from_last_season(g, tm3.team_id.tolist()), 4.0, None),
            "none": ({}, 0.25, None)}
    for wr in (0.0, 0.18, 0.35, 0.5, 0.7):
        b2 = P.Blend(w_program=bl.w_program, w_roster=wr, games=bl.games)
        cand[f"program + roster x{wr}"] = (P.combine(prog3, roster3, b2), bl.games, None)
    df3 = walk_forward(g3, b3, tm3, cand, "2026-11-04", "2026-11-30", step=1)
    summarize(df3, "Nov 2026 so far, roster weight")
    r = roster3.merge(prog3, on="team_id", suffixes=("_r", "_p"))
    print("corr(roster net, last-season net) this year:", round(np.corrcoef(r.net_r, r.net_p)[0, 1], 3),
          " blend used:", round(bl.w_program, 2), round(bl.w_roster, 2), round(bl.games, 2))


if __name__ == "__main__" and __import__("sys").argv[1:] == ["fade"]:
    fade_and_current()
