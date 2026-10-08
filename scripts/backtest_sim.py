"""Does the simulator's pricing of families B-E match reality?

Held-out design (nothing is scored on data it was fitted on):
  - goal-timing profile: fitted on verified goals from seasons <= 2024
  - half-time table: fitted on seasons <= 2021 (all five leagues pooled)
  - goals model: refit weekly on matches before the week being predicted (walk-forward, per league)
  - scored on a random sample of verified matches from 2025/26 and 2026/27
Baseline for every (market, line, selection): how often it happened in the 2023-2024 verified matches.
Reads the production database (SELECT only) via DATABASE_URL.

Usage: uv run python scripts/backtest_sim.py [sample_size] [n_sims]
"""
import os
import sys
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg

from pitchside.db.migrate import _load_env
from pitchside.markets.base import HALF_LOST, HALF_WON, LOST, WON
from pitchside.markets.record_base import price_record
from pitchside.markets.registry import RECORD_MARKETS
from pitchside.models.dixon_coles import DixonColes
from pitchside.models.split_table import HalfSplitTable
from pitchside.pipeline.weekly import MODEL_PARAMS, load_history
from pitchside.sim.record import from_many
from pitchside.sim.simulate import simulate
from pitchside.sim.timing import GoalTimeProfile

PROFILE_MAX_SEASON, SPLIT_MAX_SEASON, TEST_MIN_SEASON = 2024, 2021, 2025
GOAL_TYPES = ("goal", "own_goal", "penalty_goal")


def keys():
    out = []
    for m in RECORD_MARKETS.values():
        for line in (m.lines if m.has_line else (None,)):
            out.extend((m.id, line, sel) for sel in m.selections(line))
    return out


def indicators(rec, key_list) -> np.ndarray:
    """(matches, keys): 1 if the selection won, 0 if it lost, NaN if it pushed."""
    cols = []
    for mid, line, sel in key_list:
        c = RECORD_MARKETS[mid].codes(sel, line, rec)
        cols.append(np.where((c == WON) | (c == HALF_WON), 1.0, np.where((c == LOST) | (c == HALF_LOST), 0.0, np.nan)))
    return np.stack(cols, axis=1)


def load(conn):
    rows = conn.execute(
        "SELECT m.id, m.league_id, m.season, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away, m.ht_home, m.ht_away "
        "FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.status = 'finished' AND m.source_ids ->> 'goal_minutes' = 'true' ORDER BY m.match_date").fetchall()
    df = pd.DataFrame(rows, columns=["id", "league", "season", "date", "home", "away", "ft_h", "ft_a", "ht_h", "ht_a"])
    goals = defaultdict(list)
    for mid, side, period, minute in conn.execute(
            "SELECT match_id, details ->> 'side', period, minute FROM match_events WHERE source = 'understat' AND event_type = ANY(%s)",
            (list(GOAL_TYPES),)):
        goals[mid].append((side, period, minute))
    return df, goals


def batch(df, goals):
    return from_many(list(zip(df.ft_h, df.ft_a, strict=True)), list(zip(df.ht_h, df.ht_a, strict=True)), [goals[i] for i in df.id])


