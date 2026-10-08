"""Settle stored predictions against real results.

    uv run python -m pitchside.settle.settle

Steps (all idempotent):
  1. build_outcomes: write the real MatchRecord of every finished match that has predictions.
  2. settle_predictions: settle each prediction with the SAME market rules that priced it, and score it.

Integrity rules:
  - A prediction made at or after kickoff is voided ('made_after_kickoff'): it can never count.
  - A cancelled match voids its predictions. A postponed match stays pending until it is played.
  - If a result is corrected after settling, the affected predictions are re-settled.
  - A market we cannot settle (unknown market or selection) is 'not_scorable', counted separately, never guessed.
Scores: log loss and Brier use the stored probability and the 1/0 outcome on the stake at risk; pushes,
voids and not-scorable predictions get no score.
"""
import json
import math
import os
from collections import Counter

import psycopg

from pitchside.db.migrate import _load_env
from pitchside.markets.base import settle as settle_market
from pitchside.markets.registry import MARKETS

EPS = 1e-9
STAT_COLS = ["shots", "shots_on_target", "corners", "fouls", "yellow_cards", "red_cards", "offsides", "tackles", "xg"]


def score(probability: float, outcome: float) -> tuple[float, float]:
    """(log loss, Brier) of a probability against a 1/0 outcome. Probabilities are clipped away from 0 and 1."""
    p = min(max(probability, EPS), 1 - EPS)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p)), (probability - outcome) ** 2


def build_outcomes(conn: psycopg.Connection) -> int:
    """Upsert the real match record for every finished match that has predictions. Returns rows written."""
    matches = conn.execute(
        "SELECT m.id, m.ft_home, m.ft_away, m.ht_home, m.ht_away FROM matches m "
        "WHERE m.status = 'finished' AND EXISTS (SELECT 1 FROM predictions p WHERE p.match_id = m.id)").fetchall()
    if not matches:
        return 0
    stats = {}
    for match_id, is_home, *vals in conn.execute(
            f"SELECT match_id, is_home, {', '.join(STAT_COLS)} FROM team_match_stats WHERE match_id = ANY(%s)",
            ([m[0] for m in matches],)):
        stats[(match_id, is_home)] = {c: (None if v is None else float(v)) for c, v in zip(STAT_COLS, vals, strict=True)}
    params = []
    for match_id, fh, fa, hh, ha in matches:
        home, away = stats.get((match_id, True)), stats.get((match_id, False))
        record = {"ft_home": fh, "ft_away": fa, "ht_home": hh, "ht_away": ha, "home_stats": home, "away_stats": away}
        coverage = {"ft": True, "ht": hh is not None and ha is not None, "team_stats": home is not None and away is not None}
        params.append((match_id, json.dumps(record), json.dumps(coverage)))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO match_outcomes (match_id, record, coverage) VALUES (%s,%s,%s) "
            "ON CONFLICT (match_id) DO UPDATE SET record = EXCLUDED.record, coverage = EXCLUDED.coverage, built_at = now()",
            params)
    return len(params)


def _decide(row) -> tuple[str, float | None, dict]:
    """(result, outcome_value, observed) for one prediction row."""
    _, market_id, line, selection, _p, run_created, kickoff, status, record = row
    if status == "cancelled":
        return "void", None, {"reason": "match_cancelled"}
    if kickoff is not None and run_created >= kickoff:
        return "void", None, {"reason": "made_after_kickoff"}
    market = MARKETS.get(market_id)
    if market is None:
        return "not_scorable", None, {"reason": "unknown_market"}
    try:
        res = settle_market(market, None if line is None else float(line), selection, record["ft_home"], record["ft_away"])
    except ValueError:
        return "not_scorable", None, {"reason": "unknown_selection"}
    return res["result"], res["outcome_value"], {"ft_home": record["ft_home"], "ft_away": record["ft_away"]}


def settle_predictions(conn: psycopg.Connection) -> Counter:
    """Settle every unsettled prediction on a finished or cancelled match, and re-settle changed results."""
    rows = conn.execute(
        "SELECT p.id, p.market_id, p.line, p.selection, p.probability, r.created_at, m.kickoff, m.status, mo.record "
        "FROM predictions p JOIN prediction_runs r ON r.id = p.run_id JOIN matches m ON m.id = p.match_id "
        "LEFT JOIN match_outcomes mo ON mo.match_id = m.id LEFT JOIN settlements s ON s.prediction_id = p.id "
        "WHERE (m.status = 'cancelled' AND s.prediction_id IS NULL) "
        "   OR (m.status = 'finished' AND mo.match_id IS NOT NULL AND (s.prediction_id IS NULL "
        "       OR (s.observed ->> 'ft_home') IS DISTINCT FROM (mo.record ->> 'ft_home') "
        "       OR (s.observed ->> 'ft_away') IS DISTINCT FROM (mo.record ->> 'ft_away'))) "
        "ORDER BY p.id").fetchall()
    counts: Counter = Counter()
    params = []
    for row in rows:
        result, value, observed = _decide(row)
        log_loss = brier = None
        if value is not None:
            log_loss, brier = score(float(row[4]), value)
        counts[result] += 1
        params.append((row[0], result, value, json.dumps(observed), log_loss, brier))
    if params:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO settlements (prediction_id, result, outcome_value, observed, log_loss, brier) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (prediction_id) DO UPDATE SET result = EXCLUDED.result, "
                "outcome_value = EXCLUDED.outcome_value, observed = EXCLUDED.observed, log_loss = EXCLUDED.log_loss, "
                "brier = EXCLUDED.brier, settled_at = now()",
                params)
    return counts


def settle_all(conn: psycopg.Connection) -> dict:
    built = build_outcomes(conn)
    counts = settle_predictions(conn)
    conn.commit()
    return {"outcomes_built": built, "settled": sum(counts.values()), "by_result": dict(counts)}


if __name__ == "__main__":
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        print(settle_all(c))
