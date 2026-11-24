"""Download Division I college football games, drives and plays from ESPN's public feed.

One small file per day per table under data/football/<season>/:
    games/<day>.csv          one row per game
    drives/<day>.csv.gz      one row per drive: offense, start field position, plays, yards, result, points
    plays/<day>.csv.gz       one row per scrimmage play: down, distance, yards to goal, type, yards gained
"""
from __future__ import annotations
import re

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
    for sub in ("games", "drives", "plays", "players"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def _weather(w: dict | None) -> dict:
    """Forecast or conditions ESPN lists for the game: temperature (F), wind gusts (mph), sky."""
    w = w or {}
    return {"wx_temp": w.get("temperature"), "wx_gust": w.get("gust") or w.get("windSpeed"),
            "wx_sky": w.get("displayValue"), "wx_precip": w.get("precipitation")}


def game_context(summ: dict) -> dict:
    """Officiating crew, attendance and any weather in the summary (saved for later analysis)."""
    gi = summ.get("gameInfo") or {}
    refs = [o.get("displayName") or o.get("fullName") for o in gi.get("officials") or []]
    referee = next((o.get("displayName") for o in gi.get("officials") or [] if (o.get("position") or {}).get("name") == "Referee"), None)
    out = {"officials": "|".join(r for r in refs if r), "referee": referee, "attendance": gi.get("attendance")}
    if gi.get("weather"):
        out.update({k: v for k, v in _weather(gi["weather"]).items() if v is not None})
    return out


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
                "indoor": (comp.get("venue") or {}).get("indoor"),
                **_weather(ev.get("weather") or comp.get("weather")),
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


_RDIR = re.compile(r"\b(left|right)\s+(end|tackle|guard)\b|\bup the middle\b|\b(?:middle|center)\b", re.I)
_PASS = re.compile(r"pass\s+(?:incomplete\s+)?(short|deep)?\s*(left|right|middle)?", re.I)


def play_tags(text: str) -> dict:
    """Direction, depth and shotgun flag from ESPN play text. Only the NFL feed carries these consistently;
    most college plays have none, so the fields are left blank rather than guessed."""
    t = text or ""
    out = {"gun": "shotgun" in t.lower(), "rdir": "", "rgap": "", "pdepth": "", "pdir": ""}
    m = _RDIR.search(t)
    if m:
        if m.group(1):
            out["rdir"], out["rgap"] = m.group(1).lower(), m.group(2).lower()
        else:
            out["rdir"], out["rgap"] = "middle", "middle"
    m = _PASS.search(t)
    if m and (m.group(1) or m.group(2)):
        out["pdepth"], out["pdir"] = (m.group(1) or "").lower(), (m.group(2) or "").lower()
    return out


def _lacks_tags(path) -> bool:
    import gzip
    try:
        with gzip.open(path, "rt") as f:
            return "rdir" not in f.readline()
    except (OSError, EOFError):
        return False


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
                          "home_score": _int(p.get("homeScore")), "away_score": _int(p.get("awayScore")),
                          **play_tags(p.get("text", ""))})
    return drives, plays


# (category, label) -> column for the per-player box score
_PLAYER_COLS = {
    ("passing", "YDS"): "pass_yds", ("passing", "TD"): "pass_td", ("passing", "INT"): "pass_int",
    ("rushing", "CAR"): "rush_car", ("rushing", "YDS"): "rush_yds", ("rushing", "TD"): "rush_td",
    ("receiving", "REC"): "rec", ("receiving", "YDS"): "rec_yds", ("receiving", "TD"): "rec_td",
    ("defensive", "TOT"): "tkl", ("defensive", "SOLO"): "solo", ("defensive", "SACKS"): "sacks",
    ("defensive", "TFL"): "tfl", ("defensive", "PD"): "pd", ("defensive", "QB HUR"): "hur",
    ("interceptions", "INT"): "def_int", ("fumbles", "LOST"): "fum_lost",
    ("punting", "NO"): "punts", ("punting", "AVG"): "punt_avg",
}


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_players(summ: dict, game: dict) -> list[dict]:
    """One row per player per game from the box score: what each player produced. (No snap counts in the feed.)"""
    rows = {}
    for tm in (summ.get("boxscore") or {}).get("players") or []:
        tid = str((tm.get("team") or {}).get("id", ""))
        for cat in tm.get("statistics") or []:
            name, labels = cat.get("name"), cat.get("labels") or []
            for a in cat.get("athletes") or []:
                ath = a.get("athlete") or {}
                pid = str(ath.get("id", ""))
                if not pid:
                    continue
                r = rows.setdefault((tid, pid), {"game_id": game["game_id"], "team_id": tid, "player_id": pid,
                                                 "name": ath.get("displayName") or ath.get("fullName")})
                for lab, val in zip(labels, a.get("stats") or []):
                    if name == "passing" and lab == "C/ATT" and "/" in str(val):
                        c, at = str(val).split("/", 1)
                        r["pass_cmp"], r["pass_att"] = _num(c), _num(at)
                    elif name == "kicking" and lab == "FG" and "/" in str(val):
                        m, at = str(val).split("/", 1)
                        r["fg_made"], r["fg_att"] = _num(m), _num(at)
                    elif (name, lab) in _PLAYER_COLS:
                        r[_PLAYER_COLS[(name, lab)]] = _num(val)
    return list(rows.values())


