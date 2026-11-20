"""Prediction ledger: what the model said before each game, and how it turned out.

Every daily run saves the prediction for each game starting in the next 36 hours (and keeps refreshing it until the
game starts, so the saved number is the last one made before tip-off, with injuries and rest applied). Once the
final score is in, the game is graded. The ledger never sees a result before its prediction is frozen.

  python -m tools.ledger            # record upcoming games, grade finished ones, write site/<league>/data/record.json
  python -m tools.ledger --backfill # first, rebuild earlier days from the site's published git history
Files: data/<league>/ledger.csv (one row per game) and site/<league>/data/record.json (the summary the Record tab reads).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from math import ceil, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEAGUES = {"basketball": "Men’s college basketball", "nba": "NBA", "football": "College football", "nfl": "NFL"}
WINDOW_H = 36
COLS = ["game_id", "start", "home", "away", "home_name", "away_name", "neutral", "p_home", "margin", "snap",
        "home_pts", "away_pts", "line_spread"]


def _ts(x) -> pd.Timestamp | None:
    t = pd.to_datetime(x, utc=True, errors="coerce")
    return None if pd.isna(t) else t


def _rows_from(obj) -> list[dict]:
    """Upcoming-game predictions from a games.json or schedule.json payload."""
    if isinstance(obj, dict) and "fields" in obj:
        obj = [dict(zip(obj["fields"], r)) for r in obj["games"]]
    out = []
    for g in obj or []:
        try:
            out.append({"game_id": str(g["id"]), "start": g["start"], "home": str(g["home"]), "away": str(g["away"]),
                        "home_name": g.get("home_name"), "away_name": g.get("away_name"), "neutral": int(bool(g.get("neutral"))),
                        "p_home": float(g["home_win"]), "margin": round(float(g["home_score"]) - float(g["away_score"]), 2)})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load_ledger(league: str) -> pd.DataFrame:
    f = ROOT / "data" / league / "ledger.csv"
    if f.exists():
        return pd.read_csv(f, dtype={"game_id": str, "home": str, "away": str})
    return pd.DataFrame(columns=COLS)


def upsert(ledger: pd.DataFrame, rows: list[dict], snap: pd.Timestamp) -> pd.DataFrame:
    """Add or refresh predictions made `snap`, only for games starting within the window and not yet started."""
    have = ledger.set_index("game_id") if len(ledger) else pd.DataFrame(columns=COLS[1:]).rename_axis("game_id")
    new = []
    for r in rows:
        st = _ts(r["start"])
        if st is None or not (snap < st <= snap + pd.Timedelta(hours=WINDOW_H)):
            continue
        if r["game_id"] in have.index:
            old = _ts(have.at[r["game_id"], "snap"])
            if old is not None and old >= snap:
                continue
        new.append({**r, "snap": snap.strftime("%Y-%m-%dT%H:%MZ")})
    if not new:
        return ledger
    keep = ledger[~ledger.game_id.isin({n["game_id"] for n in new})] if len(ledger) else ledger
    out = pd.concat([keep, pd.DataFrame(new)], ignore_index=True)
    return out.reindex(columns=COLS)


def results(league: str, seasons: int = 2) -> pd.DataFrame:
    frames = []
    for s in sorted((ROOT / "data" / league).glob("20*"))[-seasons:]:
        for f in sorted((s / "games").glob("*.csv")) if (s / "games").exists() else []:
            if f.stat().st_size == 0:
                continue
            try:
                d = pd.read_csv(f, dtype={"game_id": str})
            except pd.errors.EmptyDataError:
                continue
            d = d[d.completed.astype(str).str.lower().eq("true")]
            cols = [c for c in ("game_id", "home_pts", "away_pts", "line_spread") if c in d]
            frames.append(d[cols])
    return pd.concat(frames, ignore_index=True).drop_duplicates("game_id", keep="last") if frames else pd.DataFrame(columns=["game_id"])


def grade(ledger: pd.DataFrame, res: pd.DataFrame) -> pd.DataFrame:
    if not len(ledger) or not len(res):
        return ledger
    L = ledger.drop(columns=["home_pts", "away_pts", "line_spread"], errors="ignore").merge(res, on="game_id", how="left")
    return L.reindex(columns=COLS)


def history(league: str) -> pd.DataFrame:
    """Rebuild the ledger from every published version of site/<league>/data/games.json."""
    path = f"site/{league}/data/games.json"
    log = subprocess.run(["git", "log", "--reverse", "--format=%H %aI", "--", path], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    led = load_ledger(league)
    for line in filter(None, log):
        sha, when = line.split(" ", 1)
        blob = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=ROOT, capture_output=True, text=True)
        if blob.returncode:
            continue
        try:
            led = upsert(led, _rows_from(json.loads(blob.stdout)), pd.Timestamp(when).tz_convert("UTC"))
        except Exception:
            continue
    return led


def _team_rows(g: pd.DataFrame, ranks: dict, n_teams: int) -> dict:
    big = max(10, ceil(0.1 * n_teams))
    rows = []
    for r in g.itertuples():
        for side, tid, opp in (("h", r.home, r.away), ("a", r.away, r.home)):
            sgn = 1 if side == "h" else -1
            rows.append({"team": tid, "res": sgn * (r.actual - r.margin), "hit": bool(r.hit), "big": (ranks.get(opp) or 999) <= big and (ranks.get(tid) or 999) > 0,
                         "fav": (r.p_home if side == "h" else 1 - r.p_home) >= 0.5, "won": (sgn * r.actual) > 0})
    t = pd.DataFrame(rows)
    # How much of the team-to-team spread is real? Variance of team averages minus what luck alone would produce.
    g = t.groupby("team").res.agg(["size", "mean", "var"])
    g = g[g["size"] >= 3]
    sig2 = float(t.res.var()) if len(t) > 2 else 1.0
    tau2 = max(float(g["mean"].var() - (sig2 / g["size"]).mean()), 0.0) if len(g) > 10 else 0.0
    out = {}
    for tid, x in t.groupby("team"):
        n_ = len(x)
        lam = tau2 / (tau2 + sig2 / n_) if tau2 > 0 else 0.0
        d = {"n": int(len(x)), "hit": int(x.hit.sum()), "won": int(x.won.sum()),
             "raw": round(float(x.res.mean()), 2), "res": round(lam * float(x.res.mean()), 2),
             "se": round(float(sqrt(lam * sig2 / n_)), 2),
             "sd": round(float(x.res.std(ddof=1)), 2) if len(x) > 2 else None}
        b = x[x.big]
        if len(b) >= 2:
            d["big_n"], d["big_res"] = int(len(b)), round(float(b.res.mean()), 2)
        out[tid] = d
    return {"teams": out, "tau": round(sqrt(tau2), 2), "noise_se": round(sqrt(sig2 / max(g["size"].median() if len(g) else 1, 1)), 2)}

def _persistence(league: str) -> dict | None:
    """Do teams keep beating (or missing) their predictions? Uses the two full replays (last season, this season so far)."""
    fa, fb = ROOT / "data" / league / "replay.csv", ROOT / "data" / league / "replay_now.csv"
    if not (fa.exists() and fb.exists()):
        return None

    def per_team(d):
        d = d.assign(res=(d.home_pts - d.away_pts) - d.margin).sort_values("start")
        return pd.concat([pd.DataFrame({"t": d.home.astype(str), "r": d.res}), pd.DataFrame({"t": d.away.astype(str), "r": -d.res})])
    A, B = per_team(pd.read_csv(fa)), per_team(pd.read_csv(fb))
    A["half"] = A.groupby("t").cumcount() % 2
    h = A.groupby(["t", "half"]).r.mean().unstack().dropna()
    m = A.groupby("t").r.agg(["size", "mean"]).join(B.groupby("t").r.mean().rename("b"), how="inner")
    m = m[m["size"] >= 10]
    if len(h) < 15 or len(m) < 15:
        return None
    return {"within": round(float(np.corrcoef(h[0], h[1])[0, 1]), 2), "across": round(float(np.corrcoef(m["mean"], m.b)[0, 1]), 2), "teams": int(len(m))}


def _core(led: pd.DataFrame) -> dict | None:
    """Headline numbers for a set of graded predictions."""
    g = led.dropna(subset=["home_pts", "away_pts"]).copy()
    g = g[(g.p_home != 0.5) & (g.home_pts != g.away_pts)]
    if not len(g):
        return None
    actual = g.home_pts - g.away_pts
    won = (actual > 0).astype(int)
    hit = ((g.p_home > 0.5).astype(int) == won).astype(int)
    conf = np.where(g.p_home > 0.5, g.p_home, 1 - g.p_home)
    d = {"n": int(len(g)), "hit": int(hit.sum()), "brier": round(float(((g.p_home - won) ** 2).mean()), 4),
         "mae": round(float((actual - g.margin).abs().mean()), 2), "home_rate": round(float(won.mean()), 3),
         "avg_conf": round(float(conf.mean()), 3)}
    if "line_spread" in g and g.line_spread.notna().sum() >= 10:
        m = g.dropna(subset=["line_spread"])
        m = m[m.line_spread != 0]
        d["market"] = {"n": int(len(m)), "model_hit": int(hit[m.index].sum()),
                       "market_hit": int(((m.line_spread < 0).astype(int) == won[m.index]).sum()),
                       "model_mae": round(float((actual[m.index] - m.margin).abs().mean()), 2),
                       "market_mae": round(float((actual[m.index] + m.line_spread).abs().mean()), 2)}
    return d


def _replay(league: str, g: pd.DataFrame) -> dict | None:
    """Last season's replay (tools/replay.py): the whole season, and the same dates a year earlier."""
    f = ROOT / "data" / league / "replay.csv"
    if not f.exists() or not len(g):
        return None
    r = pd.read_csv(f, dtype={"game_id": str, "home": str, "away": str})
    full = _core(r)
    if not full:
        return None
    st = pd.to_datetime(r.start, utc=True)
    cur = pd.to_datetime(g.start, utc=True)
    lo, hi = cur.min() - pd.Timedelta(days=364), cur.max() - pd.Timedelta(days=364)
    same = _core(r[(st >= lo) & (st <= hi + pd.Timedelta(days=1))])
    return {"full": full, "same": same, "from": str(lo.date()), "to": str(hi.date())}


