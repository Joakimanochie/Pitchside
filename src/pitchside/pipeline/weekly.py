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

from pitchside.accas import build_slips
from pitchside.confidence import RATED_LEAGUES
from pitchside.db.cup_teams import CupTeams
from pitchside.db.markets import seed_markets
from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.db.predictions import (
    create_run,
    ensure_model_version,
    write_context,
    write_predictions,
)
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.espn_cups import (
    fetch_finished,
    fetch_summary,
    parse_result,
    season_of,
    store_result,
)
from pitchside.ingest.espn_log import ingest_log
from pitchside.ingest.fixtures import fetch_fixtures, upsert_fixtures
from pitchside.ingest.footballdata import current_season, load_seasons
from pitchside.ingest.lineups import match_names
from pitchside.ingest.load_matches import load_footballdata
from pitchside.leagues import LEAGUES
from pitchside.markets.base import price as price_market
from pitchside.markets.counts import MARKETS as COUNT_MARKETS
from pitchside.markets.counts import STATS as COUNT_STATS
from pitchside.markets.goals import price_match
from pitchside.markets.players import MARKETS as PLAYER_MARKETS
from pitchside.markets.registry import CARD_TIMING_MARKETS, MARKETS
from pitchside.models.cardtiming import CardProfile, price_card_timing
from pitchside.models.counts import COUNT_PARAMS, CountModel
from pitchside.models.dixon_coles import DixonColes
from pitchside.models.players import (
    LOG_PARAMS,
    PLAYER_PARAMS,
    LogRates,
    TeamRates,
    apply_lineup,
    apply_lineup_log,
    at_least,
    goal_shares,
    log_rates,
    shrunk_card_rate,
    team_rates,
)
from pitchside.models.pyramid import PyramidDixonColes
from pitchside.odds.footballdata_fixtures import FootballDataFixtures
from pitchside.odds.store import store_odds
from pitchside.pipeline.goal_minutes import ingest_goal_minutes
from pitchside.settle.settle import settle_all
from pitchside.sim.inputs import fit_split_table, fit_time_profile
from pitchside.sim.pricing import price_all

MODEL_VERSION = "goals-dc-0.3.0"   # 0.1.0 priced family A only; 0.2.0 adds the half/goal-timing simulator (B-E); 0.3.0 follows the recent scoring level and compresses totals
CUP_MODEL_VERSION = "goalscup-dc-0.1.0"   # the Champions League and Europa League: the same Dixon-Coles goals model, but clubs rated across leagues (models/pyramid.py); its own line so it never mixes with the domestic leagues
FEATURE_VERSION = "scores-only-v1"
COUNT_MODEL_VERSION = "counts-nb-0.1.0"   # corners, cards, shots and shots on target: its own model line, so adding it never reopens goals predictions
COUNT_FEATURE_VERSION = "team-stats-v1"
PLAYER_MODEL_VERSION = "players-0.3.0"   # experimental: goals, shots, shots on target, assists, cards and fouls per player; no lineups (0.1.0 had no cards or fouls)
PLAYER_FEATURE_VERSION = "understat-shots+espn-log-v1"
CARD_TIMING_VERSION = "cardtime-0.1.0"   # cards by half, first card, card by a minute: from the cards count model plus the share and timing of past cards
CARD_TIMING_FEATURE_VERSION = "team-stats+espn-log-v1"
MODEL_PARAMS = {"half_life_days": 730, "ridge": 2.0, "level_window_days": 240, "level_shrink": 60, "total_compression": 0.7, "max_goals": 10, "n_sims": 50_000, "split": "empirical-table", "timing": "pooled-profile"}
N_SIMS = 50_000
def make_model() -> DixonColes:
    """The goals model with the frozen production settings."""
    return DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"], level_window_days=MODEL_PARAMS["level_window_days"],
                      level_shrink=MODEL_PARAMS["level_shrink"], total_compression=MODEL_PARAMS["total_compression"])


MIN_HISTORY_MATCHES = 1000  # about 2.5 seasons of one league; below this the strengths are too noisy to publish
MIN_CUP_STATS_MATCHES = 500    # a cup has about 190 matches a season and few clubs repeat; the count model's heavy shrinkage carries the clubs with little data


class InsufficientHistoryError(RuntimeError):
    """The warehouse holds too few finished matches to fit the model. Backfill with scripts/load_history.py."""


