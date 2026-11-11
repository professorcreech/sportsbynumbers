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
from .parse import parse_summary

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
    st = get("https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings",
             {"season": season})
    for child in (st or {}).get("children", []):
        for e in child.get("standings", {}).get("entries", []):
            conf_of[str(e.get("team", {}).get("id"))] = child.get("abbreviation") or child.get("name")
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


def scoreboard(day: date) -> list[dict]:
    data = get(f"{config.ESPN}/scoreboard",
               {"dates": day.strftime("%Y%m%d"), "groups": config.DIVISION_I_GROUP, "limit": 500})
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
    g_rows, b_rows, s_rows = [], [], []
    for sb, summ in zip(games, summaries):
        game, box, stints = parse_summary(summ) if summ else (None, [], [])
        if game is None:  # fall back to scoreboard result so team ratings still see the game
            game = {k: sb[k] for k in ("game_id", "neutral", "home_id", "away_id", "home_pts", "away_pts")}
            game.update(date=sb["date"], completed=True, conference_game=False)
        game["date"] = sb["date"]
        g_rows.append(game)
        b_rows += box
        s_rows += stints
    d = season_dir(season)
    name = day.isoformat()
    pd.DataFrame(g_rows).to_csv(d / "games" / f"{name}.csv", index=False)
    if b_rows:
        pd.DataFrame(b_rows).to_csv(d / "box" / f"{name}.csv.gz", index=False)
    if s_rows:
        pd.DataFrame(s_rows).to_csv(d / "stints" / f"{name}.csv.gz", index=False)
    return len(g_rows)


def fetch_schedule(days_ahead: int = 3) -> list[dict]:
    today = date.today()
    out = []
    for i in range(days_ahead):
        out += [g for g in scoreboard(today + timedelta(days=i)) if not g["completed"]]
    return out


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


def update(season: int | None = None) -> None:
    today = date.today()
    season = season or config.season_for(today)
    d = season_dir(season)
    fetch_teams(season)
    if season == config.season_for(today):
        fetch_rosters(season)  # rosters are only available for the current season
    fetch_prior_scores(season)
    have = {p.name.split(".")[0] for p in (d / "games").glob("*.csv")}
    day = config.season_start(season)
    last = min(today - timedelta(days=1), config.season_end(season))
    recent = last - timedelta(days=config.REFETCH_DAYS - 1)
    while day <= last:
        if day.isoformat() not in have or day >= recent:
            n = fetch_day(season, day)
            print(f"{day}: {n} games")
        day += timedelta(days=1)
