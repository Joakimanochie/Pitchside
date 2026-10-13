"""Tune the recent scoring-level adjustment on EARLY seasons only (2019/20-2021/22, Premier League).

Each block is fitted once; the adjustment (window, shrink) is applied afterwards by shifting the league goal level, so
every candidate sees exactly the same fit. Test seasons are never loaded. Usage: uv run python scripts/tune_level.py
"""
import copy
import itertools
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

from pitchside.ingest.footballdata import load_seasons
from pitchside.models.backtest import outcome_index, walk_forward  # noqa: F401
from pitchside.models.dixon_coles import DixonColes
from pitchside.models.evaluate import (
    btts_probability,
    log_loss,
    over_probability,
    result_probs,
)

TUNE = [2019, 2020, 2021]
TEST = [2022, 2023, 2024, 2025, 2026]
TEST_MODE = "--test" in sys.argv  # one frozen setting vs off, on the held-out seasons
if TEST_MODE:
    TUNE = TEST
WINDOWS = [0, 60, 120, 240]
SHRINKS = [20, 60, 200]


def binary_ll(p, o):
    p = np.clip(np.asarray(p), 1e-12, 1 - 1e-12)
    return float(-(o * np.log(p) + (1 - o) * np.log(1 - p)).mean())


if __name__ == "__main__":
    configs = [(0, 0), (240, 60)] if TEST_MODE else [(0, 0)] + [(w, k) for w, k in itertools.product(WINDOWS[1:], SHRINKS)]
    store = {c: {"p": [], "o": [], "b": [], "y": [], "pr": []} for c in configs}
    for code in ("E0", "SP1", "D1", "I1", "F1"):
      m = load_seasons(code, list(range(2015, max(TUNE) + 1)))[["season", "match_date", "home", "away", "ft_home", "ft_away"]]
      m = m.sort_values("match_date").reset_index(drop=True)
      target = m[m["season"].isin(TUNE)]
      start, end = target["match_date"].min(), target["match_date"].max()
      t0 = start
      while t0 <= end:
          t1 = t0 + timedelta(days=14)
          block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
          if len(block):
              base = DixonColes(half_life_days=730, ridge=2.0).fit(m, as_of=t0)
              for w, k in configs:
                  mod = copy.copy(base)
                  mod.mu = base.mu + base.level_adjustment(m, w, k)
                  st = store[(w, k)]
                  for r in block.itertuples(index=False):
                      p = mod.score_matrix(r.home, r.away)
                      st["p"].append(over_probability(p, 2.5)); st["b"].append(btts_probability(p)); st["pr"].append(result_probs(p))
                      st["o"].append(int(r.ft_home + r.ft_away > 2.5)); st["y"].append(int(r.ft_home > 0 and r.ft_away > 0))
                      st.setdefault("r", []).append(0 if r.ft_home > r.ft_away else 1 if r.ft_home == r.ft_away else 2)
          t0 = t1
    rows = []
    for (w, k), st in store.items():
        o = np.array(st["o"]); p = np.array(st["p"])
        rows.append({"window": w, "shrink": k, "ou25_ll": binary_ll(p, o), "btts_ll": binary_ll(st["b"], np.array(st["y"])),
                     "1x2_ll": log_loss(np.array(st["pr"]), np.array(st["r"])), "mean_p_over": p.mean(), "actual_over": o.mean()})
    res = pd.DataFrame(rows)
    res.to_csv("data/processed/test_level.csv" if TEST_MODE else "data/processed/tune_level.csv", index=False)
    print(res.round(4).to_string(index=False))
