"""Weekly job for one league: ingest new results, load upcoming fixtures, predict, store a frozen run.

    uv run python -m pitchside.pipeline.weekly --league EPL --days 8

Each step is safe to re-run. A match gets exactly one official weekly prediction per model version (made the
first time it enters the window), so a daily schedule cannot create competing predictions. --force overrides.
"""
import argparse
import json
import os
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pandas as pd
import psycopg

from pitchside.confidence import RATED_LEAGUES
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
from pitchside.markets.base import price as price_market
from pitchside.markets.counts import MARKETS as COUNT_MARKETS
from pitchside.markets.counts import STATS as COUNT_STATS
from pitchside.markets.goals import price_match
from pitchside.markets.players import MARKETS as PLAYER_MARKETS
from pitchside.markets.registry import MARKETS
from pitchside.models.counts import COUNT_PARAMS, CountModel
from pitchside.models.dixon_coles import DixonColes
from pitchside.models.players import (
    PLAYER_PARAMS,
    TeamRates,
    at_least,
    goal_shares,
    team_rates,
)
from pitchside.odds.footballdata_fixtures import FootballDataFixtures
from pitchside.odds.store import store_odds
from pitchside.pipeline.goal_minutes import ingest_goal_minutes
from pitchside.settle.settle import settle_all
from pitchside.sim.inputs import fit_split_table, fit_time_profile
from pitchside.sim.pricing import price_all

MODEL_VERSION = "goals-dc-0.3.0"   # 0.1.0 priced family A only; 0.2.0 adds the half/goal-timing simulator (B-E); 0.3.0 follows the recent scoring level and compresses totals
FEATURE_VERSION = "scores-only-v1"
COUNT_MODEL_VERSION = "counts-nb-0.1.0"   # corners, cards, shots and shots on target: its own model line, so adding it never reopens goals predictions
COUNT_FEATURE_VERSION = "team-stats-v1"
PLAYER_MODEL_VERSION = "players-0.1.0"   # experimental: anytime goalscorer, shots, shots on target, assists per player; no lineups
PLAYER_FEATURE_VERSION = "understat-shots-v1"
MODEL_PARAMS = {"half_life_days": 730, "ridge": 2.0, "level_window_days": 240, "level_shrink": 60, "total_compression": 0.7, "max_goals": 10, "n_sims": 50_000, "split": "empirical-table", "timing": "pooled-profile"}
N_SIMS = 50_000
def make_model() -> DixonColes:
    """The goals model with the frozen production settings."""
    return DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"], level_window_days=MODEL_PARAMS["level_window_days"],
                      level_shrink=MODEL_PARAMS["level_shrink"], total_compression=MODEL_PARAMS["total_compression"])


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
    model = make_model().fit(history, as_of=as_of)
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


def load_count_history(conn: psycopg.Connection, league_id: str) -> pd.DataFrame:
    """Finished matches with both teams' corners, cards (yellow plus red), shots and shots on target."""
    rows = conn.execute(
        "SELECT m.match_date, th.canonical_name, ta.canonical_name, hs.corners, a_s.corners, hs.yellow_cards + hs.red_cards, a_s.yellow_cards + a_s.red_cards, "
        "hs.shots, a_s.shots, hs.shots_on_target, a_s.shots_on_target "
        "FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "JOIN team_match_stats hs ON hs.match_id = m.id AND hs.is_home JOIN team_match_stats a_s ON a_s.match_id = m.id AND NOT a_s.is_home "
        "WHERE m.league_id = %s AND m.status = 'finished' ORDER BY m.match_date", (league_id,)).fetchall()
    cols = ["match_date", "home", "away", "corners_h", "corners_a", "cards_h", "cards_a", "shots_h", "shots_a", "sot_h", "sot_a"]
    return pd.DataFrame(rows, columns=cols).astype({c: float for c in cols[3:]})


