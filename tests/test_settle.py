import datetime as dt
import math
from datetime import UTC, datetime, timedelta

import pytest

from pitchside.db.markets import seed_markets
from pitchside.db.predictions import create_run, ensure_model_version, write_predictions
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.footballdata import RAW_DIR, load_seasons, season_code
from pitchside.ingest.load_matches import load_footballdata
from pitchside.markets.goals import price_match
from pitchside.markets.registry import MARKETS
from pitchside.models.dixon_coles import DixonColes
from pitchside.pipeline.weekly import MODEL_PARAMS, load_history
from pitchside.settle.settle import build_outcomes, score, settle_all


@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    seed_markets(conn)
    ensure_model_version(conn, "test-0", "test", {})
    conn.commit()
    return conn


def make_match(conn, status="scheduled", score_=None, kickoff=None, day=dt.date(2026, 10, 10)):
    ft = score_ or (None, None)
    return conn.execute(
        "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, ft_home, ft_away) "
        "VALUES ('EPL', 2026, %s, %s, (SELECT id FROM teams WHERE canonical_name = 'Arsenal'), "
        "(SELECT id FROM teams WHERE canonical_name = 'Leeds United'), %s, %s, %s) RETURNING id",
        (day, kickoff, status, ft[0], ft[1])).fetchone()[0]


def predict(conn, match_id, rows, run_type="weekly", markets=MARKETS):
    run_id = create_run(conn, run_type, "test-0", "f0", datetime.now(UTC))
    write_predictions(conn, run_id, match_id, rows, markets, {})
    return run_id


def row(market_id, selection, p, line=None):
    return {"market_id": market_id, "line": line, "selection": selection, "probability": p, "p_win": p, "p_lose": 1 - p, "p_push": 0.0}


def settlement(conn, market_id, selection, line=None):
    return conn.execute(
        "SELECT s.result, s.outcome_value, s.log_loss, s.brier, s.observed FROM settlements s "
        "JOIN predictions p ON p.id = s.prediction_id WHERE p.market_id = %s AND p.selection = %s "
        "AND p.line IS NOT DISTINCT FROM %s", (market_id, selection, line)).fetchone()


def test_score_function():
    assert score(0.6, 1.0)[0] == pytest.approx(-math.log(0.6))
    assert score(0.6, 0.0)[0] == pytest.approx(-math.log(0.4))
    assert score(0.6, 1.0)[1] == pytest.approx(0.16)
    assert math.isfinite(score(0.0, 1.0)[0])  # clipped, never infinite


def test_settles_and_scores_a_finished_match(db):
    mid = make_match(db, "finished", (2, 1))
    predict(db, mid, [row("1x2", "home", 0.6), row("1x2", "draw", 0.25), row("1x2", "away", 0.15),
                      row("ou_total", "over", 0.55, 2.5), row("ou_total", "over", 0.45, 3.0),
                      row("asian_handicap", "home", 0.5, -0.75)])
    out = settle_all(db)
    assert out["outcomes_built"] == 1 and out["settled"] == 6
    res, val, ll, brier, observed = settlement(db, "1x2", "home")
    assert (res, val) == ("won", 1.0) and float(ll) == pytest.approx(-math.log(0.6), abs=1e-5)
    assert float(brier) == pytest.approx(0.16, abs=1e-5) and observed == {"ft_home": 2, "ft_away": 1}
    assert settlement(db, "1x2", "draw")[:2] == ("lost", 0.0)
    assert float(settlement(db, "1x2", "draw")[2]) == pytest.approx(-math.log(0.75), abs=1e-5)
    assert settlement(db, "ou_total", "over", 2.5)[:2] == ("won", 1.0)
    assert settlement(db, "asian_handicap", "home", -0.75)[:2] == ("half_won", 1.0)


