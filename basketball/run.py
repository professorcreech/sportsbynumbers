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

from . import config, players, positions, teams


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


def build(tm, games, box, stints, prior, schedule, label: str, out_dir=None, rosters=None) -> dict:
    out_dir = out_dir or config.SITE_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    games = games[games.completed.astype(bool)] if "completed" in games else games
    prior_net = teams.prior_from_last_season(prior, tm.team_id.tolist()) if prior is not None else {}
    model = teams.fit(games, box, tm, prior_net)
    t = model["table"]
    names = dict(zip(t.team_id, t.short))

    # Players
    p = pd.DataFrame()
    if len(stints):
        stints = stints.astype({"home_players": str, "away_players": str})
        # Re-tune shrinkage by cross-validation once there is enough data; early season uses the default
        lam = players.tune_lambda(stints, box) if len(stints) > 40000 else config.PLAYER_LAMBDA
        p = players.fit(stints, box, lam)
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
                          "ppg": round(r.pts / max(r.gp, 1), 1), "ts": None if pd.isna(r.ts) else round(r.ts, 3)})

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

    team_out = [{"id": r.team_id, "name": r.name, "short": r.short, "abbr": r.abbr, "conf": r.conf, "color": r.color,
                 "rank": int(r.rank), "net": round(r.net, 2), "net_se": round(r.net_se, 2), "o": round(r.adj_o, 1),
                 "d": round(r.adj_d, 1), "tempo": round(r.tempo, 1), "w": int(r.wins), "l": int(r.losses),
                 "o_rank": 0, "d_rank": 0, "t_rank": 0} for r in t.itertuples()]
    for key, rk, rev in (("o", "o_rank", True), ("d", "d_rank", False), ("tempo", "t_rank", True)):
        for i, row in enumerate(sorted(team_out, key=lambda x: x[key], reverse=rev)):
            row[rk] = i + 1

    meta = {"site": config.SITE_NAME, "season": label, "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "games": int(len(games)), "stints": int(len(stints)), "mu": round(model["mu"], 2), "tau": round(model["tau"], 2),
            "hca": round(model["hca"], 2), "sd": round(model["sd"], 2),
            "lambda": float(p.attrs.get("lambda", config.PLAYER_LAMBDA)) if len(p) else None,
            # Everything the browser needs to predict any matchup on its own
            "model": {"ids": list(model["idx"].keys()), "O": np.round(model["O"], 3).tolist(),
                      "D": np.round(model["D"], 3).tolist(), "T": np.round(model["T"], 3).tolist()}}
    for name, obj in (("meta", meta), ("teams", team_out), ("players", p_out), ("lineups", lu_out), ("games", up)):
        (out_dir / f"{name}.json").write_text(json.dumps(_clean(obj), separators=(",", ":"), allow_nan=False))
    return {"model": model, "players": p, "teams": t}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--season", type=int)
    a = ap.parse_args()
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
    build(tm, games, box, stints, prior, sched, f"{season - 1}-{str(season)[2:]}", rosters=rosters)


if __name__ == "__main__":
    main()
