# Sports by Numbers

Statistical ratings and predictions, refit every morning and published as a website.

## Sports

| Sport | Folder | Season | What it rates |
|---|---|---|---|
| Men's college basketball | `basketball/` | Nov to Apr | Teams (adjusted efficiency, tempo), players (Bayesian plus-minus with a box-score prior), lineups, game predictions |

Adding a sport means a new folder with its own `run.py`, a page under `site/<sport>/`, and one more step in `.github/workflows/daily.yml`. Every new page needs the Google tag block copied from `site/index.html`, placed right after `<head>`.

## How it runs

A GitHub Action (`.github/workflows/daily.yml`) runs at about 3 am Mountain:

1. `python -m basketball.run --fetch` pulls any finished games since the last run from ESPN's public JSON feed and saves one small file per day under `data/basketball/<season>/`.
2. It refits every model on the full season and writes `site/basketball/data/*.json`.
3. The new data is committed, and the `site/` folder is published to GitHub Pages.

The first run of a season backfills everything since November 1 and also pulls last season's scores for the preseason prior, so it can take an hour or more. Later runs take a few minutes.

## Run it yourself

```bash
pip install -r requirements.txt
python -m basketball.run --fetch      # real data (needs internet)
python -m basketball.run --simulate   # simulated test season, no internet needed
python -m tests.test_basketball       # check the models recover known truth
cd site && python -m http.server      # view at http://localhost:8000
```

## Tuning

Model settings live in `basketball/config.py`: preseason prior strength, recency half-life, player shrinkage, and the minimum possessions shown. The full math is on the site's Method page.

## Data

Box scores and play-by-play come from ESPN's public scoreboard and game summary endpoints. They are unofficial and may change without notice; if a daily run fails, check the Actions log first.