def test_push_gets_no_outcome_and_no_score(db):
    mid = make_match(db, "finished", (2, 1))
    predict(db, mid, [row("ou_total", "over", 0.45, 3.0)])
    settle_all(db)
    assert settlement(db, "ou_total", "over", 3.0) == ("push", None, None, None, {"ft_home": 2, "ft_away": 1})


def test_settling_twice_changes_nothing(db):
    mid = make_match(db, "finished", (2, 1))
    predict(db, mid, [row("1x2", "home", 0.6)])
    assert settle_all(db)["settled"] == 1
    assert settle_all(db)["settled"] == 0


def test_unfinished_matches_are_left_pending(db):
    mid = make_match(db, "scheduled", kickoff=datetime.now(UTC) + timedelta(days=2))
    predict(db, mid, [row("1x2", "home", 0.6)])
    assert settle_all(db) == {"outcomes_built": 0, "settled": 0, "by_result": {}}
    pm = make_match(db, "postponed", day=dt.date(2026, 10, 11))
    predict(db, pm, [row("1x2", "home", 0.6)])
    assert settle_all(db)["settled"] == 0


def test_a_corrected_result_is_resettled(db):
    mid = make_match(db, "finished", (1, 1))
    predict(db, mid, [row("1x2", "home", 0.6), row("1x2", "draw", 0.25)])
    settle_all(db)
    assert settlement(db, "1x2", "home")[0] == "lost" and settlement(db, "1x2", "draw")[0] == "won"
    db.execute("UPDATE matches SET ft_home = 2, ft_away = 1 WHERE id = %s", (mid,))
    out = settle_all(db)
    assert out["settled"] == 2
    assert settlement(db, "1x2", "home")[0] == "won" and settlement(db, "1x2", "draw")[0] == "lost"
    assert settlement(db, "1x2", "home")[4] == {"ft_home": 2, "ft_away": 1}


def test_cancelled_match_voids_its_predictions(db):
    mid = make_match(db, "cancelled")
    predict(db, mid, [row("1x2", "home", 0.6)])
    settle_all(db)
    assert settlement(db, "1x2", "home") == ("void", None, None, None, {"reason": "match_cancelled"})


def test_prediction_made_after_kickoff_never_counts(db):
    mid = make_match(db, "finished", (2, 1), kickoff=datetime.now(UTC) - timedelta(hours=5))  # run is created now
    predict(db, mid, [row("1x2", "home", 0.99)])
    settle_all(db)
    assert settlement(db, "1x2", "home") == ("void", None, None, None, {"reason": "made_after_kickoff"})


def test_prediction_made_before_kickoff_counts(db):
    mid = make_match(db, "finished", (2, 1), kickoff=datetime.now(UTC) + timedelta(hours=5))
    predict(db, mid, [row("1x2", "home", 0.6)])
    settle_all(db)
    assert settlement(db, "1x2", "home")[:2] == ("won", 1.0)


def test_unknown_market_is_not_scorable(db):
    db.execute("INSERT INTO markets (id, family, name) VALUES ('mystery', 'I', 'Mystery')")
    mid = make_match(db, "finished", (2, 1))
    predict(db, mid, [row("mystery", "x", 0.3), row("1x2", "home", 0.6)], markets={**MARKETS, "mystery": MARKETS["1x2"]})
    out = settle_all(db)
    assert out["by_result"] == {"not_scorable": 1, "won": 1}
    assert settlement(db, "mystery", "x")[:2] == ("not_scorable", None)


def test_build_outcomes_records_scores_and_coverage(db):
    mid = make_match(db, "finished", (2, 1))
    db.execute("UPDATE matches SET ht_home = 1, ht_away = 0 WHERE id = %s", (mid,))
    predict(db, mid, [row("1x2", "home", 0.6)])
    assert build_outcomes(db) == 1
    record, coverage = db.execute("SELECT record, coverage FROM match_outcomes WHERE match_id = %s", (mid,)).fetchone()
    assert (record["ft_home"], record["ft_away"], record["ht_home"], record["ht_away"]) == (2, 1, 1, 0)
    assert coverage == {"ft": True, "ht": True, "team_stats": False, "goal_minutes": False}


