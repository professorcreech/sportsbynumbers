"""Settings for college football (Division I: FBS and FCS, rated on one scale)."""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "football"
SITE_DATA_DIR = ROOT / "site" / "football" / "data"

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
GROUPS = {"FBS": 80, "FCS": 81}
FETCH_WORKERS = 6
REFETCH_DAYS = 3


def season_for(d: date) -> int:
    """Named by the fall it starts in: Aug 2026 - Jan 2027 is the 2026 season."""
    return d.year if d.month >= 7 else d.year - 1


def season_start(season: int) -> date:
    return date(season, 8, 20)


def season_end(season: int) -> date:
    return date(season + 1, 1, 25)


# ---- Team model -------------------------------------------------------------
HALF_LIFE_DAYS = 120          # football seasons are short; recency matters less week to week
HFA_PRIOR = 2.5               # home-field edge in points, long-run college average
HFA_PRIOR_GAMES = 1500
PRIOR_GAMES = 3.0             # preseason prior strength in games (tuned by tests/football_backtest.py)
PRIOR_KEEP = 0.6              # share of last season's rating carried into the prior
MARGIN_SD = 15.0
