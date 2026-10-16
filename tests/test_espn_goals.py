import datetime as dt

from pitchside.ingest.espn_goals import (
    _minute,
    ingest_espn_goals,
    parse_goals,
    verified,
)


def ev(kind, team, display, period, who="Player"):
    return {"type": {"type": kind}, "team": {"displayName": team}, "clock": {"displayValue": display}, "period": {"number": period}, "participants": [{"athlete": {"displayName": who}}]}


def test_minutes_keep_the_minute_stoppage_time_was_added_to():
    assert _minute("36'") == 36 and _minute("45'+6'") == 45 and _minute("90'+1'") == 90 and _minute("") is None


def test_goals_are_read_with_side_period_and_kind_and_own_goals_go_to_the_credited_side():
    payload = {"keyEvents": [ev("goal", "Hull", "12'", 1), ev("goal---header", "Sheff", "50'", 2), ev("penalty---scored", "Hull", "86'", 2),
                             ev("own-goal", "Hull", "45'+6'", 1), ev("yellow-card", "Hull", "30'", 1)]}
    goals = parse_goals(payload, "Hull", "Sheff")
    assert [(g["side"], g["period"], g["minute"], g["type"]) for g in goals] == [
        ("home", 1, 12, "goal"), ("away", 2, 50, "goal"), ("home", 2, 86, "penalty_goal"), ("home", 1, 45, "own_goal")]


def test_a_goal_that_cannot_be_placed_discards_the_whole_match_and_no_events_means_unknown():
    assert parse_goals({"keyEvents": [ev("goal", "Someone Else", "12'", 1)]}, "Hull", "Sheff") is None
    assert parse_goals({"keyEvents": [ev("goal", "Hull", "", 1)]}, "Hull", "Sheff") is None
    assert parse_goals({}, "Hull", "Sheff") is None
    assert parse_goals({"keyEvents": [ev("yellow-card", "Hull", "9'", 1)]}, "Hull", "Sheff") == []      # a 0-0 with cards is a real, empty answer


def test_goals_are_only_trusted_when_they_add_up_to_both_scores():
    goals = parse_goals({"keyEvents": [ev("goal", "Hull", "12'", 1), ev("goal", "Hull", "70'", 2), ev("goal", "Sheff", "80'", 2)]}, "Hull", "Sheff")
    assert verified(goals, (2, 1), (1, 0))
    assert not verified(goals, (2, 1), (1, 1))      # half-time disagrees
    assert not verified(goals, (3, 1), (1, 0))      # a goal is missing


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, params=None, timeout=None):
        return FakeResponse(self.payload)


def test_ingest_stores_verified_goals_once_and_flags_the_match(conn):
    from pitchside.db.teams import load_aliases, seed_leagues
    seed_leagues(conn)
    load_aliases(conn)
    tid = lambda n: conn.execute("SELECT id FROM teams WHERE canonical_name = %s", (n,)).fetchone()[0]
    mid = conn.execute(
        "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away, ht_home, ht_away, source_ids) "
        "VALUES ('CHAMP', 2026, %s, %s, %s, 'finished', 2, 1, 1, 0, '{\"espn\": \"77\"}') RETURNING id",
        (dt.date(2026, 10, 3), tid("Millwall"), tid("Portsmouth"))).fetchone()[0]
    conn.commit()
    payload = {"header": {"competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": "Millwall"}}, {"homeAway": "away", "team": {"displayName": "Portsmouth"}}]}]},
               "keyEvents": [ev("goal", "Millwall", "12'", 1, "A"), ev("goal", "Millwall", "70'", 2, "B"), ev("goal", "Portsmouth", "80'", 2, "C")]}
    out = ingest_espn_goals(conn, "CHAMP", "eng.2", dt.date(2026, 10, 1), session=FakeSession(payload))
    assert out["loaded"] == 1 and out["unverified"] == 0
    assert conn.execute("SELECT count(*) FROM match_events WHERE match_id = %s AND source = 'espn'", (mid,)).fetchone()[0] == 3
    assert conn.execute("SELECT source_ids->>'goal_minutes' FROM matches WHERE id = %s", (mid,)).fetchone()[0] == "true"
    assert ingest_espn_goals(conn, "CHAMP", "eng.2", dt.date(2026, 10, 1), session=FakeSession(payload))["pending"] == 0      # decided: not fetched again
