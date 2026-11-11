"""College Football Playoff odds (2026 rules: 12 teams).

Each simulation:
  1. Draws every team's true strength around its rating, then plays the remaining FBS
     schedule (regular season and any scheduled conference title games).
  2. If a conference's title game isn't scheduled yet, its two best conference records meet
     (rating breaks ties) on a neutral field.
  3. Ranks teams by strength of record, plus a small credit for rating. Strength of record
     asks how a top-25-caliber team would expect to do against each team's schedule; beating
     that expectation is what committees reward. It's an approximation of the committee,
     not a copy of it.
  4. Builds the field: champions of the ACC, Big Ten, Big 12 and SEC; the highest-ranked
     champion-or-not from the American, Conference USA, MAC, Mountain West, Pac-12 and Sun
     Belt; Notre Dame if it ranks in the top 12; the rest at-large. The top four get byes.
  5. Plays it out: first round at the higher seed, later rounds at neutral sites.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

POWER4 = {"acc", "big10", "big12", "sec"}
GROUP6 = {"american", "usa", "midam", "mwest", "pac12", "belt"}
NOTRE_DAME = "87"
RATING_WEIGHT = 0.04   # résumé credit per point of rating, on the strength-of-record scale
STRENGTH_SD = 3.0      # uncertainty in true strength late in the season (points)


def simulate(model: dict, teams_df: pd.DataFrame, played: pd.DataFrame, remaining: pd.DataFrame,
             n_sims: int = 10000, seed: int = 11) -> pd.DataFrame | None:
    fbs = teams_df[teams_df["div"] == "FBS"].copy()
    if fbs.empty:
        return None
    conf = dict(zip(fbs.team_id, fbs.conf.str.lower()))
    ids = list(fbs.team_id)
    pos = {t: i for i, t in enumerate(ids)}
    n = len(ids)
    idx = model["idx"]
    net = np.array([model["O"][idx[t]] - model["D"][idx[t]] if t in idx else 0.0 for t in ids])
    O = {t: model["O"][idx[t]] for t in idx}
    Dd = {t: model["D"][idx[t]] for t in idx}
    hfa, sd = model["hfa"], model["sd"]
    elite = np.sort(net)[-25]  # a 25th-best team: the yardstick for strength of record

    def exp_margin(h, a, neutral):
        """Expected home margin from ratings (offense/defense, non-FBS pooled)."""
        nd = idx.get("NON_D1")
        oh, dh = O.get(h, O.get(nd, -10)), Dd.get(h, Dd.get(nd, 10))
        oa, da = O.get(a, O.get(nd, -10)), Dd.get(a, Dd.get(nd, 10))
        return (oh + da) - (oa + dh) + (0 if neutral else hfa)

    rng = np.random.default_rng(seed)
    shift = rng.normal(0, STRENGTH_SD, (n_sims, n))

    # ---- results so far: wins, conference record, and strength-of-record credit
    base_w = np.zeros(n); base_l = np.zeros(n); base_sor = np.zeros(n)
    conf_w = np.zeros(n); conf_l = np.zeros(n)
    for g in played.itertuples():
        hw = g.home_pts > g.away_pts
        for team, won in ((g.home_id, hw), (g.away_id, not hw)):
            if team in pos:
                i = pos[team]
                base_w[i] += won; base_l[i] += (not won)
                if bool(getattr(g, "conference_game", False)):
                    conf_w[i] += won; conf_l[i] += (not won)
    for g in played.itertuples():
        hw = g.home_pts > g.away_pts
        for team, opp, home, won in ((g.home_id, g.away_id, True, hw), (g.away_id, g.home_id, False, not hw)):
            if team not in pos:
                continue
            opp_net = net[pos[opp]] if opp in pos else (O.get(opp, O.get("NON_D1", -20)) - Dd.get(opp, Dd.get("NON_D1", 20)))
            site = 0 if g.neutral else (hfa if home else -hfa)
            base_sor[pos[team]] += won - norm.cdf((elite - opp_net + site) / sd)

    W = np.tile(base_w, (n_sims, 1)); L = np.tile(base_l, (n_sims, 1)); SOR = np.tile(base_sor, (n_sims, 1))
    CW = np.tile(conf_w, (n_sims, 1)); CL = np.tile(conf_l, (n_sims, 1))
    sims = np.arange(n_sims)

    def strength(t):
        return (net[pos[t]] + shift[:, pos[t]]) if t in pos else np.full(n_sims, O.get(t, O.get("NON_D1", -20)) - Dd.get(t, Dd.get("NON_D1", 20)))

    def play(h, a, neutral, record=True, conf_game=False):
        """Returns boolean array: home team won."""
        m = strength(h) - strength(a) + (0 if neutral else hfa)
        hw = rng.random(n_sims) < norm.cdf(m / sd)
        if record:
            for team, opp, home, won in ((h, a, True, hw), (a, h, False, ~hw)):
                if team in pos:
                    i = pos[team]
                    W[:, i] += won; L[:, i] += ~won
                    if conf_game:
                        CW[:, i] += won; CL[:, i] += ~won
                    opp_net = net[pos[opp]] if opp in pos else (O.get(opp, O.get("NON_D1", -20)) - Dd.get(opp, Dd.get("NON_D1", 20)))
                    site = 0 if neutral else (hfa if home else -hfa)
                    SOR[:, i] += won - norm.cdf((elite - opp_net + site) / sd)
        return hw

    rem = remaining.copy()
    title_note = rem.note.fillna("").str.contains("Championship", case=False) & ~rem.note.fillna("").str.contains("Playoff|Bowl", case=False)
    for g in rem[~title_note].itertuples():
        if g.home_id in pos or g.away_id in pos:
            play(g.home_id, g.away_id, bool(g.neutral), conf_game=bool(getattr(g, "conference_game", False)))

    # ---- conference champions
    champ = {}
    scheduled_title = {conf.get(g.home_id): g for g in rem[title_note].itertuples() if conf.get(g.home_id) == conf.get(g.away_id)}
    for c in sorted(set(conf.values())):
        members = [t for t in ids if conf[t] == c]
        if c in ("ind", "") or len(members) < 4:
            continue
        if c in scheduled_title:
            g = scheduled_title[c]
            hw = play(g.home_id, g.away_id, True)
            champ[c] = np.where(hw, pos[g.home_id], pos[g.away_id])
            continue
        mi = np.array([pos[t] for t in members])
        pct = CW[:, mi] / np.maximum(CW[:, mi] + CL[:, mi], 1) + 1e-3 * (net[mi] + shift[:, mi]) / 50
        order = np.argsort(-pct, axis=1)
        a, b = mi[order[:, 0]], mi[order[:, 1]]
        m = (net[a] + shift[sims, a]) - (net[b] + shift[sims, b])
        aw = rng.random(n_sims) < norm.cdf(m / sd)
        W[sims, a] += aw; L[sims, a] += ~aw; W[sims, b] += ~aw; L[sims, b] += aw
        champ[c] = np.where(aw, a, b)

    # ---- rank, select, seed, play
    score = SOR + RATING_WEIGHT * (net + shift)
    out = {k: np.zeros(n) for k in ("playoff", "bye", "conf_champ", "quarter", "semi", "final", "title")}
    for c, w in champ.items():
        np.add.at(out["conf_champ"], w, 1)
    p4 = [champ[c] for c in POWER4 if c in champ]
    g6_idx = np.array([pos[t] for t in ids if conf[t] in GROUP6])
    nd = pos.get(NOTRE_DAME)
    for s in range(n_sims):
        rank = np.argsort(-score[s])
        rank_pos = np.empty(n, int); rank_pos[rank] = np.arange(n)
        field = {int(c[s]) for c in p4}
        if len(g6_idx):
            field.add(int(g6_idx[np.argmin(rank_pos[g6_idx])]))
        if nd is not None and rank_pos[nd] < 12:
            field.add(nd)
        for t in rank:
            if len(field) >= 12:
                break
            field.add(int(t))
        seeds = sorted(field, key=lambda t: rank_pos[t])
        for t in seeds:
            out["playoff"][t] += 1
        for t in seeds[:4]:
            out["bye"][t] += 1
        st = net + shift[s]

        def game(a, b, home_a=False):
            m = st[a] - st[b] + (hfa if home_a else 0)
            return a if rng.random() < norm.cdf(m / sd) else b
        # first round: 5v12, 6v11, 7v10, 8v9 at the higher seed
        r1 = [game(seeds[4 + k], seeds[11 - k], True) for k in range(4)]
        # quarterfinals: 1 v 8/9, 2 v 7/10, 3 v 6/11, 4 v 5/12
        qf_opp = [r1[3], r1[2], r1[1], r1[0]]
        for t in seeds[:4] + r1:
            out["quarter"][t] += 1
        semis = [game(seeds[k], qf_opp[k]) for k in range(4)]
        for t in semis:
            out["semi"][t] += 1
        f1, f2 = game(semis[0], semis[3]), game(semis[1], semis[2])
        out["final"][f1] += 1; out["final"][f2] += 1
        out["title"][game(f1, f2)] += 1
    res = pd.DataFrame({k: v / n_sims for k, v in out.items()})
    res["team_id"] = ids
    res["wins"] = W.mean(axis=0); res["losses"] = L.mean(axis=0)
    res["sor"] = SOR.mean(axis=0)
    return res.sort_values("playoff", ascending=False).reset_index(drop=True)
