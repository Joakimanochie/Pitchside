"""Settle stored predictions against real results.

    uv run python -m pitchside.settle.settle

Steps (all idempotent):
  1. build_outcomes: write the real MatchRecord of every finished match that has predictions (scores, half-time score,
     and the goals with their minutes when those were verified).
  2. settle_predictions: settle each prediction with the SAME market rules that priced it, and score it.

Integrity rules:
  - A prediction made at or after kickoff is voided ('made_after_kickoff'): it can never count.
  - A cancelled match voids its predictions. A postponed match stays pending until it is played.
  - If a result is corrected after settling, the affected predictions are re-settled.
  - A market we cannot settle is 'not_scorable', counted separately, never guessed: an unknown market or selection, a
    half-time market without a half-time score, or a goal-order/minute market for a match whose goal minutes were not
    verified. The last kind is re-settled automatically if the minutes are verified later.
Scores: log loss and Brier use the stored probability and the 1/0 outcome on the stake at risk; pushes,
voids and not-scorable predictions get no score.
"""
import json
import math
import os
from collections import Counter, defaultdict

import psycopg

from pitchside.db.migrate import _load_env
from pitchside.markets.base import settle as settle_market
from pitchside.markets.cardtiming import CardTimingMarket, settle_card_timing
from pitchside.markets.counts import stat_value
from pitchside.markets.players import LOG_STATS, PlayerMarket, settle_player
from pitchside.markets.record_base import RecordMarket, settle_record
from pitchside.markets.registry import MARKETS
from pitchside.sim.record import MatchRecord, from_goals, from_scores

EPS = 1e-9
STAT_COLS = ["shots", "shots_on_target", "corners", "fouls", "yellow_cards", "red_cards", "offsides", "tackles", "xg"]
GOAL_TYPES = ("goal", "own_goal", "penalty_goal")


def score(probability: float, outcome: float) -> tuple[float, float]:
    """(log loss, Brier) of a probability against a 1/0 outcome. Probabilities are clipped away from 0 and 1."""
    p = min(max(probability, EPS), 1 - EPS)
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1 - p)), (probability - outcome) ** 2


