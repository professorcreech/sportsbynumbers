# Sports by Numbers

Statistical ratings and predictions for college and pro basketball and football, refit every
morning and published at **https://professorcreech.github.io/sportsbynumbers/**.

The approach throughout is Bayesian: every rating starts from an informed prior (last season,
this year's roster) and moves toward what this season's games say as evidence accumulates.
Every modeling choice below was tested on games the model hadn't seen.

## Track record

`tools/ledger.py` runs after every daily build. It saves each game's prediction (last one made before tip-off,
for games in the next 36 hours), grades it when the final score arrives, and writes `site/<sport>/data/record.json`
for the **Record** tab: picks right, calibration by confidence, weekly results, how the model compares with the
betting line where one exists, and per-team gaps between result and prediction (with their margin of noise).
Files: `data/<sport>/ledger.csv`. `tools/replay.py` replays last season game by game (refit on only earlier games, from last season's prior) into `data/<sport>/replay.csv`, so the tab can compare this season with the same dates a year ago. `python -m tools.ledger --backfill` rebuilds earlier days from the site's git history.

## Sports

| Section | Engine | Season | What it has |
|---|---|---|---|
| Men's college basketball | `basketball/` | Nov–Apr | Team ratings, player impact, lineups, predictions, matchup reports, tournament odds |
| College football (FBS + FCS) | `football/` | Aug–Jan | Team ratings, predictions, matchup reports, Playoff odds (2026 12-team rules) |
| NBA | `basketball/` with `SBN_LEAGUE=nba` | Oct–Jun | Same views as college basketball minus the bracket, plus player value vs. salary |
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
| NBA preseason prior | `preseason_study.py` (`SBN_LEAGUE=nba`) | Roster explains more than team results (0.25 program / 0.62 roster), worth 8 games |
| NFL preseason prior | `football_backtest.py` (`SBN_LEAGUE=nfl`) | Carry only ~30% of last season, worth 6 games (pros regress hard) |
| Replay of the 2026 NCAA tournament | `tournament_backtest.py` | 71.6% of games right (better seed: 68.7%); log loss 0.486 vs 0.580; champion Michigan was the 2nd favorite (14%); bracket 1,050 pts vs 1,000 chalk |
| Are the football settings still right? Do win probabilities need rating uncertainty? Are margins too big in some game types? (2022-26, weekly refits) | `tune_football.py`, `uncertainty.py`, `calibration_slices.py` | Settings are at a plateau (no change moves Brier more than 0.001). Adding rating uncertainty hurts college football, NCAAM and the NFL and helps the NBA only trivially. College football conference-game margins run ~10% too wide and non-conference home teams beat predictions by ~2 pts, but fixing both gains only 0.0003 Brier, so neither is applied. |
| Do players keep rising in big games from one season to the next? (2024-25 → 2025-26, NCAAM and NBA; big game = top 15% / 25% opponent; Game Score per 36) | `big_game.py` | No. Season-to-season correlation of a player's big-game elevation is +0.04 (NCAAM, 336 players) and +0.06 (NBA, 264); about 0 for players who stayed, +0.10 / +0.26 (n=165 / 78) for those who changed teams. A stable trait would show roughly +0.2 to +0.3. Stakes-based big games (tournaments, playoffs) aren't tested: too few games per player. |
| Do referee crews predict totals or home margins? (2025-26 replay residuals, officials with 30+ games, odd/even split) | ad hoc | Little. Totals: split-half correlation +0.06 (NCAAM, 227 refs), +0.18 (NBA, 68). Home margin: +0.18 / +0.21, but crews are assigned by conference and region, so that is confounded with team strength; not applied. |
| Do quarterbacks keep rising in big games? (2025 → 2026, adjusted yards per attempt vs top-15% / top-25% opponents) | `big_game_qb.py` | No. College: season-to-season correlation −0.25 (45 QBs with enough attempts); NFL +0.01 (17, too few to say). |
| Does a missing player move results, and does it matter who he is? (2025-26 box scores; replayed predictions; no hindsight) | `availability_value.py`, `qb_absence.py`, `qb_absence_live.py` | The shortfall scales with the missing players' production, not their label: about -0.8 pts per 100 usual offensive yards (college, ±0.2; NFL -0.6 ±0.5), and a flat "starting QB out" flag adds nothing once production is in (-0.3 ±1.0). Lost defensive box-score production shows no effect. Applied (`football/availability.py`): NFL, players the injury report lists Out/Doubtful/IR, 0.6 pts per 100 yards; college, players who missed the previous game (the only pregame signal; -0.68 ±0.27 for 40+ yard players, applied at 0.5). Both count only players with 3+ games and 40+ usual yards. |
| Which other factors predict games? (2025-26 walk-forward, fit on one half, tested on the other) | `factors.py` | Holds up: missing rotation players (college and NBA; needs injury reports), NBA back-to-backs (−1.8 pts, now applied). Doesn't: rest, travel, time zones, hot streaks, team-specific home court, style matchups, halftime "adjustment" teams, tip-off time. Recency half-life 60 days confirmed. The closing betting line beats the model (college 8.9 vs 9.1 MAE) |
| Does the coach matter? | `coach_study.py` | A new coach lowers the team ~1.75 pts/game vs. last season's projection and last season carries less; his record elsewhere carries over. Helped 12 of 12 held-out seasons; now in the college preseason prior (`basketball/coaching.py`). A coach's record at his current school and his past NCAA tournament overperformance add nothing |
| Situational habits | `basketball/situations.py`, `football/situations.py` | Basketball: tempo, shot mix, ball movement, fouling and pressure in the closing minutes by score. Football: pass rate, success and explosiveness by down and distance, red zone and score, plus fourth-down aggression. Rates are shrunk toward the league; last season counts partially. Play-by-play can't show zone/man, press, blitz, play-action or coverage |
| Football calibration | (inline replay of 2025) | College: actual margin = 1.01 × predicted on 1,677 games; NFL 1.15 on 269 |

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
