"""Replay the 2026 NCAA tournament as the site would have run it.   python -m tests.tournament_backtest

1. Pre-tournament: ratings as of the morning of the First Four (preseason prior + regular
   season + conference tournaments), actual bracket and sites, distance effect. Simulate the
   whole bracket and score every game and every team's odds of reaching each round.
2. Day by day: each tournament morning, refit ratings including tournament games already
   played, predict that day's games, and re-simulate what's left.

Baselines: picking the better seed, and the same model without the distance effect.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

from basketball import bracket as B, config, preseason as P, run, teams

SEASON = 2026
HIST = config.DATA_DIR / "history"
ROUND_COL = {"First Four": 1, "1st Round": 2, "2nd Round": 3, "Sweet 16": 4, "Elite 8": 5, "Final Four": 6, "National Championship": 7}
POD_OF_SEED = {s: top for top, rng in B.PODS.items() for s in (B.SEED_ORDER[i] for i in rng)}


def load_tournament():
    s = pd.read_csv(HIST / f"scores_{SEASON}.csv.gz", dtype={"home_id": str, "away_id": str, "game_id": str})
    t = s[pd.to_numeric(s.tourney_id, errors="coerce") == 22].copy()
    t["round"] = t.note.str.extract(r"(First Four|1st Round|2nd Round|Sweet 16|Elite 8|Final Four|National Championship)")[0]
    t["region"] = t.note.str.extract(r"(\w+) Region")[0]
    t["winner"] = np.where(t.home_pts > t.away_pts, t.home_id, t.away_id)
    t["loser"] = np.where(t.home_pts > t.away_pts, t.away_id, t.home_id)
    places = pd.read_csv(HIST / "places.csv")
    t = t.merge(places, on=["city", "state"], how="left")
    t["site"] = t.city + ", " + t.state
    return t.sort_values(["date", "game_id"]).reset_index(drop=True)


def build_actual_bracket(t: pd.DataFrame):
    seed = {}
    for g in t.itertuples():
        seed[g.home_id], seed[g.away_id] = int(g.home_seed), int(g.away_seed)
    ff = t[t["round"] == "First Four"]
    ff_pair = {g.winner: [g.winner, g.loser] for g in ff.itertuples()}
    r64 = t[t["round"] == "1st Round"]
    regions = sorted(r64.region.unique())
    reg_slots, pod_site, coords = [], [], {}
    for r in regions:
        games = r64[r64.region == r]
        by_seed = {}
        for g in games.itertuples():
            for tid in (g.home_id, g.away_id):
                by_seed[seed[tid]] = ff_pair.get(tid, [tid])
        reg_slots.append([by_seed[s] for s in B.SEED_ORDER])
        pods = {}
        for g in games.itertuples():
            pods[POD_OF_SEED[min(seed[g.home_id], seed[g.away_id])]] = g.site
            coords[g.site] = (g.lat, g.lon)
        pod_site.append(pods)
    reg_names = []
    for r in regions:
        g = t[(t.region == r) & (t["round"] == "Sweet 16")].iloc[0]
        reg_names.append(g.site)
        coords[g.site] = (g.lat, g.lon)
    opening = {}
    for g in ff.itertuples():
        opening[tuple(ff_pair[g.winner])] = g.site
        coords[g.site] = (g.lat, g.lon)
    # Semifinal pairs: which regions met
    reg_of = {tid: i for i, slots in enumerate(reg_slots) for sl in slots for tid in sl}
    semis = [tuple(sorted((reg_of[g.home_id], reg_of[g.away_id]))) for g in t[t["round"] == "Final Four"].itertuples()]
    final = t[t["round"] == "Final Four"].iloc[0]
    coords[final.site] = (final.lat, final.lon)
    sites = {"opening": {s: coords[s] for s in set(opening.values())}, "first": {s: coords[s] for p in pod_site for s in p.values()},
             "regional": {s: coords[s] for s in reg_names}, "final": {final.site: coords[final.site]}}
    br = {"regions": reg_slots, "region_names": reg_names, "pod_site": pod_site, "opening_site": opening, "semis": semis}
    return br, sites, seed, regions


def fit_as_of(day: str, tm, games, box, prior):
    g = games[games.date < day]
    m = teams.fit(g, box[box.game_id.isin(g.game_id)], tm, prior, as_of=date.fromisoformat(day), prior_games=config.PRESEASON_GAMES)
    meta = {"model": {"ids": list(m["idx"]), "O": list(m["O"]), "D": list(m["D"]), "T": list(m["T"])},
            "mu": m["mu"], "tau": m["tau"], "hca": m["hca"], "sd": m["sd"]}
    return m, meta


def game_prob(m, homes, a, b, lat, lon, k=config.TOURNEY_LOG_DISTANCE):
    """P(a beats b) at a neutral site with the distance edge."""
    idx = m["idx"]
    ia, ib = idx[a], idx[b]
    poss = m["tau"] + m["T"][ia] + m["T"][ib]
    eff = (m["O"][ia] + m["D"][ib]) - (m["O"][ib] + m["D"][ia])
    margin = poss * eff / 100
    if k and a in homes and b in homes and not np.isnan(lat):
        da = B.haversine(homes[a][0], homes[a][1], lat, lon)
        db = B.haversine(homes[b][0], homes[b][1], lat, lon)
        margin += k * (np.log1p(da) - np.log1p(db))
    return float(norm.cdf(margin / m["sd"]))


def score(rows: pd.DataFrame, col: str) -> dict:
    p = rows[col].clip(0.01, 0.99)
    return {"games": len(rows), "correct": float((p > 0.5).mean()), "log_loss": float(-np.log(p).mean()),
            "brier": float(((1 - p) ** 2).mean())}


def main():
    t = load_tournament()
    tm, games, box, *_ = run.load(SEASON)
    games = games[games.completed.astype(bool)]
    prior, _ = P.build_prior(SEASON, None, box)
    homes = B.team_homes()
    br, sites, seed, regions = build_actual_bracket(t)
    start = t.date.min()

    # ---------- 1. Pre-tournament ----------
    m0, meta0 = fit_as_of(start, tm, games, box, prior)
    sd0 = {"*": config.BRACKET_FINAL_SD}
    odds = B.simulate(br, meta0, sd0, n_sims=20000, sites=sites, homes=homes)
    odds_nodist = B.simulate(br, meta0, sd0, n_sims=20000)
    reached = {tid: 1 for tid in odds.index}  # everyone reaches column 0 (in the field)
    deepest = {}
    for g in t.itertuples():
        rc = ROUND_COL[g.round]
        deepest[g.winner] = max(deepest.get(g.winner, 0), rc)
        deepest[g.loser] = max(deepest.get(g.loser, 0), rc - 1)
    champion = t[t["round"] == "National Championship"].iloc[0].winner
    deepest[champion] = 7
    names = dict(zip(t.home_id, t.home_name)) | dict(zip(t.away_id, t.away_name))

    adv = []
    for tid, row in odds.iterrows():
        d = deepest.get(tid, 1)
        for c in range(2, 8):  # R32 .. Champion
            adv.append({"team": tid, "round": B.ROUNDS[c], "p": row.iloc[c], "p_nodist": odds_nodist.loc[tid].iloc[c], "hit": float(d >= c)})
    adv = pd.DataFrame(adv)

    # Per-game, frozen pre-tournament ratings
    pre_rows = []
    for g in t.itertuples():
        pw = game_prob(m0, homes, g.winner, g.loser, g.lat, g.lon)
        pw0 = game_prob(m0, homes, g.winner, g.loser, g.lat, g.lon, k=0)
        sw, sl = seed[g.winner], seed[g.loser]
        pre_rows.append({"date": g.date, "round": g.round, "winner": names[g.winner], "loser": names[g.loser],
                         "seeds": f"{sw} over {sl}", "p_pre": pw, "p_pre_nodist": pw0,
                         "p_seed": 0.5 if sw == sl else (0.75 if sw < sl else 0.25)})
    games_df = pd.DataFrame(pre_rows)

    # ---------- 2. Day by day ----------
    champ_track = []
    day_rows = []
    for day in sorted(t.date.unique()):
        m, meta = fit_as_of(day, tm, games, box, prior)
        for g in t[t.date == day].itertuples():
            day_rows.append(game_prob(m, homes, g.winner, g.loser, g.lat, g.lon))
        # what's left: rebuild the bracket with decided games locked in
        played = t[t.date < day]
        out = set(played.loser)
        locked = {"regions": [[[x for x in sl if x not in out] or sl for sl in reg] for reg in br["regions"]],
                  "region_names": br["region_names"], "pod_site": br["pod_site"], "opening_site": br["opening_site"], "semis": br["semis"]}
        # force decided later-round results by giving eliminated teams no chance
        meta_d = json.loads(json.dumps(meta))
        idx = {x: i for i, x in enumerate(meta_d["model"]["ids"])}
        for x in out:
            if x in idx:
                meta_d["model"]["O"][idx[x]] -= 500
        sim = B.simulate(locked, meta_d, {"*": config.BRACKET_FINAL_SD}, n_sims=8000, sites=sites, homes=homes)
        top = sim.Champion.sort_values(ascending=False)
        champ_track.append({"morning of": day, "Michigan": float(sim.Champion.get(champion, 0)),
                            "favorite": names.get(top.index[0], top.index[0]), "favorite_p": float(top.iloc[0])})
    games_df["p_daily"] = day_rows

    # ---------- Report ----------
    pd.set_option("display.width", 200)
    print(f"2026 tournament: {len(t)} games, champion {names[champion]}")
    print("\nGame-by-game (probability given to the actual winner):")
    res = pd.DataFrame({k: score(games_df, c) for k, c in (("Pre-tournament model", "p_pre"), ("Pre-tournament, no distance", "p_pre_nodist"),
                                                           ("Day-by-day model", "p_daily"), ("Better seed (75/25)", "p_seed"))}).T
    print(res.round(3).to_string())
    print("\nBy round (correct picks, pre-tournament / day-by-day):")
    order = list(ROUND_COL)
    br_round = games_df.groupby("round").apply(lambda d: pd.Series({"games": len(d), "pre": (d.p_pre > .5).mean(), "daily": (d.p_daily > .5).mean(),
                                                                     "seed": (d.p_seed > .5).mean() + 0.5 * (d.p_seed == .5).mean()}), include_groups=False)
    print(br_round.reindex([r for r in order if r in br_round.index]).round(3).to_string())
    print("\nAdvancement odds (pre-tournament), Brier by round, with vs. without distance:")
    a = adv.groupby("round").apply(lambda d: pd.Series({"brier": ((d.p - d.hit) ** 2).mean(), "brier_nodist": ((d.p_nodist - d.hit) ** 2).mean(),
                                                         "expected_teams": d.p.sum(), "actual": d.hit.sum()}), include_groups=False)
    print(a.reindex([r for r in B.ROUNDS[2:]]).round(4).to_string())
    print("\nPre-tournament title odds, top 8:")
    top8 = odds.Champion.sort_values(ascending=False).head(8)
    for tid, p in top8.items():
        print(f"  {names.get(tid, tid):<14} seed {seed[tid]:>2}  {p:6.1%}  reach Final 4 {odds.loc[tid, 'Final 4']:.1%}  (went to: {B.ROUNDS[deepest.get(tid, 1)]})")
    ff = [tid for tid, d in deepest.items() if d >= 5]
    print("Actual Final Four pre-tournament odds of getting there:", {names[x]: round(float(odds.loc[x, 'Final 4']), 3) for x in ff})
    print(f"Michigan's pre-tournament title odds: {odds.loc[champion, 'Champion']:.1%} (rank {int((odds.Champion > odds.loc[champion, 'Champion']).sum()) + 1})")
    # Bracket pool: fill out one bracket before the tournament and score it ESPN-style
    # (10, 20, 40, 80, 160, 320 points per correct pick from the round of 32 on)
    def fill(pick_key):
        pts, picks = 0, {}
        for r, reg in enumerate(br["regions"]):
            alive = [max(sl, key=lambda x: pick_key(x, 1)) for sl in reg]
            rnd = 2
            while len(alive) > 1:
                alive = [max(alive[i], alive[i + 1], key=lambda x: pick_key(x, rnd)) for i in range(0, len(alive), 2)]
                for x in alive:
                    picks.setdefault(rnd, []).append(x)
                rnd += 1
            picks.setdefault("reg", []).append(alive[0])
        f = [max(picks["reg"][a], picks["reg"][b], key=lambda x: pick_key(x, 6)) for a, b in br["semis"]]
        picks[6] = f
        picks[7] = [max(f, key=lambda x: pick_key(x, 7))]
        for rnd, pts_each in zip(range(2, 8), (10, 20, 40, 80, 160, 320)):
            pts += pts_each * sum(deepest.get(x, 1) >= rnd for x in picks[rnd])
        return pts, names.get(picks[7][0])
    model_pts, model_champ = fill(lambda x, c: odds.loc[x].iloc[c])
    seed_pts, seed_champ = fill(lambda x, c: (-seed[x], odds.loc[x].iloc[c]))  # chalk; model breaks ties between equal seeds
    print(f"\nBracket pool (ESPN scoring, 1,920 max): model bracket {model_pts} (champion pick {model_champ}); "
          f"chalk-by-seed bracket {seed_pts} (champion pick {seed_champ})")
    print("\nTitle odds, morning by morning:")
    print(pd.DataFrame(champ_track).round(3).to_string(index=False))
    biggest = games_df.sort_values("p_pre").head(6)
    print("\nBiggest upsets by the pre-tournament model:")
    print(biggest[["date", "round", "seeds", "winner", "loser", "p_pre", "p_daily"]].round(3).to_string(index=False))
    games_df.to_csv(HIST / "tournament_2026_backtest.csv", index=False)
    return games_df, odds, champ_track


if __name__ == "__main__":
    main()
