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


def _standings_members(node: dict, conf: str | None = None, out: dict | None = None) -> dict:
    """Walk a standings tree (conferences, sometimes split into divisions) -> {team_id: conference}."""
    out = {} if out is None else out
    name = node.get("abbreviation") or node.get("shortName") or node.get("name")
    for e in (node.get("standings") or {}).get("entries", []):
        t = e.get("team") or {}
        if t.get("id"):
            out[str(t["id"])] = {"conf": conf or name, "name": t.get("displayName"), "abbr": t.get("abbreviation"),
                                 "short": t.get("shortDisplayName") or t.get("location")}
    for child in node.get("children", []) or []:
        # The first level below the division is the conference; deeper levels are its divisions
        label = child.get("abbreviation") or child.get("shortName") or child.get("name")
        if config.IS_NFL and conf:  # NFL: "AFC" then "AFC East"; keep the division
            label = child.get("name") or label
            _standings_members(child, label, out)
        else:
            _standings_members(child, conf or label, out)
    return out


def fetch_teams(season: int) -> None:
    """Division I = every team in the FBS and FCS conference standings (independents included)."""
    rows = {}
    for div, grp in config.GROUPS.items():
        st = get(config.STANDINGS, {"season": season, **({"group": grp} if grp else {})}) or {}
        for tid, info in _standings_members(st).items():
            rows[tid] = {"team_id": tid, **info, "div": div, "color": "888888"}
    if not rows:
        print("football: standings unavailable; keeping previous team list")
        return
    # Colors and short names from the team directory
    data = get(f"{config.ESPN}/teams", {"limit": 2000})
    for t in (data or {}).get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = t.get("team", {})
        r = rows.get(str(t.get("id")))
        if r:
            r["color"] = t.get("color") or "888888"
            r["short"] = t.get("shortDisplayName") or r.get("short")
            r["abbr"] = t.get("abbreviation") or r.get("abbr")
    df = pd.DataFrame(rows.values())
    print(f"football teams: {dict(df['div'].value_counts())}")
    df.to_csv(season_dir(season) / "teams.csv", index=False)


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
        pd.DataFrame(drv).to_csv(d / "drives" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    if ply:
        pd.DataFrame(ply).to_csv(d / "plays" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    return len(games)


def fetch_schedule(days_ahead: int | None = None) -> list[dict]:
    """Every scheduled game from today through the end of the season (or the next N days)."""
    today = date.today()
    end = config.season_end(config.season_for(today))
    n = (end - today).days + 1 if days_ahead is None else days_ahead
    days = [today + timedelta(days=i) for i in range(max(n, 0))]
    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        per_day = list(pool.map(scoreboard, days))
    return [g for rows in per_day for g in rows if not g["completed"]]


def fetch_rankings(season: int) -> None:
    """Current polls (AP, coaches, and the Playoff committee's rankings when released), compactly."""
    if config.IS_NFL:
        return
    data = get(f"{config.ESPN}/rankings") or {}
    polls = {}
    for r in data.get("rankings", []) or []:
        ranks = [{"rank": e.get("current"), "team_id": str((e.get("team") or {}).get("id")),
                  "record": (e.get("recordSummary") or "")} for e in r.get("ranks", []) or []]
        polls[r.get("type") or r.get("shortName") or r.get("name")] = {
            "name": r.get("name"), "headline": r.get("headline"), "date": r.get("date"), "ranks": ranks}
    if polls:
        import json
        (season_dir(season) / "rankings.json").write_text(json.dumps(polls, indent=0))
        print(f"rankings: {', '.join(f'{k} ({len(v["ranks"])})' for k, v in polls.items())}")


def update(season: int | None = None, force: bool = False) -> None:
    today = date.today()
    season = season or config.season_for(today)
    d = season_dir(season)
    fetch_teams(season)
    if season == config.season_for(today):
        fetch_rankings(season)
    have = {p.name.split(".")[0] for p in (d / "games").glob("*.csv")}
    day, last = config.season_start(season), min(today - timedelta(days=1), config.season_end(season))
    recent = last - timedelta(days=config.REFETCH_DAYS - 1)
    while day <= last:
        if force or day.isoformat() not in have or day >= recent:
            n = fetch_day(season, day)
            if n:
                print(f"{day}: {n} games")
        day += timedelta(days=1)
