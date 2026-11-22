import pandas as pd

from football import config, qb


def test_nfl_starter_listed_out_shifts_margin(monkeypatch):
    monkeypatch.setattr(config, "IS_NFL", True)
    pl = pd.DataFrame({"game_id": ["g0"] * 2, "team_id": ["1", "1"], "player_id": ["a", "b"], "name": ["Starter", "Backup"], "pass_att": [40, 3]})
    games = pd.DataFrame({"game_id": ["g0"], "date": ["2026-11-01"], "home_id": ["1"], "away_id": ["2"]})
    sched = [{"game_id": "g1", "home_id": "1", "away_id": "2"}]
    inj = {"g1": {"1": [{"id": "a", "status": "Out"}]}}
    assert qb.adjustments(pl, games, sched, inj)["g1"]["1"]["shift"] == qb.REPORTED_OUT
    assert qb.adjustments(pl, games, sched, {"g1": {"1": [{"id": "a", "status": "Questionable"}]}}) == {}
    assert qb.adjustments(pl, games, sched, {"g1": {"1": [{"id": "b", "status": "Out"}]}}) == {}   # a backup being out changes nothing
