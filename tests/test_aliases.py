import csv
import json
from collections import defaultdict

import pytest

from pitchside.db.teams import ALIASES_CSV, TeamResolver, load_aliases, seed_leagues
from pitchside.ingest.footballdata import RAW_DIR, load_seasons, season_code
from pitchside.leagues import LEAGUES

EXPECTED_CLUBS = {"EPL": 35, "LALIGA": 32, "BUNDESLIGA": 31, "SERIEA": 35, "LIGUE1": 34}
ESPN_SNAPSHOT = ALIASES_CSV.parent / "processed" / "phase1b_names.json"
YEARS = list(range(2015, 2027))


def rows():
    with ALIASES_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_no_spelling_points_to_two_different_clubs():
    seen = defaultdict(set)
    for r in rows():
        seen[(r["source"], r["alias"])].add(r["canonical"])
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    assert clashes == {}


def test_every_club_belongs_to_exactly_one_league():
    owner = defaultdict(set)
    for r in rows():
        owner[r["canonical"]].add(r["league"])
    assert {c: lg for c, lg in owner.items() if len(lg) > 1} == {}


def test_club_counts_per_league():
    clubs = defaultdict(set)
    for r in rows():
        clubs[r["league"]].add(r["canonical"])
    assert {lg: len(c) for lg, c in clubs.items()} == EXPECTED_CLUBS
    assert set(clubs) == set(LEAGUES)


@pytest.mark.parametrize("league_id", sorted(LEAGUES))
def test_every_football_data_name_resolves_to_that_leagues_clubs(conn, league_id):
    lg = LEAGUES[league_id]
    if not all((RAW_DIR / f"{season_code(y)}_{lg.fd_code}.csv").exists() for y in YEARS):
        pytest.skip("football-data cache not downloaded")
    seed_leagues(conn)
    load_aliases(conn)
    df = load_seasons(lg.fd_code, YEARS)
    names = set(df["home"]) | set(df["away"])
    ids = TeamResolver(conn).resolve_all("footballdata", names)
    assert len(set(ids.values())) == EXPECTED_CLUBS[league_id]  # every club once: no split, no merge


@pytest.mark.parametrize("league_id", ["LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1"])
def test_every_espn_name_resolves(conn, league_id):
    if not ESPN_SNAPSHOT.exists():
        pytest.skip("ESPN name snapshot missing")
    seed_leagues(conn)
    load_aliases(conn)
    espn = json.loads(ESPN_SNAPSHOT.read_text(encoding="utf-8"))[league_id]["espn"]
    resolver = TeamResolver(conn)
    assert [n for n in espn if resolver.resolve("espn", n) is None] == []
