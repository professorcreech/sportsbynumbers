import pandas as pd
from tools import ledger


def row(i, start, p=0.7, m=5.0):
    return {"game_id": i, "start": start, "home": "1", "away": "2", "home_name": "A", "away_name": "B", "neutral": 0, "p_home": p, "margin": m}


def test_prediction_freezes_at_tipoff_and_ignores_far_future():
    led = pd.DataFrame(columns=ledger.COLS)
    t0 = pd.Timestamp("2026-11-10T10:00Z")
    led = ledger.upsert(led, [row("g1", "2026-11-10T20:00Z", 0.6), row("far", "2026-11-14T20:00Z")], t0)
    assert list(led.game_id) == ["g1"]                      # 4 days out is not saved yet
    led = ledger.upsert(led, [row("g1", "2026-11-10T20:00Z", 0.8)], t0 + pd.Timedelta(hours=5))
    assert led.p_home.iloc[0] == 0.8                        # refreshed before the game
    led = ledger.upsert(led, [row("g1", "2026-11-10T20:00Z", 0.2)], pd.Timestamp("2026-11-10T21:00Z"))
    assert led.p_home.iloc[0] == 0.8                        # after tip-off the saved number never changes


def test_grade_and_summary(tmp_path, monkeypatch):
    led = pd.DataFrame([{**row("a", "2026-11-10T20:00Z", 0.8, 6), "snap": "x"}, {**row("b", "2026-11-11T20:00Z", 0.7, 4), "snap": "x"}])
    res = pd.DataFrame({"game_id": ["a", "b"], "home_pts": [80, 60], "away_pts": [70, 70]})
    g = ledger.grade(led, res)
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    s = ledger.summarize("nba", g)
    assert (s["n"], s["hit"]) == (2, 1)
    assert s["teams"]["1"]["n"] == 2 and s["teams"]["1"]["raw"] == round(((10 - 6) + (-10 - 4)) / 2, 2)
