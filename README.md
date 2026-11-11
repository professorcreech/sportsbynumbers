# Sports by Numbers

Statistical ratings and predictions for college and pro basketball and football, refit every
morning and published at **https://professorcreech.github.io/sportsbynumbers/**.

The approach throughout is Bayesian: every rating starts from an informed prior (last season,
this year's roster) and moves toward what this season's games say as evidence accumulates.
Every modeling choice below was tested on games the model hadn't seen.

## Sports

| Section | Engine | Season | What it has |
|---|---|---|---|
| Men's college basketball | `basketball/` | Nov–Apr | Team ratings, player impact, lineups, predictions, matchup reports, tournament odds |
| College football (FBS + FCS) | `football/` | Aug–Jan | Team ratings, predictions, matchup reports, Playoff odds |
| NBA | `basketball/` with `SBN_LEAGUE=nba` | Oct–Jun | Same views as college basketball, minus the bracket |
| NFL | `football/` with `SBN_LEAGUE=nfl` | Sep–Feb | Team ratings, predictions, matchup reports |

The pro leagues reuse the college engines; `SBN_LEAGUE` switches endpoints, folders, season
dates and constants (`basketball/config.py`, `football/config.py`). The two page scripts
(`site/basketball/app.js`, `site/football/app.js`) serve both levels and read the league from
`meta.json`.

## How it runs

`.github/workflows/daily.yml` runs at about 3:17 am Mountain. For each sport in season it pulls
finished games from ESPN's public JSON feed (one small file per day under `data/<sport>/<season>/`),
refits every model, writes `site/<sport>/data/*.json`, commits the data and publishes `site/`
to GitHub Pages. Manual runs (Actions → Daily update → Run workflow) accept options to download
past seasons, re-download a season, fetch tournament history, or probe a new feed.

Every page carries the Google tag right after `<head>`; copy it from `site/index.html` into any new page.

## What was tested (scripts in `tests/`)

| Question | Script | Answer |
|---|---|---|
| Do the basketball models recover known truth? | `test_basketball.py` | Yes, on a simulated season with known player and team strengths |
| How much should last season count early on? | `prior_backtest.py`, `preseason_study.py` | Ignoring it costs ~1.4 pts/game. Full season beats last-15-games or recency-weighted. Prior worth 5 games; fading it by January hurt |
| Does the roster matter (players carrying ratings across teams)? | `preseason_study.py` | Yes: ~0.9 pts/game better on Nov 2026 games |
| Should in-season player ratings start from last season? | (inline test, Nov 2026) | Yes: 80% carry-over beat the box-score prior at every shrinkage level |
| Are win probabilities calibrated? | (inline test, 2025-26) | Actual margin = 0.96 × predicted on 1,480 held-out games |
| What matters in the NCAA tournament beyond ratings? | `tournament_factors.py` | Distance from campus (yes, ~2 pts for 50 vs 1,000 miles); road/neutral form (no); tournament reputation (not reliably) |
| Football prior and blowout damping | `football_backtest.py` | Carry 90% of last season, worth 3 games; damping margins hurt |
| Bowl games: classifiers vs. ratings (after Delen, Cogdell & Kasap 2012) | `bowl_study.py` | All ~60% out of time; random forest 61.4%, ratings 59.6%; decision tree 56.7% |

## Run it yourself

```bash
pip install -r requirements.txt
python -m basketball.run --fetch                 # college basketball (needs internet)
SBN_LEAGUE=nba python -m basketball.run --fetch  # NBA
python -m football.run --fetch                   # college football
SBN_LEAGUE=nfl python -m football.run --fetch    # NFL
python -m basketball.bracket                     # tournament odds
cd site && python -m http.server                 # view at http://localhost:8000
```

## Data

Box scores, play-by-play, schedules, rosters and polls come from ESPN's public endpoints; the
projected NCAA field comes from the Bracket Matrix (credited on the page). Venue coordinates come
from the U.S. Census Bureau gazetteer. These sources are unofficial and may change; if a daily
run fails, check the Actions log first.
