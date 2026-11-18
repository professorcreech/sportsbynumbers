"""Late-game situation profiles: what each team does when trailing or leading near the end of a half.

Built from the play-by-play "flow" files (data/<league>/<season>/flow/). For every team, and for each
score situation in the closing minutes of the first half ("h") and of the game ("g"), it measures:

    tempo        seconds per possession
    three        share of shot attempts that are threes
    rim          share of shot attempts at the rim
    ast          share of made baskets that were assisted (ball movement)
    fta          free throws taken per 100 possessions
    tov          turnovers per 100 possessions
and on defense, what opponents do against it:
    o_three      opponents' share of attempts from three
    o_fta        opponents' free throws per 100 possessions (fouling)
    o_tov        opponents' turnovers per 100 possessions (pressure)
    stl          steals per 100 opponent possessions

Teams have only a few dozen possessions in any one situation, so each rate is pulled toward the league
rate for the same situation, and last season's games count half. Also: which players take the shots
(usage) when the team is trailing, against their share over the whole game.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

PRIOR_SEASON_WEIGHT = 0.5
SHRINK = 25.0                      # pseudo-possessions of league-average behavior
WINDOW = {"g": 240, "h": 240} if not config.IS_NBA else {"g": 240, "h": 180}   # closing seconds studied
REG_PERIODS = 4 if config.IS_NBA else 2
HALF_PERIOD = 2 if config.IS_NBA else 1
FINAL_PERIOD = 4 if config.IS_NBA else 2

STATES = {
    "g": [("d11", "Down 11+"), ("d6", "Down 6–10"), ("d1", "Down 1–5"), ("t0", "Tied"), ("u1", "Up 1–5"), ("u6", "Up 6–10"), ("u11", "Up 11+")],
    "h": [("d6", "Down 6+"), ("c", "Within 5"), ("u6", "Up 6+")],
}
METRICS = ("n", "tempo", "three", "rim", "ast", "fta", "tov", "o_three", "o_fta", "o_tov", "stl")


def _state_g(m: np.ndarray) -> np.ndarray:
    return np.select([m <= -11, m <= -6, m <= -1, m == 0, m <= 5, m <= 10], ["d11", "d6", "d1", "t0", "u1", "u6"], "u11")


def _state_h(m: np.ndarray) -> np.ndarray:
    return np.select([m <= -6, m < 6], ["d6", "c"], "u6")


def _prepare(flow: pd.DataFrame, games: pd.DataFrame, weight: float) -> pd.DataFrame:
    """Events with each team's margin before the play, the closing window they fall in, and the weight."""
    g = games[["game_id", "home_id", "away_id"]].drop_duplicates("game_id")
    f = flow.merge(g, on="game_id", how="inner").sort_values(["game_id", "seq"]).reset_index(drop=True)
    f = f[f.period <= REG_PERIODS]
    f["m_after"] = f.hs - f["as"]
    # a game whose score never moves has no usable score column
    ok = f.groupby("game_id").m_after.transform(lambda x: (x != 0).any())
    f = f[ok].copy()
    f["m_before"] = f.groupby("game_id").m_after.shift(1).fillna(0)
    f["home"] = (f.team_id == f.home_id)
    f["opp_id"] = np.where(f.home, f.away_id, f.home_id)
    f["m_team"] = np.where(f.home, f.m_before, -f.m_before)
    f["win"] = np.where((f.period == FINAL_PERIOD) & (f.sec <= WINDOW["g"]), "g",
                        np.where((f.period == HALF_PERIOD) & (f.sec <= WINDOW["h"]), "h", ""))
    f["w"] = weight
    return f


def _exposure(flow: pd.DataFrame, games: pd.DataFrame, weight: float) -> pd.DataFrame:
    """Seconds each team spent in each situation inside the closing windows (clock time between events)."""
    g = games[["game_id", "home_id", "away_id"]].drop_duplicates("game_id")
    f = flow.merge(g, on="game_id", how="inner").sort_values(["game_id", "seq"]).reset_index(drop=True)
    f = f[f.period <= REG_PERIODS]
    f["m_after"] = f.hs - f["as"]
    f = f[f.groupby("game_id").m_after.transform(lambda x: (x != 0).any())]
    nxt_same = (f.game_id.shift(-1) == f.game_id) & (f.period.shift(-1) == f.period)
    f = f.assign(end=np.where(nxt_same, f.sec.shift(-1), 0.0))
    f = f[f.end <= f.sec]
    rows = []
    for win, per in (("g", FINAL_PERIOD), ("h", HALF_PERIOD)):
        W = WINDOW[win]
        x = f[(f.period == per) & (f.end < W)]
        dt = np.minimum(x.sec, W) - x.end
        for side, team, sign in (("h", x.home_id, 1), ("a", x.away_id, -1)):
            m = (x.m_after * sign).to_numpy()
            st = (_state_g(m) if win == "g" else _state_h(m))
            rows.append(pd.DataFrame({"team": team.to_numpy(), "win": win, "state": st, "sec": dt.to_numpy() * weight}))
    return pd.concat(rows).groupby(["team", "win", "state"], as_index=False).sec.sum()


