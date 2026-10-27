"""The daily odds slips: the selection rules, what is stored, and that a stored slip cannot be edited."""
import json
import math
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from pitchside.accas import (
    TARGETS,
    Leg,
    build_slip,
    build_slips,
    fair_odds,
    label,
    load_availability,
    offered,
    site_market,
    win_probability,
)
from pitchside.confidence import RATED_LEAGUES
from pitchside.db.markets import seed_markets
from pitchside.db.predictions import ensure_model_version
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.markets.registry import MARKETS


def day_of(*probs_per_match):
    """{match_id: [Leg]} where each match offers the given probabilities."""
    return {i + 1: [Leg(100 * (i + 1) + j, i + 1, "ou_total", 1.5, "over", p) for j, p in enumerate(probs)] for i, probs in enumerate(probs_per_match)}


def test_only_widely_offered_markets_and_lines_are_used():
    assert offered("1x2", None) and offered("ou_total", 2.5) and offered("btts", None) and offered("double_chance", None)
    assert not offered("ou_total", 5.5) and not offered("correct_score", None) and not offered("asian_handicap", -0.5) and not offered("ou_total", None)


def test_a_slip_reaches_its_target_and_its_chance_is_about_one_over_the_odds():
    day = day_of(*[[0.9, 0.7, 0.5]] * 8)
    for target in TARGETS:
        legs = build_slip(day, target)
        assert legs is not None
        assert fair_odds(legs) >= target
        assert math.isclose(win_probability(legs) * fair_odds(legs), 1.0, rel_tol=1e-9)
        assert len({leg.match_id for leg in legs}) == len(legs)      # one leg per match


def test_the_safest_legs_are_used_first_and_the_last_leg_lands_close_to_the_target():
    legs = build_slip(day_of(*[[0.92, 0.5]] * 12), 2)
    assert sum(1 for leg in legs if leg.p == 0.92) >= 8 and 2 <= fair_odds(legs) < 2 * 1.2


def test_no_leg_is_priced_below_what_a_site_takes_or_above_a_long_shot():
    legs = build_slip(day_of(*[[0.99, 0.97, 0.9, 0.6, 0.2]] * 6), 5)
    assert all(0.3 <= leg.p <= 0.95 for leg in legs)


def test_a_day_with_too_few_matches_gets_no_big_slip():
    assert build_slip(day_of([0.6], [0.6]), 30) is None


def test_the_same_day_gives_the_same_slip():
    day = day_of(*[[0.9, 0.7, 0.5]] * 7)
    assert build_slip(day, 10) == build_slip(day, 10)


def test_labels_read_like_a_betting_site():
    assert label("ou_total", 2.5, "over", "A", "B") == "Over 2.5 goals"
    assert label("double_chance", None, "1x", "Arsenal", "Leeds") == "Arsenal or draw"
    assert label("btts", None, "yes", "A", "B") == "Both teams to score (GG)"
    assert label("btts", None, "no", "A", "B") == "Both teams not to score (NG)"
    assert label("ou_home", 1.5, "over", "Arsenal", "Leeds") == "Arsenal over 1.5 goals"
    assert label("1x2", None, "away", "A", "B") == "B to win"


def test_a_leagues_own_list_limits_its_markets_and_lines(tmp_path):
    f = tmp_path / "availability.json"
    f.write_text(json.dumps({
        "site": "X", "site_names": {"ou_total": "Over/Under", "ou_home": "{home} Over/Under"},
        "default": {"confirmed_on": None, "lines_confirmed": False, "markets": {"1x2": None, "ou_total": [1.5, 2.5]}},
        "leagues": {"EPL": {"confirmed_on": "2026-10-06", "lines_confirmed": True, "markets": {"ou_total": [2.5]}}, "LALIGA": {"confirmed_on": None, "lines_confirmed": False}}}))
    avail = load_availability(f)
    assert offered("ou_total", 2.5, "EPL", avail) and not offered("ou_total", 1.5, "EPL", avail) and not offered("1x2", None, "EPL", avail)
    assert offered("ou_total", 1.5, "LALIGA", avail) and offered("1x2", None, "LALIGA", avail)      # no list of its own: the default list applies
    assert not offered("btts", None, "LALIGA", avail)
    assert site_market("ou_home", "Arsenal", "Leeds", avail) == "Arsenal Over/Under" and site_market("btts", "A", "B", avail) is None


def test_a_missing_availability_file_falls_back_to_the_built_in_list(tmp_path):
    avail = load_availability(tmp_path / "missing.json")
    assert offered("btts", None, "EPL", avail) and offered("ou_total", 2.5, "EPL", avail) and not offered("correct_score", None, "EPL", avail)


def test_the_shipped_availability_file_is_complete_and_only_names_markets_we_price():
    avail = load_availability()
    assert set(RATED_LEAGUES) <= set(avail["leagues"])
    for market, lines in avail["default"]["markets"].items():
        assert market in MARKETS and (lines is None or all(isinstance(x, int | float) for x in lines))
        assert market in avail["site_names"]


# ---- stored ------------------------------------------------------------------------------------------------------

@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    seed_markets(conn)
    ensure_model_version(conn, "goals-dc-test", "test", {})
    conn.commit()
    return conn


def upcoming_match(conn, hours, home, away):
    kickoff = datetime.now(UTC) + timedelta(hours=hours)
    return conn.execute(
        "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status) VALUES ('EPL', 2026, %s, %s, "
        "(SELECT id FROM teams WHERE canonical_name = %s), (SELECT id FROM teams WHERE canonical_name = %s), 'scheduled') RETURNING id",
        (kickoff.date(), kickoff, home, away)).fetchone()[0]


def predict(conn, match_id, rows):
    run = conn.execute("INSERT INTO prediction_runs (run_type, model_version_id, feature_version, data_cutoff) VALUES ('weekly', 'goals-dc-test', 'f', now()) RETURNING id").fetchone()[0]
    conn.execute("INSERT INTO prediction_context (run_id, match_id, context) VALUES (%s,%s,'{}')", (run, match_id))
    for market, line, sel, p in rows:
        conn.execute("INSERT INTO predictions (run_id, match_id, market_id, line, selection, probability) VALUES (%s,%s,%s,%s,%s,%s)", (run, match_id, market, line, sel, p))


def test_slips_are_stored_once_per_day_and_cannot_be_edited(db):
    teams = [r[0] for r in db.execute("SELECT canonical_name FROM teams ORDER BY id LIMIT 8")]
    for i in range(4):
        mid = upcoming_match(db, 3 + i, teams[2 * i], teams[2 * i + 1])
        predict(db, mid, [("ou_total", 1.5, "over", 0.82), ("ou_total", 2.5, "over", 0.55), ("1x2", None, "home", 0.5), ("correct_score", None, "1-0", 0.3)])
    first = build_slips(db)
    assert first["slips"] >= 3
    again = build_slips(db)
    assert again["slips"] == 0                              # stored once per day and target
    legs = db.execute("SELECT count(*) FROM accumulator_legs").fetchone()[0]
    assert legs >= first["slips"]
    assert db.execute("SELECT count(*) FROM accumulator_legs l JOIN predictions p ON p.id = l.prediction_id WHERE p.market_id = 'correct_score'").fetchone()[0] == 0
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("UPDATE accumulators SET win_probability = 0.99")
