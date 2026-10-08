import datetime as dt
import json
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


# ---- the full simulator path ------------------------------------------------------------------------------------------------

def add_synthetic_goal_minutes(conn):
    """Self-consistent goal events for every finished match: goals placed in the right half with random minutes."""
    rng = __import__("numpy").random.default_rng(0)
    rows = conn.execute("SELECT id, home_team_id, away_team_id, ft_home, ft_away, ht_home, ht_away FROM matches "
                        "WHERE status = 'finished' AND ht_home IS NOT NULL").fetchall()
    events, ids = [], []
    for mid, hid, aid, fh, fa, hh, ha in rows:
        ids.append(mid)
        for side, team, ft_n, ht_n in (("home", hid, fh, hh), ("away", aid, fa, ha)):
            for k in range(ft_n):
                first = k < ht_n
                minute = int(rng.integers(1, 46)) if first else int(rng.integers(46, 91))
                events.append((mid, team, "goal", 1 if first else 2, minute, json.dumps({"side": side}), "understat"))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO match_events (match_id, team_id, event_type, period, minute, details, source) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)", events)
        cur.execute("UPDATE matches SET source_ids = source_ids || '{\"goal_minutes\": true}'::jsonb WHERE id = ANY(%s)", (ids,))
    conn.commit()


@pytest.fixture()
def world_sim(world):
    add_synthetic_goal_minutes(world)
    return world


def test_prediction_run_prices_every_family_and_stores_context_once_per_match(world_sim):
    from pitchside.sim.inputs import fit_split_table, fit_time_profile
    from pitchside.sim.pricing import price_all

    upsert_fixtures(world_sim, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United"),
                                                       event(2, in_days(2), "Chelsea", "AFC Bournemouth")))
    out = predict_week(world_sim, "EPL", datetime.now(UTC).date(), days=8, n_sims=3000)
    assert out["families"] == "ABCDE" and out["matches"] == 2
    per_match = len(price_all(__import__("numpy").full((11, 11), 1 / 121), fit_split_table(world_sim), fit_time_profile(world_sim), 200, seed=0))
    assert out["predictions"] == 2 * per_match and per_match > 900
    fams = {r[0] for r in world_sim.execute("SELECT DISTINCT mk.family FROM predictions p JOIN markets mk ON mk.id = p.market_id")}
    assert fams == {"A", "B", "C", "D", "E"}
    assert world_sim.execute("SELECT count(*) FROM predictions WHERE probability < 0 OR probability > 1").fetchone()[0] == 0
    ctx = world_sim.execute("SELECT count(*), count(DISTINCT match_id) FROM prediction_context").fetchone()
    assert ctx == (2, 2)                                           # once per match, not once per prediction row
    c = world_sim.execute("SELECT context FROM prediction_context LIMIT 1").fetchone()[0]
    assert c["families"] == "ABCDE" and c["n_sims"] == 3000 and c["lambda_home"] > 0
    # rows carry no copy of the context: 'why' is empty unless a push is possible
    assert world_sim.execute("SELECT count(*) FROM predictions WHERE why ? 'lambda_home'").fetchone()[0] == 0


def test_family_a_stays_exact_while_the_simulated_families_agree_with_it(world_sim):
    upsert_fixtures(world_sim, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United")))
    predict_week(world_sim, "EPL", datetime.now(UTC).date(), days=8, n_sims=20_000)
    rows = {(m, None if ln is None else float(ln), s): float(p) for m, ln, s, p in
            world_sim.execute("SELECT market_id, line, selection, probability FROM predictions")}
    # exact family A prices and simulated families describe the same match: related events must agree
    home_win = rows[("1x2", None, "home")]
    sim_home_win = sum(v for (m, ln, s), v in rows.items() if m == "x12_ou_25" and s.startswith("home&"))
    assert sim_home_win == pytest.approx(home_win, abs=0.012)
    p_over = rows[("ou_total", 2.5, "over")]
    assert sum(v for (m, ln, s), v in rows.items() if m == "x12_ou_25" and s.endswith("&over")) == pytest.approx(p_over, abs=0.012)
    assert 1 - sum(v for (m, ln, s), v in rows.items() if m == "first_goal" and s == "none") == pytest.approx(1 - rows[("correct_score", None, "0:0")], abs=0.012)


def test_without_verified_goal_minutes_only_family_a_is_priced_and_says_so(world):
    upsert_fixtures(world, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United")))
    out = predict_week(world, "EPL", datetime.now(UTC).date(), days=8)
    assert out["families"] == "A"
    assert world.execute("SELECT DISTINCT mk.family FROM predictions p JOIN markets mk ON mk.id = p.market_id").fetchall() == [("A",)]
    assert world.execute("SELECT context ->> 'families' FROM prediction_context").fetchone()[0] == "A"


def test_context_is_append_only(world_sim):
    upsert_fixtures(world_sim, "EPL", fixtures_payload(event(1, in_days(2), "Arsenal", "Leeds United")))
    predict_week(world_sim, "EPL", datetime.now(UTC).date(), days=8, n_sims=1000)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        world_sim.execute("UPDATE prediction_context SET context = '{}'")
    world_sim.rollback()
