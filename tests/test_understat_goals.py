import datetime as dt

import pandas as pd
import pytest

from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.understat_goals import assign_periods, credited_goals, load_goals

SCHEDULE = pd.DataFrame({"game_id": [1], "home_team": ["Arsenal"], "away_team": ["Leeds"]})


def events(*rows):
    """rows: (team, result, minute, player)"""
    return pd.DataFrame([{"game_id": 1, "team": t, "result": r, "minute": m, "player": p, "assist_player": None, "xg": 0.2,
                          "situation": "OpenPlay", "shot_id": 100 + i} for i, (t, r, m, p) in enumerate(rows)])


def test_goals_are_credited_to_the_scoring_side_and_own_goals_to_the_opponent():
    ev = events(("Arsenal", "Goal", 10, "A"), ("Leeds", "Goal", 30, "B"), ("Leeds", "Own Goal", 55, "C"),
                ("Arsenal", "Saved Shot", 60, "D"))
    g = credited_goals(ev, SCHEDULE)
    assert g[["side", "minute", "own_goal"]].values.tolist() == [["home", 10, False], ["away", 30, False], ["home", 55, True]]


def test_periods_come_from_the_half_time_score():
    g = credited_goals(events(("Arsenal", "Goal", 44, "A"), ("Arsenal", "Goal", 47, "A2"), ("Leeds", "Goal", 80, "B")), SCHEDULE)
    # home 2-1 away, half-time 1-0: the 47th-minute goal is in stoppage time of a SECOND half only if ht says so
    out, why = assign_periods(g, ft=(2, 1), ht=(1, 0))
    assert why == "" and out[["side", "minute", "period"]].values.tolist() == [["home", 44, 1], ["home", 47, 2], ["away", 80, 2]]
    out, _ = assign_periods(g, ft=(2, 1), ht=(2, 0))   # same goals, but half-time says both home goals were first-half
    assert out["period"].tolist() == [1, 1, 2]


def test_a_goal_count_that_disagrees_with_the_score_is_rejected():
    g = credited_goals(events(("Arsenal", "Goal", 10, "A")), SCHEDULE)
    out, why = assign_periods(g, ft=(2, 0), ht=(1, 0))
    assert out is None and "home goals 1 != full-time 2" in why


def test_half_time_score_that_cannot_fit_is_rejected():
    g = credited_goals(events(("Arsenal", "Goal", 10, "A"), ("Arsenal", "Goal", 80, "A")), SCHEDULE)
    assert assign_periods(g, ft=(2, 0), ht=(3, 0))[0] is None            # more half-time goals than full-time goals
    late = credited_goals(events(("Arsenal", "Goal", 75, "A")), SCHEDULE)
    assert "later than minute 60" in assign_periods(late, ft=(1, 0), ht=(1, 0))[1]
    early = credited_goals(events(("Arsenal", "Goal", 12, "A")), SCHEDULE)
    assert "earlier than minute 40" in assign_periods(early, ft=(1, 0), ht=(0, 0))[1]


# ---- database ----------------------------------------------------------------------------------------------------

@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    return conn


def add_match(conn, home, away, ft, ht, day=dt.date(2026, 9, 1), status="finished"):
    return conn.execute(
        "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away, ht_home, ht_away) "
        "VALUES ('EPL', 2026, %s, (SELECT id FROM teams WHERE canonical_name = %s), (SELECT id FROM teams WHERE canonical_name = %s), "
        "%s, %s, %s, %s, %s) RETURNING id", (day, home, away, status, ft[0] if ft else None, ft[1] if ft else None,
                                             ht[0] if ht else None, ht[1] if ht else None)).fetchone()[0]


