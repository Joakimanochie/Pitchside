import datetime as dt
from datetime import UTC, datetime, timedelta

import pytest

from pitchside.db.markets import seed_markets
from pitchside.db.predictions import (
    create_run,
    ensure_model_version,
    write_context,
    write_predictions,
)
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.markets.players import MARKETS as PLAYER_MARKETS
from pitchside.markets.players import settle_player
from pitchside.markets.registry import MARKETS
from pitchside.pipeline.weekly import (
    PLAYER_MODEL_VERSION,
    load_team_rates,
    player_rows,
    predict_players,
)
from pitchside.settle.settle import build_outcomes, settle_all


@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    seed_markets(conn)
    ensure_model_version(conn, "goals-dc-test", "test", {})
    conn.commit()
    return conn


def team_id(conn, name):
    return conn.execute("SELECT id FROM teams WHERE canonical_name = %s", (name,)).fetchone()[0]


def add_match(conn, day, status="finished", home="Arsenal", away="Leeds United", kickoff=None):
    return conn.execute(
        "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, ft_home, ft_away, ht_home, ht_away) "
        "VALUES ('EPL', 2026, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (day, kickoff, team_id(conn, home), team_id(conn, away), status, 2 if status == "finished" else None, 1 if status == "finished" else None,
         1 if status == "finished" else None, 0 if status == "finished" else None)).fetchone()[0]


