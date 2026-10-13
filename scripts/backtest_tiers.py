"""Build the evidence confidence tiers are set from: every market priced and then settled on held-out matches.

Same held-out design as scripts/backtest_sim.py (goal-timing profile fitted on seasons <= 2024, half-time table on seasons <= 2021,
goals model refit weekly on matches before the week predicted) but every family, A to E, is priced with the production model settings
and each selection is settled against the real result. Scored matches are a random sample of verified matches from 2025/26 onward.

Writes data/raw/tier_backtest.csv.gz (not committed): one row per match and selection with the probability, the outcome (1/0, empty for a
push) and how much recent history each team had. Reads the production database (SELECT only) via DATABASE_URL.

Usage: uv run python scripts/backtest_tiers.py [sample_size] [n_sims]
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_sim as bs

from pitchside.db.migrate import _load_env
from pitchside.markets.base import settle as settle_market
from pitchside.markets.record_base import RecordMarket, settle_record
from pitchside.markets.registry import MARKETS
from pitchside.models.split_table import HalfSplitTable
from pitchside.pipeline.weekly import make_model
from pitchside.sim.pricing import price_all
from pitchside.sim.record import from_goals
from pitchside.sim.timing import GoalTimeProfile

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "tier_backtest.csv.gz"
HISTORY_DAYS = 3 * 365


def team_matches(history: pd.DataFrame, team: str, as_of) -> int:
    start = as_of - timedelta(days=HISTORY_DAYS)
    h = history[(history["match_date"] < as_of) & (history["match_date"] >= start)]
    return int(((h["home"] == team) | (h["away"] == team)).sum())


def outcome(row: dict, ft: tuple[int, int], record) -> float | None:
    market = MARKETS[row["market_id"]]
    if isinstance(market, RecordMarket):
        return settle_record(market, row["line"], row["selection"], record)["outcome_value"]
    return settle_market(market, row["line"], row["selection"], ft[0], ft[1])["outcome_value"]


def main(sample: int, n_sims: int) -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        df, goals = bs.load(conn)
        split_rows = conn.execute("SELECT ht_home, ht_away, ft_home, ft_away FROM matches WHERE status = 'finished' AND ht_home IS NOT NULL "
                                  "AND season <= %s", (bs.SPLIT_MAX_SEASON,)).fetchall()
        histories = {lg: bs.load_history(conn, lg) for lg in df.league.unique()}
    a = np.array(split_rows, dtype=int)
    split = HalfSplitTable().fit(a[:, 0], a[:, 1], a[:, 2], a[:, 3])
    train = df[df.season <= bs.PROFILE_MAX_SEASON]
    periods = np.array([p for i in train.id for (_s, p, _m) in goals[i]])
    minutes = np.array([m for i in train.id for (_s, _p, m) in goals[i]])
    profile = GoalTimeProfile().fit(periods, minutes)
    pool = df[df.season >= bs.TEST_MIN_SEASON]
    test = pool.sample(n=min(sample, len(pool)), random_state=1).sort_values("date")
    print(f"scoring {len(test)} held-out matches ({test.date.min()} to {test.date.max()})", flush=True)

    fits, out = {}, []
    for i, r in enumerate(test.itertuples(index=False)):
        week = r.date - timedelta(days=r.date.weekday())
        if (r.league, week) not in fits:
            fits[(r.league, week)] = make_model().fit(histories[r.league], as_of=week)
        scoreline = fits[(r.league, week)].score_matrix(r.home, r.away)
        rows = price_all(scoreline, split, profile, n_sims, seed=int(r.id))
        record = from_goals((r.ft_h, r.ft_a), (r.ht_h, r.ht_a), goals[r.id])
        low = min(team_matches(histories[r.league], r.home, r.date), team_matches(histories[r.league], r.away, r.date))
        for row in rows:
            out.append((r.id, r.date, r.league, row["market_id"], MARKETS[row["market_id"]].family, row["line"], row["selection"],
                        row["probability"], outcome(row, (r.ft_h, r.ft_a), record), low))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(test)}", flush=True)
    cols = ["match_id", "date", "league", "market_id", "family", "line", "selection", "p", "y", "min_team_matches"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out, columns=cols).to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(out):,} rows)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1200, int(sys.argv[2]) if len(sys.argv) > 2 else 10_000)
