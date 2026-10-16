"""Backtest player-to-be-carded, fouls committed and fouls won on matches the player layer never saw.

Same walk-forward set-up as scripts/backtest_player_counts.py: for every logged match (from 2024/25 onward) each club's players get an expected count from their own
recent record per club match over the club's last N logged matches (recent ones weigh more); for cards the rate is also scaled by how many cards the club was
expected to get in that match compared with its recent average (the cards count model, refit weekly). Counts are negative binomial with a spread, and a scale for
rotation and injuries, estimated on matches before 2026-01-01; scoring is on the matches after, against the same chance for every player.

Writes data/raw/player_dataset_cards.csv.gz (all matches, for the confidence ratings) and data/processed/player_cards_test.csv. Reads the database (SELECT only).
Usage: uv run python scripts/backtest_player_cards.py
"""
import os
import sys
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg

from pitchside.db.migrate import _load_env
from pitchside.markets.counts import STATS
from pitchside.models.counts import COUNT_PARAMS, CountModel
from pitchside.models.players import LOG_PARAMS, at_least, log_rates
from pitchside.pipeline.weekly import load_count_history

TEST_FROM = pd.Timestamp("2024-08-01").date()
SPLIT = pd.Timestamp("2026-01-01").date()
N_MATCHES, HALF_LIFE = LOG_PARAMS["n_matches"], LOG_PARAMS["half_life_matches"]
SCALES = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
SHRINKS = {"cards": [0.0, 0.1, 0.2, 0.3, 0.4], "fouls": [0.0], "fouled": [0.0]}   # pull of a player's own cards rate toward the average (regression to the mean)
THRESHOLDS = {"cards": [1], "fouls": [1, 2], "fouled": [1, 2, 3]}
CACHE = "data/processed/player_cards_df.pkl"
MARKET = {"cards": "player_carded", "fouls": "player_fouls", "fouled": "player_fouled"}