def _counts(f: pd.DataFrame) -> pd.DataFrame:
    """Weighted event counts per team, role (own / what opponents did), window and situation."""
    f = f[f.win != ""].copy()
    f["state"] = np.where(f.win == "g", _state_g(f.m_team.to_numpy()), _state_h(f.m_team.to_numpy()))
    fg, ft = f.ev == "fg", f.ev == "ft"
    ind = pd.DataFrame({
        "fga": fg, "tpa": fg & f.three, "fgm": fg & f.made, "ast": fg & f.ast, "rim": fg & f.rim,
        "fta": ft, "tov": f.ev == "tov", "oreb": f.ev == "oreb", "stl": f.ev == "stl",
    }).astype(float).mul(f.w, axis=0)
    own = ind.assign(team=f.team_id.to_numpy(), win=f.win.to_numpy(), state=f.state.to_numpy(), role="own")
    # The same events seen by the other team: opponents' shots, free throws and turnovers against it
    other_state = np.where(f.win == "g", _state_g((-f.m_team).to_numpy()), _state_h((-f.m_team).to_numpy()))
    opp = ind.assign(team=f.opp_id.to_numpy(), win=f.win.to_numpy(), state=other_state, role="opp")
    both = pd.concat([own, opp])
    return both.groupby(["team", "role", "win", "state"], as_index=False).sum(numeric_only=True)


def _usage(flow_cur: pd.DataFrame, games: pd.DataFrame) -> dict:
    """{team_id: {"trail": [(player_id, share_trailing, share_overall, n)], "lead": ...}} for the game-end window."""
    f = _prepare(flow_cur, games, 1.0)
    use = f[f.ev.isin(["fg", "ft", "tov"]) & (f.player_id != "")].copy()
    use["u"] = np.where(use.ev == "ft", 0.44, 1.0)
    base = use.groupby(["team_id", "player_id"]).u.sum()
    base = base / base.groupby(level=0).transform("sum")
    late = use[use.win == "g"]
    out = {}
    for label, mask in (("trail", late.m_team < 0), ("lead", late.m_team > 0)):
        x = late[mask].groupby(["team_id", "player_id"]).u.sum()
        tot = x.groupby(level=0).transform("sum")
        for (t, pid), v in x.items():
            if tot[(t, pid)] < 15:
                continue
            out.setdefault(t, {}).setdefault(label, []).append((pid, v / tot[(t, pid)], float(base.get((t, pid), 0.0)), float(tot[(t, pid)])))
    return {t: {k: sorted(v, key=lambda r: -r[1])[:3] for k, v in d.items()} for t, d in out.items()}


def _metrics(c_own: pd.Series, c_opp: pd.Series, sec: float, lg: dict | None) -> dict:
    """Rates from weighted counts, pulled toward the league rates in lg (None = no pull)."""
    def ratio(num, den, key):
        k = SHRINK if lg else 0.0
        base = lg[key] if lg else 0.0
        return (num + k * base) / (den + k) if den + k > 0 else base
    poss = lambda c: max(c.fga + 0.44 * c.fta + c.tov - c.oreb, 0.0)
    po, pd_ = poss(c_own), poss(c_opp)
    return {
        "n": po,
        "tempo": ratio(sec, po, "tempo") if po > 0 or lg else float("nan"),
        "three": ratio(c_own.tpa, c_own.fga, "three"),
        "rim": ratio(c_own.rim, c_own.fga, "rim"),
        "ast": ratio(c_own.ast, c_own.fgm, "ast"),
        "fta": 100 * ratio(c_own.fta, po, "fta100"),
        "tov": 100 * ratio(c_own.tov, po, "tov100"),
        "o_three": ratio(c_opp.tpa, c_opp.fga, "o_three"),
        "o_fta": 100 * ratio(c_opp.fta, pd_, "o_fta100"),
        "o_tov": 100 * ratio(c_opp.tov, pd_, "o_tov100"),
        "stl": 100 * ratio(c_own.stl, pd_, "stl100"),
    }


