"""Download new games from ESPN's public JSON feed and store them as one small file per day.

Per-day files are written once and rarely change, which keeps the repository small even
though the job runs every day all season.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

from . import config
from .parse import parse_shots, parse_summary

session = requests.Session()
session.headers["User-Agent"] = "sportsbynumbers/1.0"


def get(url: str, params: dict | None = None, tries: int = 4):
    for i in range(tries):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except (requests.RequestException, json.JSONDecodeError):
            pass
        time.sleep(2 ** i)
    return None


def season_dir(season: int):
    d = config.DATA_DIR / str(season)
    for sub in ("games", "box", "stints"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def fetch_teams(season: int) -> None:
    data = get(f"{config.ESPN}/teams", {"groups": config.DIVISION_I_GROUP, "limit": 500})
    teams = []
    for t in (data or {}).get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = t.get("team", {})
        teams.append({"team_id": str(t.get("id")), "name": t.get("displayName"),
                      "short": t.get("shortDisplayName") or t.get("location"),
                      "abbr": t.get("abbreviation"), "color": t.get("color") or "888888"})
    # Conference names come from the standings feed; it is optional.
    conf_of = {}
    st = get(config.STANDINGS, {"season": season})
    for child in (st or {}).get("children", []):
        label = (child.get("name") or "").replace(" Conference", "") if config.IS_NBA else (child.get("abbreviation") or child.get("name"))
        for e in child.get("standings", {}).get("entries", []):
            conf_of[str(e.get("team", {}).get("id"))] = label
    for t in teams:
        t["conf"] = conf_of.get(t["team_id"], "")
    if teams:
        pd.DataFrame(teams).to_csv(season_dir(season) / "teams.csv", index=False)


def fetch_rosters(season: int, max_age_days: int = 7) -> None:
    """Heights and listed positions for every D-I player. Refreshed weekly; rosters rarely change."""
    path = season_dir(season) / "rosters.csv"
    # File times reset on every checkout, so the fetch date is stored inside the file
    if path.exists():
        try:
            last = date.fromisoformat(str(pd.read_csv(path, usecols=["fetched"]).fetched.max()))
            if (date.today() - last).days < max_age_days:
                return
        except (ValueError, KeyError):
            pass
    teams_csv = season_dir(season) / "teams.csv"
    if not teams_csv.exists():
        return
    team_ids = pd.read_csv(teams_csv, dtype={"team_id": str}).team_id.tolist()

    def one(tid):
        data = get(f"{config.ESPN}/teams/{tid}/roster") or {}
        rows = []
        for a in data.get("athletes", []):
            if not isinstance(a, dict) or "id" not in a:
                continue
            rows.append({"player_id": str(a["id"]), "team_id": tid, "name": a.get("displayName", ""),
                         "pos": (a.get("position") or {}).get("abbreviation", ""),
                         "height": a.get("height"), "weight": a.get("weight"),
                         "class": (a.get("experience") or {}).get("abbreviation", "")})
        return rows

    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        rows = [r for team_rows in pool.map(one, team_ids) for r in team_rows]
    if rows:
        pd.DataFrame(rows).assign(fetched=date.today().isoformat()).to_csv(path, index=False)
        print(f"rosters: {len(rows)} players")


CORE_NBA = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"


def fetch_salaries(season: int, max_age_days: int = 7) -> None:
    """NBA only: each rostered player's current salary (weekly)."""
    if not config.IS_NBA:
        return
    path = season_dir(season) / "salaries.csv"
    if path.exists():
        try:
            last = date.fromisoformat(str(pd.read_csv(path, usecols=["fetched"]).fetched.max()))
            if (date.today() - last).days < max_age_days:
                return
        except (ValueError, KeyError):
            pass
    rpath = season_dir(season) / "rosters.csv"
    if not rpath.exists():
        return
    ids = pd.read_csv(rpath, dtype={"player_id": str}).player_id.unique().tolist()

    def one(pid):
        a = get(f"{CORE_NBA}/athletes/{pid}") or {}
        c = a.get("contract") or {}
        sal = c.get("salary")
        return {"player_id": pid, "salary": float(sal) if sal not in (None, "") else None,
                "min_exception": bool(c.get("minimumSalaryException"))}

    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        rows = list(pool.map(one, ids))
    df = pd.DataFrame(rows).assign(fetched=date.today().isoformat())
    df.to_csv(path, index=False)
    print(f"salaries: {df.salary.notna().sum()} of {len(df)} players")