def test_verified_goals_are_loaded_and_flagged(db):
    mid = add_match(db, "Arsenal", "Leeds United", (2, 1), (1, 0))
    ev = events(("Arsenal", "Goal", 44, "A"), ("Leeds", "Own Goal", 70, "Own"), ("Leeds", "Goal", 80, "B"))
    sched = pd.DataFrame({"game_id": [1], "home_team": ["Arsenal"], "away_team": ["Leeds"]})
    out = load_goals(db, "EPL", 2026, ev, sched)
    assert out["loaded"] == 1 and out["goals"] == 3 and out["inconsistent"] == []
    rows = db.execute("SELECT event_type, period, minute, (SELECT canonical_name FROM teams WHERE id = team_id) "
                      "FROM match_events WHERE match_id = %s ORDER BY minute", (mid,)).fetchall()
    assert rows == [("goal", 1, 44, "Arsenal"), ("own_goal", 2, 70, "Arsenal"), ("goal", 2, 80, "Leeds United")]
    assert db.execute("SELECT source_ids FROM matches WHERE id = %s", (mid,)).fetchone()[0] == {"understat": "1", "goal_minutes": True}


def test_a_goalless_draw_is_verified_not_missing(db):
    mid = add_match(db, "Arsenal", "Leeds United", (0, 0), (0, 0))
    out = load_goals(db, "EPL", 2026, events(("Arsenal", "Missed Shot", 10, "A")), SCHEDULE)
    assert out["loaded"] == 1 and out["goals"] == 0
    assert db.execute("SELECT source_ids ->> 'goal_minutes' FROM matches WHERE id = %s", (mid,)).fetchone()[0] == "true"


def test_inconsistent_match_is_not_loaded_and_is_flagged(db):
    mid = add_match(db, "Arsenal", "Leeds United", (2, 0), (1, 0))
    out = load_goals(db, "EPL", 2026, events(("Arsenal", "Goal", 10, "A")), SCHEDULE)   # only one goal for a 2-0 score
    assert out["loaded"] == 0 and len(out["inconsistent"]) == 1
    assert db.execute("SELECT count(*) FROM match_events WHERE match_id = %s", (mid,)).fetchone()[0] == 0
    assert db.execute("SELECT source_ids ->> 'goal_minutes' FROM matches WHERE id = %s", (mid,)).fetchone()[0] == "false"


def test_loading_twice_replaces_rather_than_duplicates(db):
    mid = add_match(db, "Arsenal", "Leeds United", (1, 0), (1, 0))
    ev = events(("Arsenal", "Goal", 20, "A"))
    load_goals(db, "EPL", 2026, ev, SCHEDULE)
    load_goals(db, "EPL", 2026, ev, SCHEDULE)
    assert db.execute("SELECT count(*) FROM match_events WHERE match_id = %s", (mid,)).fetchone()[0] == 1


def test_matches_not_finished_or_without_half_time_are_skipped(db):
    add_match(db, "Arsenal", "Leeds United", None, None, status="scheduled")
    out = load_goals(db, "EPL", 2026, events(), SCHEDULE)
    assert out["not_finished_in_db"] == 1 and out["loaded"] == 0
    add_match(db, "Chelsea", "AFC Bournemouth", (1, 0), None)
    sched2 = pd.DataFrame({"game_id": [2], "home_team": ["Chelsea"], "away_team": ["Bournemouth"]})
    out2 = load_goals(db, "EPL", 2026, events(), sched2)
    assert out2["no_half_time_score"] == 1


def test_missing_situation_and_player_do_not_break_the_load(db):
    mid = add_match(db, "Arsenal", "Leeds United", (1, 0), (1, 0))
    ev = events(("Arsenal", "Goal", 20, "A"))
    ev["situation"] = pd.NA
    ev["player"] = pd.NA
    out = load_goals(db, "EPL", 2026, ev, SCHEDULE)
    assert out["loaded"] == 1
    assert db.execute("SELECT event_type, player_name FROM match_events WHERE match_id = %s", (mid,)).fetchone() == ("goal", None)


def test_penalties_are_recognised_by_xg_when_the_situation_is_missing(db):
    mid = add_match(db, "Arsenal", "Leeds United", (2, 0), (1, 0))
    ev = events(("Arsenal", "Goal", 20, "A"), ("Arsenal", "Goal", 70, "B"))
    ev["situation"] = [pd.NA, "Open Play"]
    ev["xg"] = [0.76, 0.76]            # the second has a known situation, so xG alone must not turn it into a penalty
    load_goals(db, "EPL", 2026, ev, SCHEDULE)
    assert db.execute("SELECT event_type FROM match_events WHERE match_id = %s ORDER BY minute", (mid,)).fetchall() == [
        ("penalty_goal",), ("goal",)]
