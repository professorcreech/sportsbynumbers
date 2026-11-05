"""Do the models recover known truth from a simulated season?  Run: python -m tests.test_basketball"""
import time

import numpy as np
import pandas as pd

from basketball import players, teams
from basketball.simulate import season, HCA


def main():
    t0 = time.time()
    tm, games, box, stints, truth_p, truth_t = season()
    print(f"simulated {len(games)} games, {len(stints)} stints, {len(box)} box rows in {time.time() - t0:.0f}s")

    games = games.sort_values("date")
    train = games[games.date < "2027-02-15"]
    test = games[games.date >= "2027-02-15"]

    # ---- team ratings: compare to true lineup-weighted team strength
    m = teams.fit(train, box[box.game_id.isin(train.game_id)], tm)
    p = truth_p.copy()
    p["net"] = (p.true_off + p.true_def) * p.share
    true_net = p.groupby("team_id").net.sum() * 5 / p.groupby("team_id").share.sum()
    est = m["table"].set_index("team_id").net
    print(f"team net rating   corr with truth: {np.corrcoef(est.reindex(true_net.index), true_net)[0, 1]:.3f}")
    print(f"home court        est {m['hca']:.2f}  true {HCA:.2f}  (per 100 poss)")

    # ---- out-of-sample predictions
    pr = [teams.predict(m, g.home_id, g.away_id, g.neutral) for g in test.itertuples()]
    pm = np.array([x["margin"] for x in pr]); pw = np.array([x["home_win"] for x in pr])
    actual = (test.home_pts - test.away_pts).to_numpy()
    won = (actual > 0).astype(float)
    print(f"held-out games    n={len(test)}  margin MAE {np.mean(np.abs(actual - pm)):.2f}  "
          f"straight-up acc {np.mean((pm > 0) == (actual > 0)):.3f}  Brier {np.mean((pw - won) ** 2):.3f}")
    bins = pd.cut(pw, [0, .2, .4, .6, .8, 1])
    print("calibration:", pd.Series(won).groupby(bins, observed=True).agg(["mean", "count"]).round(3).to_dict("index"))

    # ---- players
    t1 = time.time()
    lam = players.tune_lambda(stints.astype({"home_players": str, "away_players": str}), box)
    print(f"chosen lambda: {lam}")
    pl = players.fit(stints, box, lam).set_index("player_id")
    tp = truth_p.set_index("player_id")
    j = pl.join(tp[["true_off", "true_def", "share"]], how="inner")
    big = j[j.poss > 800]
    for col, tcol in (("off", "true_off"), ("def", "true_def")):
        print(f"player {col:>3}  corr with truth: all {np.corrcoef(j[col], j[tcol])[0,1]:.3f}  "
              f"regulars {np.corrcoef(big[col], big[tcol])[0,1]:.3f}")
    j["true_total"] = j.true_off + j.true_def
    print(f"player total corr: regulars {np.corrcoef(big.total, big.true_off + big.true_def)[0,1]:.3f}  "
          f"RMSE {np.sqrt(np.mean((big.total - big.true_off - big.true_def) ** 2)):.2f} "
          f"(box prior alone RMSE {np.sqrt(np.mean((big.prior_off + big.prior_def - big.true_off - big.true_def) ** 2)):.2f})  "
          f"fit in {time.time() - t1:.0f}s")
    lu = players.lineups(stints)
    print(f"lineups with 20+ possessions: {len(lu)}")


if __name__ == "__main__":
    main()
