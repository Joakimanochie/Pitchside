"""Same-day results: a played match is finished from ESPN's score, its score-based predictions are settled, and the rest wait for the full statistics."""
import datetime as dt
from datetime import UTC, datetime, timedelta

import pytest

from pitchside.confidence import tier_for
from pitchside.db.markets import seed_markets
from pitchside.db.predictions import ensure_model_version, write_predictions
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.markets.registry import MARKETS
from pitchside.pipeline.results import finish_matches
from pitchside.settle.settle import settle_all
from tests.test_cups import summary


@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    seed_markets(conn)
    ensure_model_version(conn, "test-0", "test", {})
    conn.commit()
    return conn


def scheduled(conn, kickoff, espn="900", day_offset=0):
    kickoff = kickoff - timedelta(days=day_offset)
    return conn.execute(
        "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, source_ids) "
        "VALUES ('EPL', 2026, %s, %s, (SELECT id FROM teams WHERE canonical_name = 'Arsenal'), (SELECT id FROM teams WHERE canonical_name = 'Leeds United'), 'scheduled', jsonb_build_object('espn', %s::text)) RETURNING id",
        (kickoff.date(), kickoff, espn)).fetchone()[0]


def payload(status, home_score="2", away_score="1", goals=None):
    s = summary(home_score, away_score, goals if goals is not None else [("goal", "Arsenal", "12'", 1), ("goal", "Porto", "50'", 2), ("goal", "Arsenal", "88'", 2)])
    s["header"]["competitions"][0]["status"] = {"type": {"name": status}}
    return s


def predict(conn, match_id, rows):
    run_id = conn.execute("INSERT INTO prediction_runs (created_at, run_type, model_version_id, feature_version, data_cutoff) "
                          "VALUES (now() - interval '1 day', 'weekly', 'test-0', 'f0', now() - interval '1 day') RETURNING id").fetchone()[0]
    write_predictions(conn, run_id, match_id, rows, MARKETS, {})


def row(market_id, selection, p, line=None):
    return {"market_id": market_id, "line": line, "selection": selection, "probability": p, "p_win": p, "p_lose": 1 - p, "p_push": 0.0}


def fake(payloads):
    return lambda code, event_id: payloads[event_id]


def test_a_played_match_is_finished_and_settled_the_same_day(db):
    mid = scheduled(db, datetime.now(UTC) + timedelta(hours=3))      # predicted before kickoff, then the clock moves on
    predict(db, mid, [row("1x2", "home", 0.5), row("1x2", "away", 0.3)])
    db.execute("UPDATE matches SET kickoff = now() - interval '3 hours' WHERE id = %s", (mid,))
    out = finish_matches(db, fetch=fake({"900": payload("STATUS_FULL_TIME")}))
    assert out["finished"] == 1 and out["matches"] == [mid]
    assert db.execute("SELECT status, ft_home, ft_away, ht_home, ht_away FROM matches WHERE id = %s", (mid,)).fetchone() == ("finished", 2, 1, 1, 0)
    settle_all(db)
    results = dict(db.execute("SELECT p.selection, s.result FROM settlements s JOIN predictions p ON p.id = s.prediction_id WHERE p.market_id = '1x2'").fetchall())
    assert results == {"home": "won", "away": "lost"}


def test_a_match_still_being_played_or_too_recent_is_left_alone(db):
    live = scheduled(db, datetime.now(UTC) - timedelta(hours=3), "901")
    recent = scheduled(db, datetime.now(UTC) - timedelta(minutes=60), "902")
    out = finish_matches(db, fetch=fake({"901": payload("STATUS_SECOND_HALF"), "902": payload("STATUS_FULL_TIME")}))
    assert out["checked"] == 1 and out["finished"] == 0
    assert {r[0] for r in db.execute("SELECT status FROM matches WHERE id IN (%s, %s)", (live, recent))} == {"scheduled"}


def test_goals_that_disagree_with_the_final_score_are_not_stored(db):
    mid = scheduled(db, datetime.now(UTC) - timedelta(hours=3))
    out = finish_matches(db, fetch=fake({"900": payload("STATUS_FULL_TIME", "3", "1")}))
    assert out["finished"] == 0 and out["skipped"] == 1
    assert db.execute("SELECT status FROM matches WHERE id = %s", (mid,)).fetchone()[0] == "scheduled"


def test_a_feed_failure_on_one_match_does_not_stop_the_others(db):
    bad = scheduled(db, datetime.now(UTC) - timedelta(hours=4), "903", day_offset=2)
    good = scheduled(db, datetime.now(UTC) - timedelta(hours=3), "900")

    def fetch(code, event_id):
        if event_id == "903":
            raise OSError("feed down")
        return payload("STATUS_FULL_TIME")

    out = finish_matches(db, fetch=fetch)
    assert out["matches"] == [good] and out["skipped"] == 1 and bad not in out["matches"]


def test_player_markets_are_capped_at_medium():
    rules = {"thresholds": {"min_cell": 1}, "markets": {}, "families": {"I|3": {"tier": "High", "n": 500}, "A|3": {"tier": "High", "n": 500}}}
    assert tier_for(rules, "any", "I", 0.5) == "Medium"
    assert tier_for(rules, "any", "A", 0.5) == "High"


def test_a_player_who_did_not_play_voids_the_card_bet(db):
    mid = db.execute(
        "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, ft_home, ft_away, ht_home, ht_away, source_ids) "
        "VALUES ('EPL', 2026, %s, %s, (SELECT id FROM teams WHERE canonical_name = 'Arsenal'), (SELECT id FROM teams WHERE canonical_name = 'Leeds United'), 'finished', 1, 0, 0, 0, '{\"espn_log\": true}') RETURNING id",
        (dt.date(2026, 10, 10), datetime.now(UTC) + timedelta(hours=2))).fetchone()[0]
    team = db.execute("SELECT id FROM teams WHERE canonical_name = 'Arsenal'").fetchone()[0]
    db.execute("INSERT INTO player_match_log (match_id, team_id, player_name, starter, played, yellow) VALUES (%s,%s,'Starter',true,true,1), (%s,%s,'Unused sub',false,false,0)", (mid, team, mid, team))
    market = next(mid_ for mid_, mk in MARKETS.items() if getattr(mk, "player_stat", None) == "cards")
    predict(db, mid, [row(market, "Starter", 0.3), row(market, "Unused sub", 0.1)])
    settle_all(db)
    got = dict(db.execute("SELECT p.selection, s.result FROM settlements s JOIN predictions p ON p.id = s.prediction_id WHERE p.market_id = %s", (market,)).fetchall())
    assert got == {"Starter": "won", "Unused sub": "void"}
