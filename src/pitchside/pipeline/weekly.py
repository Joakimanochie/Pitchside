"""Weekly job for one league: ingest new results, load upcoming fixtures, predict, store a frozen run.

    uv run python -m pitchside.pipeline.weekly --league EPL --days 8

Each step is safe to re-run. A second run on the same day with the same model is refused unless --force,
so one set of inputs cannot become two competing track records by accident.
"""
import argparse
import os
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import psycopg

from pitchside.db.markets import seed_markets
from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.db.predictions import (
    create_run,
    ensure_model_version,
    existing_run,
    write_predictions,
)
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.fixtures import fetch_fixtures, upsert_fixtures
from pitchside.ingest.footballdata import current_season, load_seasons
from pitchside.ingest.load_matches import load_footballdata
from pitchside.leagues import LEAGUES
from pitchside.markets.goals import MARKETS, price_match
from pitchside.models.dixon_coles import DixonColes

MODEL_VERSION = "goals-dc-0.1.0"
FEATURE_VERSION = "scores-only-v1"
MODEL_PARAMS = {"half_life_days": 730, "ridge": 2.0, "max_goals": 10}
MIN_HISTORY_MATCHES = 1000  # about 2.5 seasons of one league; below this the strengths are too noisy to publish


class InsufficientHistoryError(RuntimeError):
    """The warehouse holds too few finished matches to fit the model. Backfill with scripts/load_history.py."""


def ingest_results(conn: psycopg.Connection, league_id: str, seasons_back: int = 1) -> dict:
    """Refresh results for the current season and the previous one (late corrections), logged in ingest_log."""
    lg = LEAGUES[league_id]
    end = current_season()
    years = list(range(end - seasons_back, end + 1))
    log_id = conn.execute("INSERT INTO ingest_log (source, league_id, season) VALUES ('footballdata', %s, %s) RETURNING id",
                          (league_id, end)).fetchone()[0]
    try:
        out = load_footballdata(conn, league_id, load_seasons(lg.fd_code, years))
    except Exception as e:
        conn.rollback()
        conn.execute("INSERT INTO ingest_log (source, league_id, season, status, error, finished_at) "
                     "VALUES ('footballdata', %s, %s, 'failed', %s, now())", (league_id, end, str(e)[:500]))
        conn.commit()
        raise
    conn.execute("UPDATE ingest_log SET status = 'ok', rows_written = %s, finished_at = now() WHERE id = %s",
                 (out["matches"], log_id))
    conn.commit()
    return out


def plan_fixtures(conn: psycopg.Connection, league_id: str, start: date, days: int) -> dict:
    out = upsert_fixtures(conn, league_id, fetch_fixtures(LEAGUES[league_id].espn_code, start, days))
    conn.commit()
    return out


def load_history(conn: psycopg.Connection, league_id: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT m.season, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away "
        "FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'finished' ORDER BY m.match_date", (league_id,)).fetchall()
    return pd.DataFrame(rows, columns=["season", "match_date", "home", "away", "ft_home", "ft_away"])


def predict_week(conn: psycopg.Connection, league_id: str, as_of: date, days: int, force: bool = False) -> dict:
    """Fit on matches before `as_of`, price every family A market for fixtures kicking off in the next `days` days."""
    now = datetime.now(UTC)
    fixtures = conn.execute(
        "SELECT m.id, m.kickoff, th.canonical_name, ta.canonical_name FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'scheduled' AND m.match_date >= %s AND m.match_date < %s "
        "AND (m.kickoff IS NULL OR m.kickoff > %s) ORDER BY m.kickoff, m.id",
        (league_id, as_of, as_of + timedelta(days=days), now)).fetchall()
    if not fixtures:
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "no upcoming fixtures in the window"}

    cutoff = datetime.combine(as_of, time.min, tzinfo=UTC)
    if not force and existing_run(conn, "weekly", MODEL_VERSION, cutoff):
        return {"run_id": None, "matches": len(fixtures), "predictions": 0, "skipped": "run already exists (use --force)"}

    history = load_history(conn, league_id)
    if len(history) < MIN_HISTORY_MATCHES:
        raise InsufficientHistoryError(
            f"{league_id}: only {len(history)} finished matches in the database, need at least {MIN_HISTORY_MATCHES}. "
            f"Run: uv run python scripts/load_history.py {league_id}")
    model = DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"]).fit(history, as_of=as_of)
    seed_markets(conn)
    ensure_model_version(conn, MODEL_VERSION, "Dixon-Coles goals model, scores only", MODEL_PARAMS)
    run_id = create_run(conn, "weekly", MODEL_VERSION, FEATURE_VERSION, cutoff,
                        notes=f"{league_id}, {len(fixtures)} fixtures, window {as_of} + {days} days")
    total = 0
    for match_id, kickoff, home, away in fixtures:
        lam_h, lam_a = model.lambdas(home, away)
        why = {"lambda_home": round(lam_h, 3), "lambda_away": round(lam_a, 3), "matches_used": model.n_matches,
               "home_known": model.known(home), "away_known": model.known(away),
               "kickoff": kickoff.isoformat() if kickoff else None}
        total += write_predictions(conn, run_id, match_id, price_match(model.score_matrix(home, away)), MARKETS, why)
    conn.commit()
    return {"run_id": run_id, "matches": len(fixtures), "predictions": total}


def run(conn: psycopg.Connection, league_id: str, days: int = 8, force: bool = False, ingest: bool = True) -> dict:
    apply_migrations(conn)
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    report = {}
    if ingest:
        report["results"] = ingest_results(conn, league_id)
    today = datetime.now(UTC).date()
    report["fixtures"] = plan_fixtures(conn, league_id, today, days)
    report["predictions"] = predict_week(conn, league_id, today, days, force)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="EPL", choices=sorted(LEAGUES))
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-ingest", action="store_true")
    args = ap.parse_args()
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        print(run(c, args.league, args.days, args.force, not args.no_ingest))
