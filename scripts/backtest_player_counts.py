"""Backtest player shots, shots on target and assists on matches the player layer never saw.

Same walk-forward set-up as scripts/backtest_players.py (matches from 2025/26 onward; each player's expected count is his own recent rate per club match over the
club's last N matches, recent ones weighing more). Counts are modelled as negative binomial with a spread estimated on the matches before 2026-01-01 and a scale for
rotation and injuries chosen there too; scoring is on the matches after. Compared with the same chance of each outcome for every player.
Reads the database (SELECT only). Usage: uv run python scripts/backtest_player_counts.py
"""
import os
from collections import defaultdict

import numpy as np
import pandas as pd
import psycopg

from pitchside.db.migrate import _load_env
from pitchside.models.players import ON_TARGET, at_least, team_rates

TEST_FROM = "2025-08-01"
SPLIT = pd.Timestamp("2026-01-01").date()
N_MATCHES, HALF_LIFE = 45, 14.0
SCALES = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
THRESHOLDS = {"shots": [1, 2, 3], "sot": [1, 2], "assists": [1]}


def ll(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def main() -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        shots = pd.DataFrame(conn.execute(
            "SELECT s.match_id, m.match_date, t.canonical_name, s.player_name, s.assist_name, s.xg, s.result "
            "FROM shot_events s JOIN matches m ON m.id = s.match_id JOIN teams t ON t.id = s.team_id").fetchall(),
            columns=["match_id", "match_date", "team", "player", "assist", "xg", "result"])
        matches = conn.execute(
            "SELECT m.id, m.match_date, th.canonical_name, ta.canonical_name FROM matches m JOIN teams th ON th.id = m.home_team_id "
            "JOIN teams ta ON ta.id = m.away_team_id WHERE m.status = 'finished' AND EXISTS (SELECT 1 FROM shot_events s WHERE s.match_id = m.id) "
            "ORDER BY m.match_date, m.id").fetchall()
    shots["xg"] = shots["xg"].astype(float)
    team_matches: dict[str, list[tuple]] = defaultdict(list)
    for mid, day, home, away in matches:
        team_matches[home].append((day, mid))
        team_matches[away].append((day, mid))
    by_team = {t: g for t, g in shots.groupby("team")}
    rows = []
    for mid, day, home, away in matches:
        if str(day) < TEST_FROM:
            continue
        for team in (home, away):
            past = [m for d, m in team_matches[team] if d < day]
            if len(past) < 8:
                continue
            tshots = by_team[team]
            rates = team_rates(tshots, past[::-1][:N_MATCHES], half_life_matches=HALF_LIFE)
            now = tshots[(tshots["match_id"] == mid) & (tshots["result"] != "Own Goal")]
            actual = pd.DataFrame({
                "shots": now.dropna(subset=["player"]).groupby("player").size(),
                "sot": now[now["result"].isin(ON_TARGET)].dropna(subset=["player"]).groupby("player").size(),
                "assists": now[now["result"] == "Goal"].dropna(subset=["assist"]).groupby("assist").size()})
            p = rates.players
            for player in p.index[(p["shots"] / rates.weight > 0.15) | (p["assists"] / rates.weight > 0.05)]:
                a = actual.loc[player] if player in actual.index else pd.Series({"shots": 0, "sot": 0, "assists": 0})
                rows.append((day, player, float(p.loc[player, "shots"] / rates.weight), float(p.loc[player, "sot"] / rates.weight), float(p.loc[player, "assists"] / rates.weight),
                             int(np.nan_to_num(a["shots"])), int(np.nan_to_num(a["sot"])), int(np.nan_to_num(a["assists"]))))
    df = pd.DataFrame(rows, columns=["date", "player", "r_shots", "r_sot", "r_assists", "shots", "sot", "assists"])
    tune, test = df[df["date"] < SPLIT], df[df["date"] >= SPLIT]
    pd.set_option("display.width", 200)
    out = []
    dataset = []
    for stat in list(THRESHOLDS):
        rate = "r_" + stat
        t = tune[tune[rate] > 0]
        best = (9.0, 1.0, 0.0)
        for scale in SCALES:                                   # spread from the moments, scale from the likelihood
            mean = scale * t[rate].to_numpy()
            alpha = max(0.0, float(((t[stat].to_numpy() - mean) ** 2 - mean).sum() / (mean ** 2).sum()))
            score = sum(ll(at_least(mean, k, alpha), (t[stat].to_numpy() >= k).astype(float)) for k in THRESHOLDS[stat])
            if score < best[0]:
                best = (score, scale, alpha)
        _, scale, alpha = best
        everything = df[df[rate] > 0]            # before and after the split, for the confidence ratings
        for k in THRESHOLDS[stat]:
            market = {"shots": "player_shots", "sot": "player_sot", "assists": "player_assist"}[stat]
            line = None if stat == "assists" else k - 0.5
            dataset.append(pd.DataFrame({"match_id": range(len(everything)), "date": everything["date"], "league": "", "market_id": market, "family": "I", "line": line,
                                         "selection": "player", "p": at_least(scale * everything[rate].to_numpy(), k, alpha), "y": (everything[stat].to_numpy() >= k).astype(float)}))
        g = test[test[rate] > 0]
        for k in THRESHOLDS[stat]:
            y = (g[stat].to_numpy() >= k).astype(float)
            p = at_least(scale * g[rate].to_numpy(), k, alpha)
            flat = float((t[stat] >= k).mean())
            out.append({"stat": stat, "at_least": k, "rows": len(g), "scale": scale, "alpha": round(alpha, 3), "happened": y.mean(), "predicted": p.mean(),
                        "ll": ll(p, y), "flat": ll(np.full(len(y), flat), y), "skill": 1 - ll(p, y) / ll(np.full(len(y), flat), y)})
            band = pd.cut(p, [0, 0.1, 0.2, 0.35, 0.5, 0.7, 1.0])
            print(f"\n{stat} >= {k}: calibration by band")
            print(pd.DataFrame({"p": p, "y": y, "band": band}).groupby("band", observed=True).agg(n=("p", "size"), predicted=("p", "mean"), happened=("y", "mean")).round(3).to_string())
    res = pd.DataFrame(out)
    print("\nHELD-OUT SUMMARY\n", res.round(4).to_string(index=False))
    res.to_csv("data/processed/player_counts_test.csv", index=False)
    pd.concat(dataset).to_csv("data/raw/player_dataset_counts.csv.gz", index=False)


if __name__ == "__main__":
    main()
