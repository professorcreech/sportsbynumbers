"""Are predicted margins too big or too small in some kinds of games?   python -m tests.calibration_slices football 2022 ... 2026

Slope = how many points the home team actually wins by per point predicted (1.0 is right; below 1 means the model's
margins are too extreme). Bias = actual minus predicted margin.
"""
import sys

import numpy as np
import pandas as pd

from tests import uncertainty as U

kind, seasons = sys.argv[1], [int(s) for s in sys.argv[2:]]
df = pd.concat([(U.football if kind == "football" else U.basketball)(s) for s in seasons], ignore_index=True)
df["early"] = df.n_train < (600 if kind == "football" else 1500)
df["res"] = df.actual - df.margin


def slope(d):
    return float(np.polyfit(d.margin, d.actual, 1)[0]) if len(d) > 30 else np.nan


rows = []
for lab, mask in (("all", df.margin == df.margin), ("conference game", df.conf), ("non-conference", ~df.conf), ("neutral site", df.neutral),
                  ("early season", df.early), ("later", ~df.early), ("big favorite (|m|>14)", df.margin.abs() > 14), ("close (|m|<=7)", df.margin.abs() <= 7)):
    d = df[mask]
    per = [slope(x) for _, x in d.groupby("season")]
    rows.append({"slice": lab, "n": len(d), "slope": slope(d), "bias": d.res.mean(), "bias_se": d.res.std() / np.sqrt(max(len(d), 1)),
                 "slope_by_season": " ".join("%.2f" % v for v in per)})
print(pd.DataFrame(rows).round(3).to_string(index=False))