def test_track_record_views_separate_live_from_backtest(db):
    live = make_match(db, "finished", (2, 1), kickoff=datetime.now(UTC) + timedelta(hours=1))
    predict(db, live, [row("1x2", "home", 0.6), row("1x2", "draw", 0.3), row("ou_total", "over", 0.55, 2.5)])
    bt = make_match(db, "finished", (0, 0), day=dt.date(2026, 10, 11))
    predict(db, bt, [row("1x2", "home", 0.7)], run_type="backtest")
    settle_all(db)
    fam = {(r[0], r[1]): r[2:] for r in db.execute("SELECT run_type, family, n, avg_log_loss FROM v_scores_by_family")}
    assert fam[("weekly", "A")][0] == 3 and fam[("backtest", "A")][0] == 1
    # live run: home won (p .6), draw lost (p .3), over 2.5 won (p .55)
    expected_live = (-math.log(0.6) - math.log(0.7) - math.log(0.55)) / 3
    assert float(fam[("weekly", "A")][1]) == pytest.approx(expected_live, abs=1e-4)
    assert float(fam[("backtest", "A")][1]) == pytest.approx(-math.log(0.3), abs=1e-4)  # home lost at p .7
    cal = db.execute("SELECT bucket_from, n, hit_rate FROM v_calibration WHERE run_type = 'weekly' ORDER BY bucket_from").fetchall()
    assert [(float(b), n) for b, n, _ in cal] == [(0.3, 1), (0.5, 1), (0.6, 1)]


# ---- the whole chain on real data: predict -> store -> settle ------------------------------------------------------

def test_stored_and_settled_scores_equal_the_models_own_probabilities(conn):
    years = list(range(2021, 2027))
    if not all((RAW_DIR / f"{season_code(y)}_E0.csv").exists() for y in years):
        pytest.skip("football-data cache not downloaded")
    seed_leagues(conn)
    load_aliases(conn)
    seed_markets(conn)
    load_footballdata(conn, "EPL", load_seasons("E0", years))
    ensure_model_version(conn, "bt-0", "backtest", MODEL_PARAMS)
    conn.commit()

    as_of = dt.date(2026, 9, 1)
    model = DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"]).fit(
        load_history(conn, "EPL"), as_of=as_of)
    matches = conn.execute(
        "SELECT m.id, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.match_date >= %s AND m.status = 'finished' AND m.season = 2026", (as_of,)).fetchall()
    assert len(matches) >= 10
    run_id = create_run(conn, "backtest", "bt-0", "f0", datetime(2026, 9, 1, tzinfo=UTC))
    for mid, home, away, _fh, _fa in matches:
        write_predictions(conn, run_id, mid, price_match(model.score_matrix(home, away)), MARKETS, {})
    conn.commit()

    out = settle_all(conn)
    assert out["by_result"].get("not_scorable", 0) == 0 and out["by_result"].get("void", 0) == 0
    for mid, home, away, fh, fa in matches:
        p = model.score_matrix(home, away)
        actual = "home" if fh > fa else "draw" if fh == fa else "away"
        prob = {"home": sum(p[i, j] for i in range(11) for j in range(11) if i > j),
                "draw": sum(p[i, i] for i in range(11)),
                "away": sum(p[i, j] for i in range(11) for j in range(11) if i < j)}[actual]
        stored = conn.execute(
            "SELECT s.result, s.log_loss FROM settlements s JOIN predictions p ON p.id = s.prediction_id "
            "WHERE p.match_id = %s AND p.market_id = '1x2' AND p.selection = %s", (mid, actual)).fetchone()
        assert stored[0] == "won" and float(stored[1]) == pytest.approx(-math.log(prob), abs=1e-4)
    # every two-way market settles to exactly one winner per match and line
    n_bad = conn.execute(
        "SELECT count(*) FROM (SELECT p.match_id, p.market_id, p.line, count(*) FILTER (WHERE s.result IN ('won','half_won')) w, "
        "count(*) FILTER (WHERE s.result IN ('lost','half_lost')) l FROM predictions p JOIN settlements s ON s.prediction_id = p.id "
        "WHERE p.market_id IN ('ou_total','btts','draw_no_bet') GROUP BY 1,2,3) t WHERE w > 1 OR l > 1").fetchone()[0]
    assert n_bad == 0


