from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.pipeline.goal_minutes import ingest_goal_minutes, pending_matches


class FakeUnderstat:
    """Stands in for soccerdata.Understat: a schedule and shot events per game, with a log of what was requested."""

    def __init__(self, games, events):
        self.games, self.events, self.requested = games, events, []

    def read_schedule(self):
        return pd.DataFrame(self.games)

    def read_shot_events(self, match_id):
        self.requested.append(match_id)
        rows = self.events.get(match_id, [])
        return pd.DataFrame(rows, columns=["game_id", "team", "result", "minute", "player", "assist_player", "xg", "situation", "shot_id"])


def shot(game_id, team, minute, result="Goal"):
    return (game_id, team, result, minute, "P", None, 0.2, "Open Play", game_id * 100 + minute)


@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    return conn


def add_match(conn, home, away, ft, ht, days_ago=1, season=2026):
    day = (datetime.now(UTC) - timedelta(days=days_ago)).date()
    return conn.execute(
        "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away, ht_home, ht_away) "
        "VALUES ('EPL', %s, %s, (SELECT id FROM teams WHERE canonical_name = %s), (SELECT id FROM teams WHERE canonical_name = %s), "
        "'finished', %s, %s, %s, %s) RETURNING id", (season, day, home, away, *ft, *ht)).fetchone()[0]


def flag(conn, match_id):
    return conn.execute("SELECT source_ids ->> 'goal_minutes' FROM matches WHERE id = %s", (match_id,)).fetchone()[0]


def factory(fake):
    return lambda league_name, season: fake


GAMES = [{"game_id": 1, "home_team": "Arsenal", "away_team": "Leeds"}]


def test_nothing_pending_means_no_request_at_all(db):
    def boom(*a):
        raise AssertionError("Understat must not be contacted when nothing is pending")
    assert ingest_goal_minutes(db, "EPL", 2026, client_factory=boom) == {"pending": 0, "fetched": 0, "loaded": 0}


def test_a_finished_match_is_fetched_verified_and_flagged(db):
    mid = add_match(db, "Arsenal", "Leeds United", (2, 0), (1, 0))
    fake = FakeUnderstat(GAMES, {1: [shot(1, "Arsenal", 20), shot(1, "Arsenal", 70)]})
    out = ingest_goal_minutes(db, "EPL", 2026, client_factory=factory(fake))
    assert out["loaded"] == 1 and fake.requested == [1] and flag(db, mid) == "true"
    assert db.execute("SELECT count(*) FROM match_events WHERE match_id = %s", (mid,)).fetchone()[0] == 2
    # verified, so it is not asked for again
    again = FakeUnderstat(GAMES, {})
    assert ingest_goal_minutes(db, "EPL", 2026, client_factory=factory(again))["pending"] == 0 and again.requested == []


def test_data_not_published_yet_is_left_untouched_and_retried(db):
    mid = add_match(db, "Arsenal", "Leeds United", (2, 0), (1, 0))
    out = ingest_goal_minutes(db, "EPL", 2026, client_factory=factory(FakeUnderstat(GAMES, {})))
    assert out["loaded"] == 0 and out["unavailable"] == 1 and flag(db, mid) is None     # NOT flagged unverified
    later = FakeUnderstat(GAMES, {1: [shot(1, "Arsenal", 20), shot(1, "Arsenal", 70)]})
    assert ingest_goal_minutes(db, "EPL", 2026, client_factory=factory(later))["loaded"] == 1 and flag(db, mid) == "true"


def test_a_recent_mismatch_is_flagged_but_retried_an_old_one_is_not(db):
    recent = add_match(db, "Arsenal", "Leeds United", (2, 0), (1, 0), days_ago=1)
    old = add_match(db, "Chelsea", "AFC Bournemouth", (1, 0), (0, 0), days_ago=20)
    games = [*GAMES, {"game_id": 2, "home_team": "Chelsea", "away_team": "Bournemouth"}]
    partial = {1: [shot(1, "Arsenal", 20)], 2: [shot(2, "Chelsea", 80), shot(2, "Chelsea", 85)]}   # both disagree with the score
    out = ingest_goal_minutes(db, "EPL", 2026, client_factory=factory(FakeUnderstat(games, {k: v for k, v in partial.items()})))
    assert out["unverified"] == 2 and flag(db, recent) == "false" and flag(db, old) == "false"
    # the recent match is retried (its data was completed); the 20-day-old one is not asked for again
    fixed = FakeUnderstat(games, {1: [shot(1, "Arsenal", 20), shot(1, "Arsenal", 70)]})
    assert pending_matches(db, "EPL", 2026) == {_ids(db, "Arsenal", "Leeds United")}
    ingest_goal_minutes(db, "EPL", 2026, client_factory=factory(fixed))
    assert fixed.requested == [1] and flag(db, recent) == "true" and flag(db, old) == "false"


def _ids(conn, home, away):
    return tuple(conn.execute("SELECT id FROM teams WHERE canonical_name = %s", (n,)).fetchone()[0] for n in (home, away))


def test_matches_without_a_half_time_score_are_not_pending(db):
    add_match(db, "Arsenal", "Leeds United", (1, 0), (0, 0))
    db.execute("UPDATE matches SET ht_home = NULL, ht_away = NULL")
    assert pending_matches(db, "EPL", 2026) == set()


def test_one_unreadable_match_does_not_stop_the_others(db):
    add_match(db, "Arsenal", "Leeds United", (1, 0), (1, 0))
    add_match(db, "Chelsea", "AFC Bournemouth", (1, 0), (1, 0))
    games = [*GAMES, {"game_id": 2, "home_team": "Chelsea", "away_team": "Bournemouth"}]

    class Flaky(FakeUnderstat):
        def read_shot_events(self, match_id):
            if match_id == 1:
                raise RuntimeError("roster parse error")
            return super().read_shot_events(match_id)

    out = ingest_goal_minutes(db, "EPL", 2026, client_factory=factory(Flaky(games, {2: [shot(2, "Chelsea", 30)]})))
    assert out["loaded"] == 1 and out["unavailable"] == 1