def ingest_results(conn: psycopg.Connection, league_id: str, seasons_back: int = 1) -> dict:
    """Refresh results for the current season and the previous one (late corrections), logged in ingest_log. The European cups have no football-data file: see ingest_cup_results."""
    lg = LEAGUES[league_id]
    if lg.cup:
        return ingest_cup_results(conn, league_id)
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


def ingest_cup_results(conn: psycopg.Connection, league_id: str, days_back: int = 4) -> dict:
    """Finished cup matches of the last few days, from ESPN: the 90-minute score, half-time score and team statistics (extra time and penalties are left out)."""
    lg = LEAGUES[league_id]
    teams = CupTeams(conn)
    today = datetime.now(UTC).date()
    stored = skipped = 0
    for i in range(days_back):
        for event in fetch_finished(lg.espn_code, today - timedelta(days=i)):
            local = event["kickoff"]
            home, away = teams.resolve("espn", event["home"]), teams.resolve("espn", event["away"])
            parsed = parse_result(fetch_summary(lg.espn_code, event["id"]), event["beyond_90"])
            if parsed is None:
                skipped += 1
                continue
            store_result(conn, league_id, season_of(local.date()), event, parsed, home, away)
            stored += 1
    conn.commit()
    return {"matches": stored, "skipped": skipped, "new_clubs": teams.created}


def plan_fixtures(conn: psycopg.Connection, league_id: str, start: date, days: int) -> dict:
    fixtures = fetch_fixtures(LEAGUES[league_id].espn_code, start, days)
    ids = None
    if LEAGUES[league_id].cup:
        teams = CupTeams(conn)
        ids = {n: teams.resolve("espn", n) for f in fixtures for n in (f["home"], f["away"])}
    out = upsert_fixtures(conn, league_id, fixtures, ids)
    conn.commit()
    return out


def load_history(conn: psycopg.Connection, league_id: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT m.season, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away "
        "FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'finished' ORDER BY m.match_date", (league_id,)).fetchall()
    return pd.DataFrame(rows, columns=["season", "match_date", "home", "away", "ft_home", "ft_away"])


