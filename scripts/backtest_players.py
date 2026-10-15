"""Backtest the anytime-goalscorer probabilities on matches the player layer never saw.

For every finished match from 2025/26 onward (Understat shots are in the database from 2023/24) and each club in it:
  - the club's expected goals come from the production goals model refit on matches before that week (walk-forward);
  - each player's share of the club's goals comes from the club's last N matches before the match (recent ones weigh more, goals blended with the xG of his shots);
  - P(player scores) = 1 - exp(-club expected goals x share), compared with whether he scored.
Settings (N, memory in matches, goals/xG blend) are chosen on matches before 2026-01-01 and scored on the matches after; the baseline is the player's own
recent scoring rate per club match, with no opponent adjustment. Reads the database (SELECT only).

Usage: uv run python scripts/backtest_players.py
"""
import itertools
import os
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg

from pitchside.db.migrate import _load_env
from pitchside.models.players import team_rates
from pitchside.pipeline.weekly import load_history, make_model

TEST_FROM = "2025-08-01"
SPLIT = pd.Timestamp("2026-01-01").date()
GRID = list(itertools.product([20, 30, 45], [7.0, 10.0, 14.0], [0.75, 1.0]))     # matches in the window, memory in matches, weight on xG
SCALES = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1]         # a multiplier on the player's expected goals, for rotation and injuries the shares cannot see


def ll(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def main() -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        shots = pd.DataFrame(conn.execute(
            "SELECT s.match_id, m.match_date, m.league_id, t.canonical_name, s.player_name, s.assist_name, s.xg, s.result "
            "FROM shot_events s JOIN matches m ON m.id = s.match_id JOIN teams t ON t.id = s.team_id").fetchall(),
            columns=["match_id", "match_date", "league", "team", "player", "assist", "xg", "result"])
        matches = conn.execute(
            "SELECT m.id, m.league_id, m.match_date, th.canonical_name, ta.canonical_name FROM matches m JOIN teams th ON th.id = m.home_team_id "
            "JOIN teams ta ON ta.id = m.away_team_id WHERE m.status = 'finished' AND EXISTS (SELECT 1 FROM shot_events s WHERE s.match_id = m.id) "
            "ORDER BY m.match_date, m.id").fetchall()
        histories = {lg: load_history(conn, lg) for lg in shots["league"].unique()}
    shots["xg"] = shots["xg"].astype(float)
    team_matches: dict[str, list[tuple]] = defaultdict(list)      # team -> [(date, match_id)] ascending
    for mid, _lg, day, home, away in matches:
        team_matches[home].append((day, mid))
        team_matches[away].append((day, mid))
    by_team = {t: g for t, g in shots.groupby("team")}
    fits: dict = {}
    rows = []
    for mid, league, day, home, away in matches:
        if str(day) < TEST_FROM:
            continue
        week = day - timedelta(days=day.weekday())
        if (league, week) not in fits:
            fits[(league, week)] = make_model().fit(histories[league], as_of=week)
        lam = dict(zip(("home", "away"), fits[(league, week)].lambdas(home, away), strict=True))
        for side, team in (("home", home), ("away", away)):
            past = [m for d, m in team_matches[team] if d < day]
            if len(past) < 8:
                continue
            tshots = by_team[team]
            actual = set(tshots[(tshots["match_id"] == mid) & (tshots["result"] == "Goal")]["player"].dropna())
            for n, h, a in GRID:
                rates = team_rates(tshots, past[::-1][:n], half_life_matches=h)
                t, p = rates.team, rates.players
                if t["goals"] > 0 and t["xg"] > 0:
                    share = a * (p["xg"] / t["xg"]) + (1 - a) * (p["goals"] / t["goals"])
                elif t["xg"] > 0:
                    share = p["xg"] / t["xg"]
                else:
                    continue
                prob = 1 - np.exp(-lam[side] * share)
                naive = 1 - np.exp(-(p["goals"] / rates.weight))
                for player in p.index[share > 0.005]:
                    rows.append((day, league, n, h, a, float(prob[player]), float(naive[player]), int(player in actual)))
        if len(rows) % 500000 < 5000:
            print(f"  {day} rows {len(rows):,}", flush=True)
    df = pd.DataFrame(rows, columns=["date", "league", "n", "h", "a", "p", "naive", "y"])
    tune, test = df[df["date"] < SPLIT], df[df["date"] >= SPLIT]
    res = []
    for (n, h, a), g in tune.groupby(["n", "h", "a"]):
        res.append({"n": n, "h": h, "a": a, "rows": len(g), "ll": ll(g["p"].to_numpy(), g["y"].to_numpy()), "naive": ll(g["naive"].to_numpy(), g["y"].to_numpy())})
    res = pd.DataFrame(res).sort_values("ll")
    pd.set_option("display.width", 200)
    print("\nTUNING (before 2026-01-01), best settings:\n", res.head(6).round(5).to_string(index=False))
    best = res.iloc[0]
    tune_g = tune[(tune["n"] == best["n"]) & (tune["h"] == best["h"]) & (tune["a"] == best["a"])]
    lam_tune = -np.log1p(-np.clip(tune_g["p"].to_numpy(), 0, 1 - 1e-9))
    losses = {k: ll(1 - np.exp(-k * lam_tune), tune_g["y"].to_numpy()) for k in SCALES}
    k = min(losses, key=losses.get)
    print(f"\nscale chosen on the tuning matches: {k} (log loss by scale {({a: round(b, 5) for a, b in losses.items()})})")
    g = test[(test["n"] == best["n"]) & (test["h"] == best["h"]) & (test["a"] == best["a"])].copy()
    g["p_raw"] = g["p"]
    g["p"] = 1 - np.exp(-k * -np.log1p(-np.clip(g["p_raw"].to_numpy(), 0, 1 - 1e-9)))
    y = g["y"].to_numpy()
    flat = float(tune_g["y"].mean())
    print(f"\nHELD-OUT with n={best['n']:.0f}, memory {best['h']:.0f}, xG weight {best['a']}, scale {k}: rows {len(g):,}, scored {y.mean():.4f}")
    print(f"  log loss: model {ll(g['p'].to_numpy(), y):.5f} (unscaled {ll(g['p_raw'].to_numpy(), y):.5f}), naive recent rate {ll(g['naive'].to_numpy(), y):.5f}, "
          f"same chance for everyone {ll(np.full(len(y), flat), y):.5f}")
    print(f"  skill over the same-chance baseline {1 - ll(g['p'].to_numpy(), y) / ll(np.full(len(y), flat), y):+.4f}")
    g = g.assign(band=pd.cut(g["p"], [0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 1.0]))
    print(g.groupby("band", observed=True).agg(n=("p", "size"), predicted=("p", "mean"), happened=("y", "mean")).round(4).to_string())
    g.to_csv("data/raw/player_goal_backtest.csv", index=False)
    # every row of the chosen settings (before and after the split), scaled, as a dataset for the confidence ratings
    allg = df[(df["n"] == best["n"]) & (df["h"] == best["h"]) & (df["a"] == best["a"])].copy()
    allg["p"] = 1 - np.exp(-k * -np.log1p(-np.clip(allg["p"].to_numpy(), 0, 1 - 1e-9)))
    pd.DataFrame({"match_id": range(len(allg)), "date": allg["date"], "league": allg["league"], "market_id": "player_anytime_goal", "family": "I", "line": np.nan,
                  "selection": "player", "p": allg["p"], "y": allg["y"]}).to_csv("data/raw/player_dataset_goals.csv.gz", index=False)
    res.to_csv("data/processed/tune_players.csv", index=False)


if __name__ == "__main__":
    main()