# ---- families B-E: record-based markets ------------------------------------------------------------------------------------

def add_goal_events(conn, match_id, goals):
    """goals: (side, period, minute). Marks the match's goal minutes as verified."""
    for side, period, minute in goals:
        conn.execute(
            "INSERT INTO match_events (match_id, team_id, event_type, period, minute, details, source) VALUES "
            "(%s, (SELECT CASE WHEN %s = 'home' THEN home_team_id ELSE away_team_id END FROM matches WHERE id = %s), "
            "'goal', %s, %s, jsonb_build_object('side', %s::text), 'understat')", (match_id, side, match_id, period, minute, side))
    conn.execute("UPDATE matches SET source_ids = source_ids || '{\"goal_minutes\": true}'::jsonb WHERE id = %s", (match_id,))


def test_half_and_combination_markets_settle_from_scores_alone(db):
    mid = make_match(db, "finished", (3, 2))
    db.execute("UPDATE matches SET ht_home = 1, ht_away = 0 WHERE id = %s", (mid,))
    predict(db, mid, [row("ht_ft", "home/home", 0.4), row("1x2_h1", "home", 0.5),
                      row("x12_ou_25", "home&over", 0.3), row("highest_scoring_half", "2nd", 0.45)])
    out = settle_all(db)
    assert out["by_result"] == {"won": 4}
    assert settlement(db, "ht_ft", "home/home")[:2] == ("won", 1.0)
    assert settlement(db, "highest_scoring_half", "2nd")[0] == "won"       # second half ended 2-2: more than the 1 first-half goal


def test_goal_minute_markets_wait_for_verified_minutes_then_settle(db):
    mid = make_match(db, "finished", (3, 2))
    db.execute("UPDATE matches SET ht_home = 1, ht_away = 0 WHERE id = %s", (mid,))
    predict(db, mid, [row("first_goal", "home", 0.6), row("lead_by_away", "yes", 0.2, 1.0), row("1x2", "home", 0.7)])
    out = settle_all(db)
    assert out["by_result"] == {"not_scorable": 2, "won": 1}
    assert settlement(db, "first_goal", "home")[4]["reason"] == "goal_minutes_unverified"

    # the minutes are verified later: 20' H, 50' A, 60' H, 70' A, 88' H
    add_goal_events(db, mid, [("home", 1, 20), ("away", 2, 50), ("home", 2, 60), ("away", 2, 70), ("home", 2, 88)])
    out = settle_all(db)
    assert out["settled"] == 2                     # only the two that were waiting
    assert settlement(db, "first_goal", "home")[:2] == ("won", 1.0)
    assert settlement(db, "lead_by_away", "yes", 1.0)[:2] == ("lost", 0.0)   # the away side never led
    assert settlement(db, "1x2", "home")[0] == "won" and settle_all(db)["settled"] == 0


def test_a_match_without_a_half_time_score_cannot_settle_half_markets(db):
    mid = make_match(db, "finished", (1, 0))
    predict(db, mid, [row("1x2_h1", "home", 0.5), row("1x2", "home", 0.6)])
    settle_all(db)
    assert settlement(db, "1x2_h1", "home")[4]["reason"] == "no_half_time_score" and settlement(db, "1x2", "home")[0] == "won"
