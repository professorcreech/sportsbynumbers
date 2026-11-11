"""Settings for college football (Division I: FBS and FCS, rated on one scale)."""
from datetime import date
from pathlib import Path

import os

# One engine, two leagues: SBN_LEAGUE=nfl switches endpoints, folders, dates and constants.
LEAGUE = os.environ.get("SBN_LEAGUE", "ncaaf").lower()
IS_NFL = LEAGUE == "nfl"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / ("nfl" if IS_NFL else "football")
SITE_DATA_DIR = ROOT / "site" / ("nfl" if IS_NFL else "football") / "data"

ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl" if IS_NFL
        else "https://site.api.espn.com/apis/site/v2/sports/football/college-football")
STANDINGS = ("https://site.api.espn.com/apis/v2/sports/football/nfl/standings" if IS_NFL
             else "https://site.api.espn.com/apis/v2/sports/football/college-football/standings")
GROUPS = {"NFL": None} if IS_NFL else {"FBS": 80, "FCS": 81}
FETCH_WORKERS = 6
REFETCH_DAYS = 3


def season_for(d: date) -> int:
    """Named by the fall it starts in: Aug 2026 - Jan 2027 is the 2026 season."""
    return d.year if d.month >= 7 else d.year - 1


def season_start(season: int) -> date:
    return date(season, 9, 1) if IS_NFL else date(season, 8, 20)


def season_end(season: int) -> date:
    return date(season + 1, 2, 15) if IS_NFL else date(season + 1, 1, 25)


# ---- Team model -------------------------------------------------------------
HALF_LIFE_DAYS = 120          # football seasons are short; recency matters less week to week
HFA_PRIOR = 1.8 if IS_NFL else 2.5   # home-field edge in points (NFL has shrunk to ~1.5-2 in recent seasons)
HFA_PRIOR_GAMES = 1500
PRIOR_GAMES = 6.0 if IS_NFL else 3.0   # prior strength in games (tests/football_backtest.py; NFL: plateau 4-6 on 2025)
PRIOR_KEEP = 0.3 if IS_NFL else 0.9    # share of last season carried over (college: best of 50/70/90% on 2025;
                                       # NFL: 15-45% all similar on 2025, 30% chosen; NFL teams regress hard)
MARGIN_SD = 13.5 if IS_NFL else 15.0
