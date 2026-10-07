import datetime as dt

import pandas as pd
import pytest

from pitchside.db.teams import (
    TeamResolver,
    UnknownTeamsError,
    load_aliases,
    seed_leagues,
)
from pitchside.ingest.footballdata import COLUMNS, RAW_DIR, load_seasons, season_code
from pitchside.ingest.load_matches import load_footballdata


@pytest.fixture()
def seeded(conn):
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    return conn


def frame(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    df.insert(0, "season", 2025)
    return df


def row(home="Man City", away="Arsenal", date=dt.date(2025, 8, 17), **kw):
    base = {
        "match_date": date, "home": home, "away": away, "referee": "A Taylor",
        "ft_home": 2, "ft_away": 1, "ht_home": 1, "ht_away": 0,
        "shots_h": 15, "shots_a": 8, "sot_h": 6, "sot_a": 3, "corners_h": 7, "corners_a": 4,
        "fouls_h": 10, "fouls_a": 12, "yellow_h": 1, "yellow_a": 2, "red_h": 0, "red_a": 0,
        "xg_h": pd.NA, "xg_a": pd.NA,
    }
    base.update(kw)
    return [base[c] for c in COLUMNS]


def test_alias_resolution_variants(seeded):
    r = TeamResolver(seeded)
    assert r.resolve("footballdata", "Man City") == r.resolve("understat", "Manchester City")
    assert r.resolve("whoscored", "Wolves") == r.resolve("espn", "Wolverhampton Wanderers")
    assert r.resolve("footballdata", "Not A Club") is None


def test_all_real_epl_names_are_mapped(seeded):
    cached = [RAW_DIR / f"{season_code(y)}_E0.csv" for y in range(2015, 2027)]
    if not all(p.exists() for p in cached):
        pytest.skip("football-data cache not downloaded")
    df = load_seasons("E0", list(range(2015, 2027)))
    ids = TeamResolver(seeded).resolve_all("footballdata", [*df["home"], *df["away"]])
    assert len(set(ids.values())) == 35  # 35 distinct clubs, no two spellings sharing or splitting a club


def test_load_is_idempotent_and_keeps_missing_as_null(seeded):
    df = frame([row(), row(home="Arsenal", away="Wolves", date=dt.date(2025, 8, 24), corners_h=pd.NA, shots_h=pd.NA)])
    assert load_footballdata(seeded, "EPL", df) == {"matches": 2, "team_stats": 4}
    load_footballdata(seeded, "EPL", df)  # second run: no duplicates
    assert seeded.execute("SELECT count(*) FROM matches").fetchone()[0] == 2
    assert seeded.execute("SELECT count(*) FROM team_match_stats").fetchone()[0] == 4
    corners = seeded.execute(
        "SELECT s.corners, s.shots FROM team_match_stats s JOIN matches m ON m.id = s.match_id "
        "JOIN teams t ON t.id = s.team_id WHERE t.canonical_name = 'Arsenal' AND m.match_date = '2025-08-24'"
    ).fetchone()
    assert corners == (None, None)  # missing stays NULL, never 0


def test_unknown_club_blocks_the_whole_load(seeded):
    df = frame([row(), row(home="Imaginary FC", away="Arsenal", date=dt.date(2025, 8, 24))])
    with pytest.raises(UnknownTeamsError, match="Imaginary FC"):
        load_footballdata(seeded, "EPL", df)
    assert seeded.execute("SELECT count(*) FROM matches").fetchone()[0] == 0


def test_rerun_updates_a_corrected_result(seeded):
    load_footballdata(seeded, "EPL", frame([row(ft_home=1, ft_away=1)]))
    load_footballdata(seeded, "EPL", frame([row(ft_home=2, ft_away=1)]))
    assert seeded.execute("SELECT ft_home, ft_away FROM matches").fetchone() == (2, 1)
