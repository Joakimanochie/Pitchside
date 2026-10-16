import datetime as dt
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.fixtures import parse_scoreboard, upsert_fixtures
from pitchside.odds.compare import (
    demargin,
    edge,
    expected_value,
    kelly_fraction,
    overround,
)
from pitchside.odds.footballdata_fixtures import parse
from pitchside.odds.provider import OddsRow
from pitchside.odds.store import store_odds

HEADER = "Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,B365>2.5,B365<2.5,Max>2.5,Max<2.5,Avg>2.5,Avg<2.5,AHh,B365AHH,B365AHA,MaxAHH,MaxAHA,AvgAHH,AvgAHA"
EPL_ROW = "E0,17/10/2026,12:30,Arsenal,Leeds,1.30,5.5,9.5,1.33,5.8,10,1.31,5.6,9.2,1.5,2.7,1.55,2.8,1.5,2.65,-1.5,1.95,1.95,2.0,2.0,1.93,1.97"


# ---- comparison maths ------------------------------------------------------------------------------------------

def test_demargin_removes_the_bookmakers_margin():
    odds = [1.31, 5.6, 9.2]
    assert overround(odds) > 0.03
    fair = demargin(odds)
    assert sum(fair) == pytest.approx(1.0)
    assert fair[0] > fair[1] > fair[2]


def test_edge_and_expected_value():
    assert edge(0.60, 0.55) == pytest.approx(0.05)
    assert expected_value(0.5, 2.1) == pytest.approx(0.05)
    assert expected_value(0.4, 2.0) == pytest.approx(-0.2)
    assert kelly_fraction(0.4, 2.0) == 0.0
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)


# ---- parsing fixtures.csv ----------------------------------------------------------------------------------------

def test_parse_reads_three_markets_for_each_bookmaker_and_skips_other_leagues():
    scottish = "SC0,17/10/2026,15:00,Burnley,Charlton,1.6,3.7,5.2,1.7,4,5.5,1.6,3.9,5.2,1.8,2,1.9,2,1.8,1.9,-0.5,1.8,2,1.8,2,1.8,2"
    rows = parse(f"﻿{HEADER}\n{EPL_ROW}\n{scottish}")      # the real file starts with a byte-order mark
    assert {r.league_id for r in rows} == {"EPL"}
    assert len(rows) == 3 * (3 + 2 + 2)     # three bookmakers x (1X2 + over/under + handicap)
    ah = [r for r in rows if r.market_id == "asian_handicap" and r.bookmaker == "avg"]
    assert {(r.selection, r.line, r.odds) for r in ah} == {("home", -1.5, 1.93), ("away", -1.5, 1.97)}
    assert {r.match_date for r in rows} == {dt.date(2026, 10, 17)}


def test_a_market_missing_any_price_is_dropped_whole():
    row = EPL_ROW.replace(",1.5,2.65,", ",1.5,,", 1)          # Avg>2.5 present, Avg<2.5 blank
    rows = parse(f"{HEADER}\n{row}")
    assert not [r for r in rows if r.bookmaker == "avg" and r.market_id == "ou_total"]
    assert [r for r in rows if r.bookmaker == "avg" and r.market_id == "1x2"]


# ---- storing ---------------------------------------------------------------------------------------------------

