"""Half-hourly job: when a club names its team, store the lineup.

    uv run python -m pitchside.pipeline.lineups

Lineups appear about an hour before kickoff, so the job looks at matches starting within the next few hours. Lineup-aware player prices
(players-0.4.0, see predict_lineup_players) are PAUSED: on the live record they were miscalibrated (audit of 2026-10-25), so the weekly players-0.3.0
prediction is the one the site shows and no new 0.4.0 runs are made. Lineups are still stored so the model can be rebuilt and backtested on them.
Set PRICE_WITH_LINEUPS to switch pricing back on once it passes a backtest. Prints `new_lineups=N` for the workflow, which only exports and deploys when something changed.
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
from pitchside.ingest.lineups import fetch_lineup
from pitchside.leagues import LEAGUES
from pitchside.markets.registry import MARKETS
from pitchside.models.players import LOG_PARAMS, PLAYER_PARAMS
from pitchside.pipeline.weekly import (
    PLAYER_FEATURE_VERSION,
    club_card_model,
    match_player_rows,
)

PRICE_WITH_LINEUPS = False   # paused: the lineup-aware player model was miscalibrated live; lineups are stored, not priced
LINEUP_PLAYER_VERSION = "players-0.4.0"   # players-0.3.0 plus the announced lineup (starters 1, substitutes 0.3, others out); 0.2.0 was the same for the shot-based markets only


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
    """Lineup-aware player prices for these matches (once per match per version): the same markets as the weekly player run, with the announced lineup applied."""
    todo = conn.execute(
        "SELECT m.id, m.league_id, m.home_team_id, m.away_team_id, m.match_date FROM matches m WHERE m.id = ANY(%s) AND NOT EXISTS ("
        "SELECT 1 FROM predictions p JOIN prediction_runs r ON r.id = p.run_id WHERE p.match_id = m.id AND r.run_type = 'weekly' AND r.model_version_id = %s)",
        (match_ids, LINEUP_PLAYER_VERSION)).fetchall()
    if not todo:
        return {"run_id": None, "matches": 0, "predictions": 0}
    seed_markets(conn)
    ensure_model_version(conn, LINEUP_PLAYER_VERSION, "Experimental player layer with the announced lineup applied", {**PLAYER_PARAMS, "log": LOG_PARAMS})
    run_id = create_run(conn, "weekly", LINEUP_PLAYER_VERSION, PLAYER_FEATURE_VERSION, datetime.now(UTC), notes=f"lineup refresh, {len(todo)} matches")
    card_models: dict[str, object] = {}
    total = matches = 0
    for match_id, league_id, home_id, away_id, match_date in todo:
        lineup = {}
        for team_id in (home_id, away_id):
            row = conn.execute("SELECT starters, bench FROM lineups WHERE match_id = %s AND team_id = %s ORDER BY fetched_at DESC LIMIT 1", (match_id, team_id)).fetchone()
            if row is not None:
                lineup[team_id] = (row[0], row[1])
        if league_id not in card_models:
            card_models[league_id] = club_card_model(conn, league_id, match_date)
        rows = match_player_rows(conn, league_id, match_id, home_id, away_id, match_date, card_models[league_id], lineup)
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
        result = predict_lineup_players(c, ids) if ids and PRICE_WITH_LINEUPS else {}
    print(json.dumps({"lineups": ids, "players": result}, default=str))
    print(f"new_lineups={len(ids)}")
