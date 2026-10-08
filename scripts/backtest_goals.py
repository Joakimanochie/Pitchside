"""Final walk-forward evaluation of the goals model on the held-out test seasons (2022/23 onwards).

Hyperparameters were chosen on 2019/20-2021/22 only (scripts/tune_goals.py) and are frozen here.
Usage: uv run python scripts/backtest_goals.py
"""
import pandas as pd

from pitchside.ingest.footballdata import load_seasons
from pitchside.ingest.odds_history import load_closing_odds
from pitchside.models.backtest import score, walk_forward

HALF_LIFE_DAYS, RIDGE = 730, 2.0
TEST_SEASONS = [2022, 2023, 2024, 2025, 2026]

if __name__ == "__main__":
    years = list(range(2015, 2027))
    m = load_seasons("E0", years)
    o = load_closing_odds("E0", years)
    m = m[["season", "match_date", "home", "away", "ft_home", "ft_away"]].merge(o, on=["season", "match_date", "home", "away"], how="left")
    pred = walk_forward(m, TEST_SEASONS, HALF_LIFE_DAYS, RIDGE, step_days=7)
    pred.to_csv("data/processed/backtest_goals_predictions.csv", index=False)

    rows = {f"{s}/{str(s + 1)[2:]}": score(pred[pred["season"] == s]) for s in TEST_SEASONS}
    rows["ALL"] = score(pred)
    table = pd.DataFrame(rows).T
    table.to_csv("data/processed/backtest_goals_summary.csv")
    pd.set_option("display.width", 250)
    print(table[["n", "1x2_logloss_model", "1x2_logloss_base", "1x2_logloss_book", "1x2_rps_model", "1x2_rps_book",
                 "1x2_accuracy_model", "1x2_accuracy_book"]].round(4).to_string())
    print()
    print(table[["ou25_logloss_model", "ou25_logloss_base", "ou25_logloss_book", "btts_logloss_model", "btts_logloss_base"]].round(4).to_string())
    unknown = pred[~pred["known_teams"]]
    print(f"\nmatches involving a team with no prior history in the window: {len(unknown)} of {len(pred)}")
    if len(unknown):
        print(score(unknown))
