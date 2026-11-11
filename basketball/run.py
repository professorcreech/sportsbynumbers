"""Daily entry point: fetch new games, refit every model, write the site's data files.

    python -m basketball.run --fetch          # what the GitHub job runs
    python -m basketball.run --simulate       # build the site from a simulated test season
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from . import config, conferences, players, positions, scouting, teams


def _clean(x):
    """Make data safe for browsers: missing values (NaN, None) become null, numpy types become plain."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


def _read(folder, pattern):
    frames = []
    for p in sorted(folder.glob(pattern)):
        if p.stat().st_size == 0:
            continue
        try:
            frames.append(pd.read_csv(p, dtype={"game_id": str, "team_id": str, "player_id": str,
                                                "home_id": str, "away_id": str}))
        except pd.errors.EmptyDataError:
            pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load(season: int):
    d = config.DATA_DIR / str(season)
    tm = pd.read_csv(d / "teams.csv", dtype={"team_id": str})
    games = _read(d / "games", "*.csv").drop_duplicates("game_id", keep="last")
    box = _read(d / "box", "*.csv.gz").drop_duplicates(["game_id", "player_id"], keep="last")
    stints = _read(d / "stints", "*.csv.gz")
    prior = pd.read_csv(d / "prior_scores.csv", dtype={"home_id": str, "away_id": str}) \
        if (d / "prior_scores.csv").exists() else None
    rosters = pd.read_csv(d / "rosters.csv", dtype={"player_id": str, "team_id": str}) \
        if (d / "rosters.csv").exists() else None
    return tm, games, box, stints, prior, rosters


def load_shots(season: int):
    d = config.DATA_DIR / str(season)
    shots = _read(d / "shots", "*.csv.gz") if (d / "shots").exists() else None
    return shots.drop_duplicates() if shots is not None and len(shots) else None


REPLACEMENT = -2.0    # a freely available player is ~2 points per 100 possessions below average
POINTS_PER_WIN = 30.0  # NBA: ~2.7 wins per point of average margin over 82 games
MIN_SALARY = 1.3e6     # roughly the league minimum; pay above it is what buys wins


def player_value(p: pd.DataFrame, t: pd.DataFrame, season: int) -> dict | None:
    """NBA: wins added over replacement and what each team pays for them."""
    path = config.DATA_DIR / str(season) / "salaries.csv"
    if not path.exists():
        return None
    sal = pd.read_csv(path, dtype={"player_id": str}).set_index("player_id").salary
    v = p[["player_id", "name", "team_id", "gp", "poss", "total"]].copy()
    v["salary"] = v.player_id.map(sal)
    v["war"] = (v.total - REPLACEMENT) * v.poss / 100 / POINTS_PER_WIN
    team_games = t.set_index("team_id").pipe(lambda d: d.wins + d.losses)
    v["pace"] = v.war * 82 / v.team_id.map(team_games).clip(lower=1)
    paid = v[v.salary.notna()]
    above_min = (paid.salary - MIN_SALARY).clip(lower=0).sum()
    total_war = paid.pace.clip(lower=0).sum()
    per_win = above_min / total_war if total_war > 0 else None
    v["surplus"] = v.pace * per_win - (v.salary - MIN_SALARY).clip(lower=0) if per_win else None
    teams_v = []
    for tid, g in v.groupby("team_id"):
        if tid not in set(t.team_id):
            continue
        payroll = g.salary.sum()
        teams_v.append({"id": tid, "payroll": round(float(payroll)), "war_pace": round(float(g.pace.sum()), 1),
                        "per_win": round(float((payroll - MIN_SALARY * g.salary.notna().sum()) / g.pace.clip(lower=0).sum()))
                        if g.pace.clip(lower=0).sum() > 0 else None})
    players_v = [{"id": r.player_id, "name": r.name, "team": r.team_id, "salary": None if pd.isna(r.salary) else round(float(r.salary)),
                  "war": round(float(r.war), 2), "pace": round(float(r.pace), 1),
                  "surplus": None if pd.isna(r.surplus) else round(float(r.surplus))}
                 for r in v[v.poss >= 100].itertuples()]
    return {"per_win": None if per_win is None else round(per_win), "replacement": REPLACEMENT, "points_per_win": POINTS_PER_WIN,
            "players": players_v, "teams": teams_v}


