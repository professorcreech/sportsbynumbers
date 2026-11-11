"""College football daily entry point.

    python -m football.run --fetch            # what the GitHub job runs during the season
    python -m football.run --backfill 2025    # download a past season
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from basketball.conferences import name as conf_name
from basketball.run import _clean
from . import config, playoff, scouting, teams


def _read(folder, pattern):
    frames = []
    for p in sorted(folder.glob(pattern)):
        if p.stat().st_size == 0:
            continue
        try:
            frames.append(pd.read_csv(p, dtype={"game_id": str, "home_id": str, "away_id": str,
                                                "offense": str, "defense": str}))
        except pd.errors.EmptyDataError:
            pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load(season: int):
    d = config.DATA_DIR / str(season)
    tm = pd.read_csv(d / "teams.csv", dtype={"team_id": str})
    games = _read(d / "games", "*.csv")
    if len(games):
        games = games.drop_duplicates("game_id", keep="last")
        games = games[games.completed.astype(bool)]
    drives = _read(d / "drives", "*.csv.gz")
    return tm, games, drives


def load_plays(season: int) -> pd.DataFrame:
    d = config.DATA_DIR / str(season)
    return _read(d / "plays", "*.csv.gz") if (d / "plays").exists() else pd.DataFrame()


def prior_for(season: int) -> dict:
    prev = config.DATA_DIR / str(season - 1)
    if not (prev / "games").exists():
        return {}
    tm_p, g_p, _ = load(season - 1)
    return teams.last_season_prior(g_p, tm_p) if len(g_p) else {}


def _polls(season: int) -> dict:
    """Committee (or AP) top 25 for display next to the odds."""
    import json as _json
    p = config.DATA_DIR / str(season) / "rankings.json"
    if not p.exists():
        return {}
    polls = _json.loads(p.read_text())
    pick = next((k for k in polls if "cfp" in str(k).lower() or "playoff" in str(polls[k].get("name", "")).lower()), None) or \
        next((k for k in polls if str(k).lower() == "ap"), None)
    if not pick:
        return {}
    return {"name": polls[pick].get("name"), "headline": polls[pick].get("headline"),
            "ranks": {r["team_id"]: r["rank"] for r in polls[pick]["ranks"]}}


def build(season: int, schedule: list[dict]) -> None:
    tm, games, drives = load(season)
    prior = prior_for(season)
    m = teams.fit(games, tm, prior)
    t = m["table"]
    names = dict(zip(t.team_id, t.short))

    # Drive-level context for the table: points per drive for and against (raw)
    ppd = {}
    if len(drives):
        dv = drives[drives.plays > 0]
        f = dv.groupby("offense").agg(n=("pts_off", "size"), pts=("pts_off", "sum"))
        a = dv.groupby("defense").agg(n=("pts_off", "size"), pts=("pts_off", "sum"))
        for tid in t.team_id:
            ppd[tid] = (f.pts.get(tid, np.nan) / f.n.get(tid, np.nan), a.pts.get(tid, np.nan) / a.n.get(tid, np.nan))

    out_t = [{"id": r.team_id, "name": r.name, "short": r.short, "abbr": r.abbr, "conf": conf_name(r.conf), "div": r.div,
              "color": r.color, "rank": int(r.rank), "net": round(r.net, 2), "net_se": round(r.net_se, 2),
              "o": round(r.off, 1), "d": round(r.dfn, 1), "w": int(r.wins), "l": int(r.losses),
              "pre": None if r.pre is None or pd.isna(r.pre) else round(r.pre, 1),
              "ppd_o": ppd.get(r.team_id, (None, None))[0], "ppd_d": ppd.get(r.team_id, (None, None))[1]}
             for r in t.itertuples()]
    for key, rk, rev in (("o", "o_rank", True), ("d", "d_rank", False)):
        for i, row in enumerate(sorted(out_t, key=lambda x: x[key], reverse=rev)):
            row[rk] = i + 1
    for row in out_t:
        for k in ("ppd_o", "ppd_d"):
            row[k] = None if row[k] is None or not np.isfinite(row[k]) else round(float(row[k]), 2)

    # The Games tab shows the next eight days; the playoff simulation uses everything left
    horizon = (datetime.now(timezone.utc) + pd.Timedelta(days=8)).strftime("%Y-%m-%dT%H:%M")
    remaining = pd.DataFrame(schedule)
    up = []
    for g in [x for x in schedule if str(x.get("start") or x.get("date")) < horizon]:
        p = teams.predict(m, g["home_id"], g["away_id"], g.get("neutral", False))
        if p and (g["home_id"] in names or g["away_id"] in names):
            up.append({"id": g["game_id"], "start": g.get("start"), "neutral": bool(g.get("neutral")),
                       "home": g["home_id"], "away": g["away_id"],
                       "home_name": names.get(g["home_id"], g.get("home_name")), "away_name": names.get(g["away_id"], g.get("away_name")),
                       "home_score": round(p["home_score"], 1), "away_score": round(p["away_score"], 1),
                       "home_win": round(p["home_win"], 3), "note": g.get("note") or ""})
    meta = {"season": f"{season}",
            "league": {"key": config.LEAGUE, "nfl": config.IS_NFL, "level": "NFL" if config.IS_NFL else "Division I",
                       "short": "NFL" if config.IS_NFL else "D-I"}, "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "games": int(len(games)), "drives": int(len(drives)), "mu": round(m["mu"], 2), "hfa": round(m["hfa"], 2),
            "sd": round(m["sd"], 2), "prior_games": config.PRIOR_GAMES, "prior_keep": config.PRIOR_KEEP,
            "model": {"ids": list(m["idx"]), "O": np.round(m["O"], 3).tolist(), "D": np.round(m["D"], 3).tolist()}}
    out = config.SITE_DATA_DIR
    out.mkdir(parents=True, exist_ok=True)
    plays = load_plays(season)
    stats = scouting.team_profiles(plays, drives, set(t.team_id)) if len(plays) and len(drives) else {"league": {}, "teams": {}}
    po = None
    if not config.IS_NFL and len(remaining) and "season_type" in remaining:
        reg = remaining[pd.to_numeric(remaining.season_type, errors="coerce") == 2]
        res = playoff.simulate(m, tm, games[pd.to_numeric(games.season_type, errors="coerce") == 2]
                               if "season_type" in games else games, reg)
        if res is not None:
            keep = res[(res.playoff >= 0.005) | (res.index < 30)]
            po = {"sims": 10000, "updated": meta["updated"], "polls": _polls(season),
                  "teams": [{"id": r.team_id, **{k: round(float(getattr(r, k)), 4) for k in
                             ("playoff", "bye", "conf_champ", "quarter", "semi", "final", "title")},
                             "wins": round(float(r.wins), 1), "losses": round(float(r.losses), 1), "sor": round(float(r.sor), 2)}
                            for r in keep.itertuples()]}
    for name, obj in (("meta", meta), ("teams", out_t), ("games", up), ("teamstats", stats)) + ((("playoff", po),) if po else ()):
        (out / f"{name}.json").write_text(json.dumps(_clean(obj), separators=(",", ":"), allow_nan=False))
    print(f"football: {len(games)} games, {len(t)} teams rated, {len(up)} upcoming")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--backfill", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--season", type=int)
    a = ap.parse_args()
    from . import fetch
    if a.backfill:
        fetch.update(a.backfill, force=a.force)
        return
    season = a.season or config.season_for(date.today())
    sched = []
    if a.fetch:
        fetch.update(season)
        sched = fetch.fetch_schedule()
    build(season, sched)


if __name__ == "__main__":
    main()
