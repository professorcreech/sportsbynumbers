"""Does a missing starting quarterback move results away from the ratings' predictions?   python -m tests.qb_absence [football|nfl]

The starter is the quarterback with the most pass attempts for his team over the season (known only afterwards, which is
fine for measuring the size of the effect). A game counts as "starter out" if he threw fewer than 5 passes in it.
Effect = team's actual margin minus the replay's predicted margin, starter-out games against all other games.
"""
import sys

import numpy as np
import pandas as pd

from football import run


def season(league, s, rep):
    from pathlib import Path
    root = Path("data") / league / str(s)
    pl = run._read(root / "players", "*.csv.gz")
    pl = pl[pl.pass_att.fillna(0) > 0].astype({"player_id": str, "team_id": str, "game_id": str})
    tot = pl.groupby(["team_id", "player_id"]).pass_att.sum().reset_index().sort_values("pass_att").drop_duplicates("team_id", keep="last")
    starter = dict(zip(tot.team_id, tot.player_id))
    att = pl.set_index(["game_id", "team_id", "player_id"]).pass_att
    r = rep.copy()
    r["res"] = (r.home_pts - r.away_pts) - r.margin
    rows = []
    for x in r.itertuples():
        for tid, sg in ((str(x.home), 1), (str(x.away), -1)):
            sp = starter.get(tid)
            if sp is None:
                continue
            a = att.get((str(x.game_id), tid, sp), 0)
            rows.append({"season": s, "team": tid, "game": x.game_id, "res": sg * x.res, "out": a < 5})
    return pd.DataFrame(rows)


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "football"
    frames = []
    for s, f in ((2025, "replay.csv"), (2026, "replay_now.csv")):
        frames.append(season(league, s, pd.read_csv(f"data/{league}/{f}", dtype={"game_id": str, "home": str, "away": str})))
    d = pd.concat(frames)
    for lab, x in [("both seasons", d)] + [(str(s), g) for s, g in d.groupby("season")]:
        o, k = x[x.out], x[~x.out]
        se = np.sqrt(o.res.var() / max(len(o), 1) + k.res.var() / len(k))
        print(f"{league} {lab}: starter out in {len(o)} of {len(x)} team-games ({len(o) / len(x):.1%}); "
              f"avg result vs prediction: out {o.res.mean():+.1f}, in {k.res.mean():+.1f}; difference {o.res.mean() - k.res.mean():+.1f} ± {se:.1f}")


if __name__ == "__main__":
    main()
