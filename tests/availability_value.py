"""Does the shortfall scale with the production of the players who are missing?   python -m tests.availability_value [football|nfl]

For every team-game, find players with at least 3 earlier games this season (production counted only from games before
this one) who have no box-score line in this game. Their usual per-game production is summed:
  offense: passing + rushing + receiving yards;   defense: tackles + 2*TFL + 3*sacks + 2*pass breakups + 4*interceptions.
Team result minus replayed prediction is regressed on lost offense and lost defense (both seasons pooled), and compared
with the flat "starting QB out" indicator. Ground truth of who played comes from this game's box score, so this
measures the value of the effect, not yet a forecast.
"""
import sys

import numpy as np
import pandas as pd

from football import run


def team_games(league, s, rep):
    from pathlib import Path
    root = Path("data") / league / str(s)
    pl = run._read(root / "players", "*.csv.gz").astype({"player_id": str, "team_id": str, "game_id": str})
    for c in ("pass_yds", "rush_yds", "rec_yds", "tkl", "tfl", "sacks", "pd", "def_int", "pass_att"):
        pl[c] = pl.get(c, 0).fillna(0) if c in pl else 0
    pl["off"] = pl.pass_yds + pl.rush_yds + pl.rec_yds
    pl["dfn"] = pl.tkl + 2 * pl.tfl + 3 * pl.sacks + 2 * pl.pd + 4 * pl.def_int
    r = rep.copy(); r["res"] = (r.home_pts - r.away_pts) - r.margin; r = r.sort_values("start")
    order = {g: i for i, g in enumerate(r.game_id)}
    pl = pl[pl.game_id.isin(order)]
    rows = []
    for tid, tp in pl.groupby("team_id"):
        games = sorted(set(tp.game_id), key=order.get)
        by_game = {g: x for g, x in tp.groupby("game_id")}
        seen = {}     # player -> [n games, off sum, dfn sum, att sum]
        prev_state = None
        for g in games:
            here = by_game[g]
            if len(here) < 15:        # incomplete box score
                continue
            lost_off = lost_def = lost_qb = 0.0
            present = set(here.player_id)
            for p, (n, o, d, a) in seen.items():
                if n >= 3 and p not in present:
                    lost_off += o / n; lost_def += d / n
                    if a / n >= 15: lost_qb += 1
            prev_lost = prev_state[0] if prev_state else None   # offense missing from the previous game, known before this one
            rr = r[r.game_id == g]
            if len(rr):
                x = rr.iloc[0]
                sg = 1 if str(x.home) == tid else -1 if str(x.away) == tid else 0
                if sg:
                    rows.append({"season": s, "res": sg * x.res, "lost_off": lost_off, "prev_lost": prev_lost, "lost_def": lost_def, "qb_out": lost_qb > 0})
            prev_state = (lost_off,)
            for p, o, d, a in zip(here.player_id, here.off, here.dfn, here.pass_att):
                v = seen.setdefault(p, [0, 0.0, 0.0, 0.0]); v[0] += 1; v[1] += o; v[2] += d; v[3] += a
    return pd.DataFrame(rows)


def ols(X, y):
    X1 = np.c_[np.ones(len(X)), X]
    b = np.linalg.lstsq(X1, y, rcond=None)[0]
    e = y - X1 @ b
    se = np.sqrt(np.diag(np.linalg.inv(X1.T @ X1)) * e.var(ddof=X1.shape[1]))
    return b, se, 1 - e.var() / y.var()


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "football"
    d = pd.concat([team_games(league, s, pd.read_csv(f"data/{league}/{f}", dtype={"game_id": str, "home": str, "away": str}))
                   for s, f in ((2025, "replay.csv"), (2026, "replay_now.csv"))])
    print(f"{league}: {len(d)} team-games; lost offense/game avg {d.lost_off.mean():.0f} yds (sd {d.lost_off.std():.0f}), lost defense {d.lost_def.mean():.1f} (sd {d.lost_def.std():.1f})")
    y = d.res.to_numpy(float)
    d2 = d.dropna(subset=["prev_lost"])
    b, se, r2 = ols(d2[["prev_lost"]].to_numpy(float), d2.res.to_numpy(float))
    print(f"  pregame-knowable: offense missing from the PREVIOUS game ({len(d2)} team-games): {b[1] * 100:+.2f} ± {se[1] * 100:.2f} pts per 100 yds")
    for lab, cols in (("flat QB indicator", ["qb_out"]), ("lost offense + lost defense", ["lost_off", "lost_def"]), ("both", ["qb_out", "lost_off", "lost_def"])):
        b, se, r2 = ols(d[cols].astype(float).to_numpy(), y)
        print(f"  {lab:28s} R2 {r2:.4f}  " + "  ".join(f"{c}: {b[i + 1]:+.3f}±{se[i + 1]:.3f}" for i, c in enumerate(cols)))
    # effect size in points per 100 lost yards, split by season for stability
    for s, x in d.groupby("season"):
        b, se, _ = ols(x[["lost_off", "lost_def"]].to_numpy(float), x.res.to_numpy(float))
        print(f"  {s}: lost_off {b[1] * 100:+.2f}±{se[1] * 100:.2f} pts per 100 yds, lost_def {b[2]:+.3f}±{se[2]:.3f} per unit")


if __name__ == "__main__":
    main()
