import datetime as dt
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from pitchside.db.teams import UnknownTeamsError, load_aliases, seed_leagues
from pitchside.ingest.fixtures import parse_scoreboard, upsert_fixtures
from pitchside.ingest.footballdata import RAW_DIR, load_seasons, season_code
from pitchside.ingest.load_matches import load_footballdata
from pitchside.leagues import LEAGUES
from pitchside.markets.goals import price_match
from pitchside.markets.registry import MARKETS
from pitchside.models.dixon_coles import DixonColes
from pitchside.pipeline.weekly import (
    MODEL_PARAMS,
    MODEL_VERSION,
    InsufficientHistoryError,
    load_history,
    predict_week,
)

YEARS = list(range(2021, 2027))


def event(eid, kickoff, home, away, status="STATUS_SCHEDULED"):
    return {"id": str(eid), "date": kickoff.strftime("%Y-%m-%dT%H:%MZ"), "season": {"year": 2026},
            "status": {"type": {"name": status}},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": home}},
                                              {"homeAway": "away", "team": {"displayName": away}}]}]}


def in_days(n, hour=14):
    d = datetime.now(UTC) + timedelta(days=n)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


@pytest.fixture()
def world(conn):
    """Embedded Postgres with real Premier League results loaded."""
    if not all((RAW_DIR / f"{season_code(y)}_E0.csv").exists() for y in YEARS):
        pytest.skip("football-data cache not downloaded")
    seed_leagues(conn)
    load_aliases(conn)
    load_footballdata(conn, "EPL", load_seasons("E0", YEARS))
    conn.commit()
    return conn


def fixtures_payload(*events):
    return parse_scoreboard({"events": list(events)})


# ---- ESPN parsing ----------------------------------------------------------------------------------------------

def test_parse_keeps_scheduled_and_called_off_but_skips_live_and_finished():
    k = in_days(2)
    got = fixtures_payload(event(1, k, "Arsenal", "Leeds United"),
                           event(2, k, "Chelsea", "Fulham", "STATUS_IN_PROGRESS"),
                           event(3, k, "Everton", "Burnley", "STATUS_FULL_TIME"),
                           event(4, k, "Liverpool", "Brentford", "STATUS_POSTPONED"))
    assert [(f["espn_id"], f["status"]) for f in got] == [("1", "scheduled"), ("4", "postponed")]


def test_match_date_is_the_uk_local_date():
    # 23:30 UTC on a BST day is 00:30 the next day in London
    k = datetime(2026, 7, 14, 23, 30, tzinfo=UTC)
    [f] = fixtures_payload(event(1, k, "Arsenal", "Leeds United"))
    assert f["kickoff"] == k and f["match_date"] == dt.date(2026, 7, 15)


# ---- storing fixtures ------------------------------------------------------------------------------------------

def test_fixtures_are_stored_and_idempotent(world):
    fx = fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United"), event(2, in_days(2), "Chelsea", "AFC Bournemouth"))
    assert upsert_fixtures(world, "EPL", fx) == {"scheduled": 2, "postponed": 0}
    upsert_fixtures(world, "EPL", fx)
    assert world.execute("SELECT count(*) FROM matches WHERE status = 'scheduled'").fetchone()[0] == 2


def test_unknown_club_blocks_all_fixtures(world):
    fx = fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United"), event(2, in_days(2), "Made Up FC", "Chelsea"))
    with pytest.raises(UnknownTeamsError, match="Made Up FC"):
        upsert_fixtures(world, "EPL", fx)
    assert world.execute("SELECT count(*) FROM matches WHERE status = 'scheduled'").fetchone()[0] == 0


def test_called_off_fixture_is_marked_postponed(world):
    k = in_days(3)
    upsert_fixtures(world, "EPL", fixtures_payload(event(1, k, "Liverpool", "Brentford")))
    out = upsert_fixtures(world, "EPL", fixtures_payload(event(1, k, "Liverpool", "Brentford", "STATUS_POSTPONED")))
    assert out["postponed"] == 1
    assert world.execute("SELECT status FROM matches WHERE status <> 'finished' AND season = 2026").fetchone()[0] == "postponed"