def build(tm, games, box, stints, prior, schedule, label: str, out_dir=None, rosters=None,
          season: int | None = None, shots=None) -> dict:
    out_dir = out_dir or config.SITE_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    games = games[games.completed.astype(bool)] if "completed" in games else games
    prior_games, pre_info = None, {}
    if season is not None:
        from . import preseason
        prior_net, pre_info = preseason.build_prior(season, rosters, box)
        prior_games = config.PRESEASON_GAMES if prior_net else None
    if not prior_net:  # fall back to last season's scores
        prior_net = teams.prior_from_last_season(prior, tm.team_id.tolist()) if prior is not None else {}
    model = teams.fit(games, box, tm, prior_net, prior_games=prior_games)
    t = model["table"]
    names = dict(zip(t.team_id, t.short))

    # Players
    p = pd.DataFrame()
    if len(stints):
        stints = stints.astype({"home_players": str, "away_players": str})
        # Re-tune shrinkage by cross-validation once there is enough data; early season uses the default
        proj, cw = pre_info.get("player_proj"), config.PLAYER_CARRY_WEIGHT
        lam = players.tune_lambda(stints, box, carry=proj, carry_weight=cw) if len(stints) > 40000 else config.PLAYER_LAMBDA
        p = players.fit(stints, box, lam, carry=proj, carry_weight=cw)
    p_out = []
    if len(p):
        p = p[p.team_id.isin(set(t.team_id))]
        p = positions.fill(p, rosters)
        print(f"positions: {int(p.pos_inferred.sum())} inferred from height, {int((p.pos == '').sum())} still blank, "
              f"{int(p.height.notna().sum())} of {len(p)} players have a height")
        p["rank"] = np.arange(1, len(p) + 1)
        for r in p.rename(columns={"def": "dfn"}).itertuples():
            p_out.append({"id": r.player_id, "name": r.name, "team": r.team_id, "pos": r.pos, "pos_inferred": bool(r.pos_inferred),
                          "ht": positions.display_height(r.height), "gp": int(r.gp),
                          "mpg": round(r.min / max(r.gp, 1), 1), "poss": int(r.poss),
                          "off": round(r.off, 2), "def": round(r.dfn, 2), "total": round(r.total, 2),
                          "prior": round(r.prior_off + r.prior_def, 2), "impact": round(r.impact, 2),
                          "ppg": round(r.pts / max(r.gp, 1), 1), "ts": None if pd.isna(r.ts) else round(r.ts, 3),
                          # per-40-minute rates used to fit lineups to an opponent
                          "r40": {k: round(float(getattr(r, k + "_40")), 1) for k in ("oreb", "dreb", "ast", "tov", "stl", "blk", "tpm", "fta")},
                          "tp_pct": None if not r.tpa else round(r.tpm / r.tpa, 3)})

    # Lineups
    lu_out = []
    if len(stints):
        pname = dict(zip(box.player_id, box.name))
        for r in players.lineups(stints).rename(columns={"def": "dfn"}).itertuples():
            if r.team_id not in names:
                continue
            lu_out.append({"team": r.team_id, "players": [pname.get(x, x) for x in r.players.split()],
                           "poss": round(r.poss, 1), "off": round(r.off, 1), "def": round(r.dfn, 1),
                           "net": round(r.net, 1)})

    # Upcoming games with predictions
    up = []
    for g in schedule:
        pr = teams.predict(model, g["home_id"], g["away_id"], g.get("neutral", False))
        if pr:
            up.append({"id": g["game_id"], "start": g.get("start") or g.get("date"), "neutral": bool(g.get("neutral")),
                       "home": g["home_id"], "away": g["away_id"],
                       "home_name": names.get(g["home_id"], g.get("home_name")), "away_name": names.get(g["away_id"], g.get("away_name")),
                       "home_score": round(pr["home_score"], 1), "away_score": round(pr["away_score"], 1),
                       "home_win": round(pr["home_win"], 3), "poss": round(pr["poss"], 1)})
    up.sort(key=lambda g: str(g["start"]))
    # The Games tab opens on the next three days; the full schedule is a separate, compact file
    # that loads only when someone searches for a team.
    cutoff = (datetime.now(timezone.utc) + pd.Timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    full = [[g["id"], g["start"], int(g["neutral"]), g["home"], g["away"], g["home_name"], g["away_name"],
             g["home_score"], g["away_score"], g["home_win"], g["poss"]] for g in up]
    up = [g for g in up if str(g["start"]) < cutoff]

    team_out = [{"id": r.team_id, "name": r.name, "short": r.short, "abbr": r.abbr, "conf": conferences.name(r.conf), "color": r.color,
                 "rank": int(r.rank), "net": round(r.net, 2), "net_se": round(r.net_se, 2), "o": round(r.adj_o, 1),
                 "d": round(r.adj_d, 1), "tempo": round(r.tempo, 1), "w": int(r.wins), "l": int(r.losses),
                 "o_rank": 0, "d_rank": 0, "t_rank": 0,
                 "ret": pre_info.get("returning", {}).get(r.team_id),
                 "pre": None if r.prior_net is None else round(r.prior_net, 2)} for r in t.itertuples()]
    for key, rk, rev in (("o", "o_rank", True), ("d", "d_rank", False), ("tempo", "t_rank", True)):
        for i, row in enumerate(sorted(team_out, key=lambda x: x[key], reverse=rev)):
            row[rk] = i + 1

    meta = {"site": config.SITE_NAME, "season": label,
            "league": {"key": config.LEAGUE, "nba": config.IS_NBA, "level": "NBA" if config.IS_NBA else "Division I",
                       "short": "NBA" if config.IS_NBA else "D-I", "minutes": config.GAME_MINUTES}, "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "games": int(len(games)), "stints": int(len(stints)), "mu": round(model["mu"], 2), "tau": round(model["tau"], 2),
            "hca": round(model["hca"], 2), "sd": round(model["sd"], 2),
            "lambda": float(p.attrs.get("lambda", config.PLAYER_LAMBDA)) if len(p) else None,
            "preseason": {k: v for k, v in pre_info.items() if k not in ("returning", "player_proj")},
            "player_carry_weight": config.PLAYER_CARRY_WEIGHT if pre_info.get("player_proj") else 0,
            # Spread of the preseason belief about a team's net rating (per 100 possessions):
            # offense and defense priors each have variance s2 / (games * 68)
            "prior_sd": round(float(np.sqrt(2 * model["s2"] / ((prior_games or config.TEAM_PRIOR_GAMES) * 68.0))), 2),
            # Everything the browser needs to predict any matchup on its own
            "model": {"ids": list(model["idx"].keys()), "O": np.round(model["O"], 3).tolist(),
                      "D": np.round(model["D"], 3).tolist(), "T": np.round(model["T"], 3).tolist()}}
    stats_out = scouting.team_profiles(games, box, shots, set(t.team_id)) if len(box) else {"league": {}, "teams": {}}
    value_out = player_value(p, t, season) if (config.IS_NBA and season and len(p)) else None
    schedule_out = {"fields": ["id", "start", "neutral", "home", "away", "home_name", "away_name",
                               "home_score", "away_score", "home_win", "poss"], "games": full}
    for name, obj in (("meta", meta), ("teams", team_out), ("players", p_out), ("lineups", lu_out), ("games", up),
                      ("schedule", schedule_out), ("teamstats", stats_out)) + ((("value", value_out),) if value_out else ()):
        (out_dir / f"{name}.json").write_text(json.dumps(_clean(obj), separators=(",", ":"), allow_nan=False))
    return {"model": model, "players": p, "teams": t}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--season", type=int)
    ap.add_argument("--backfill", type=int, help="download a past season (e.g. 2026 for 2025-26); no site build")
    ap.add_argument("--force", action="store_true", help="with --backfill: re-download days already saved")
    a = ap.parse_args()
    if a.backfill:
        from . import fetch
        fetch.update(a.backfill, force=a.force)
        return
    if a.simulate:
        from .simulate import season as sim
        tm, games, box, stints, *_ = sim()
        games = games.sort_values("date")
        last = games.date.max()
        played, future = games[games.date < "2027-02-20"], games[games.date >= "2027-02-20"].head(40)
        sched = future.to_dict("records")
        build(tm, played, box[box.game_id.isin(played.game_id)], stints[stints.game_id.isin(played.game_id)],
              None, sched, "Simulated test season")
        return
    season = a.season or config.season_for(date.today())
    sched = []
    if a.fetch:
        from . import fetch
        fetch.update(season)
        sched = fetch.fetch_schedule()
    tm, games, box, stints, prior, rosters = load(season)
    build(tm, games, box, stints, prior, sched, f"{season - 1}-{str(season)[2:]}", rosters=rosters, season=season,
          shots=load_shots(season))


if __name__ == "__main__":
    main()