DOMESTIC_LEAGUES = ("EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "CHAMP")


def load_cross_history(conn: psycopg.Connection, comp: str) -> pd.DataFrame:
    """Domestic matches of the six leagues and the cup matches together, one row each, with the competition in `league` (the history a cup model is fitted on)."""
    rows = conn.execute(
        "SELECT m.league_id, m.season, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away "
        "FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.status = 'finished' AND m.ft_home IS NOT NULL AND m.league_id = ANY(%s) ORDER BY m.match_date, m.id", (list(DOMESTIC_LEAGUES) + ["CL", "EL"],)).fetchall()
    return pd.DataFrame(rows, columns=["league", "season", "match_date", "home", "away", "ft_home", "ft_away"])


def make_cross_model(comp: str, history: pd.DataFrame, as_of: date) -> PyramidDixonColes:
    """The goals model for a cup: every club rated on one scale from its domestic and European matches together (models/pyramid.py). A club of none of the six leagues
    belongs to the shared group "OTHER", and a club never seen is rated as an average member of it."""
    domestic = history[history["league"].isin(DOMESTIC_LEAGUES)]
    group = {}
    for r in domestic[domestic["match_date"] < as_of].sort_values("match_date", kind="stable").itertuples(index=False):
        group[r.home] = r.league
        group[r.away] = r.league
    return PyramidDixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"], level_window_days=MODEL_PARAMS["level_window_days"],
                             level_shrink=MODEL_PARAMS["level_shrink"], total_compression=MODEL_PARAMS["total_compression"],
                             target_league=comp, team_group=group, ref_group="EPL").fit(history, as_of=as_of)


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
    params = [league_id, as_of, as_of + timedelta(days=days), now] + ([] if force else [CUP_MODEL_VERSION if LEAGUES[league_id].cup else MODEL_VERSION])
    fixtures = conn.execute(
        "SELECT m.id, m.kickoff, th.canonical_name, ta.canonical_name FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'scheduled' AND m.match_date >= %s AND m.match_date < %s "
        "AND (m.kickoff IS NULL OR m.kickoff > %s) " + not_yet_predicted + "ORDER BY m.kickoff, m.id", params).fetchall()
    if not fixtures:
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "no upcoming fixtures in the window"}

    cutoff = datetime.combine(as_of, time.min, tzinfo=UTC)

    cup = LEAGUES[league_id].cup
    history = load_cross_history(conn, league_id) if cup else load_history(conn, league_id)
    if len(history) < MIN_HISTORY_MATCHES:
        raise InsufficientHistoryError(
            f"{league_id}: only {len(history)} finished matches in the database, need at least {MIN_HISTORY_MATCHES}. "
            f"Run: uv run python scripts/load_history.py {league_id}")
    model = make_cross_model(league_id, history, as_of) if cup else make_model().fit(history, as_of=as_of)
    split = fit_split_table(conn)
    profile = fit_time_profile(conn)       # None when too few verified goal minutes exist: then only family A is priced
    families = "ABCDE" if profile is not None else "A"
    seed_markets(conn)
    version_id = CUP_MODEL_VERSION if cup else MODEL_VERSION
    ensure_model_version(conn, version_id, "Dixon-Coles goals model plus half-time split and goal-timing simulator" + (", clubs rated across leagues" if cup else ""),
                         {**MODEL_PARAMS, "cross_league": True} if cup else MODEL_PARAMS)
    run_id = create_run(conn, "weekly", version_id, FEATURE_VERSION, cutoff,
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
    need = MIN_CUP_STATS_MATCHES if LEAGUES[league_id].cup else MIN_HISTORY_MATCHES
    if len(history) < need:
        raise InsufficientHistoryError(f"{league_id}: only {len(history)} matches with team statistics, need at least {need}")
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


def fit_card_profile(conn: psycopg.Connection) -> CardProfile | None:
    """First-half share and minute profile of cards from every verified match log (all leagues pooled). None when there are too few cards."""
    rows = conn.execute("SELECT c.period, c.minute FROM card_events c JOIN matches m ON m.id = c.match_id WHERE m.source_ids ->> 'espn_log' = 'true'").fetchall()
    if len(rows) < 500:
        return None
    a = np.array(rows, dtype=int)
    return CardProfile.fit(a[:, 0], a[:, 1])


def predict_card_timing(conn: psycopg.Connection, league_id: str, as_of: date, days: int, force: bool = False) -> dict:
    """Price the card timing markets for fixtures in the next `days` days, once per match per model version."""
    now = datetime.now(UTC)
    not_yet = "" if force else ("AND NOT EXISTS (SELECT 1 FROM predictions p JOIN prediction_runs r ON r.id = p.run_id "
                                "WHERE p.match_id = m.id AND r.run_type = 'weekly' AND r.model_version_id = %s) ")
    params = [league_id, as_of, as_of + timedelta(days=days), now] + ([] if force else [CARD_TIMING_VERSION])
    fixtures = conn.execute(
        "SELECT m.id, th.canonical_name, ta.canonical_name FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'scheduled' AND m.match_date >= %s AND m.match_date < %s AND (m.kickoff IS NULL OR m.kickoff > %s) " + not_yet
        + "ORDER BY m.kickoff, m.id", params).fetchall()
    if not fixtures:
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "no upcoming fixtures in the window"}
    profile = fit_card_profile(conn)
    model = club_card_model(conn, league_id, as_of)
    if profile is None or model is None:
        return {"run_id": None, "matches": 0, "predictions": 0, "note": "too few logged cards to price card timing yet"}
    seed_markets(conn)
    ensure_model_version(conn, CARD_TIMING_VERSION, "Card timing: cards by half, first card, card by a minute", {"cards": COUNT_PARAMS["cards"], "profile": profile.to_dict()})
    run_id = create_run(conn, "weekly", CARD_TIMING_VERSION, CARD_TIMING_FEATURE_VERSION, datetime.combine(as_of, time.min, tzinfo=UTC),
                        notes=f"{league_id}, {len(fixtures)} fixtures, window {as_of} + {days} days, card timing")
    total = 0
    for match_id, home, away in fixtures:
        rows = price_card_timing(model.count_matrix(home, away), profile, CARD_TIMING_MARKETS)
        total += write_predictions(conn, run_id, match_id, rows, MARKETS, {})
        write_context(conn, run_id, match_id, {"first_half_share": round(profile.first_half_share, 4), "cards_logged": profile.n_cards})
    conn.commit()
    return {"run_id": run_id, "matches": len(fixtures), "predictions": total}