def summarize(league: str, led: pd.DataFrame) -> dict | None:
    g = led.dropna(subset=["home_pts", "away_pts"]).copy()
    g = g[(g.p_home != 0.5) & (g.home_pts != g.away_pts)]
    if not len(g):
        return None
    g["actual"] = g.home_pts - g.away_pts
    g["won"] = (g.actual > 0).astype(int)
    g["pick"] = (g.p_home > 0.5).astype(int)
    g["hit"] = (g.pick == g.won).astype(int)
    g["conf"] = np.where(g.p_home > 0.5, g.p_home, 1 - g.p_home)
    g = g.sort_values("start")
    n = len(g)
    bins = []
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        x = g[(g.conf >= lo) & (g.conf < hi)]
        if len(x):
            bins.append({"lo": lo, "hi": min(hi, 1.0), "n": int(len(x)), "pred": round(float(x.conf.mean()), 3), "hit": round(float(x.hit.mean()), 3)})
    st = pd.to_datetime(g.start, utc=True)
    wk = st.dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")
    weekly = [{"week": k, "n": int(len(x)), "hit": int(x.hit.sum())} for k, x in g.groupby(wk)]
    out = {"league": league, "name": LEAGUES[league], "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "first": str(st.min().date()), "n": int(n), "hit": int(g.hit.sum()),
           "brier": round(float(((g.p_home - g.won) ** 2).mean()), 4), "brier_coin": 0.25,
           "mae": round(float((g.actual - g.margin).abs().mean()), 2),
           "home_rate": round(float((g.actual > 0).mean()), 3),
           "fav_n": int((g.conf >= 0.7).sum()), "fav_hit": int(g[g.conf >= 0.7].hit.sum()),
           "bins": bins, "weekly": weekly}
    if "line_spread" in g and g.line_spread.notna().sum() >= 10:
        m = g.dropna(subset=["line_spread"])
        m = m[m.line_spread != 0]
        mk = (m.line_spread < 0).astype(int)
        out["market"] = {"n": int(len(m)), "model_hit": int(m.hit.sum()), "market_hit": int((mk == m.won).sum()),
                         "model_mae": round(float((m.actual - m.margin).abs().mean()), 2),
                         "market_mae": round(float((m.actual + m.line_spread).abs().mean()), 2)}
    site = ROOT / "site" / league / "data" / "teams.json"
    try:
        tj = json.loads(site.read_text())
        ranks = {str(t["id"]): t["rank"] for t in tj}
    except Exception:
        ranks = {}
    out["replay"] = _replay(league, g)
    out["big_top"] = max(10, ceil(0.1 * max(len(ranks), 1)))
    tr = _team_rows(g, ranks, len(ranks)) if len(g) else {"teams": {}, "tau": 0, "noise_se": 0}
    out["teams"], out["team_tau"], out["team_noise"] = tr["teams"], tr["tau"], tr["noise_se"]
    out["persist"] = _persistence(league)
    last = g.tail(40).iloc[::-1]
    out["recent"] = [{"start": r.start, "home": r.home_name, "away": r.away_name, "p": round(float(r.p_home), 3),
                      "pred": round(float(r.margin), 1), "actual": int(r.actual), "hit": int(r.hit), "neutral": int(r.neutral)} for r in last.itertuples()]
    return out


def run(leagues=None, backfill: bool = False) -> None:
    now = pd.Timestamp.now(tz="UTC")
    for league in leagues or LEAGUES:
        led = history(league) if backfill else load_ledger(league)
        for name in ("schedule.json", "games.json"):
            f = ROOT / "site" / league / "data" / name
            if f.exists():
                led = upsert(led, _rows_from(json.loads(f.read_text())), now)
                if name == "schedule.json":
                    break
        led = grade(led, results(league))
        (ROOT / "data" / league).mkdir(parents=True, exist_ok=True)
        led.sort_values("start").to_csv(ROOT / "data" / league / "ledger.csv", index=False)
        s = summarize(league, led)
        if s:
            (ROOT / "site" / league / "data" / "record.json").write_text(json.dumps(s, separators=(",", ":"), allow_nan=False))
        print(f"ledger {league}: {len(led)} predictions saved, {0 if not s else s['n']} graded" + ("" if not s else f", {s['hit']}/{s['n']} right"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--league", nargs="*")
    a = ap.parse_args()
    run(a.league, a.backfill)


if __name__ == "__main__":
    main()