def fetch_roster(season: int, max_age_days: float = 7) -> None:
    """Every team's roster (position, class, height, weight), refreshed weekly: roster.csv."""
    import time
    f = season_dir(season) / "roster.csv"
    if f.exists() and time.time() - f.stat().st_mtime < max_age_days * 86400:
        return
    teams = season_dir(season) / "teams.csv"
    if not teams.exists():
        return
    ids = [str(t) for t in pd.read_csv(teams, dtype={"team_id": str}).team_id]

    def one(tid):
        out = []
        try:
            data = get(f"{config.ESPN}/teams/{tid}/roster") or {}
        except Exception:
            return out
        for grp in data.get("athletes") or []:
            for a in grp.get("items") or []:
                pos = a.get("position") or {}
                out.append({"team_id": tid, "player_id": str(a.get("id")), "name": a.get("displayName") or a.get("fullName"),
                            "pos": pos.get("abbreviation"), "jersey": a.get("jersey"),
                            "class": (a.get("experience") or {}).get("abbreviation"),
                            "years": (a.get("experience") or {}).get("years"),
                            "height": a.get("height"), "weight": a.get("weight")})
        return out

    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        rows = [r for rs in pool.map(one, ids) for r in rs]
    if len(rows) > 500:
        pd.DataFrame(rows).to_csv(f, index=False)
        print(f"roster: {len(rows)} players on {len(ids)} teams")


def fetch_day(season: int, day: date) -> int:
    d = season_dir(season)
    games = [g for g in scoreboard(day) if g["completed"]]
    if not games:
        (d / "games" / f"{day.isoformat()}.csv").write_text("")
        return 0
    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        summaries = list(pool.map(lambda g: get(f"{config.ESPN}/summary", {"event": g["game_id"]}), games))
    drv, ply, pls = [], [], []
    for g, s in zip(games, summaries):
        if s:
            g.update(game_context(s))
            try:
                a, b = parse_summary(s, g)
                drv += a
                ply += b
                pls += parse_players(s, g)
            except Exception as e:
                print(f"  could not parse {g['game_id']}: {e}")
    name = day.isoformat()
    pd.DataFrame(games).to_csv(d / "games" / f"{name}.csv", index=False)
    if drv:
        pd.DataFrame(drv).to_csv(d / "drives" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    if ply:
        pd.DataFrame(ply).to_csv(d / "plays" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    if pls:
        pd.DataFrame(pls).to_csv(d / "players" / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    return len(games)


def fetch_schedule(days_ahead: int | None = None) -> list[dict]:
    """Every scheduled game from today through the end of the season (or the next N days)."""
    today = date.today()
    end = config.season_end(config.season_for(today))
    n = (end - today).days + 1 if days_ahead is None else days_ahead
    days = [today + timedelta(days=i) for i in range(max(n, 0))]
    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        per_day = list(pool.map(scoreboard, days))
    # A late game can be listed on two calendar days; keep each game once
    seen, out = set(), []
    for g in (g for rows in per_day for g in rows if not g["completed"]):
        if g["game_id"] not in seen:
            seen.add(g["game_id"])
            out.append(g)
    return out


def fetch_injuries(schedule: list, days: int = 3) -> None:
    """NFL pregame injury reports for games in the next few days, saved by day under data/nfl/injuries/ so their value
    (for example a starting quarterback out) can be tested once enough games have been played. ESPN lists none for college."""
    if not config.IS_NFL:
        return
    import json
    from datetime import datetime, timezone
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    ids = [g["game_id"] for g in schedule if str(g.get("start") or g.get("date")) < cutoff]
    if not ids:
        return
    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        sums = list(pool.map(lambda i: get(f"{config.ESPN}/summary", {"event": i}), ids))
    out = {}
    for gid, sm in zip(ids, sums):
        teams = {}
        for blk in (sm or {}).get("injuries") or []:
            tid = str((blk.get("team") or {}).get("id"))
            rows = []
            for i in blk.get("injuries") or []:
                a = i.get("athlete") or {}
                if a.get("id"):
                    rows.append({"id": str(a["id"]), "name": a.get("displayName"), "pos": (a.get("position") or {}).get("abbreviation"),
                                 "status": i.get("status"), "date": i.get("date")})
            teams[tid] = rows
        out[gid] = teams
    if out:
        d = config.DATA_DIR / "injuries"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{date.today().isoformat()}.json").write_text(json.dumps(out, separators=(",", ":")))
        print(f"injuries: {sum(len(v) for t in out.values() for v in t.values())} listed for {len(out)} games")


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
    have_pl = {p.name.split(".")[0] for p in (d / "players").glob("*.csv.gz")}
    if season == config.season_for(today):
        fetch_roster(season)   # ESPN only serves current rosters
    day, last = config.season_start(season), min(today - timedelta(days=1), config.season_end(season))
    recent = last - timedelta(days=config.REFETCH_DAYS - 1)
    while day <= last:
        iso = day.isoformat()
        # one-time backfill of box scores for the current season's earlier days
        need_pl = iso in have and iso not in have_pl and (d / "games" / f"{iso}.csv").stat().st_size > 5
        need_tag = iso in have and _lacks_tags(d / "plays" / f"{iso}.csv.gz")   # one-time pickup of direction/depth tags
        if force or iso not in have or day >= recent or need_pl or need_tag:
            n = fetch_day(season, day)
            if n:
                print(f"{day}: {n} games")
        day += timedelta(days=1)