def main(sample: int, n_sims: int):
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        df, goals = load(conn)
        split_rows = conn.execute("SELECT ht_home, ht_away, ft_home, ft_away FROM matches WHERE status = 'finished' AND ht_home IS NOT NULL "
                                  "AND season <= %s", (SPLIT_MAX_SEASON,)).fetchall()
        histories = {lg: load_history(conn, lg) for lg in df.league.unique()}
    a = np.array(split_rows, dtype=int)
    split = HalfSplitTable().fit(a[:, 0], a[:, 1], a[:, 2], a[:, 3])
    train = df[df.season <= PROFILE_MAX_SEASON]
    periods = np.array([p for i in train.id for (_s, p, _m) in goals[i]])
    minutes = np.array([m for i in train.id for (_s, _p, m) in goals[i]])
    profile = GoalTimeProfile().fit(periods, minutes)
    test = df[df.season >= TEST_MIN_SEASON].sample(n=min(sample, (df.season >= TEST_MIN_SEASON).sum()), random_state=0).sort_values("date")
    print(f"profile from {len(periods)} goals (seasons <= {PROFILE_MAX_SEASON}); split table from {len(a)} matches; scoring {len(test)} held-out matches", flush=True)

    key_list = keys()
    base_y = indicators(batch(train, goals), key_list)
    n_obs = np.sum(~np.isnan(base_y), axis=0)
    base_rate = (np.nansum(base_y, axis=0) + 0.5) / (n_obs + 1.0)         # add-half smoothing so nothing is exactly 0 or 1
    y = indicators(batch(test, goals), key_list)

    fits, pred = {}, np.zeros((len(test), len(key_list)))
    for i, r in enumerate(test.itertuples(index=False)):
        week = r.date - timedelta(days=r.date.weekday())
        if (r.league, week) not in fits:
            fits[(r.league, week)] = DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"]).fit(histories[r.league], as_of=week)
        scoreline = fits[(r.league, week)].score_matrix(r.home, r.away)
        rec = simulate(scoreline, split, profile, n_sims, np.random.default_rng(int(r.id)))
        lookup = {(row["market_id"], row["line"], row["selection"]): row["probability"] for m in RECORD_MARKETS.values()
                  for line in (m.lines if m.has_line else (None,)) for row in price_record(m, line, rec)}
        pred[i] = [lookup[k] for k in key_list]
        if (i + 1) % 50 == 0:
            print(f"  priced {i + 1}/{len(test)}", flush=True)

    eps = 1e-6
    p = np.clip(pred, eps, 1 - eps)
    b = np.clip(base_rate[None, :], eps, 1 - eps)
    model_ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    base_ll = -(y * np.log(b) + (1 - y) * np.log(1 - b))
    out = pd.DataFrame({"market": [k[0] for k in key_list], "line": [k[1] for k in key_list], "selection": [k[2] for k in key_list],
                        "n": np.sum(~np.isnan(y), axis=0), "base_rate": base_rate, "mean_pred": np.nanmean(np.where(np.isnan(y), np.nan, pred), axis=0),
                        "actual": np.nanmean(y, axis=0), "model_ll": np.nanmean(model_ll, axis=0), "base_ll": np.nanmean(base_ll, axis=0)})
    out["family"] = out.market.map(lambda m: RECORD_MARKETS[m].family)
    out.to_csv("data/processed/backtest_sim_selections.csv", index=False)

    by_market = out.groupby(["family", "market"]).agg(selections=("selection", "size"), model_ll=("model_ll", "mean"), base_ll=("base_ll", "mean"),
                                                      mean_pred=("mean_pred", "mean"), actual=("actual", "mean")).reset_index()
    by_market["skill"] = 1 - by_market.model_ll / by_market.base_ll     # share of the base-rate loss removed; <0 means worse than the base rate
    by_market.to_csv("data/processed/backtest_sim_markets.csv", index=False)
    by_family = out.groupby("family").agg(selections=("selection", "size"), model_ll=("model_ll", "mean"), base_ll=("base_ll", "mean")).reset_index()
    by_family["skill"] = 1 - by_family.model_ll / by_family.base_ll
    pd.set_option("display.width", 220); pd.set_option("display.max_rows", 400)
    print("\n== BY FAMILY (skill = share of the base-rate log loss removed; higher is better, negative = worse than the base rate) ==")
    print(by_family.round(4).to_string(index=False))
    print("\n== MARKETS WITH THE LEAST SKILL ==")
    print(by_market.sort_values("skill").head(15).round(4).to_string(index=False))
    print("\n== MARKETS WITH THE MOST SKILL ==")
    print(by_market.sort_values("skill").tail(10).round(4).to_string(index=False))
    # calibration over every selection and match
    flat_p, flat_y = pred.ravel(), y.ravel()
    ok = ~np.isnan(flat_y)
    bins = np.array([0, .02, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, .98, 1.0001])
    idx = np.digitize(flat_p[ok], bins) - 1
    print("\n== CALIBRATION (all families B-E, every selection) ==")
    for k in range(len(bins) - 1):
        m = idx == k
        if m.sum():
            print(f"  predicted {bins[k]:.2f}-{bins[k + 1]:.2f}: n={m.sum():7d}  avg predicted {flat_p[ok][m].mean():.3f}  actual {flat_y[ok][m].mean():.3f}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500, int(sys.argv[2]) if len(sys.argv) > 2 else 15_000)
