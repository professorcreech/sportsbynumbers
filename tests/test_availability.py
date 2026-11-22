import pandas as pd

from football import availability, config


def _data():
    rows = []
    for g in ("g1", "g2", "g3", "g4"):
        for i in range(20):                                   # a full box score, 20 players per team
            rows.append({"game_id": g, "team_id": "1", "player_id": f"p{i}", "name": f"P{i}", "pass_yds": 0, "rush_yds": 5, "rec_yds": 0})
    star = [r for r in rows if r["player_id"] == "p0"]
    for r in star:
        r["rush_yds"] = 100                                   # p0 averages 100 yards a game
    pl = pd.DataFrame(rows)
    pl = pl[~((pl.game_id == "g4") & (pl.player_id == "p0"))]  # and sat out the last game
    games = pd.DataFrame({"game_id": ["g1", "g2", "g3", "g4"], "date": ["2026-10-01", "2026-10-08", "2026-10-15", "2026-10-22"],
                          "home_id": ["1"] * 4, "away_id": ["2"] * 4})
    return pl, games, [{"game_id": "x", "home_id": "1", "away_id": "2"}]


def test_college_uses_previous_game_absence_scaled_by_production(monkeypatch):
    monkeypatch.setattr(config, "IS_NFL", False)
    pl, games, sched = _data()
    a = availability.adjustments(pl, games, sched)
    sh = a["x"]["1"]["shift"]
    assert sh == -0.5                 # 100 usual yards x 0.5 per 100
    assert a["x"]["1"]["who"][0]["name"] == "P0"


def test_nfl_uses_injury_report_and_ignores_questionable(monkeypatch):
    monkeypatch.setattr(config, "IS_NFL", True)
    pl, games, sched = _data()
    inj = {"x": {"1": [{"id": "p0", "status": "Out"}]}}
    assert availability.adjustments(pl, games, sched, inj)["x"]["1"]["shift"] == -0.6      # 100 usual yards x 0.6 per 100
    assert availability.adjustments(pl, games, sched, {"x": {"1": [{"id": "p0", "status": "Questionable"}]}}) == {}
