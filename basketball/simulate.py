"""Simulated season in the same format the fetcher writes, with known true ratings.

Used for testing: if the models can't recover the truth here, they can't be trusted on
real games. Also lets the site be built and previewed before real data arrives.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

MU = 104.0     # league points per 100 possessions
HCA = 4.0      # full home-court swing per 100


def season(n_teams=362, games_per_team=30, roster=12, seed=7):
    rng = np.random.default_rng(seed)
    teams, players = [], []
    for t in range(n_teams):
        tid = str(1000 + t)
        strength = rng.normal(0, 1)                      # program quality drives player quality
        conf = f"C{t // 12 + 1:02d}"
        teams.append({"team_id": tid, "name": f"Team {t + 1}", "short": f"Team {t + 1}", "abbr": f"T{t + 1}",
                      "conf": conf, "color": "%06x" % rng.integers(0, 0xFFFFFF), "tempo": rng.normal(68, 3)})
        for j in range(roster):
            o = rng.normal(0.9 * strength, 1.6)
            d = rng.normal(0.6 * strength, 1.3)          # positive = better defender
            share = max(0.02, [0.85, 0.82, 0.78, 0.72, 0.66, 0.5, 0.4, 0.3, 0.2, 0.12, 0.08, 0.05][j] + rng.normal(0, .04))
            # Box-score "style" only partly reflects true impact, as in real basketball
            players.append({"player_id": f"{tid}{j:02d}", "team_id": tid, "name": f"Player {t + 1}-{j + 1}",
                            "pos": ["G", "G", "F", "F", "C"][j % 5], "true_off": o, "true_def": d, "share": share,
                            "style_off": o + rng.normal(0, 1.6), "style_def": d + rng.normal(0, 1.6)})
    teams = pd.DataFrame(teams)
    players = pd.DataFrame(players)
    by_team = {t: g.reset_index(drop=True) for t, g in players.groupby("team_id")}
    arr = {t: (g.player_id.to_numpy(), g.true_off.to_numpy(), g.true_def.to_numpy(),
               (g.share / g.share.sum()).to_numpy(), list(g.itertuples())) for t, g in by_team.items()}

    # Schedule: conference-heavy, like real college ball
    pairs = []
    ids = teams.team_id.tolist()
    conf_of = dict(zip(teams.team_id, teams.conf))
    start = date(2026, 11, 3)
    for _ in range(n_teams * games_per_team // 2):
        a = rng.choice(ids)
        same = [x for x in ids if conf_of[x] == conf_of[a] and x != a]
        b = rng.choice(same) if rng.random() < 0.55 else rng.choice([x for x in ids if x != a])
        pairs.append((a, b, start + timedelta(days=int(rng.integers(0, 120))), rng.random() < 0.08))

    games, box, stints = [], [], []
    tempo = dict(zip(teams.team_id, teams.tempo))
    for gi, (h, a, day, neutral) in enumerate(sorted(pairs, key=lambda x: x[2])):
        gid = str(500000 + gi)
        total_poss = tempo[h] + tempo[a] - 68 + rng.normal(0, 3)
        hflag = 0 if neutral else 1
        on_min = {}
        pts = {h: 0, a: 0}
        stat = {}
        n_stints = int(rng.integers(25, 40))
        game_poss = 0.0
        for k in range(n_stints):
            poss = float(total_poss / n_stints * rng.uniform(.4, 1.6))
            lu = {tid: rng.choice(len(arr[tid][0]), 5, replace=False, p=arr[tid][3]) for tid in (h, a)}
            res = {}
            for off, de, sign in ((h, a, 1), (a, h, -1)):
                ppp = MU + arr[off][1][lu[off]].sum() - arr[de][2][lu[de]].sum() + sign * hflag * HCA / 2
                res[off] = max(0, int(round(poss * ppp / 100 + rng.normal(0, 1.15 * np.sqrt(poss)))))
                pts[off] += res[off]
            stints.append({"game_id": gid, "home_id": h, "away_id": a, "neutral": neutral,
                           "home_players": " ".join(sorted(arr[h][0][lu[h]])), "away_players": " ".join(sorted(arr[a][0][lu[a]])),
                           "home_pts": res[h], "away_pts": res[a], "poss": round(poss, 2)})
            game_poss += poss
            for tid in (h, a):
                for i in lu[tid]:
                    pid = arr[tid][0][i]
                    on_min[pid] = on_min.get(pid, 0) + poss * 40 / total_poss
                    stat.setdefault(pid, (arr[tid][4][i], tid))
        games.append({"game_id": gid, "date": day.isoformat(), "neutral": neutral, "conference_game": conf_of[h] == conf_of[a],
                      "completed": True, "poss": round(game_poss, 1), "home_id": h, "away_id": a, "home_pts": pts[h], "away_pts": pts[a]})
        # Box scores loosely tied to true talent, so the box-score prior has signal to learn
        for pid, (p, tid) in stat.items():
            m = on_min[pid]
            f = m / 40
            fga = rng.poisson(max(.1, f * (13 + 1.2 * p.style_off)))
            fgm = rng.binomial(fga, min(.7, max(.2, .45 + .015 * p.style_off)))
            tpa = rng.binomial(fga, .38); tpm = rng.binomial(min(tpa, fgm), .5)
            fta = rng.poisson(max(.1, f * (5 + .5 * p.style_off))); ftm = rng.binomial(fta, .71)
            box.append({"game_id": gid, "team_id": tid, "player_id": pid, "name": p.name, "pos": p.pos, "starter": p.share > .6,
                        "min": int(round(m)), "pts": 2 * fgm + tpm + ftm, "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa,
                        "ftm": ftm, "fta": fta, "oreb": rng.poisson(f * 2), "dreb": rng.poisson(max(.1, f * (5 + .4 * p.style_def))),
                        "ast": rng.poisson(max(.1, f * (3 + .4 * p.style_off))), "tov": rng.poisson(max(.1, f * (2.5 - .2 * p.style_off))),
                        "stl": rng.poisson(max(.05, f * (1.3 + .25 * p.style_def))), "blk": rng.poisson(max(.05, f * (.8 + .2 * p.style_def))),
                        "pf": rng.poisson(f * 3)})
    return (teams.drop(columns="tempo"), pd.DataFrame(games), pd.DataFrame(box), pd.DataFrame(stints), players, teams)