def add_shot(conn, match_id, team, player, result="Missed Shot", xg=0.1, assist=None, n=1, start=1):
    for i in range(n):
        conn.execute("INSERT INTO shot_events (match_id, team_id, player_name, assist_name, minute, xg, result, understat_shot_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (match_id, team_id(conn, team), player, assist, 10 + i, xg, result, start + i + abs(hash((match_id, player, result))) % 10**6))


def history(conn, matches=10):
    """Ten finished matches in which Arsenal's Striker scores often and shoots a lot and the Winger sets goals up."""
    for k in range(matches):
        mid = add_match(conn, dt.date(2026, 1, 1) + dt.timedelta(days=7 * k))
        add_shot(conn, mid, "Arsenal", "Striker", "Goal", 0.4, assist="Winger", n=1 + (k % 2))
        add_shot(conn, mid, "Arsenal", "Striker", "Saved Shot", 0.2, n=2)
        add_shot(conn, mid, "Arsenal", "Winger", "Missed Shot", 0.08, n=1)
        add_shot(conn, mid, "Arsenal", "Defender", "Blocked Shot", 0.03, n=1)
        add_shot(conn, mid, "Leeds United", "Forward", "Goal" if k % 3 == 0 else "Saved Shot", 0.3, n=2)
        add_shot(conn, mid, "Leeds United", "Opponent", "Own Goal", 0.0, n=1 if k == 4 else 0)
    conn.commit()


def goals_context(conn, match_id, lam_home=1.8, lam_away=1.0):
    run_id = create_run(conn, "weekly", "goals-dc-test", "f0", datetime.now(UTC))
    write_context(conn, run_id, match_id, {"lambda_home": lam_home, "lambda_away": lam_away})
    conn.commit()


def future_fixture(conn, days=2):
    kickoff = datetime.now(UTC) + timedelta(days=days)
    return add_match(conn, kickoff.date(), "scheduled", kickoff=kickoff)


# ---- rates and prices --------------------------------------------------------------------------------------------

def test_too_little_shot_history_gives_no_rates(db):
    history(db, matches=5)
    assert load_team_rates(db, team_id(db, "Arsenal"), dt.date(2026, 6, 1)) is None


def test_recent_rates_cover_only_matches_before_the_date_and_exclude_own_goals(db):
    history(db, matches=10)
    rates = load_team_rates(db, team_id(db, "Arsenal"), dt.date(2026, 6, 1))
    assert rates is not None and rates.players.loc["Striker", "goals"] > rates.players.loc["Winger", "goals"] == 0
    assert "Opponent" not in rates.players.index
    early = load_team_rates(db, team_id(db, "Arsenal"), dt.date(2026, 2, 20))        # only the eight matches played by then
    assert early is not None and early.weight < rates.weight


def test_player_prices_follow_each_players_role_and_the_clubs_expected_goals(db):
    history(db)
    rates = load_team_rates(db, team_id(db, "Arsenal"), dt.date(2026, 6, 1))
    rows = player_rows(rates, club_goals=1.8)
    by = {(r["market_id"], r["line"], r["selection"]): r["probability"] for r in rows}
    assert by[("player_anytime_goal", None, "Striker")] > 0.3
    assert by.get(("player_anytime_goal", None, "Defender"), 0) < 0.1 < by[("player_anytime_goal", None, "Winger")] + 0.05
    assert by[("player_shots", 0.5, "Striker")] > by[("player_shots", 1.5, "Striker")] > by[("player_shots", 2.5, "Striker")]
    assert by[("player_assist", None, "Winger")] > 0.1 and all(0 < p < 1 for p in by.values())
    more = {(r["market_id"], r["line"], r["selection"]): r["probability"] for r in player_rows(rates, club_goals=3.0)}
    assert more[("player_anytime_goal", None, "Striker")] > by[("player_anytime_goal", None, "Striker")]
    assert {r["market_id"] for r in rows} <= set(PLAYER_MARKETS)


# ---- the weekly step ---------------------------------------------------------------------------------------------

def test_weekly_player_step_prices_both_clubs_once_under_its_own_version(db):
    history(db)
    mid = future_fixture(db)
    goals_context(db, mid)
    today = datetime.now(UTC).date()
    out = predict_players(db, "EPL", today, days=5)
    assert out["matches"] == 1 and out["predictions"] > 10
    versions = {r[0] for r in db.execute("SELECT DISTINCT r.model_version_id FROM predictions p JOIN prediction_runs r ON r.id = p.run_id")}
    assert versions == {PLAYER_MODEL_VERSION}
    assert {r[0] for r in db.execute("SELECT DISTINCT market_id FROM predictions")} <= set(PLAYER_MARKETS)
    assert predict_players(db, "EPL", today, days=5)["matches"] == 0              # one official run per match per version


def test_no_goals_prediction_means_no_player_prices_and_clubs_without_history_are_skipped(db):
    history(db)
    future_fixture(db)
    assert predict_players(db, "EPL", datetime.now(UTC).date(), days=5)["predictions"] == 0   # no goals context for the match
    mid2 = future_fixture(db, days=3)
    db.execute("UPDATE matches SET home_team_id = %s WHERE id = %s", (team_id(db, "Chelsea"), mid2))   # Chelsea has no shot history; Leeds does
    goals_context(db, mid2)
    out = predict_players(db, "EPL", datetime.now(UTC).date(), days=5)
    sel = {r[0] for r in db.execute("SELECT DISTINCT selection FROM predictions")}
    assert out["matches"] == 1 and "Forward" in sel and "Striker" not in sel


# ---- settling ----------------------------------------------------------------------------------------------------

def test_settle_player_uses_the_players_own_counts_and_zero_when_unrecorded():
    players = {"Striker": {"goals": 1, "shots": 3, "sot": 2, "assists": 0}}
    assert settle_player(PLAYER_MARKETS["player_anytime_goal"], None, "Striker", players)["result"] == "won"
    assert settle_player(PLAYER_MARKETS["player_shots"], 2.5, "Striker", players)["result"] == "won"
    assert settle_player(PLAYER_MARKETS["player_shots"], 3.5 - 1, "Striker", players)["outcome_value"] == 1.0
    assert settle_player(PLAYER_MARKETS["player_sot"], 2.5, "Striker", players)["result"] == "lost"
    assert settle_player(PLAYER_MARKETS["player_assist"], None, "Striker", players)["result"] == "lost"
    assert settle_player(PLAYER_MARKETS["player_anytime_goal"], None, "Nobody", players)["result"] == "lost"


def predict_rows(conn, match_id, rows):
    run_id = create_run(conn, "weekly", "goals-dc-test", "f0", datetime.now(UTC) - timedelta(days=2))
    write_predictions(conn, run_id, match_id, rows, MARKETS, {})
    conn.commit()


def prow(market, selection, p, line=None):
    return {"market_id": market, "line": line, "selection": selection, "probability": p, "p_win": p, "p_lose": 1 - p, "p_push": 0.0}


def settled(conn, market, selection, line=None):
    return conn.execute("SELECT s.result, s.outcome_value, s.observed FROM settlements s JOIN predictions p ON p.id = s.prediction_id "
                        "WHERE p.market_id = %s AND p.selection = %s AND p.line IS NOT DISTINCT FROM %s", (market, selection, line)).fetchone()


def test_player_markets_settle_from_shot_events_and_wait_when_there_are_none(db):
    mid = add_match(db, dt.date(2099, 1, 1), kickoff=datetime(2099, 1, 1, 15, tzinfo=UTC))      # kickoff after the predictions, as in real life
    predict_rows(db, mid, [prow("player_anytime_goal", "Striker", 0.5), prow("player_shots", "Striker", 0.6, 2.5), prow("player_assist", "Winger", 0.2),
                           prow("player_anytime_goal", "Defender", 0.05), prow("1x2", "home", 0.5)])
    settle_all(db)
    res, val, observed = settled(db, "player_anytime_goal", "Striker")
    assert (res, val) == ("not_scorable", None) and observed["reason"] == "player_data_missing"      # shots not published yet
    assert settled(db, "1x2", "home")[0] == "won"
    add_shot(db, mid, "Arsenal", "Striker", "Goal", 0.4, assist="Winger", n=1)
    add_shot(db, mid, "Arsenal", "Striker", "Saved Shot", 0.2, n=2, start=50)
    add_shot(db, mid, "Arsenal", "Defender", "Missed Shot", 0.02, n=1)
    db.commit()
    settle_all(db)                                                                                  # the shots arrived: re-settled
    assert settled(db, "player_anytime_goal", "Striker")[:2] == ("won", 1.0)
    assert settled(db, "player_shots", "Striker", 2.5)[:2] == ("won", 1.0)                         # three shots
    assert settled(db, "player_assist", "Winger")[:2] == ("won", 1.0)
    assert settled(db, "player_anytime_goal", "Defender")[:2] == ("lost", 0.0)
    assert build_outcomes(db) == 1


def test_a_player_who_moved_between_the_two_clubs_is_priced_once_for_his_current_club(db):
    history(db)
    for k in range(9):    # the Leeds striker used to play for Arsenal: older shots for Arsenal, newer ones for Leeds
        mid = add_match(db, dt.date(2025, 6, 1) + dt.timedelta(days=7 * k))
        add_shot(db, mid, "Arsenal", "Nomad", "Goal", 0.4, n=1)
    for k in range(3):
        mid = add_match(db, dt.date(2026, 6, 1) + dt.timedelta(days=7 * k))
        add_shot(db, mid, "Leeds United", "Nomad", "Goal", 0.4, n=1)
        add_shot(db, mid, "Arsenal", "Striker", "Goal", 0.4, n=1)
    db.commit()
    fixture = future_fixture(db)
    goals_context(db, fixture)
    predict_players(db, "EPL", datetime.now(UTC).date(), days=5)
    rows = db.execute("SELECT market_id, line, count(*) FROM predictions WHERE selection = 'Nomad' GROUP BY market_id, line").fetchall()
    assert rows and all(n == 1 for _m, _l, n in rows)
