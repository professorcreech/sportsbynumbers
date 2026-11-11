"""Bowl game prediction: rating model vs. data-mining classifiers.   python -m tests.bowl_study

Following Delen, Cogdell & Kasap (2012, International Journal of Forecasting 28(2)): build
team features as of the end of the regular season (records, non-conference record, average
margin, scoring, strength of schedule, recent form, conference strength, layoff) plus this
site's ratings, and predict bowl winners.

Validation is season by season: each bowl season is predicted by models trained only on
earlier bowl seasons, the way the model would be used in December. (The paper used 10-fold
cross-validation, which mixes seasons.)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from football import config, run, teams

FEATURES = ["net", "off", "dfn", "win_pct", "nonconf_win_pct", "conf_win_pct", "avg_margin", "pts_for", "pts_against",
            "sos", "last3_margin", "conf_strength", "games", "days_off", "fbs"]


def season_features(season: int):
    tm, g, _ = run.load(season)
    g = g.sort_values("date")
    post = g[pd.to_numeric(g.season_type, errors="coerce") == 3]
    if post.empty:
        return None, None
    start = post.date.min()
    reg = g[g.date < start]
    fbs = set(tm[tm["div"] == "FBS"].team_id)
    prior = {}
    if (config.DATA_DIR / str(season - 1) / "games").exists():
        tm_p, g_p, _ = run.load(season - 1)
        prior = teams.last_season_prior(g_p, tm_p)
    m = teams.fit(reg, tm, prior, as_of=pd.Timestamp(start).date())
    tab = m["table"].set_index("team_id")
    conf_of = dict(zip(tm.team_id, tm.conf))
    long = pd.concat([
        pd.DataFrame({"team": reg.home_id, "opp": reg.away_id, "pf": reg.home_pts, "pa": reg.away_pts, "date": reg.date, "conf_game": reg.conference_game}),
        pd.DataFrame({"team": reg.away_id, "opp": reg.home_id, "pf": reg.away_pts, "pa": reg.home_pts, "date": reg.date, "conf_game": reg.conference_game}),
    ])
    long["win"] = (long.pf > long.pa).astype(float)
    long["margin"] = long.pf - long.pa
    long["opp_net"] = long.opp.map(tab.net).fillna(tab.net.min())
    conf_strength = tab[tab.index.isin(fbs)].groupby(tab[tab.index.isin(fbs)].index.map(conf_of)).net.mean()
    feats = {}
    for t, d in long.groupby("team"):
        if t not in tab.index:
            continue
        d = d.sort_values("date")
        nc, cg = d[~d.conf_game.astype(bool)], d[d.conf_game.astype(bool)]
        feats[t] = {"net": tab.at[t, "net"], "off": tab.at[t, "off"] - m["mu"], "dfn": m["mu"] - tab.at[t, "dfn"],
                    "win_pct": d.win.mean(), "nonconf_win_pct": nc.win.mean() if len(nc) else d.win.mean(),
                    "conf_win_pct": cg.win.mean() if len(cg) else d.win.mean(), "avg_margin": d.margin.mean(),
                    "pts_for": d.pf.mean(), "pts_against": d.pa.mean(), "sos": d.opp_net.mean(),
                    "last3_margin": d.margin.tail(3).mean(), "conf_strength": conf_strength.get(conf_of.get(t), np.nan),
                    "games": len(d), "last_game": d.date.max(), "fbs": float(t in fbs)}
    rows = []
    for x in post.itertuples():
        a, b = x.home_id, x.away_id
        if a not in feats or b not in feats or x.home_pts == x.away_pts or a not in fbs or b not in fbs:
            continue  # bowls and the Playoff only (ESPN's postseason also lists FCS playoff games)
        fa, fb = dict(feats[a]), dict(feats[b])
        for f, other in ((fa, fb), (fb, fa)):
            f["days_off"] = (pd.Timestamp(x.date) - pd.Timestamp(f["last_game"])).days
        pr = teams.predict(m, a, b, bool(x.neutral))
        rows.append({"season": season, "game_id": x.game_id, "note": x.note, "a": a, "b": b,
                     "a_won": float(x.home_pts > x.away_pts), "rating_p": pr["home_win"],
                     **{f"d_{k}": (fa[k] - fb[k]) if pd.notna(fa[k]) and pd.notna(fb[k]) else 0.0 for k in FEATURES}})
    return pd.DataFrame(rows), m


def evaluate(df: pd.DataFrame) -> pd.DataFrame:
    cols = [f"d_{k}" for k in FEATURES]
    models = {
        "Logistic, rating gap only": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=1.0)),
        "Logistic, all features": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000)),
        "Decision tree (as in the paper)": lambda: DecisionTreeClassifier(max_depth=4, min_samples_leaf=20, random_state=0),
        "Random forest": lambda: RandomForestClassifier(n_estimators=400, min_samples_leaf=10, random_state=0),
        "Gradient boosting": lambda: GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=0),
    }
    out = []
    seasons = sorted(df.season.unique())
    for s in seasons[2:]:  # need at least two earlier bowl seasons to train on
        tr, te = df[df.season < s], df[df.season == s]
        # every game appears from both sides in training, so "home" in bowls means nothing
        X = np.r_[tr[cols].to_numpy(), -tr[cols].to_numpy()]
        y = np.r_[tr.a_won.to_numpy(), 1 - tr.a_won.to_numpy()]
        rec = {"season": s, "games": len(te)}
        p = te.rating_p.clip(0.01, 0.99).to_numpy()
        rec["Rating model (this site)"] = p
        for name, make in models.items():
            mdl = make()
            use = ["d_net"] if "rating gap" in name else cols
            idx = [cols.index(c) for c in use]
            mdl.fit(X[:, idx], y)
            rec[name] = mdl.predict_proba(te[use].to_numpy())[:, 1].clip(0.01, 0.99)
        rec["y"] = te.a_won.to_numpy()
        out.append(rec)
    names = ["Rating model (this site)"] + list(models)
    rows = []
    for name in names:
        p = np.concatenate([r[name] for r in out]); y = np.concatenate([r["y"] for r in out])
        per = [((r[name] > 0.5) == (r["y"] == 1)).mean() for r in out]
        rows.append({"model": name, "games": len(y), "accuracy": ((p > 0.5) == (y == 1)).mean(),
                     "log_loss": -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)), "brier": np.mean((p - y) ** 2),
                     "worst_season": min(per), "best_season": max(per)})
    return pd.DataFrame(rows).sort_values("log_loss")


def main(first=2016, last=2025):
    frames = []
    for s in range(first, last + 1):
        if not (config.DATA_DIR / str(s) / "games").exists():
            continue
        df, _ = season_features(s)
        if df is not None and len(df):
            frames.append(df)
            print(f"{s}: {len(df)} postseason games")
    df = pd.concat(frames, ignore_index=True)
    res = evaluate(df)
    pd.set_option("display.width", 200)
    print(f"\nPredicting {df.season.nunique() - 2} bowl seasons, each from earlier seasons only:")
    print(res.round(3).to_string(index=False))
    # What the paper's two key variables say on their own
    for k in ("d_nonconf_win_pct", "d_avg_margin", "d_net"):
        acc = ((df[k] > 0) == (df.a_won == 1))[df[k] != 0].mean()
        print(f"picking the team with the higher {k[2:]}: {acc:.3f} of games")
    df.to_csv(config.DATA_DIR / "bowl_games.csv", index=False)
    return df, res


if __name__ == "__main__":
    main(*(int(x) for x in sys.argv[1:3]))