def load_log_rates(conn: psycopg.Connection, team_id: int, before: date) -> LogRates | None:
    """Recency-weighted fouls and cards of a club's players over its last matches with a verified ESPN log. None when it has too few."""
    ids = [r[0] for r in conn.execute(
        "SELECT m.id FROM matches m WHERE m.status = 'finished' AND m.match_date < %s AND (m.home_team_id = %s OR m.away_team_id = %s) "
        "AND m.source_ids ->> 'espn_log' = 'true' ORDER BY m.match_date DESC LIMIT %s", (before, team_id, team_id, LOG_PARAMS["n_matches"]))]
    if len(ids) < 8:
        return None
    rows = conn.execute("SELECT match_id, player_name, yellow + red, fouls_committed, fouls_suffered FROM player_match_log WHERE match_id = ANY(%s) AND team_id = %s", (ids, team_id)).fetchall()
    log = pd.DataFrame(rows, columns=["match_id", "player", "cards", "fouls", "fouled"])
    return log_rates(log, ids, half_life_matches=LOG_PARAMS["half_life_matches"])


def log_player_rows(rates: LogRates, club_cards: float) -> list[dict]:
    """Probabilities for one club's players being carded and committing or winning fouls (see models/players.py). Only players with a meaningful chance are priced."""
    out = []

    def add(market, line, player, p):
        out.append({"market_id": market, "line": line, "selection": player, "probability": float(p), "p_win": float(p), "p_lose": float(1 - p), "p_push": 0.0})

    cfg = LOG_PARAMS["cards"]
    lam = (cfg["scale"] * shrunk_card_rate(rates, club_cards, cfg["shrink"], cfg["prior"])).sort_values(ascending=False)
    for player, mean in lam.head(14).items():
        p = float(at_least(float(mean), 1, cfg["dispersion"]))
        if p >= 0.03:
            add("player_carded", None, player, p)
    for stat, column, market in (("fouls", "fouls", "player_fouls"), ("fouled", "fouled", "player_fouled")):
        cfg = LOG_PARAMS[stat]
        mean = cfg["scale"] * rates.players[column] / rates.weight
        for player in mean.sort_values(ascending=False).head(12).index:
            for line in PLAYER_MARKETS[market].lines:
                p = float(at_least(float(mean[player]), int(line + 0.5), cfg["dispersion"]))
                if p >= 0.05:
                    add(market, line, player, p)
    return out


def club_card_model(conn: psycopg.Connection, league_id: str, as_of: date) -> CountModel | None:
    """The cards count model of a league (for the clubs' expected cards in a coming match); None when the league has too little data."""
    try:
        history = load_count_history(conn, league_id)
        data = history.assign(count_home=history["cards_h"], count_away=history["cards_a"])
        return CountModel(half_life_days=COUNT_PARAMS["cards"]["half_life_days"], ridge=COUNT_PARAMS["cards"]["ridge"], max_count=COUNT_STATS["cards"]["max"]).fit(data, as_of=as_of)
    except ValueError:
        return None