def ll(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def expected_cards(conn, logged: pd.DataFrame) -> dict[int, tuple[float, float]]:
    """Cards the cards count model (refit each week on earlier matches) expected for each side of each logged match."""
    out: dict[int, tuple[float, float]] = {}
    for lg, games in logged.groupby("league"):
        h = load_count_history(conn, lg)
        data = h.assign(count_home=h["cards_h"], count_away=h["cards_a"])
        block = TEST_FROM
        end = games["date"].max()
        while block <= end:
            nxt = block + timedelta(days=7)
            week = games[(games["date"] >= block) & (games["date"] < nxt)]
            if len(week):
                model = CountModel(half_life_days=COUNT_PARAMS["cards"]["half_life_days"], ridge=COUNT_PARAMS["cards"]["ridge"], max_count=STATS["cards"]["max"]).fit(data, as_of=block)
                for r in week.itertuples(index=False):
                    out[r.id] = model.means(r.home, r.away)
            block = nxt
    return out


def main() -> None:
    if "--cached" in sys.argv:            # tune and score again from the saved player-matches, without recomputing the walk-forward rates
        report(pd.read_pickle(CACHE))
        return
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        logged = pd.DataFrame(conn.execute(
            "SELECT m.id, m.league_id, m.match_date, th.canonical_name, ta.canonical_name, m.home_team_id, m.away_team_id FROM matches m "
            "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id WHERE m.source_ids ->> 'espn_log' = 'true' ORDER BY m.match_date, m.id").fetchall(),
            columns=["id", "league", "date", "home", "away", "home_id", "away_id"])
        log = pd.DataFrame(conn.execute("SELECT match_id, team_id, player_name, yellow + red, fouls_committed, fouls_suffered FROM player_match_log").fetchall(),
                           columns=["match_id", "team_id", "player", "cards", "fouls", "fouled"])
        means = expected_cards(conn, logged)
    club_matches: dict[int, list[tuple]] = defaultdict(list)
    for r in logged.itertuples(index=False):
        club_matches[r.home_id].append((r.date, r.id))
        club_matches[r.away_id].append((r.date, r.id))
    by_club = {t: g for t, g in log.groupby("team_id")}
    rows = []
    for r in logged.itertuples(index=False):
        if r.date < TEST_FROM or r.id not in means:
            continue
        for team_id, expect in ((r.home_id, means[r.id][0]), (r.away_id, means[r.id][1])):
            past = [m for d, m in club_matches[team_id] if d < r.date]
            if len(past) < 8:
                continue
            club_log = by_club[team_id]
            rates = log_rates(club_log, past[::-1][:N_MATCHES], half_life_matches=HALF_LIFE)
            per_match = rates.team_cards / rates.weight
            factor = expect / per_match if per_match > 0 else 1.0
            now = club_log[club_log["match_id"] == r.id].set_index("player")
            p = rates.players
            for player in p.index:
                a = now.loc[player] if player in now.index else None
                rows.append((r.date, player, float(p.loc[player, "cards"] / rates.weight * factor), float(p.loc[player, "fouls"] / rates.weight), float(p.loc[player, "fouled"] / rates.weight),
                             0 if a is None else int(a["cards"]), 0 if a is None else int(a["fouls"]), 0 if a is None else int(a["fouled"])))
    df = pd.DataFrame(rows, columns=["date", "player", "r_cards", "r_fouls", "r_fouled", "cards", "fouls", "fouled"])
    df.to_pickle(CACHE)
    report(df)


def report(df: pd.DataFrame) -> None:
    print(f"{len(df):,} player-matches from {df['date'].min()} to {df['date'].max()}")
    tune, test = df[df["date"] < SPLIT], df[df["date"] >= SPLIT]
    pd.set_option("display.width", 200)
    out, dataset = [], []
    for stat, thresholds in THRESHOLDS.items():
        rate = "r_" + stat
        t = tune[tune[rate] > 0.03]
        prior = float(t[rate].mean())
        best = (9.0, 1.0, 0.0, 0.0)
        for shrink in SHRINKS[stat]:
            for scale in SCALES:
                mean = scale * ((1 - shrink) * t[rate].to_numpy() + shrink * prior)
                alpha = max(0.0, float(((t[stat].to_numpy() - mean) ** 2 - mean).sum() / (mean ** 2).sum()))
                score = sum(ll(at_least(mean, k, alpha), (t[stat].to_numpy() >= k).astype(float)) for k in thresholds)
                if score < best[0]:
                    best = (score, scale, alpha, shrink)
        _, scale, alpha, shrink = best
        print(f"{stat}: scale {scale}, spread {alpha:.3f}, shrink {shrink}, prior rate {prior:.4f}")
        adjust = lambda x, shrink=shrink, prior=prior: (1 - shrink) * x + shrink * prior
        everything = df[df[rate] > 0.03]
        for k in thresholds:
            line = None if stat == "cards" else k - 0.5
            dataset.append(pd.DataFrame({"match_id": range(len(everything)), "date": everything["date"], "league": "", "market_id": MARKET[stat], "family": "I", "line": line,
                                         "selection": "player", "p": at_least(scale * adjust(everything[rate].to_numpy()), k, alpha), "y": (everything[stat].to_numpy() >= k).astype(float)}))
        g = test[test[rate] > 0.03]
        for k in thresholds:
            y = (g[stat].to_numpy() >= k).astype(float)
            pr = at_least(scale * adjust(g[rate].to_numpy()), k, alpha)
            flat = float((t[stat] >= k).mean())
            out.append({"stat": stat, "at_least": k, "rows": len(g), "scale": scale, "alpha": round(alpha, 3), "happened": y.mean(), "predicted": pr.mean(),
                        "ll": ll(pr, y), "flat": ll(np.full(len(y), flat), y), "skill": 1 - ll(pr, y) / ll(np.full(len(y), flat), y)})
            band = pd.cut(pr, [0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0])
            print(f"\n{stat} >= {k}: calibration by band")
            print(pd.DataFrame({"p": pr, "y": y, "band": band}).groupby("band", observed=True).agg(n=("p", "size"), predicted=("p", "mean"), happened=("y", "mean")).round(3).to_string())
    res = pd.DataFrame(out)
    print("\nHELD-OUT SUMMARY\n", res.round(4).to_string(index=False))
    res.to_csv("data/processed/player_cards_test.csv", index=False)
    pd.concat(dataset).to_csv("data/raw/player_dataset_cards.csv.gz", index=False)


if __name__ == "__main__":
    main()