def _league(counts: pd.DataFrame, expo: pd.DataFrame) -> dict:
    """League-wide rates (as fractions, not per 100) in each window and situation."""
    out = {}
    for (win, state), grp in counts.groupby(["win", "state"]):
        own = grp[grp.role == "own"].sum(numeric_only=True)
        opp = grp[grp.role == "opp"].sum(numeric_only=True)
        sec = expo[(expo.win == win) & (expo.state == state)].sec.sum()
        po = max(own.fga + 0.44 * own.fta + own.tov - own.oreb, 1e-9)
        pp = max(opp.fga + 0.44 * opp.fta + opp.tov - opp.oreb, 1e-9)
        out.setdefault(win, {})[state] = {
            "tempo": sec / po, "three": own.tpa / max(own.fga, 1e-9), "rim": own.rim / max(own.fga, 1e-9),
            "ast": own.ast / max(own.fgm, 1e-9), "fta100": own.fta / po, "tov100": own.tov / po,
            "o_three": opp.tpa / max(opp.fga, 1e-9), "o_fta100": opp.fta / pp, "o_tov100": opp.tov / pp, "stl100": own.stl / pp,
            "n": float(po),
        }
    return out


def build(flow: pd.DataFrame | None, games: pd.DataFrame, flow_prev: pd.DataFrame | None = None,
          games_prev: pd.DataFrame | None = None, names: dict | None = None, teams_in: set | None = None) -> dict | None:
    if flow is None or not len(flow):
        return None
    if teams_in:   # only games between rated teams, so the league baseline is the league being scouted
        games = games[games.home_id.isin(teams_in) & games.away_id.isin(teams_in)]
        if games_prev is not None:
            games_prev = games_prev[games_prev.home_id.isin(teams_in) & games_prev.away_id.isin(teams_in)]
    parts, expos = [_prepare(flow, games, 1.0)], [_exposure(flow, games, 1.0)]
    if flow_prev is not None and len(flow_prev) and games_prev is not None:
        parts.append(_prepare(flow_prev, games_prev, PRIOR_SEASON_WEIGHT))
        expos.append(_exposure(flow_prev, games_prev, PRIOR_SEASON_WEIGHT))
    counts = pd.concat([_counts(p) for p in parts]).groupby(["team", "role", "win", "state"], as_index=False).sum(numeric_only=True)
    expo = pd.concat(expos).groupby(["team", "win", "state"], as_index=False).sec.sum()
    lg = _league(counts, expo)
    zero = pd.Series({k: 0.0 for k in ("fga", "tpa", "fgm", "ast", "rim", "fta", "tov", "oreb", "stl")})
    teams = {}
    idx = counts.set_index(["team", "role", "win", "state"])
    ex = expo.set_index(["team", "win", "state"]).sec
    for t in sorted(set(counts.team)):
        d = {}
        for win in ("g", "h"):
            for state, _ in STATES[win]:
                get = lambda role: idx.loc[(t, role, win, state)] if (t, role, win, state) in idx.index else zero
                m = _metrics(get("own"), get("opp"), float(ex.get((t, win, state), 0.0)), lg.get(win, {}).get(state))
                d.setdefault(win, {})[state] = {k: (None if not np.isfinite(v) else round(float(v), 3 if k in ("three", "rim", "ast", "o_three") else 1)) for k, v in m.items()}
        teams[t] = d
    for t, u in _usage(flow, games).items():
        if t in teams:
            teams[t]["use"] = {k: [{"id": pid, "name": (names or {}).get(pid), "share": round(s, 3), "base": round(b, 3), "n": round(n)} for pid, s, b, n in v] for k, v in u.items()}
    league = {}
    for win, states in lg.items():
        for state, v in states.items():
            league.setdefault(win, {})[state] = {
                "n": round(v["n"]), "tempo": round(v["tempo"], 1), "three": round(v["three"], 3), "rim": round(v["rim"], 3),
                "ast": round(v["ast"], 3), "fta": round(100 * v["fta100"], 1), "tov": round(100 * v["tov100"], 1),
                "o_three": round(v["o_three"], 3), "o_fta": round(100 * v["o_fta100"], 1), "o_tov": round(100 * v["o_tov100"], 1),
                "stl": round(100 * v["stl100"], 1)}
    return {"window": WINDOW, "states": STATES, "league": league, "teams": teams}
