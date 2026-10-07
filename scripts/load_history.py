"""Load football-data history for one league into Postgres (DATABASE_URL), then print a summary.

Usage: uv run python scripts/load_history.py EPL [first_season] [last_season]
Without DATABASE_URL, loads into a throwaway embedded Postgres so you can check the numbers.
"""
import os
import sys
import tempfile
from pathlib import Path

import psycopg

from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.footballdata import current_season, load_seasons
from pitchside.ingest.load_matches import load_footballdata
from pitchside.leagues import LEAGUES


def run(conn: psycopg.Connection, league_id: str, first: int, last: int) -> None:
    apply_migrations(conn)
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    df = load_seasons(LEAGUES[league_id].fd_code, list(range(first, last + 1)))
    print("loaded", load_footballdata(conn, league_id, df))
    conn.commit()
    print("matches per season:", dict(conn.execute("SELECT season, count(*) FROM matches GROUP BY 1 ORDER BY 1").fetchall()))
    print("teams:", conn.execute("SELECT count(*) FROM teams").fetchone()[0],
          "| goals (home+away):", conn.execute("SELECT sum(ft_home + ft_away) FROM matches").fetchone()[0],
          "| avg goals/match:", round(float(conn.execute("SELECT avg(ft_home + ft_away) FROM matches").fetchone()[0]), 3))
    print("null corners:", conn.execute("SELECT count(*) FROM team_match_stats WHERE corners IS NULL").fetchone()[0])


if __name__ == "__main__":
    league = sys.argv[1] if len(sys.argv) > 1 else "EPL"
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 2015
    last = int(sys.argv[3]) if len(sys.argv) > 3 else current_season()
    _load_env()
    if url := os.environ.get("DATABASE_URL"):
        with psycopg.connect(url) as c:
            run(c, league, first, last)
    else:
        import pgserver
        server = pgserver.get_server(Path(tempfile.mkdtemp()) / "pg")
        try:
            with psycopg.connect(server.get_uri()) as c:
                run(c, league, first, last)
        finally:
            server.cleanup()