def test_result_updates_the_scheduled_row_instead_of_duplicating_it(world):
    # a fixture we scheduled for tomorrow is actually played the day after; the result must land on the same row
    played = (datetime.now(UTC) + timedelta(days=2)).date()
    scheduled_day = in_days(1)
    upsert_fixtures(world, "EPL", fixtures_payload(event(1, scheduled_day, "Arsenal", "Leeds United")))
    before = world.execute("SELECT id FROM matches WHERE status = 'scheduled'").fetchone()[0]
    import pandas as pd

    from pitchside.ingest.footballdata import COLUMNS
    row = dict.fromkeys(COLUMNS)
    row.update(match_date=played, home="Arsenal", away="Leeds", ft_home=3, ft_away=0, ht_home=1, ht_away=0)
    df = pd.DataFrame([[row[c] for c in COLUMNS]], columns=COLUMNS)
    df.insert(0, "season", 2026)
    load_footballdata(world, "EPL", df)
    rows = world.execute("SELECT id, status, match_date, ft_home FROM matches WHERE id = %s", (before,)).fetchall()
    assert rows == [(before, "finished", played, 3)]
    assert world.execute("SELECT count(*) FROM matches WHERE season = 2026 AND status = 'scheduled'").fetchone()[0] == 0


# ---- predicting a week -----------------------------------------------------------------------------------------

def test_prediction_run_is_complete_valid_and_frozen(world):
    upsert_fixtures(world, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United"),
                                                    event(2, in_days(2), "Chelsea", "AFC Bournemouth")))
    today = datetime.now(UTC).date()
    out = predict_week(world, "EPL", today, days=8)
    per_match = len(price_match(__import__("numpy").full((11, 11), 1 / 121)))
    assert out["matches"] == 2 and out["predictions"] == 2 * per_match
    assert world.execute("SELECT count(*) FROM predictions WHERE probability < 0 OR probability > 1").fetchone()[0] == 0

    # exactly one pick per exclusive (market, line); none for markets whose selections overlap
    for match_id in [r[0] for r in world.execute("SELECT DISTINCT match_id FROM predictions")]:
        picks = world.execute("SELECT market_id, line, count(*) FILTER (WHERE is_pick) FROM predictions "
                              "WHERE match_id = %s GROUP BY 1, 2", (match_id,)).fetchall()
        for market_id, _line, n in picks:
            assert n == (1 if MARKETS[market_id].exclusive else 0), market_id

    run = world.execute("SELECT model_version_id, run_type, data_cutoff FROM prediction_runs").fetchall()
    assert run == [(MODEL_VERSION, "weekly", datetime.combine(today, dt.time.min, tzinfo=UTC))]
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        world.execute("UPDATE predictions SET probability = 0.5")
    world.rollback()


def test_predictions_equal_a_direct_fit_on_the_same_history(world):
    upsert_fixtures(world, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United")))
    today = datetime.now(UTC).date()
    predict_week(world, "EPL", today, days=8)
    model = DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"]).fit(
        load_history(world, "EPL"), as_of=today)
    expected = {(r["market_id"], r["line"], r["selection"]): r["probability"] for r in price_match(model.score_matrix("Arsenal", "Leeds United"))}
    stored = {(m, None if ln is None else float(ln), s): float(p) for m, ln, s, p in
              world.execute("SELECT market_id, line, selection, probability FROM predictions")}
    assert stored.keys() == expected.keys()
    assert max(abs(stored[k] - expected[k]) for k in stored) < 1e-6


