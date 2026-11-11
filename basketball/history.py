"""One-time download of past seasons for the tournament model.

    python -m basketball.history 2012 2026

For each season: every Division I game's score, site, and (for NCAA tournament games) round,
region and seed. Then every arena city is located on a map using the Census Bureau's
public place list, and each school's home city is inferred from where it plays home games.

Writes data/basketball/history/:
    scores_<season>.csv.gz   one row per game
    places.csv               city, state, lat, lon for every venue city seen
    team_homes.csv           team_id, city, state, lat, lon
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from . import config
from .fetch import scoreboard, session

HIST = config.DATA_DIR / "history"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_{}_national.zip"
# Places the Census lists under another name (lat, lon)
MANUAL = {
    ("queens", "NY"): (40.7282, -73.7949), ("staten island", "NY"): (40.5795, -74.1502),
    ("riverdale", "NY"): (40.9005, -73.9064), ("bronx", "NY"): (40.8448, -73.8648),
    ("brooklyn", "NY"): (40.6782, -73.9442), ("jamaica", "NY"): (40.7027, -73.7890),
    ("honolulu", "HI"): (21.3069, -157.8583), ("university park", "PA"): (40.7982, -77.8599),
    ("chestnut hill", "MA"): (42.3357, -71.1684), ("normal", "AL"): (34.7834, -86.5719),
    ("lorman", "MS"): (31.8202, -91.0587), ("uncasville", "CT"): (41.4343, -72.1098),
}
TOURNAMENT_ID = 22
NCAA_TOURNAMENT_GROUP = 100


def season_scores(season: int) -> pd.DataFrame:
    path = HIST / f"scores_{season}.csv.gz"
    if path.exists():
        return pd.read_csv(path, dtype={"game_id": str, "home_id": str, "away_id": str})
    days, d = [], config.season_start(season)
    while d <= config.season_end(season):
        days.append(d)
        d += timedelta(days=1)

    def one(day):
        rows = scoreboard(day)
        if day.month in (3, 4):  # make sure every tournament game is included
            rows += scoreboard(day, NCAA_TOURNAMENT_GROUP)
        return rows

    with ThreadPoolExecutor(config.FETCH_WORKERS) as pool:
        rows = [r for day_rows in pool.map(one, days) for r in day_rows]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df.completed].drop_duplicates("game_id")
    df.insert(0, "season", season)
    HIST.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
    t = df[pd.to_numeric(df.tourney_id, errors="coerce") == TOURNAMENT_ID]
    print(f"{season}: {len(df)} games, {len(t)} NCAA tournament games")
    return df


_SUFFIX = re.compile(r"\s+(city and borough|consolidated government \(balance\)|metropolitan government \(balance\)|"
                     r"unified government \(balance\)|urban county|township|city|town|village|borough|CDP|municipality|"
                     r"\(balance\))$", re.I)


def _clean_city(s: str) -> str:
    s = str(s).strip()
    for _ in range(2):
        s = _SUFFIX.sub("", s).strip()
    s = s.lower()
    s = re.sub(r"\bsaint\s+", "st. ", s)
    return re.sub(r"\bst\.?\s+", "st. ", s)


def _gaz(kind: str) -> pd.DataFrame:
    r = session.get(GAZ.format(kind), timeout=120)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    g = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype=str)
    g.columns = [c.strip() for c in g.columns]
    return g


def gazetteer() -> pd.DataFrame:
    """Census places (cities, towns, CDPs), then county subdivisions (townships, New England towns)."""
    g = _gaz("place").assign(alt=0)
    try:
        g = pd.concat([g, _gaz("cousubs").assign(alt=2)])
    except Exception as e:
        print(f"county subdivisions not loaded: {e}")
    g["key"] = g.NAME.map(_clean_city)
    g["ALAND"] = pd.to_numeric(g.ALAND, errors="coerce")
    # "Nashville-Davidson", "Lexington-Fayette": also match on the first part
    hy = g[g.key.str.contains("-")].assign(key=lambda d: d.key.str.split("-").str[0], alt=lambda d: d.alt + 1)
    g = pd.concat([g, hy]).sort_values(["alt", "ALAND"], ascending=[True, False]).drop_duplicates(["key", "USPS"])
    return g.rename(columns={"USPS": "state", "INTPTLAT": "lat", "INTPTLONG": "lon"})[["key", "state", "lat", "lon"]]


def locate(scores: pd.DataFrame) -> None:
    cities = scores[["city", "state"]].dropna().drop_duplicates()
    g = gazetteer()
    cities["key"] = cities.city.map(_clean_city)
    places = cities.merge(g, on=["key", "state"], how="left")
    places["lat"] = pd.to_numeric(places.lat, errors="coerce")
    places["lon"] = pd.to_numeric(places.lon, errors="coerce")
    for i, r in places[places.lat.isna()].iterrows():
        if (r.key, r.state) in MANUAL:
            places.loc[i, ["lat", "lon"]] = MANUAL[(r.key, r.state)]
    places = places.drop(columns="key")
    missing = places[places.lat.isna()]
    print(f"located {places.lat.notna().sum()} of {len(places)} venue cities; missing e.g. "
          f"{missing.head(15)[['city', 'state']].values.tolist()}")
    places.to_csv(HIST / "places.csv", index=False)

    # A school's home city: where it most often plays non-neutral home games (recent seasons first)
    h = scores[~scores.neutral.astype(bool)].dropna(subset=["city"])
    h = h[h.season >= h.season.max() - 4]
    homes = (h.groupby(["home_id", "city", "state"]).size().rename("n").reset_index()
             .sort_values("n", ascending=False).drop_duplicates("home_id"))
    homes = homes.rename(columns={"home_id": "team_id"}).merge(places, on=["city", "state"], how="left")
    homes.to_csv(HIST / "team_homes.csv", index=False)
    print(f"home cities: {len(homes)} teams, {homes.lat.notna().sum()} located")


def main(first: int, last: int) -> None:
    frames = [season_scores(s) for s in range(first, last + 1)]
    locate(pd.concat(frames, ignore_index=True))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 2012, int(a[1]) if len(a) > 1 else config.season_for(date.today()) - 1)
