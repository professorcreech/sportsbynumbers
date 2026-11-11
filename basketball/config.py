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
HCA_PRIOR = 4.3               # home-court swing per 100 possessions (about 3 points a game), long-run college average
HCA_PRIOR_GAMES = 1500        # games of evidence the home-court prior is worth (a full season has ~5,500)

# ---- Preseason prior (see basketball/preseason.py and tests/preseason_study.py) ----------
# Fit on 2025-26 and checked on Nov 2026: last season's full-season rating beat recency-weighted
# and last-15-game versions; adding the roster (players carry ratings across teams) helped most;
# fading the prior by January made predictions worse, so it doesn't fade.
PRESEASON_W_PROGRAM = 0.69
PRESEASON_W_ROSTER = 0.5
PRESEASON_GAMES = 2.7

# ---- Tournament simulation ---------------------------------------------------------------
# How far a team's true strength may be from today's rating on Selection Sunday (per 100 poss).
# Measured on 2025-26: ratings moved ~5.2 from Dec 1, 4.2 from Jan 1, 2.8 from Feb 1 to March.
BRACKET_DRIFT_PER_100_DAYS = 4.9   # grows with the square root of days left
BRACKET_FINAL_SD = 2.5             # uncertainty that remains on tournament day


# Distance edge in tournament games (tests/tournament_factors.py, 2012-2026 tournaments):
# margin moves by -0.75 points per unit of log(1 + miles from campus), team minus opponent.
TOURNEY_LOG_DISTANCE = -0.75

# Announced sites (lat, lon). Regions are listed in the order they're filled by the S-curve.
TOURNEY_SITES = {
    2027: {
        "opening": {"Dayton": (39.7589, -84.1916), "Wichita": (37.6872, -97.3301)},
        # Arenas, so a team is never sent to its own home floor
        "venues": {"Dayton": "UD Arena", "Wichita": "INTRUST Bank Arena", "Pittsburgh": "PPG Paints Arena",
                   "Omaha": "CHI Health Center", "Fort Worth": "Dickies Arena", "Spokane": "Numerica Veterans Arena",
                   "Charlotte": "Spectrum Center", "Minneapolis": "Target Center", "Louisville": "KFC Yum! Center",
                   "Sacramento": "Golden 1 Center"},
        "first": {"Pittsburgh": (40.4406, -79.9959), "Omaha": (41.2565, -95.9345), "Fort Worth": (32.7555, -97.3308),
                  "Spokane": (47.6588, -117.4260), "Charlotte": (35.2271, -80.8431), "Minneapolis": (44.9778, -93.2650),
                  "Louisville": (38.2527, -85.7585), "Sacramento": (38.5816, -121.4944)},
        "regional": {"South (San Antonio)": (29.4241, -98.4936), "West (Los Angeles)": (34.0522, -118.2437),
                     "Midwest (Kansas City)": (39.0997, -94.5786), "East (New York)": (40.7128, -74.0060)},
        "final": {"Detroit": (42.3314, -83.0458)},
    },
}


def selection_sunday(season: int) -> date:
    """The Sunday between March 11 and 17 (2023-2027 all fit this rule)."""
    d = date(season, 3, 11)
    return d.fromordinal(d.toordinal() + (6 - d.weekday()) % 7)


# ---- Player model -----------------------------------------------------------
PLAYER_LAMBDA = 3000.0        # ridge strength in possessions; re-tuned by cross-validation mid-season
PLAYER_MIN_POSS_DISPLAY = 150 # players below this are kept out of the main table
LINEUP_MIN_POSS = 20
