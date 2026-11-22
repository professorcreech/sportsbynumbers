"""Walk-forward version of qb_absence: the usual starter is the attempts leader BEFORE each game (no hindsight),
and the flag is "he missed the previous game". Splits by how many games in a row he has missed.   python -m tests.qb_absence_live [football|nfl]"""
import sys

import numpy as np
import pandas as pd

from football import run


def season(league, s, rep):
    from pathlib import Path
    root = Path("data") / league / str(s)
    pl = run._read(root / "players", "*.csv.gz")
    pl = pl[pl.pass_att.fillna(0) > 0].astype({"player_id": str, "team_id": str, "game_id": str})
    r = rep.copy(); r["res"] = (r.home_pts - r.away_pts) - r.margin; r = r.sort_values("start")
    cum, rows, hist = {}, [], {}
    att = pl.groupby(["game_id", "team_id", "player_id"]).pass_att.sum()
    tatt = pl.groupby(["game_id", "team_id"]).pass_att.sum()
    for x in r.itertuples():
        for tid, sg in ((str(x.home), 1), (str(x.away), -1)):
            c = cum.get(tid, {})
            lead = max(c, key=c.get) if c and max(c.values()) >= 30 else None
            h = hist.get(tid, [])           # was the (then) leader absent, game by game
            streak = 0
            for v in reversed(h):
                if v: streak += 1
                else: break
            if lead is not None and h:
                rows.append({"season": s, "res": sg * x.res, "prev_out": h[-1], "streak": streak})
            if tatt.get((str(x.game_id), tid), 0) >= 10:
                lead_att = att.get((str(x.game_id), tid, lead), 0) if lead else None
                hist.setdefault(tid, []).append(None if lead is None else bool(lead_att < 5))
                hist[tid] = [v for v in hist[tid] if v is not None] if False else hist[tid]
                for (g_, t_, p_), a_ in att[[(str(x.game_id), tid, q) for q in pl[(pl.game_id == str(x.game_id)) & (pl.team_id == tid)].player_id]].items():
                    cum.setdefault(tid, {}); cum[tid][p_] = cum[tid].get(p_, 0) + a_
    d = pd.DataFrame(rows)
    d["prev_out"] = d.prev_out.fillna(False).astype(bool)
    return d


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "football"
    d = pd.concat([season(league, s, pd.read_csv(f"data/{league}/{f}", dtype={"game_id": str, "home": str, "away": str}))
                   for s, f in ((2025, "replay.csv"), (2026, "replay_now.csv"))])
    base = d[~d.prev_out]
    print(f"{league}: usual starter (leader before the game) missed the previous game in {d.prev_out.mean():.1%} of {len(d)} team-games")
    for lab, m in (("missed last game", d.prev_out), ("  exactly 1 game", d.prev_out & (d.streak == 1)), ("  2 in a row", d.prev_out & (d.streak == 2)), ("  3+ in a row", d.prev_out & (d.streak >= 3))):
        a = d[m]
        if len(a) > 5:
            print(f"  {lab:18s} n={len(a):4d}  result vs prediction {a.res.mean():+.1f} (others {base.res.mean():+.1f}); diff {a.res.mean() - base.res.mean():+.1f} ± {np.sqrt(a.res.var() / len(a) + base.res.var() / len(base)):.1f}")


if __name__ == "__main__":
    main()
