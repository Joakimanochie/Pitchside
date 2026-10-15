"""Hourly job: when a club names its team, store the lineup and re-price the player markets for that match with it.

    uv run python -m pitchside.pipeline.lineups

Lineups appear about an hour before kickoff, so the job looks at matches starting within the next few hours. The lineup-aware player prices are
their own model version (players-0.2.0); the weekly players-0.1.0 prediction stays untouched, and the site shows the newer one when it exists.
Prints `new_lineups=N` for the workflow, which only exports and deploys when something changed.
"""
import argparse
import json
import os
from datetime import UTC, datetime, timedelta

import psycopg

from pitchside.db.markets import seed_markets
from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.db.predictions import (
    create_run,
    ensure_model_version,
    write_context,
    write_predictions,
)
from pitchside.ingest.lineups import fetch_lineup, match_names
from pitchside.leagues import LEAGUES
from pitchside.markets.registry import MARKETS
from pitchside.models.players import PLAYER_PARAMS, apply_lineup
from pitchside.pipeline.weekly import (
    PLAYER_FEATURE_VERSION,
    load_team_rates,
    player_rows,
)

LINEUP_PLAYER_VERSION = "players-0.2.0"   # players-0.1.0 plus the announced lineup (starters 1, substitutes 0.3, others out)


def ingest_lineups(conn: psycopg.Connection, hours: float = 3.0) -> list[int]:
    """Fetch and store the lineup of every match kicking off within `hours` that has none yet. Returns the match ids that got one."""
    now = datetime.now(UTC)
    rows = conn.execute(
        "SELECT m.id, m.league_id, m.home_team_id, m.away_team_id, m.source_ids->>'espn' FROM matches m "
        "WHERE m.status = 'scheduled' AND m.kickoff > %s AND m.kickoff < %s AND m.source_ids ? 'espn' "
        "AND NOT EXISTS (SELECT 1 FROM lineups l WHERE l.match_id = m.id)", (now - timedelta(minutes=10), now + timedelta(hours=hours))).fetchall()
    got = []
    for match_id, league_id, home_id, away_id, event in rows:
        try:
            lineup = fetch_lineup(LEAGUES[league_id].espn_code, event)
        except Exception as e:  # noqa: BLE001 - one match's feed trouble must not stop the others; it is retried next hour
            print(f"lineup fetch failed for match {match_id}: {e}")
            continue
        if lineup is None:
            continue
        for side, team_id in (("home", home_id), ("away", away_id)):
            conn.execute("INSERT INTO lineups (match_id, team_id, formation, starters, bench) VALUES (%s,%s,%s,%s,%s)",
                         (match_id, team_id, lineup[side]["formation"], json.dumps(lineup[side]["starters"]), json.dumps(lineup[side]["bench"])))
        got.append(match_id)
    conn.commit()
    return got


def predict_lineup_players(conn: psycopg.Connection, match_ids: list[int]) -> dict:
    """Lineup-aware player prices for these matches (once per match per version)."""
    todo = [r for r in conn.execute(
        "SELECT m.id, m.home_team_id, m.away_team_id, m.match_date FROM matches m WHERE m.id = ANY(%s) AND NOT EXISTS ("
        "SELECT 1 FROM predictions p JOIN prediction_runs r ON r.id = p.run_id WHERE p.match_id = m.id AND r.run_type = 'weekly' AND r.model_version_id = %s)",
        (match_ids, LINEUP_PLAYER_VERSION)).fetchall()]
    if not todo:
        return {"run_id": None, "matches": 0, "predictions": 0}
    seed_markets(conn)
    ensure_model_version(conn, LINEUP_PLAYER_VERSION, "Experimental player layer with the announced lineup applied", PLAYER_PARAMS)
    run_id = create_run(conn, "weekly", LINEUP_PLAYER_VERSION, PLAYER_FEATURE_VERSION, datetime.now(UTC), notes=f"lineup refresh, {len(todo)} matches")
    total = matches = 0
    for match_id, home_id, away_id, match_date in todo:
        ctx = conn.execute(
            "SELECT c.context FROM prediction_context c JOIN prediction_runs r ON r.id = c.run_id WHERE c.match_id = %s AND r.model_version_id LIKE 'goals-%%' "
            "ORDER BY r.created_at DESC LIMIT 1", (match_id,)).fetchone()
        if ctx is None:
            continue
        latest = dict(conn.execute(
            "SELECT DISTINCT ON (s.player_name) s.player_name, s.team_id FROM shot_events s JOIN matches m ON m.id = s.match_id "
            "WHERE s.team_id IN (%s, %s) AND s.player_name IS NOT NULL ORDER BY s.player_name, m.match_date DESC, m.id DESC", (home_id, away_id)).fetchall())
        rows = []
        for team_id, lam in ((home_id, ctx[0]["lambda_home"]), (away_id, ctx[0]["lambda_away"])):
            rates = load_team_rates(conn, team_id, match_date)
            line = conn.execute("SELECT starters, bench FROM lineups WHERE match_id = %s AND team_id = %s ORDER BY fetched_at DESC LIMIT 1", (match_id, team_id)).fetchone()
            if rates is None or line is None:
                continue
            rates.players = rates.players[[latest.get(name, team_id) == team_id for name in rates.players.index]]
            known = list(rates.players.index)
            rates = apply_lineup(rates, match_names(known, line[0]), match_names(known, line[1]))
            rows.extend(player_rows(rates, float(lam)))
        if rows:
            total += write_predictions(conn, run_id, match_id, rows, MARKETS, {})
            write_context(conn, run_id, match_id, {"players_priced": len({r["selection"] for r in rows}), "lineup": True})
            matches += 1
    conn.commit()
    return {"run_id": run_id, "matches": matches, "predictions": total}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3.0)
    args = ap.parse_args()
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        apply_migrations(c)
        ids = ingest_lineups(c, args.hours)
        result = predict_lineup_players(c, ids) if ids else {}
    print(json.dumps({"lineups": ids, "players": result}, default=str))
    print(f"new_lineups={len(ids)}")
