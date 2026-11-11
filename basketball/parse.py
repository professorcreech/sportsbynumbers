"""Turn one ESPN game summary into three tables: game, player box score, lineup stints.

A stint is a stretch of play with the same ten players on the floor. For each stint we
record who was on court, points for each side, and an estimate of possessions. Stints are
the raw material for the player impact model and the lineup tables.
"""
from __future__ import annotations

from . import config

FT_SHARE = config.FT_SHARE  # possessions per free-throw attempt
BOX_FIELDS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF"]


def _int(x, default=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def _split(x):
    """'5-11' -> (5, 11)"""
    if not isinstance(x, str) or "-" not in x:
        return 0, 0
    a, b = x.split("-", 1)
    return _int(a), _int(b)


def parse_header(summary: dict) -> dict | None:
    comp = summary.get("header", {}).get("competitions", [{}])[0]
    teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in teams or "away" not in teams:
        return None
    status = comp.get("status", {}).get("type", {})
    return {
        "game_id": str(summary.get("header", {}).get("id") or comp.get("id")),
        "date": (comp.get("date") or "")[:10],
        "neutral": bool(comp.get("neutralSite", False)),
        "conference_game": bool(comp.get("conferenceCompetition", False)),
        "completed": bool(status.get("completed", False)),
        "home_id": str(teams["home"]["team"]["id"]),
        "away_id": str(teams["away"]["team"]["id"]),
        "home_pts": _int(teams["home"].get("score")),
        "away_pts": _int(teams["away"].get("score")),
        "start": comp.get("date"),
        # points by period ("38|41" or "25|28|30|27"), for halftime and quarter analysis
        "home_periods": "|".join(str(_int(x.get("displayValue", x.get("value")))) for x in teams["home"].get("linescores") or []),
        "away_periods": "|".join(str(_int(x.get("displayValue", x.get("value")))) for x in teams["away"].get("linescores") or []),
        **parse_odds(summary),
    }


def parse_odds(summary: dict) -> dict:
    """Pregame betting line from ESPN's pickcenter (first provider listed)."""
    pc = summary.get("pickcenter") or []
    if not pc:
        return {}
    o = pc[0]
    num = lambda x: float(x) if isinstance(x, (int, float)) or (isinstance(x, str) and x.replace(".", "", 1).lstrip("+-").isdigit()) else None
    return {"line_provider": (o.get("provider") or {}).get("name"), "line_details": o.get("details"),
            "line_spread": num(o.get("spread")), "line_total": num(o.get("overUnder")),
            "line_home_ml": num((o.get("homeTeamOdds") or {}).get("moneyLine")),
            "line_away_ml": num((o.get("awayTeamOdds") or {}).get("moneyLine")),
            "line_home_fav": (o.get("homeTeamOdds") or {}).get("favorite")}


def parse_box(summary: dict, game_id: str) -> list[dict]:
    rows = []
    for block in summary.get("boxscore", {}).get("players", []):
        team_id = str(block.get("team", {}).get("id"))
        for stat_group in block.get("statistics", [])[:1]:
            names = stat_group.get("names") or stat_group.get("labels") or []
            for a in stat_group.get("athletes", []):
                if a.get("didNotPlay"):
                    continue
                vals = dict(zip(names, a.get("stats", [])))
                fgm, fga = _split(vals.get("FG"))
                tpm, tpa = _split(vals.get("3PT"))
                ftm, fta = _split(vals.get("FT"))
                ath = a.get("athlete", {})
                rows.append({
                    "game_id": game_id, "team_id": team_id,
                    "player_id": str(ath.get("id")), "name": ath.get("displayName", ""),
                    "pos": (ath.get("position") or {}).get("abbreviation", ""),
                    "starter": bool(a.get("starter", False)),
                    "min": _int(vals.get("MIN")), "pts": _int(vals.get("PTS")),
                    "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa, "ftm": ftm, "fta": fta,
                    "oreb": _int(vals.get("OREB")), "dreb": _int(vals.get("DREB")),
                    "ast": _int(vals.get("AST")), "tov": _int(vals.get("TO")),
                    "stl": _int(vals.get("STL")), "blk": _int(vals.get("BLK")), "pf": _int(vals.get("PF")),
                })
    return rows


# ---- play-by-play -----------------------------------------------------------

def _kind(play: dict) -> str:
    t = (play.get("type") or {}).get("text", "") or ""
    text = (play.get("text") or "").lower()
    if t == "Substitution" or "subbing" in text or "enters the game" in text:
        if "enters the game" in text:
            return "sub_swap"  # NBA: one play, participants = [player in, player out]
        return "sub_in" if "subbing in" in text else ("sub_out" if "subbing out" in text else "sub")
    if "FreeThrow" in t.replace(" ", "") or "free throw" in text:
        return "fta"
    if t == "Offensive Rebound":
        return "oreb"
    if "Turnover" in t:
        return "tov"
    if play.get("shootingPlay"):
        return "fga"
    return "other"


def _athlete(play: dict) -> str | None:
    parts = play.get("participants") or []
    if parts:
        return str((parts[0].get("athlete") or {}).get("id"))
    return None


def parse_stints(summary: dict, game: dict, box: list[dict]) -> list[dict]:
    plays = sorted(summary.get("plays", []), key=lambda p: _int(p.get("sequenceNumber"), 0))
    if not plays:
        return []
    # Without substitutions we can't know who was on the floor; guessing "starters all game" would
    # bias every player rating, so record nothing for that game.
    if sum(_kind(p) in ("sub_in", "sub_out", "sub_swap") for p in plays) < 4:
        return []
    home, away = game["home_id"], game["away_id"]
    team_of = {r["player_id"]: r["team_id"] for r in box}
    starters = {home: {r["player_id"] for r in box if r["team_id"] == home and r["starter"]},
                away: {r["player_id"] for r in box if r["team_id"] == away and r["starter"]}}

    # Who is on the floor at the start of each period: anyone whose first action in
    # that period is something other than subbing in. Fall back to previous lineup.
    periods = {}
    for p in plays:
        periods.setdefault(_int((p.get("period") or {}).get("number"), 1), []).append(p)

    def period_start_lineup(pplays, prev):
        first = {}
        for p in pplays:
            k = _kind(p)
            if k == "sub_swap":  # the player coming in wasn't on the floor; the one going out was
                parts = p.get("participants") or []
                ids = [str((x.get("athlete") or {}).get("id")) for x in parts[:2]]
                for pid, role in zip(ids, ("sub_in", "sub_out")):
                    if pid in team_of and pid not in first:
                        first[pid] = role
                continue
            pid = _athlete(p)
            if pid and pid in team_of and pid not in first:
                first[pid] = k
        lineup = {}
        for tid in (home, away):
            on = {pid for pid, k in first.items() if team_of[pid] == tid and k != "sub_in"}
            if len(on) < 5:  # quiet players who never touched the ball: keep from previous lineup
                for pid in prev.get(tid, set()):
                    if len(on) >= 5:
                        break
                    if first.get(pid) != "sub_in":
                        on.add(pid)
            lineup[tid] = on
        return lineup

    stints = []
    lineup = {home: set(starters[home]), away: set(starters[away])}
    cur = None
    last_score = (0, 0)

    def open_stint():
        return {"h": frozenset(lineup[home]), "a": frozenset(lineup[away]),
                "pts": {home: 0, away: 0},
                "cnt": {tid: {"fga": 0, "oreb": 0, "tov": 0, "fta": 0} for tid in (home, away)},
                "events": 0}

    def close(st):
        if st is None or st["events"] == 0:
            return
        if len(st["h"]) != 5 or len(st["a"]) != 5:
            return  # lineup tracking failed for this stretch; drop rather than guess
        poss = []
        for tid in (home, away):
            c = st["cnt"][tid]
            poss.append(max(0.0, c["fga"] - c["oreb"] + c["tov"] + FT_SHARE * c["fta"]))
        n = (poss[0] + poss[1]) / 2
        if n <= 0:
            return
        stints.append({
            "game_id": game["game_id"], "home_id": home, "away_id": away, "neutral": game["neutral"],
            "home_players": " ".join(sorted(st["h"])), "away_players": " ".join(sorted(st["a"])),
            "home_pts": st["pts"][home], "away_pts": st["pts"][away], "poss": round(n, 2),
        })

    for period in sorted(periods):
        if period > 1 or len(lineup[home]) != 5 or len(lineup[away]) != 5:
            close(cur)
            lineup = period_start_lineup(periods[period], lineup)
            cur = None
        dirty = cur is None
        for p in periods[period]:
            k = _kind(p)
            pid = _athlete(p)
            if k == "sub_swap":
                parts = p.get("participants") or []
                ids = [str((x.get("athlete") or {}).get("id")) for x in parts[:2]]
                if len(ids) == 2 and ids[0] in team_of:
                    tid = team_of[ids[0]]
                    lineup[tid].discard(ids[1])
                    lineup[tid].add(ids[0])
                    dirty = True
                continue
            if k in ("sub_in", "sub_out"):
                tid = team_of.get(pid)
                if tid:
                    (lineup[tid].add if k == "sub_in" else lineup[tid].discard)(pid)
                    dirty = True
                continue
            if dirty:
                close(cur)
                cur = open_stint()
                dirty = False
            hs, as_ = _int(p.get("homeScore"), last_score[0]), _int(p.get("awayScore"), last_score[1])
            cur["pts"][home] += max(0, hs - last_score[0])
            cur["pts"][away] += max(0, as_ - last_score[1])
            last_score = (max(hs, last_score[0]), max(as_, last_score[1]))
            tid = str((p.get("team") or {}).get("id")) if p.get("team") else None
            if tid in cur["cnt"] and k in cur["cnt"][tid]:
                cur["cnt"][tid][k] += 1
            cur["events"] += 1
    close(cur)
    return stints


def parse_summary(summary: dict):
    game = parse_header(summary)
    if game is None:
        return None, [], []
    box = parse_box(summary, game["game_id"])
    try:
        stints = parse_stints(summary, game, box)
    except Exception:
        stints = []
    return game, box, stints


def parse_shots(summary: dict, game: dict) -> list[dict]:
    """One row per shot attempt (free throws included), for style and scouting profiles.

    ESPN coordinates are in feet on a half court; free throws carry placeholder values,
    which are kept but flagged by kind == "ft"."""
    rows = []
    for p in summary.get("plays", []):
        if not p.get("shootingPlay"):
            continue
        t = (p.get("type") or {}).get("text", "") or ""
        text = p.get("text") or ""
        low = text.lower()
        team = str((p.get("team") or {}).get("id", "")) if p.get("team") else ""
        parts = p.get("participants") or []
        shooter = str((parts[0].get("athlete") or {}).get("id")) if parts else ""
        assister = str((parts[1].get("athlete") or {}).get("id")) if len(parts) > 1 and "assist" in low else ""
        is_ft = "freethrow" in t.replace(" ", "").lower() or "free throw" in low
        pts_att = p.get("pointsAttempted")
        three = (pts_att == 3) or ("three point" in low) or ("3-pt" in low)
        tl = t.lower()
        # College types are "LayUpShot"/"DunkShot"/"TipShot"; the NBA's are "Driving Layup Shot",
        # "Cutting Dunk Shot", "Alley Oop Layup", "Putback Dunk", "Tip Shot" and so on.
        rim = "dunk" if "dunk" in tl else "layup" if ("layup" in tl or "lay up" in tl or "alley" in tl) else "tip" if "tip" in tl else None
        kind = "ft" if is_ft else ("three" if three else (rim or "jumper"))
        c = p.get("coordinate") or {}
        x, y = c.get("x"), c.get("y")
        if not isinstance(x, (int, float)) or abs(x) > 1000:
            x = y = None
        rows.append({
            "game_id": game["game_id"], "team_id": team,
            "opp_id": game["away_id"] if team == game["home_id"] else game["home_id"],
            "player_id": shooter, "assist_id": assister,
            "period": _int((p.get("period") or {}).get("number"), 0),
            "clock": (p.get("clock") or {}).get("displayValue", ""),
            "kind": kind, "type": t, "made": bool(p.get("scoringPlay")) or " made " in f" {low} ",
            "x": x, "y": y,
        })
    return rows