def match_player_rows(conn: psycopg.Connection, league_id: str, match_id: int, home_id: int, away_id: int, as_of: date, cards: CountModel | None,
                      lineup: dict | None = None) -> list[dict]:
    """Every player price for one match: shot-based markets (rated leagues only, from the goals model's expected goals) and card/foul markets (from the ESPN log).
    `lineup` maps a team id to (starters, bench) as ESPN spells them; None when the lineup is not known (the weekly run)."""
    rows: list[dict] = []
    ctx = conn.execute(
        "SELECT c.context FROM prediction_context c JOIN prediction_runs r ON r.id = c.run_id WHERE c.match_id = %s AND r.model_version_id LIKE 'goals-%%' "
        "ORDER BY r.created_at DESC LIMIT 1", (match_id,)).fetchone()
    team_name = dict(conn.execute("SELECT id, canonical_name FROM teams WHERE id IN (%s, %s)", (home_id, away_id)).fetchall())
    card_mean = cards.means(team_name[home_id], team_name[away_id]) if cards is not None else (None, None)
    # a player who moved between these two clubs has shots for both: he belongs to the club he shot for most recently
    latest = dict(conn.execute(
        "SELECT DISTINCT ON (s.player_name) s.player_name, s.team_id FROM shot_events s JOIN matches m ON m.id = s.match_id "
        "WHERE s.team_id IN (%s, %s) AND s.player_name IS NOT NULL ORDER BY s.player_name, m.match_date DESC, m.id DESC", (home_id, away_id)).fetchall())
    # likewise for the players of the match log: a player with rows for both clubs belongs to the one he played for most recently
    latest_log = dict(conn.execute(
        "SELECT DISTINCT ON (l.player_name) l.player_name, l.team_id FROM player_match_log l JOIN matches m ON m.id = l.match_id "
        "WHERE l.team_id IN (%s, %s) ORDER BY l.player_name, m.match_date DESC, m.id DESC", (home_id, away_id)).fetchall())
    for team_id, side, expect_cards in ((home_id, "home", card_mean[0]), (away_id, "away", card_mean[1])):
        if ctx is not None and league_id in RATED_LEAGUES:
            rates = load_team_rates(conn, team_id, as_of)
            if rates is not None:
                rates.players = rates.players[[latest.get(name, team_id) == team_id for name in rates.players.index]]
                if lineup and team_id in lineup:
                    known = list(rates.players.index)
                    rates = apply_lineup(rates, match_names(known, lineup[team_id][0]), match_names(known, lineup[team_id][1]))
                rows.extend(player_rows(rates, float(ctx[0]["lambda_home" if side == "home" else "lambda_away"])))
        log = load_log_rates(conn, team_id, as_of)
        if log is not None:
            log.players = log.players[[latest_log.get(name, team_id) == team_id for name in log.players.index]]
        if log is not None and expect_cards is not None:
            if lineup and team_id in lineup:
                log = apply_lineup_log(log, set(lineup[team_id][0]), set(lineup[team_id][1]))
            rows.extend(log_player_rows(log, float(expect_cards)))
    return rows


def predict_players(conn: psycopg.Connection, league_id: str, as_of: date, days: int, force: bool = False) -> dict:
    """Price player markets (experimental) for fixtures in the next `days` days: shots, goals and assists from each club's recent shot data and the goals model's
    expected goals (the five leagues Understat covers), and cards and fouls from the clubs' recent ESPN match logs (every league)."""
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
    ensure_model_version(conn, PLAYER_MODEL_VERSION, "Experimental player layer: goals, shots, shots on target, assists, cards and fouls per player", {**PLAYER_PARAMS, "log": LOG_PARAMS})
    run_id = create_run(conn, "weekly", PLAYER_MODEL_VERSION, PLAYER_FEATURE_VERSION, datetime.combine(as_of, time.min, tzinfo=UTC),
                        notes=f"{league_id}, {len(fixtures)} fixtures, window {as_of} + {days} days, players")
    cards = club_card_model(conn, league_id, as_of)
    total = matches = 0
    for match_id, _kickoff, home_id, away_id in fixtures:
        rows = match_player_rows(conn, league_id, match_id, home_id, away_id, as_of, cards)
        if rows:
            total += write_predictions(conn, run_id, match_id, rows, MARKETS, {})
            write_context(conn, run_id, match_id, {"players_priced": len({r["selection"] for r in rows}), "params": "see model version"})
            matches += 1
    conn.commit()
    return {"run_id": run_id, "matches": matches, "predictions": total}


def ingest_match_log(conn: psycopg.Connection, league_id: str) -> dict:
    """Cards with minutes and players' fouls and cards for this league's matches that finished recently (ESPN), verified against the real card counts."""
    today = datetime.now(UTC).date()
    return ingest_log(conn, league_id, LEAGUES[league_id].espn_code, since=today - timedelta(days=45), retry_from=today - timedelta(days=3))


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
    if force:       # --force writes a second official run for a match: the database guards (migration 011) are lifted for this session only
        conn.execute("SET pitchside.unsafe_writes = 'on'")

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
        for lid in league_ids:      # likewise cards with minutes and players' fouls and cards
            attempt(lid, "match_log", ingest_match_log, conn, lid)
    attempt("settle", "all", settle_all, conn)  # one global pass: settles every league's finished matches
    today = datetime.now(UTC).date()
    for lid in league_ids:
        attempt(lid, "fixtures", plan_fixtures, conn, lid, today, days)
        attempt(lid, "predictions", predict_week, conn, lid, today, days, force)
        attempt(lid, "counts", predict_counts, conn, lid, today, days, force)
        attempt(lid, "card_timing", predict_card_timing, conn, lid, today, days, force)
        attempt(lid, "players", predict_players, conn, lid, today, days, force)
    attempt("accas", "all", build_slips, conn)   # the daily 2 to 30 odds slips, after every match of the window has its predictions
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