def predict_counts(conn: psycopg.Connection, league_id: str, as_of: date, days: int, force: bool = False) -> dict:
    """Price corners, cards, shots and shots-on-target markets for fixtures in the next `days` days, one run per match per count-model version."""
    now = datetime.now(UTC)
    not_yet = "" if force else ("AND NOT EXISTS (SELECT 1 FROM predictions p JOIN prediction_runs r ON r.id = p.run_id "
                                "WHERE p.match_id = m.id AND r.run_type = 'weekly' AND r.model_version_id = %s) ")
    params = [league_id, as_of, as_of + timedelta(days=days), now] + ([] if force else [COUNT_MODEL_VERSION])
    fixtures = conn.execute(
        "SELECT m.id, m.kickoff, th.canonical_name, ta.canonical_name FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'scheduled' AND m.match_date >= %s AND m.match_date < %s "
        "AND (m.kickoff IS NULL OR m.kickoff > %s) " + not_yet + "ORDER BY m.kickoff, m.id", params).fetchall()
    if not fixtures:
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "no upcoming fixtures in the window"}
    history = load_count_history(conn, league_id)
    if len(history) < MIN_HISTORY_MATCHES:
        raise InsufficientHistoryError(f"{league_id}: only {len(history)} matches with team statistics, need at least {MIN_HISTORY_MATCHES}")
    models = {}
    for stat, cfg in COUNT_STATS.items():
        data = history.assign(count_home=history[f"{stat}_h"], count_away=history[f"{stat}_a"])
        models[stat] = CountModel(half_life_days=COUNT_PARAMS[stat]["half_life_days"], ridge=COUNT_PARAMS[stat]["ridge"], max_count=cfg["max"]).fit(data, as_of=as_of)
    seed_markets(conn)
    ensure_model_version(conn, COUNT_MODEL_VERSION, "Negative binomial count model per statistic: corners, cards, shots, shots on target",
                         {"stats": list(COUNT_STATS), **{s: COUNT_PARAMS[s] for s in COUNT_STATS}})
    cutoff = datetime.combine(as_of, time.min, tzinfo=UTC)
    run_id = create_run(conn, "weekly", COUNT_MODEL_VERSION, COUNT_FEATURE_VERSION, cutoff,
                        notes=f"{league_id}, {len(fixtures)} fixtures, window {as_of} + {days} days, counts")
    total = 0
    for match_id, kickoff, home, away in fixtures:
        rows, context = [], {"kickoff": kickoff.isoformat() if kickoff else None, "matches_used": models["corners"].n_matches}
        for stat, model in models.items():
            matrix = model.count_matrix(home, away)
            for market in (m for m in COUNT_MARKETS.values() if m.stat == stat):
                for line in market.lines if market.has_line else (None,):
                    rows.extend(price_market(market, line, matrix))
            mh, ma = model.means(home, away)
            context[stat] = {"mean_home": round(mh, 2), "mean_away": round(ma, 2), "dispersion": round(model.dispersion, 3)}
        total += write_predictions(conn, run_id, match_id, rows, MARKETS, {})
        write_context(conn, run_id, match_id, context)
    conn.commit()
    return {"run_id": run_id, "matches": len(fixtures), "predictions": total}


def load_team_rates(conn: psycopg.Connection, team_id: int, before: date) -> TeamRates | None:
    """Recency-weighted shot, goal and assist totals over the club's last matches that have shot data. None when it has too few."""
    ids = [r[0] for r in conn.execute(
        "SELECT m.id FROM matches m WHERE m.status = 'finished' AND m.match_date < %s AND (m.home_team_id = %s OR m.away_team_id = %s) "
        "AND EXISTS (SELECT 1 FROM shot_events s WHERE s.match_id = m.id) ORDER BY m.match_date DESC LIMIT %s",
        (before, team_id, team_id, PLAYER_PARAMS["n_matches"]))]
    if len(ids) < 8:
        return None
    rows = conn.execute("SELECT match_id, player_name, assist_name, xg, result FROM shot_events WHERE match_id = ANY(%s) AND team_id = %s", (ids, team_id)).fetchall()
    shots = pd.DataFrame(rows, columns=["match_id", "player", "assist", "xg", "result"]).astype({"xg": float}, errors="ignore")
    return team_rates(shots, ids, half_life_matches=PLAYER_PARAMS["half_life_matches"])


def player_rows(rates: TeamRates, club_goals: float) -> list[dict]:
    """Probabilities for one club's players in a coming match (see models/players.py). Only players with a meaningful chance are priced."""
    out = []

    def add(market, line, player, p):
        out.append({"market_id": market, "line": line, "selection": player, "probability": float(p), "p_win": float(p), "p_lose": float(1 - p), "p_push": 0.0})

    p, w = rates.players, rates.weight
    goal = 1 - np.exp(-PLAYER_PARAMS["goal_scale"] * club_goals * goal_shares(rates, PLAYER_PARAMS["xg_weight"]))
    for player, prob in goal.sort_values(ascending=False).head(12).items():
        if prob >= 0.02:
            add("player_anytime_goal", None, player, prob)
    for stat, column, market, lines in (("assists", "assists", "player_assist", (None,)), ("shots", "shots", "player_shots", PLAYER_MARKETS["player_shots"].lines),
                                        ("sot", "sot", "player_sot", PLAYER_MARKETS["player_sot"].lines)):
        cfg = PLAYER_PARAMS[stat]
        mean = cfg["scale"] * p[column] / w
        for player in mean.sort_values(ascending=False).head(10 if stat != "assists" else 8).index:
            for line in lines:
                prob = at_least(float(mean[player]), 1 if line is None else int(line + 0.5), cfg["dispersion"])
                if prob >= (0.03 if stat == "assists" else 0.02):
                    add(market, line, player, prob)
    return out