def espn_event(eid, kickoff, home, away):
    return {"id": str(eid), "date": kickoff.strftime("%Y-%m-%dT%H:%MZ"), "season": {"year": 2026}, "status": {"type": {"name": "STATUS_SCHEDULED"}},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": home}}, {"homeAway": "away", "team": {"displayName": away}}]}]}


class Stub:
    source, name_source = "stub", "footballdata"

    def __init__(self, rows):
        self.rows = rows

    def fetch(self):
        return self.rows


@pytest.fixture()
def world(conn):
    seed_leagues(conn)
    load_aliases(conn)
    kickoff = (datetime.now(UTC) + timedelta(days=3)).replace(hour=14, minute=0, second=0, microsecond=0)
    upsert_fixtures(conn, "EPL", parse_scoreboard({"events": [espn_event(1, kickoff, "Arsenal", "Leeds United")]}))
    conn.commit()
    return conn, kickoff.date()


def row(day, sel="home", odds=1.31, market="1x2", line=None, home="Arsenal", away="Leeds", bookmaker="avg"):
    return OddsRow("EPL", day, home, away, bookmaker, market, line, sel, odds)


def test_odds_are_matched_to_the_scheduled_match_and_stored_once(world):
    conn, day = world
    rows = [row(day, "home", 1.31), row(day, "draw", 5.6), row(day, "away", 9.2)]
    assert store_odds(conn, Stub(rows)) == {"fixtures": 1, "rows_read": 3, "rows_written": 3, "unmatched": [], "unmapped_names": []}
    assert store_odds(conn, Stub(rows))["rows_written"] == 0          # nothing changed, nothing stored
    changed = [row(day, "home", 1.29), row(day, "draw", 5.6), row(day, "away", 9.2)]
    assert store_odds(conn, Stub(changed))["rows_written"] == 1       # only the price that moved
    latest = dict(conn.execute("SELECT selection, odds FROM v_latest_odds").fetchall())
    assert float(latest["home"]) == 1.29
    assert conn.execute("SELECT count(*) FROM odds_snapshots").fetchone()[0] == 4


def test_a_date_one_day_off_still_matches(world):
    conn, day = world
    assert store_odds(conn, Stub([row(day + timedelta(days=1))]))["fixtures"] == 1


def test_unknown_clubs_and_unscheduled_fixtures_are_reported_not_created(world):
    conn, day = world
    got = store_odds(conn, Stub([row(day, home="Nowhere FC"), row(day, home="Chelsea", away="Fulham")]))
    assert got["unmapped_names"] == ["Nowhere FC"]
    assert got["fixtures"] == 0 and got["rows_written"] == 0
    assert got["unmatched"] == [("EPL", day.isoformat(), "Chelsea", "Fulham")]
    assert conn.execute("SELECT count(*) FROM matches").fetchone()[0] == 1


def test_snapshots_are_append_only(world):
    conn, day = world
    store_odds(conn, Stub([row(day)]))
    conn.commit()
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("UPDATE odds_snapshots SET odds = 2")
    conn.rollback()
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM odds_snapshots")


# ---- the block exported to the web app -----------------------------------------------------------------------------

def test_exported_comparison_matches_our_probabilities_to_the_bookmakers_view(world):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from export_app_data import odds_block

    conn, day = world
    avg = [row(day, "home", 1.30), row(day, "draw", 5.6), row(day, "away", 9.2)]
    best = [row(day, "home", 1.33, bookmaker="max"), row(day, "draw", 5.8, bookmaker="max"), row(day, "away", 10.0, bookmaker="max")]
    ou = [row(day, "over", 1.5, market="ou_total", line=2.5), row(day, "under", 2.65, market="ou_total", line=2.5)]
    ah = [row(day, "home", 1.9, market="asian_handicap", line=-1.0), row(day, "away", 2.0, market="asian_handicap", line=-1.0)]
    store_odds(conn, Stub(avg + best + ou + ah))
    match_id = conn.execute("SELECT id FROM matches").fetchone()[0]
    preds = {"1x2": {"null": [["home", 0.80, 1, 0], ["draw", 0.12, 0, 1], ["away", 0.08, 0, 2]]},
             "ou_total": {"2.5": [["over", 0.55, 0, 1], ["under", 0.45, 1, 1]]},
             "asian_handicap": {"-1.0": [["home", 0.5, 0, 1], ["away", 0.5, 0, 1]]}}
    block = odds_block(conn, match_id, preds, {})
    markets = {(m["market"], m["line"]): m for m in block["markets"]}
    x12 = markets[("1x2", None)]
    home = next(r for r in x12["rows"] if r["selection"] == "home")
    assert home["best_odds"] == 1.33 and home["avg_odds"] == 1.30
    assert home["edge"] == pytest.approx(0.80 - home["fair"], abs=1e-4)
    assert home["ev"] == pytest.approx(0.80 * 1.33 - 1, abs=1e-4)
    assert sum(r["fair"] for r in x12["rows"]) == pytest.approx(1.0, abs=1e-3)
    assert markets[("ou_total", 2.5)]["rows"][0]["ev"] is not None
    assert markets[("asian_handicap", -1.0)]["stake_can_be_returned"] is True
    assert all(r["ev"] is None for r in markets[("asian_handicap", -1.0)]["rows"])


def test_no_comparison_when_no_prices_or_when_a_market_is_incomplete(world):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from export_app_data import odds_block

    conn, day = world
    match_id = conn.execute("SELECT id FROM matches").fetchone()[0]
    assert odds_block(conn, match_id, {}, {}) is None
    store_odds(conn, Stub([row(day, "home", 1.3), row(day, "draw", 5.6)]))       # no away price: not a complete market
    assert odds_block(conn, match_id, {"1x2": {"null": [["home", 0.8, 1, 0], ["draw", 0.1, 0, 1], ["away", 0.1, 0, 2]]}}, {}) is None
