"""Weekly job for one league: ingest new results, load upcoming fixtures, predict, store a frozen run.

    uv run python -m pitchside.pipeline.weekly --league EPL --days 8

Each step is safe to re-run. A match gets exactly one official weekly prediction per model version (made the
first time it enters the window), so a daily schedule cannot create competing predictions. --force overrides.
"""
import argparse
import json
import os
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import psycopg

from pitchside.db.markets import seed_markets
from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.db.predictions import (
    create_run,
    ensure_model_version,
    write_context,
    write_predictions,
)
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.fixtures import fetch_fixtures, upsert_fixtures
from pitchside.ingest.footballdata import current_season, load_seasons
from pitchside.ingest.load_matches import load_footballdata
from pitchside.leagues import LEAGUES
from pitchside.markets.goals import price_match
from pitchside.markets.registry import MARKETS
from pitchside.models.dixon_coles import DixonColes
from pitchside.pipeline.goal_minutes import ingest_goal_minutes
from pitchside.settle.settle import settle_all
from pitchside.sim.inputs import fit_split_table, fit_time_profile
from pitchside.sim.pricing import price_all

MODEL_VERSION = "goals-dc-0.2.0"   # 0.1.0 priced family A only; 0.2.0 adds the half/goal-timing simulator (families B-E)
FEATURE_VERSION = "scores-only-v1"
MODEL_PARAMS = {"half_life_days": 730, "ridge": 2.0, "max_goals": 10, "n_sims": 50_000, "split": "empirical-table", "timing": "pooled-profile"}
N_SIMS = 50_000
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


def predict_week(conn: psycopg.Connection, league_id: str, as_of: date, days: int, force: bool = False,
                 n_sims: int = N_SIMS) -> dict:
    """Fit on matches before `as_of`, price every market for fixtures kicking off in the next `days` days.
    Family A comes exactly from the scoreline matrix; families B-E from `n_sims` simulated matches."""
    now = datetime.now(UTC)
    # One official weekly prediction per match per model version: a match already predicted is not predicted again,
    # so a daily schedule cannot pile up competing predictions for the same match. --force bypasses this.
    not_yet_predicted = "" if force else (
        "AND NOT EXISTS (SELECT 1 FROM predictions p JOIN prediction_runs r ON r.id = p.run_id "
        "WHERE p.match_id = m.id AND r.run_type = 'weekly' AND r.model_version_id = %s) ")
    params = [league_id, as_of, as_of + timedelta(days=days), now] + ([] if force else [MODEL_VERSION])
    fixtures = conn.execute(
        "SELECT m.id, m.kickoff, th.canonical_name, ta.canonical_name FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'scheduled' AND m.match_date >= %s AND m.match_date < %s "
        "AND (m.kickoff IS NULL OR m.kickoff > %s) " + not_yet_predicted + "ORDER BY m.kickoff, m.id", params).fetchall()
    if not fixtures:
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "no upcoming fixtures in the window"}

    cutoff = datetime.combine(as_of, time.min, tzinfo=UTC)

    history = load_history(conn, league_id)
    if len(history) < MIN_HISTORY_MATCHES:
        raise InsufficientHistoryError(
            f"{league_id}: only {len(history)} finished matches in the database, need at least {MIN_HISTORY_MATCHES}. "
            f"Run: uv run python scripts/load_history.py {league_id}")
    model = DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"]).fit(history, as_of=as_of)
    split = fit_split_table(conn)
    profile = fit_time_profile(conn)       # None when too few verified goal minutes exist: then only family A is priced
    families = "ABCDE" if profile is not None else "A"
    seed_markets(conn)
    ensure_model_version(conn, MODEL_VERSION, "Dixon-Coles goals model plus half-time split and goal-timing simulator", MODEL_PARAMS)
    run_id = create_run(conn, "weekly", MODEL_VERSION, FEATURE_VERSION, cutoff,
                        notes=f"{league_id}, {len(fixtures)} fixtures, window {as_of} + {days} days, families {families}")
    total = 0
    for match_id, kickoff, home, away in fixtures:
        scoreline = model.score_matrix(home, away)
        rows = price_all(scoreline, split, profile, n_sims, seed=match_id) if profile is not None else price_match(scoreline)
        lam_h, lam_a = model.lambdas(home, away)
        context = {"lambda_home": round(lam_h, 3), "lambda_away": round(lam_a, 3), "matches_used": model.n_matches,
                   "home_known": model.known(home), "away_known": model.known(away),
                   "kickoff": kickoff.isoformat() if kickoff else None, "families": families,
                   "n_sims": n_sims if profile is not None else None, "first_half_goal_share": round(split.p1, 4)}
        total += write_predictions(conn, run_id, match_id, rows, MARKETS, {})
        write_context(conn, run_id, match_id, context)
    conn.commit()
    return {"run_id": run_id, "matches": len(fixtures), "predictions": total, "families": families}


def run_leagues(conn: psycopg.Connection, league_ids: list[str], days: int = 8, force: bool = False,
                ingest: bool = True) -> tuple[dict, dict]:
    """Run the pipeline for several leagues. One league failing never stops the others.
    Returns (report, errors); errors maps league (or 'settle') to the failure message."""
    apply_migrations(conn)
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    report: dict = {lid: {} for lid in league_ids}
    errors: dict = {}

    def attempt(key: str, section: str, fn, *args):
        try:
            result = fn(*args)
            if key in report:
                report[key][section] = result
            else:
                report[key] = result
        except Exception as e:  # noqa: BLE001 - isolate failures, report them, keep going
            conn.rollback()
            errors[f"{key}/{section}"] = f"{type(e).__name__}: {e}"

    if ingest:
        for lid in league_ids:
            attempt(lid, "results", ingest_results, conn, lid)
        for lid in league_ids:      # goal minutes for matches that just finished, before settling needs them
            attempt(lid, "goal_minutes", ingest_goal_minutes, conn, lid)
    attempt("settle", "all", settle_all, conn)  # one global pass: settles every league's finished matches
    today = datetime.now(UTC).date()
    for lid in league_ids:
        attempt(lid, "fixtures", plan_fixtures, conn, lid, today, days)
        attempt(lid, "predictions", predict_week, conn, lid, today, days, force)
    return report, errors


def parse_leagues(values: list[str]) -> list[str]:
    ids = sorted(LEAGUES) if [v.upper() for v in values] == ["ALL"] else [v.upper() for v in values]
    unknown = [i for i in ids if i not in LEAGUES]
    if unknown:
        raise SystemExit(f"unknown league(s): {unknown}; choose from {sorted(LEAGUES)} or ALL")
    return ids


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", nargs="+", default=["ALL"], help="league ids (EPL LALIGA ...) or ALL")
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-ingest", action="store_true")
    args = ap.parse_args()
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        rep, errs = run_leagues(c, parse_leagues(args.league), args.days, args.force, not args.no_ingest)
    print(json.dumps(rep, indent=1, default=str))
    if errs:
        failures = [f"  {k}: {v}" for k, v in errs.items()]
        print("FAILURES:", *failures, sep="\n")
        raise SystemExit(1)
