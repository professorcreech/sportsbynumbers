"""Download Division I college football games, drives and plays from ESPN's public feed.

One small file per day per table under data/football/<season>/:
    games/<day>.csv          one row per game
    drives/<day>.csv.gz      one row per drive: offense, start field position, plays, yards, result, points
    plays/<day>.csv.gz       one row per scrimmage play: down, distance, yards to goal, type, yards gained
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from basketball.fetch import get  # shared HTTP client with retries
from . import config


def _int(x, default=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def season_dir(season: int):
    d = config.DATA_DIR / str(season)
    for sub in ("games", "drives", "plays"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def scoreboard(day: date) -> list[dict]:
    out = {}
    for div, grp in config.GROUPS.items():
        data = get(f"{config.ESPN}/scoreboard", {"dates": day.strftime("%Y%m%d"), "groups": grp, "limit": 400})
        for ev in (data or {}).get("events", []):
            comp = ev.get("competitions", [{}])[0]
            teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            if "home" not in teams or "away" not in teams:
                continue
            addr = (comp.get("venue") or {}).get("address") or {}
            out[str(ev.get("id"))] = {
                "game_id": str(ev.get("id")), "date": day.isoformat(), "start": ev.get("date"),
                "week": (ev.get("week") or {}).get("number"), "season_type": (ev.get("season") or {}).get("type"),
                "completed": bool(comp.get("status", {}).get("type", {}).get("completed")),
                "neutral": bool(comp.get("neutralSite")), "conference_game": bool(comp.get("conferenceCompetition")),
                "home_id": str(teams["home"]["team"]["id"]), "away_id": str(teams["away"]["team"]["id"]),
                "home_name": teams["home"]["team"].get("shortDisplayName") or teams["home"]["team"].get("displayName"),
                "away_name": teams["away"]["team"].get("shortDisplayName") or teams["away"]["team"].get("displayName"),
                "home_pts": _int(teams["home"].get("score")), "away_pts": _int(teams["away"].get("score")),
                "note": "; ".join(n.get("headline", "") for n in comp.get("notes", []) if n.get("headline")),
                "city": addr.get("city"), "state": addr.get("state"),
            }
    return list(out.values())


def fetch_teams(season: int) -> None:
    rows = {}
    for div, grp in config.GROUPS.items():
        data = get(f"{config.ESPN}/teams", {"groups": grp, "limit": 400})
        for t in (data or {}).get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
            t = t.get("team", {})
            rows[str(t.get("id"))] = {"team_id": str(t.get("id")), "name": t.get("displayName"),
                                      "short": t.get("shortDisplayName") or t.get("location"),
                                      "abbr": t.get("abbreviation"), "color": t.get("color") or "888888", "div": div}
    # Conference names from standings (optional)
    conf = {}
    for div, grp in config.GROUPS.items():
        st = get("https://site.api.espn.com/apis/v2/sports/football/college-football/standings",
                 {"season": season, "group": grp})
        for child in (st or {}).get("children", []):
            for e in child.get("standings", {}).get("entries", []):
                conf[str(e.get("team", {}).get("id"))] = child.get("abbreviation") or child.get("name")
    for t in rows.values():
        t["conf"] = conf.get(t["team_id"], "")
    if rows:
        pd.DataFrame(rows.values()).to_csv(season_dir(season) / "teams.csv", index=False)


def parse_summary(summ: dict, game: dict):
    """Drives and scrimmage plays for one game."""
    drives, plays = [], []
    home, away = game["home_id"], game["away_id"]
    prev = (0, 0)
    for k, dr in enumerate((summ.get("drives") or {}).get("previous", []) or []):
        off = str((dr.get("team") or {}).get("id", ""))
        dplays = dr.get("plays") or []
        start = dr.get("start") or {}
        first = next((p for p in dplays if (p.get("start") or {}).get("yardsToEndzone") is not None), None)
        ytg = _int((first or {}).get("start", {}).get("yardsToEndzone"), None) if first else None
        last = dplays[-1] if dplays else {}
        hs, as_ = _int(last.get("homeScore"), prev[0]), _int(last.get("awayScore"), prev[1])
        dh, da = max(hs - prev[0], 0), max(as_ - prev[1], 0)
        prev = (max(hs, prev[0]), max(as_, prev[1]))
        pts_off = dh if off == home else da
        pts_def = da if off == home else dh
        drives.append({"game_id": game["game_id"], "drive": k, "offense": off,
                       "defense": away if off == home else home,
                       "period": _int(start.get("period", {}).get("number") if isinstance(start.get("period"), dict) else start.get("period")),
                       "start_ytg": ytg, "plays": _int(dr.get("offensivePlays")), "yards": _int(dr.get("yards")),
                       "result": dr.get("result") or dr.get("displayResult") or "",
                       "pts_off": pts_off, "pts_def": pts_def})
        for p in dplays:
            st, t = p.get("start") or {}, (p.get("type") or {}).get("text", "")
            if t in ("Kickoff", "Timeout", "End Period", "End of Half", "End of Game", "Coin Toss") or "Kickoff" in t:
                continue
            plays.append({"game_id": game["game_id"], "drive": k, "offense": off,
                          "period": _int((p.get("period") or {}).get("number")),
                          "clock": (p.get("clock") or {}).get("displayValue", ""),
                          "down": _int(st.get("down"), None), "distance": _int(st.get("distance"), None),
                          "ytg": _int(st.get("yardsToEndzone"), None), "type": t,
                          "yards": _int(p.get("statYardage")), "penalty": bool(p.get("isPenalty")),
                          "turnover": bool(p.get("isTurnover")), "scoring": bool(p.get("scoringPlay")),
                          "home_score": _int(p.get("homeScore")), "away_score": _int(p.get("awayScore"))})
    return drives, plays


def fetch_day(season: int, day: date) -> int:
    d = season_dir(season)
    games = [g for g in scoreboard(day) if g["completed"]]
    if not games:
        (d / "games" / f"{day.isoformat()}.csv").write_text("")
        return 0
    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        summaries = list(pool.map(lambda g: get(f"{config.ESPN}/summary", {"event": g["game_id"]}), games))
    drv, ply = [], []
    for g, s in zip(games, summaries):
        if s:
            try:
                a, b = parse_summary(s, g)
                drv += a
                ply += b
            except Exception as e:
                print(f"  could not parse {g['game_id']}: {e}")
    name = day.isoformat()
    pd.DataFrame(games).to_csv(d / "games" / f"{name}.csv", index=False)
    if drv:
        pd.DataFrame(drv).to_csv(d / "drives" / f"{name}.csv.gz", index=False)
    if ply:
        pd.DataFrame(ply).to_csv(d / "plays" / f"{name}.csv.gz", index=False)
    return len(games)


def fetch_schedule(days_ahead: int = 8) -> list[dict]:
    today = date.today()
    return [g for i in range(days_ahead) for g in scoreboard(today + timedelta(days=i)) if not g["completed"]]


def update(season: int | None = None, force: bool = False) -> None:
    today = date.today()
    season = season or config.season_for(today)
    d = season_dir(season)
    fetch_teams(season)
    have = {p.name.split(".")[0] for p in (d / "games").glob("*.csv")}
    day, last = config.season_start(season), min(today - timedelta(days=1), config.season_end(season))
    recent = last - timedelta(days=config.REFETCH_DAYS - 1)
    while day <= last:
        if force or day.isoformat() not in have or day >= recent:
            n = fetch_day(season, day)
            if n:
                print(f"{day}: {n} games")
        day += timedelta(days=1)