def build_outcomes(conn: psycopg.Connection) -> int:
    """Upsert the real match record for every finished match that has predictions. Returns rows written."""
    matches = conn.execute(
        "SELECT m.id, m.ft_home, m.ft_away, m.ht_home, m.ht_away, m.source_ids ->> 'goal_minutes' FROM matches m "
        "WHERE m.status = 'finished' AND EXISTS (SELECT 1 FROM predictions p WHERE p.match_id = m.id)").fetchall()
    if not matches:
        return 0
    ids = [m[0] for m in matches]
    stats = {}
    for match_id, is_home, *vals in conn.execute(
            f"SELECT match_id, is_home, {', '.join(STAT_COLS)} FROM team_match_stats WHERE match_id = ANY(%s)", (ids,)):
        stats[(match_id, is_home)] = {c: (None if v is None else float(v)) for c, v in zip(STAT_COLS, vals, strict=True)}
    goals: dict[int, list] = defaultdict(list)
    verified = [m[0] for m in matches if m[5] == "true"]
    for match_id, period, minute, side in conn.execute(
            "SELECT match_id, period, minute, details ->> 'side' FROM match_events WHERE match_id = ANY(%s) "
            "AND source IN ('understat', 'espn') AND event_type = ANY(%s) ORDER BY match_id, period, minute", (verified, list(GOAL_TYPES))):
        goals[match_id].append([side, period, minute])
    players: dict[int, dict] = defaultdict(dict)     # per player counts, only for matches whose shots we hold
    for match_id, name, goals_n, shots_n, sot_n in conn.execute(
            "SELECT match_id, player_name, count(*) FILTER (WHERE result = 'Goal'), count(*), count(*) FILTER (WHERE result IN ('Goal', 'Saved Shot')) "
            "FROM shot_events WHERE match_id = ANY(%s) AND result <> 'Own Goal' AND player_name IS NOT NULL GROUP BY match_id, player_name", (ids,)):
        players[match_id][name] = {"goals": goals_n, "shots": shots_n, "sot": sot_n, "assists": 0}
    for match_id, name, assists_n in conn.execute(
            "SELECT match_id, assist_name, count(*) FROM shot_events WHERE match_id = ANY(%s) AND result = 'Goal' AND assist_name IS NOT NULL "
            "GROUP BY match_id, assist_name", (ids,)):
        players[match_id].setdefault(name, {"goals": 0, "shots": 0, "sot": 0, "assists": 0})["assists"] = assists_n
    logged = [r[0] for r in conn.execute("SELECT id FROM matches WHERE id = ANY(%s) AND source_ids ->> 'espn_log' = 'true'", (ids,))]
    cards: dict[int, list] = {mid: [] for mid in logged}
    for match_id, team_id, home_team_id, period, minute in conn.execute(
            "SELECT c.match_id, c.team_id, m.home_team_id, c.period, c.minute FROM card_events c JOIN matches m ON m.id = c.match_id "
            "WHERE c.match_id = ANY(%s) ORDER BY c.id", (logged,)):
        cards[match_id].append(["home" if team_id == home_team_id else "away", period, minute])
    log_players: dict[int, dict] = {mid: {} for mid in logged}
    for match_id, name, yellow, red, fouls, fouled in conn.execute(
            "SELECT match_id, player_name, yellow, red, fouls_committed, fouls_suffered FROM player_match_log WHERE match_id = ANY(%s)", (logged,)):
        log_players[match_id][name] = {"cards": yellow + red, "fouls": fouls, "fouled": fouled}
    params = []
    for match_id, fh, fa, hh, ha, flag in matches:
        home, away = stats.get((match_id, True)), stats.get((match_id, False))
        has_minutes = flag == "true"
        record = {"ft_home": fh, "ft_away": fa, "ht_home": hh, "ht_away": ha, "home_stats": home, "away_stats": away,
                  "goals": goals[match_id] if has_minutes else None, "players": players.get(match_id),
                  "cards": cards.get(match_id), "log_players": log_players.get(match_id)}
        coverage = {"ft": True, "ht": hh is not None and ha is not None, "team_stats": home is not None and away is not None,
                    "goal_minutes": has_minutes, "player_data": match_id in players, "card_log": match_id in cards}
        params.append((match_id, json.dumps(record), json.dumps(coverage)))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO match_outcomes (match_id, record, coverage) VALUES (%s,%s,%s) "
            "ON CONFLICT (match_id) DO UPDATE SET record = EXCLUDED.record, coverage = EXCLUDED.coverage, built_at = now()",
            params)
    return len(params)


def _match_record(record: dict, coverage: dict) -> MatchRecord:
    ft, ht = (record["ft_home"], record["ft_away"]), (record["ht_home"], record["ht_away"])
    if coverage.get("goal_minutes") and record.get("goals") is not None:
        return from_goals(ft, ht, [tuple(g) for g in record["goals"]])
    return from_scores(ft, ht)