def test_second_run_finds_nothing_new_unless_forced(world):
    upsert_fixtures(world, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United")))
    today = datetime.now(UTC).date()
    assert predict_week(world, "EPL", today, days=8)["run_id"]
    assert predict_week(world, "EPL", today, days=8)["run_id"] is None
    assert predict_week(world, "EPL", today, days=8, force=True)["run_id"]
    assert world.execute("SELECT count(*) FROM prediction_runs").fetchone()[0] == 2


def test_only_future_fixtures_inside_the_window_are_predicted(world):
    upsert_fixtures(world, "EPL", fixtures_payload(
        event(1, in_days(2), "Arsenal", "Leeds United"),            # in window
        event(2, in_days(20), "Chelsea", "AFC Bournemouth"),        # beyond the window
        event(3, datetime.now(UTC) - timedelta(hours=3), "Liverpool", "Brentford"),  # already kicked off
    ))
    out = predict_week(world, "EPL", datetime.now(UTC).date(), days=8)
    assert out["matches"] == 1


def test_no_fixtures_means_no_run(world):
    out = predict_week(world, "EPL", datetime.now(UTC).date(), days=8)
    assert out["run_id"] is None and world.execute("SELECT count(*) FROM prediction_runs").fetchone()[0] == 0


def test_refuses_to_predict_without_enough_history(conn):
    seed_leagues(conn)
    load_aliases(conn)
    load_footballdata(conn, "EPL", load_seasons("E0", [2025, 2026]))  # about 430 matches
    conn.commit()
    upsert_fixtures(conn, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United")))
    with pytest.raises(InsufficientHistoryError, match="load_history.py"):
        predict_week(conn, "EPL", datetime.now(UTC).date(), days=8)
    assert conn.execute("SELECT count(*) FROM prediction_runs").fetchone()[0] == 0


def test_a_match_is_predicted_once_per_model_version_across_daily_runs(world):
    upsert_fixtures(world, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United")))
    today = datetime.now(UTC).date()
    first = predict_week(world, "EPL", today, days=8)
    assert first["matches"] == 1
    # the next day's run sees the same fixture plus a new one: only the new one is predicted
    upsert_fixtures(world, "EPL", fixtures_payload(event(2, in_days(5), "Chelsea", "AFC Bournemouth")))
    second = predict_week(world, "EPL", today + timedelta(days=1), days=8)
    assert second["matches"] == 1
    per_match = world.execute("SELECT match_id, count(DISTINCT run_id) FROM predictions GROUP BY 1").fetchall()
    assert all(n == 1 for _, n in per_match) and len(per_match) == 2
    # a third run with nothing new creates nothing
    third = predict_week(world, "EPL", today + timedelta(days=2), days=8)
    assert third["run_id"] is None and world.execute("SELECT count(*) FROM prediction_runs").fetchone()[0] == 2


def test_one_league_failing_does_not_stop_the_others(conn, monkeypatch):
    from pitchside.pipeline import weekly

    calls = []

    def fake_ingest(c, league_id, *a, **k):
        if league_id == "LALIGA":
            raise RuntimeError("football-data is down")
        calls.append(("ingest", league_id))
        return {"matches": 1}

    monkeypatch.setattr(weekly, "ingest_results", fake_ingest)
    monkeypatch.setattr(weekly, "plan_fixtures", lambda c, lid, start, days: calls.append(("fixtures", lid)) or {})
    monkeypatch.setattr(weekly, "predict_week", lambda c, lid, as_of, days, force=False: calls.append(("predict", lid)) or {})
    report, errors = weekly.run_leagues(conn, ["EPL", "LALIGA", "SERIEA"], days=5)

    assert list(errors) == ["LALIGA/results"] and "football-data is down" in errors["LALIGA/results"]
    assert ("predict", "EPL") in calls and ("predict", "SERIEA") in calls
    assert report["EPL"]["results"] == {"matches": 1} and "settle" in report
    assert conn.execute("SELECT count(*) FROM leagues").fetchone()[0] == len(LEAGUES)  # connection still usable


def test_league_argument_parsing():
    from pitchside.pipeline.weekly import parse_leagues

    assert parse_leagues(["ALL"]) == sorted(LEAGUES)
    assert parse_leagues(["epl", "laliga"]) == ["EPL", "LALIGA"]
    with pytest.raises(SystemExit):
        parse_leagues(["MARS"])
