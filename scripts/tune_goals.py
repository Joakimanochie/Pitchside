"""Tune Dixon-Coles half-life and ridge on EARLY seasons only (2019/20-2021/22).

The later seasons (2022/23 onwards) are the untouched test set and are not read here.
Usage: uv run python scripts/tune_goals.py
"""
import itertools

import pandas as pd

from pitchside.ingest.footballdata import load_seasons
from pitchside.ingest.odds_history import load_closing_odds
from pitchside.models.backtest import score, walk_forward

TUNE_SEASONS = [2019, 2020, 2021]
HALF_LIVES = [90, 180, 365, 730]
RIDGES = [0.5, 2, 8, 20, 50]

if __name__ == "__main__":
    years = list(range(2015, max(TUNE_SEASONS) + 1))  # test seasons are never loaded here
    m = load_seasons("E0", years)
    o = load_closing_odds("E0", years)
    m = m[["season", "match_date", "home", "away", "ft_home", "ft_away"]].merge(o, on=["season", "match_date", "home", "away"], how="left")
    rows = []
    for hl, rg in itertools.product(HALF_LIVES, RIDGES):
        s = score(walk_forward(m, TUNE_SEASONS, half_life_days=hl, ridge=rg, step_days=14))
        rows.append({"half_life": hl, "ridge": rg, "1x2_logloss": s["1x2_logloss_model"], "1x2_rps": s["1x2_rps_model"],
                     "ou25_logloss": s["ou25_logloss_model"], "btts_logloss": s["btts_logloss_model"]})
        print(rows[-1], flush=True)
    res = pd.DataFrame(rows).sort_values("1x2_logloss")
    res.to_csv("data/processed/tune_goals.csv", index=False)
    print("\nBest by 1X2 log loss:\n", res.head(5).to_string(index=False))
    print("\nBase rate reference (same seasons): see backtest report")