def _decide(row, records: dict) -> tuple[str, float | None, dict]:
    """(result, outcome_value, observed) for one prediction row."""
    _pid, match_id, market_id, line, selection, _p, run_created, kickoff, status, record, coverage = row
    if status == "cancelled":
        return "void", None, {"reason": "match_cancelled"}
    if kickoff is not None and run_created >= kickoff:
        return "void", None, {"reason": "made_after_kickoff"}
    market = MARKETS.get(market_id)
    if market is None:
        return "not_scorable", None, {"reason": "unknown_market"}
    observed = {"ft_home": record["ft_home"], "ft_away": record["ft_away"]}
    coverage = coverage or {}
    try:
        if isinstance(market, CardTimingMarket):   # cards by half, first card: from the cards of the match with their minutes
            if record.get("cards") is None:
                return "not_scorable", None, {"reason": "card_log_missing", **observed}
            res = settle_card_timing(market, None if line is None else float(line), selection, record["cards"])
        elif isinstance(market, PlayerMarket) and market.player_stat in LOG_STATS:   # a player's cards or fouls, from the ESPN match log
            if record.get("log_players") is None:
                return "not_scorable", None, {"reason": "card_log_missing", **observed}
            res = settle_player(market, None if line is None else float(line), selection, record["log_players"])
        elif isinstance(market, PlayerMarket):   # one player's own count, from the shot events
            if record.get("players") is None:
                return "not_scorable", None, {"reason": "player_data_missing", **observed}
            res = settle_player(market, None if line is None else float(line), selection, record["players"])
        elif getattr(market, "stat", None):   # corners, cards, shots: settled from the real team statistics, never from goals
            home_n, away_n = stat_value(market.stat, record.get("home_stats")), stat_value(market.stat, record.get("away_stats"))
            if home_n is None or away_n is None:
                return "not_scorable", None, {"reason": "team_stats_missing", **observed}
            res = settle_market(market, None if line is None else float(line), selection, int(home_n), int(away_n))
        elif isinstance(market, RecordMarket):
            if market.needs_minutes and not coverage.get("goal_minutes"):
                return "not_scorable", None, {"reason": "goal_minutes_unverified", **observed}
            if record["ht_home"] is None or record["ht_away"] is None:
                return "not_scorable", None, {"reason": "no_half_time_score", **observed}
            if match_id not in records:
                records[match_id] = _match_record(record, coverage)
            res = settle_record(market, None if line is None else float(line), selection, records[match_id])
        else:
            res = settle_market(market, None if line is None else float(line), selection, record["ft_home"], record["ft_away"])
    except ValueError:
        return "not_scorable", None, {"reason": "unknown_selection_or_inconsistent_record", **observed}
    return res["result"], res["outcome_value"], observed


def settle_predictions(conn: psycopg.Connection) -> Counter:
    """Settle every unsettled prediction on a finished or cancelled match; re-settle changed results and
    predictions that were waiting for goal minutes which have since been verified."""
    rows = conn.execute(
        "SELECT p.id, p.match_id, p.market_id, p.line, p.selection, p.probability, r.created_at, m.kickoff, m.status, "
        "mo.record, mo.coverage "
        "FROM predictions p JOIN prediction_runs r ON r.id = p.run_id JOIN matches m ON m.id = p.match_id "
        "LEFT JOIN match_outcomes mo ON mo.match_id = m.id LEFT JOIN settlements s ON s.prediction_id = p.id "
        "WHERE (m.status = 'cancelled' AND s.prediction_id IS NULL) "
        "   OR (m.status = 'finished' AND mo.match_id IS NOT NULL AND (s.prediction_id IS NULL "
        "       OR (s.observed ->> 'ft_home') IS DISTINCT FROM (mo.record ->> 'ft_home') "
        "       OR (s.observed ->> 'ft_away') IS DISTINCT FROM (mo.record ->> 'ft_away') "
        "       OR ((s.observed ->> 'reason') = 'goal_minutes_unverified' AND (mo.coverage ->> 'goal_minutes') = 'true') "
        "       OR ((s.observed ->> 'reason') = 'player_data_missing' AND (mo.coverage ->> 'player_data') = 'true') "
        "       OR ((s.observed ->> 'reason') = 'card_log_missing' AND (mo.coverage ->> 'card_log') = 'true') "
        "       OR ((s.observed ->> 'reason') = 'team_stats_missing' AND (mo.coverage ->> 'team_stats') = 'true'))) "
        "ORDER BY p.id").fetchall()
    counts: Counter = Counter()
    records: dict = {}
    params = []
    for row in rows:
        result, value, observed = _decide(row, records)
        log_loss = brier = None
        if value is not None:
            log_loss, brier = score(float(row[5]), value)
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
