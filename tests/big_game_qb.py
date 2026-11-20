"""Do quarterbacks keep rising in big games?   python -m tests.big_game_qb [football|nfl]

Big game = against a top-15% (NFL: top 25%) opponent by that season's ratings. Production = adjusted yards per
attempt (yards + 20 per TD - 45 per interception, over attempts). Elevation = big-game rate minus other-game rate,
less what the average quarterback loses against strong opponents. Compared across seasons, any team change included.
"""
import sys

import numpy as np
import pandas as pd

from basketball import coaching
from football import run


def frame(league, season, top):
    from pathlib import Path
    root = Path("data") / league / str(season)
    g = run._read(root / "games", "*.csv").drop_duplicates("game_id", keep="last")
    g = g[g.completed.astype(str).str.lower().eq("true") & ((g.home_pts + g.away_pts) > 0)]
    pl = run._read(root / "players", "*.csv.gz")
    pl = pl[pl.pass_att.fillna(0) > 0].astype({"player_id": str, "team_id": str})
    cnt = pd.concat([g.home_id, g.away_id]).value_counts()
    keep = set(cnt[cnt >= (5 if league == "nfl" else 6)].index)
    R = coaching._season_ratings(g[g.home_id.isin(keep) & g.away_id.isin(keep)].assign(neutral=g.neutral))
    cut = np.quantile(list(R.values()), 1 - top)
    opp = pd.concat([g[["game_id", "home_id", "away_id"]].rename(columns={"home_id": "team_id", "away_id": "opp"}),
                     g[["game_id", "home_id", "away_id"]].rename(columns={"away_id": "team_id", "home_id": "opp"})])
    b = pl.merge(opp, on=["game_id", "team_id"], how="inner")
    b["big"] = b.opp.map(lambda t: R.get(t, -99) >= cut)
    b["ay"] = b.pass_yds + 20 * b.pass_td - 45 * b.pass_int
    return b


def elevation(b, min_big, min_other):
    rows = []
    for pid, x in b.groupby("player_id"):
        big, oth = x[x.big], x[~x.big]
        if big.pass_att.sum() < min_big or oth.pass_att.sum() < min_other:
            continue
        rows.append({"player_id": pid, "d": big.ay.sum() / big.pass_att.sum() - oth.ay.sum() / oth.pass_att.sum(), "team": x.team_id.iloc[-1]})
    e = pd.DataFrame(rows)
    return e.assign(d=e.d - e.d.mean()) if len(e) else e


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "football"
    top = 0.25 if league == "nfl" else 0.15
    mb, mo = (40, 100) if league == "nfl" else (30, 100)
    A, B = frame(league, 2025, top), frame(league, 2026, top)
    ea, eb = elevation(A, mb, mo), elevation(B, mb, mo)
    m = ea.merge(eb, on="player_id", suffixes=("_a", "_b"))
    print(f"{league}: quarterbacks with enough attempts: 2025 {len(ea)}, 2026 {len(eb)}, both {len(m)}; sd of elevation {ea.d.std():.2f} AY/A")
    if len(m) > 8:
        print(f"season to season corr {np.corrcoef(m.d_a, m.d_b)[0,1]:+.2f} (n={len(m)}); same team {int((m.team_a == m.team_b).sum())}, changed {int((m.team_a != m.team_b).sum())}")


if __name__ == "__main__":
    main()
