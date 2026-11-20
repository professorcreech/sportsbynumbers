"""Do players keep rising (or shrinking) in big games from one season to the next?   python -m tests.big_game [basketball|nba]

A "big game" is one against a top opponent (top 15% of teams by that season's ratings). Production is Game Score per
minute; a player's elevation is his rate in big games minus his rate in other games, less what the average player
loses against strong opponents. Tested two ways: split-half within a season (odd vs even big games) and from the
season before to this one, including players who changed teams.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from basketball import coaching, run


def season_frame(league_dir: str, season: int, top: float = 0.15) -> pd.DataFrame:
    from pathlib import Path
    root = Path("data") / league_dir / str(season)
    g = run._read(root / "games", "*.csv").drop_duplicates("game_id", keep="last")
    g = g[g.completed.astype(str).str.lower().eq("true") & ((g.home_pts + g.away_pts) > 0)]
    box = run._read(root / "box", "*.csv.gz").drop_duplicates(["game_id", "player_id"], keep="last")
    ids = pd.concat([g.home_id, g.away_id]).value_counts()
    keep = set(ids[ids >= 10].index)
    R = coaching._season_ratings(g[g.home_id.isin(keep) & g.away_id.isin(keep)])
    cut = np.quantile(list(R.values()), 1 - top)
    opp = pd.concat([g[["game_id", "home_id", "away_id", "date"]].rename(columns={"home_id": "team_id", "away_id": "opp"}),
                     g[["game_id", "home_id", "away_id", "date"]].rename(columns={"away_id": "team_id", "home_id": "opp"})])
    b = box.merge(opp, on=["game_id", "team_id"], how="inner")
    b["big"] = b.opp.map(lambda t: R.get(t, -99) >= cut)
    m = b["min"].astype(float)
    b["gs"] = (b.pts + 0.4 * b.fgm - 0.7 * b.fga - 0.4 * (b.fta - b.ftm) + 0.7 * b.oreb + 0.3 * b.dreb + b.stl + 0.7 * b.ast
               + 0.7 * b.blk - 0.4 * b.pf - b.tov)
    b["m"] = m
    return b[b.m > 0].sort_values(["player_id", "date"])


def elevation(b: pd.DataFrame, min_big=4, min_other=8, min_min=15, mask=None) -> pd.DataFrame:
    b = b if mask is None else b[mask]
    rows = []
    for pid, x in b.groupby("player_id"):
        big, oth = x[x.big], x[~x.big]
        if len(big) < min_big or len(oth) < min_other or x.m.mean() < min_min:
            continue
        rows.append({"player_id": pid, "n_big": len(big), "d": big.gs.sum() / big.m.sum() * 36 - oth.gs.sum() / oth.m.sum() * 36,
                     "team": x.team_id.iloc[-1]})
    e = pd.DataFrame(rows)
    return e.assign(d=e.d - e.d.mean()) if len(e) else e   # subtract what the average player loses against strong teams


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "basketball"
    top = 0.25 if league == "nba" else 0.15
    A, B = season_frame(league, 2025, top), season_frame(league, 2026, top)
    for lab, b in (("2024-25", A), ("2025-26", B)):
        e = elevation(b)
        # split-half: alternate each player's big games
        b2 = b.copy()
        b2["k"] = b2[b2.big].groupby("player_id").cumcount() % 2
        b2["k"] = b2.k.fillna(-1)
        eh0 = elevation(b2, 2, 4, 15, (b2.k == 0) | (~b2.big)); eh1 = elevation(b2, 2, 4, 15, (b2.k == 1) | (~b2.big))
        h = eh0.merge(eh1, on="player_id")
        print(f"{league} {lab}: {len(e)} players with enough games; sd of elevation {e.d.std():.1f} GmSc/36; split-half corr {np.corrcoef(h.d_x, h.d_y)[0,1]:+.2f} (n={len(h)})")
    ea, eb = elevation(A), elevation(B)
    m = ea.merge(eb, on="player_id", suffixes=("_a", "_b"))
    print(f"season to season: n={len(m)} corr {np.corrcoef(m.d_a, m.d_b)[0,1]:+.2f}; same team {np.corrcoef(*(m[m.team_a == m.team_b][['d_a','d_b']].T.values))[0,1]:+.2f} "
          f"(n={int((m.team_a == m.team_b).sum())}); changed team {np.corrcoef(*(m[m.team_a != m.team_b][['d_a','d_b']].T.values))[0,1]:+.2f} (n={int((m.team_a != m.team_b).sum())})")
    # rate persistence for comparison: does overall production persist?
    for lab, d in (("elevation", m),):
        top_a = m[m.d_a >= m.d_a.quantile(.8)]
        print(f"players in the top 20% of elevation in 2024-25: average elevation next season {top_a.d_b.mean():+.2f} (everyone: {m.d_b.mean():+.2f}, sd {m.d_b.std():.2f})")


if __name__ == "__main__":
    main()