def scoreboard(day: date, group: int | None = None) -> list[dict]:
    data = get(f"{config.ESPN}/scoreboard",
               {"dates": day.strftime("%Y%m%d"), "groups": group or config.DIVISION_I_GROUP, "limit": 500})
    out = []
    for ev in (data or {}).get("events", []):
        comp = ev.get("competitions", [{}])[0]
        teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in teams or "away" not in teams:
            continue
        out.append({
            "game_id": str(ev.get("id")), "date": day.isoformat(), "start": ev.get("date"),
            "completed": bool(comp.get("status", {}).get("type", {}).get("completed")),
            "neutral": bool(comp.get("neutralSite")),
            "home_id": str(teams["home"]["team"]["id"]), "away_id": str(teams["away"]["team"]["id"]),
            "home_name": teams["home"]["team"].get("shortDisplayName"),
            "away_name": teams["away"]["team"].get("shortDisplayName"),
            "home_pts": int(teams["home"].get("score") or 0), "away_pts": int(teams["away"].get("score") or 0),
            # Context used by the tournament model
            "season_type": (ev.get("season") or {}).get("type"),
            "tourney_id": comp.get("tournamentId"),
            "note": "; ".join(n.get("headline", "") for n in comp.get("notes", []) if n.get("headline")),
            "venue": (comp.get("venue") or {}).get("fullName"),
            "city": ((comp.get("venue") or {}).get("address") or {}).get("city"),
            "state": ((comp.get("venue") or {}).get("address") or {}).get("state"),
            "home_seed": (teams["home"].get("curatedRank") or {}).get("current"),
            "away_seed": (teams["away"].get("curatedRank") or {}).get("current"),
        })
    return out


def fetch_day(season: int, day: date) -> int:
    games = [g for g in scoreboard(day) if g["completed"]]
    if not games:
        (season_dir(season) / "games" / f"{day.isoformat()}.csv").write_text("")  # mark day as done
        return 0
    summaries = []
    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        summaries = list(pool.map(lambda g: get(f"{config.ESPN}/summary", {"event": g["game_id"]}), games))
    g_rows, b_rows, s_rows, shot_rows = [], [], [], []
    for sb, summ in zip(games, summaries):
        game, box, stints = parse_summary(summ) if summ else (None, [], [])
        if game is None:  # fall back to scoreboard result so team ratings still see the game
            game = {k: sb[k] for k in ("game_id", "neutral", "home_id", "away_id", "home_pts", "away_pts")}
            game.update(date=sb["date"], completed=True, conference_game=False)
        game["date"] = sb["date"]
        g_rows.append(game)
        b_rows += box
        s_rows += stints
        if summ and stints is not None:
            try:
                shot_rows += parse_shots(summ, game)
            except Exception:
                pass
    d = season_dir(season)
    name = day.isoformat()
    pd.DataFrame(g_rows).to_csv(d / "games" / f"{name}.csv", index=False)
    if b_rows:
        pd.DataFrame(b_rows).to_csv(d / "box" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    if s_rows:
        pd.DataFrame(s_rows).to_csv(d / "stints" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    if shot_rows:
        (d / "shots").mkdir(exist_ok=True)
        pd.DataFrame(shot_rows).to_csv(d / "shots" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    return len(g_rows)


def fetch_schedule(days_ahead: int | None = None) -> list[dict]:
    """Every scheduled game from today through the end of the season (or the next N days)."""
    today = date.today()
    end = config.season_end(config.season_for(today))
    n = (end - today).days + 1 if days_ahead is None else days_ahead
    days = [today + timedelta(days=i) for i in range(max(n, 0))]
    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        per_day = list(pool.map(scoreboard, days))
    return [g for rows in per_day for g in rows if not g["completed"]]


def fetch_prior_scores(season: int) -> None:
    """Final scores for last season (scoreboard only) to build the preseason prior."""
    path = config.DATA_DIR / str(season) / "prior_scores.csv"
    if path.exists():
        return
    prev = season - 1
    rows, day = [], config.season_start(prev)
    while day <= config.season_end(prev):
        rows += [g for g in scoreboard(day) if g["completed"]]
        day += timedelta(days=1)
    if rows:
        season_dir(season)
        pd.DataFrame(rows).to_csv(path, index=False)


def update(season: int | None = None, force: bool = False) -> None:
    today = date.today()
    season = season or config.season_for(today)
    d = season_dir(season)
    fetch_teams(season)
    if season == config.season_for(today):
        fetch_rosters(season)  # rosters are only available for the current season
        fetch_salaries(season)
    fetch_prior_scores(season)
    have = {p.name.split(".")[0] for p in (d / "games").glob("*.csv")}
    day = config.season_start(season)
    last = min(today - timedelta(days=1), config.season_end(season))
    recent = last - timedelta(days=config.REFETCH_DAYS - 1)
    while day <= last:
        if force or day.isoformat() not in have or day >= recent:
            n = fetch_day(season, day)
            print(f"{day}: {n} games")
        day += timedelta(days=1)