def predict_players(conn: psycopg.Connection, league_id: str, as_of: date, days: int, force: bool = False) -> dict:
    """Price player markets (experimental) for fixtures in the next `days` days from each club's recent shot data and the goals model's expected goals."""
    if league_id not in RATED_LEAGUES:      # shot data (Understat) covers only the five rated leagues; a promoted or relegated club's old shots would be stale
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "no player data for this league"}
    now = datetime.now(UTC)
    not_yet = "" if force else ("AND NOT EXISTS (SELECT 1 FROM predictions p JOIN prediction_runs r ON r.id = p.run_id "
                                "WHERE p.match_id = m.id AND r.run_type = 'weekly' AND r.model_version_id = %s) ")
    params = [league_id, as_of, as_of + timedelta(days=days), now] + ([] if force else [PLAYER_MODEL_VERSION])
    fixtures = conn.execute(
        "SELECT m.id, m.kickoff, m.home_team_id, m.away_team_id FROM matches m WHERE m.league_id = %s AND m.status = 'scheduled' AND m.match_date >= %s "
        "AND m.match_date < %s AND (m.kickoff IS NULL OR m.kickoff > %s) " + not_yet + "ORDER BY m.kickoff, m.id", params).fetchall()
    if not fixtures:
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "no upcoming fixtures in the window"}
    seed_markets(conn)
    ensure_model_version(conn, PLAYER_MODEL_VERSION, "Experimental player layer: recent share of club goals, shots, shots on target and assists", PLAYER_PARAMS)
    run_id = create_run(conn, "weekly", PLAYER_MODEL_VERSION, PLAYER_FEATURE_VERSION, datetime.combine(as_of, time.min, tzinfo=UTC),
                        notes=f"{league_id}, {len(fixtures)} fixtures, window {as_of} + {days} days, players")
    total = matches = 0
    for match_id, _kickoff, home_id, away_id in fixtures:
        ctx = conn.execute(
            "SELECT c.context FROM prediction_context c JOIN prediction_runs r ON r.id = c.run_id WHERE c.match_id = %s AND r.model_version_id LIKE 'goals-%%' "
            "ORDER BY r.created_at DESC LIMIT 1", (match_id,)).fetchone()
        if ctx is None:                 # the club goals come from the goals model: no goals prediction, no player prices
            continue
        rows = []
        # a player who moved between these two clubs has shots for both: he belongs to the club he shot for most recently
        latest = dict(conn.execute(
            "SELECT DISTINCT ON (s.player_name) s.player_name, s.team_id FROM shot_events s JOIN matches m ON m.id = s.match_id "
            "WHERE s.team_id IN (%s, %s) AND s.player_name IS NOT NULL ORDER BY s.player_name, m.match_date DESC, m.id DESC", (home_id, away_id)).fetchall())
        for team_id, lam in ((home_id, ctx[0]["lambda_home"]), (away_id, ctx[0]["lambda_away"])):
            rates = load_team_rates(conn, team_id, as_of)
            if rates is not None:
                rates.players = rates.players[[latest.get(name, team_id) == team_id for name in rates.players.index]]
                rows.extend(player_rows(rates, float(lam)))
        if rows:
            total += write_predictions(conn, run_id, match_id, rows, MARKETS, {})
            write_context(conn, run_id, match_id, {"players_priced": len({r["selection"] for r in rows}), "params": "see model version"})
            matches += 1
    conn.commit()
    return {"run_id": run_id, "matches": matches, "predictions": total}


def ingest_odds(conn: psycopg.Connection) -> dict:
    """Snapshot the pre-match bookmaker prices published for the coming fixtures (comparison only; never a model input)."""
    result = store_odds(conn, FootballDataFixtures())
    conn.commit()
    return {k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}


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
        attempt(lid, "counts", predict_counts, conn, lid, today, days, force)
        attempt(lid, "players", predict_players, conn, lid, today, days, force)
    attempt("odds", "all", ingest_odds, conn)  # after fixtures exist, so the prices find their matches; one file covers every league
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
