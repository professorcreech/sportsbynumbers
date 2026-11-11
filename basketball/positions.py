"""Fill in missing player positions.

Order of preference:
  1. Position listed in the box score
  2. Position listed on the team roster
  3. Inferred from height (marked as inferred on the site)

Inference treats height within each position (G, F, C) as normally distributed, using
this season's players whose position and height are both known, and picks the position
with the highest posterior probability:

    P(pos | height) ∝ P(pos) × Normal(height; mean_pos, sd_pos)

P(pos) is how common each position is, so a 6'7" player isn't called a center just
because 6'7" is closer to the center average than the guard average would suggest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GROUPS = {"PG": "G", "SG": "G", "G": "G", "GF": "F", "SF": "F", "PF": "F", "F": "F", "FC": "C", "C": "C"}


def normalize(pos) -> str:
    """Collapse ESPN position labels to G / F / C; anything else is treated as missing."""
    if not isinstance(pos, str):
        return ""
    p = pos.strip().upper().replace("-", "").replace("/", "")
    return GROUPS.get(p, "")


def height_model(known: pd.DataFrame) -> dict:
    """Mean, SD and share of each position among players with both values known."""
    k = known[(known.pos.isin(["G", "F", "C"])) & (known.height > 60) & (known.height < 96)]
    if len(k) < 30:
        return {}
    model = {}
    for pos, g in k.groupby("pos"):
        model[pos] = {"mean": float(g.height.mean()), "sd": max(float(g.height.std(ddof=1)), 1.0),
                      "share": len(g) / len(k)}
    return model


def infer(height: float, model: dict) -> str:
    if not model or not np.isfinite(height) or height <= 60:
        return ""
    scores = {p: np.log(m["share"]) - np.log(m["sd"]) - 0.5 * ((height - m["mean"]) / m["sd"]) ** 2
              for p, m in model.items()}
    return max(scores, key=scores.get)


def fill(players: pd.DataFrame, rosters: pd.DataFrame | None) -> pd.DataFrame:
    """players needs player_id and pos (from the box score). Adds pos, pos_inferred, height."""
    out = players.copy()
    out["pos"] = out["pos"].map(normalize)
    out["height"] = np.nan
    if rosters is not None and len(rosters):
        r = rosters.drop_duplicates("player_id", keep="last").set_index("player_id")
        out["height"] = out.player_id.map(r.height).astype(float)
        roster_pos = out.player_id.map(r.pos).map(normalize)
        out["pos"] = out.pos.where(out.pos != "", roster_pos.fillna(""))
        known = pd.concat([out[["pos", "height"]],
                           r.assign(pos=r.pos.map(normalize))[["pos", "height"]]])
    else:
        known = out[["pos", "height"]]
    model = height_model(known.dropna(subset=["height"]))
    missing = out.pos == ""
    out["pos_inferred"] = False
    if missing.any() and model:
        guess = out.loc[missing, "height"].map(lambda h: infer(h, model))
        out.loc[missing, "pos"] = guess
        out.loc[missing, "pos_inferred"] = guess != ""
    out.attrs["height_model"] = model
    return out


def display_height(h) -> str:
    if h is None or not np.isfinite(h) or h <= 0:
        return ""
    h = int(round(h))
    return f"{h // 12}'{h % 12}\""
