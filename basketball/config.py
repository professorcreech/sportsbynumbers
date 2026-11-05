"""Settings shared by every step. Change the site name and model knobs here."""
from datetime import date
from pathlib import Path

SITE_NAME = "Sports by Numbers"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "basketball"
SITE_DATA_DIR = ROOT / "site" / "basketball" / "data"

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
DIVISION_I_GROUP = 50
FETCH_WORKERS = 6          # parallel game requests; keep modest to be polite
REFETCH_DAYS = 2           # re-pull the last N days in case games were late or corrected


def season_for(d: date) -> int:
    """Season is named by the year it ends: Nov 2026 - Apr 2027 is 2027."""
    return d.year + 1 if d.month >= 8 else d.year


def season_start(season: int) -> date:
    return date(season - 1, 11, 1)


def season_end(season: int) -> date:
    return date(season, 4, 10)


# ---- Team model -------------------------------------------------------------
TEAM_PRIOR_GAMES = 4.0        # strength of the preseason prior, in games
TEAM_PRIOR_REGRESS = 0.6      # how much of last season's rating carries over
TEAM_HALF_LIFE_DAYS = 60      # recency weighting; older games count less
MARGIN_SD = 11.0              # fallback game-to-game margin standard deviation

# ---- Player model -----------------------------------------------------------
PLAYER_LAMBDA = 3000.0        # ridge strength in possessions; re-tuned by cross-validation mid-season
PLAYER_MIN_POSS_DISPLAY = 150 # players below this are kept out of the main table
LINEUP_MIN_POSS = 20
