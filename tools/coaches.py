"""Head coach of every Division I men's basketball team, by season (one-time download).

    python -m tools.coaches 2012 2026

Writes data/basketball/history/coaches.csv: season, team_id, coach_id, coach_name.
Teams come from each season's saved scores; coaches from ESPN's season-by-season team records.
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from basketball import config
from basketball.fetch import get

CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball"
HIST = config.DATA_DIR / "history"


def team_coaches(season: int, team_id: str) -> list[dict]:
    data = get(f"{CORE}/seasons/{season}/teams/{team_id}/coaches", {"limit": 10}) or {}
    out = []
    for item in data.get("items", []) or []:
        ref = item.get("$ref", "")
        m = re.search(r"/coaches/(\d+)", ref)
        if m:
            out.append({"season": season, "team_id": team_id, "coach_id": m.group(1), "ref": ref})
    return out


def coach_name(ref: str) -> str:
    d = get(ref) or {}
    return " ".join(x for x in (d.get("firstName"), d.get("lastName")) if x) or ""


def main(first: int, last: int) -> None:
    jobs = []
    for s in range(first, last + 1):
        p = HIST / f"scores_{s}.csv.gz"
        if not p.exists():
            continue
        sc = pd.read_csv(p, dtype={"home_id": str, "away_id": str})
        counts = pd.concat([sc.home_id, sc.away_id]).value_counts()
        jobs += [(s, t) for t in counts[counts >= 10].index]  # teams with a real D-I schedule
    with ThreadPoolExecutor(8) as pool:
        rows = [r for rs in pool.map(lambda j: team_coaches(*j), jobs) for r in rs]
    df = pd.DataFrame(rows)
    if df.empty:
        print("coaches: nothing returned")
        return
    refs = df.drop_duplicates("coach_id")[["coach_id", "ref"]]
    with ThreadPoolExecutor(8) as pool:
        names = dict(zip(refs.coach_id, pool.map(coach_name, refs.ref)))
    df["coach_name"] = df.coach_id.map(names)
    df.drop(columns="ref").to_csv(HIST / "coaches.csv", index=False)
    print(f"coaches: {len(df)} team-seasons, {df.coach_id.nunique()} coaches, {df.groupby(['season', 'team_id']).size().gt(1).sum()} team-seasons with 2+ coaches")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 2012, int(a[1]) if len(a) > 1 else 2026)
