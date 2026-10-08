"""Load verified Understat goal minutes into Postgres (DATABASE_URL), or into a throwaway database if it is not set.

Usage: uv run python scripts/load_goal_minutes.py [first_season] [last_season] [LEAGUE ...]
Needs the Understat shot events in the soccerdata cache (scripts/pull_understat.py) and the results already loaded.
"""
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SOCCERDATA_DIR", str(ROOT / "data" / "raw" / "soccerdata"))
logging.disable(logging.CRITICAL)

import psycopg
import soccerdata as sd

from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.footballdata import load_seasons
from pitchside.ingest.load_matches import load_footballdata
from pitchside.ingest.understat_goals import load_goals
from pitchside.leagues import LEAGUES


def run(conn: psycopg.Connection, first: int, last: int, league_ids: list[str], load_results: bool) -> None:
    apply_migrations(conn)
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    grand = {"loaded": 0, "goals": 0, "bad": 0}
    for lid in league_ids:
        lg = LEAGUES[lid]
        if load_results:
            load_footballdata(conn, lid, load_seasons(lg.fd_code, list(range(first, last + 1))))
            conn.commit()
        for season in range(first, last + 1):
            us = sd.Understat(lg.understat, str(season))
            out = load_goals(conn, lid, season, us.read_shot_events().reset_index(), us.read_schedule().reset_index())
            conn.commit()
            finished = conn.execute("SELECT count(*) FROM matches WHERE league_id = %s AND season = %s AND status = 'finished'",
                                    (lid, season)).fetchone()[0]
            print(f"{lid:10} {season}: finished {finished:3} | verified {out['loaded']:3} ({out['loaded'] / max(finished, 1):.1%}) "
                  f"| goals {out['goals']:4} | inconsistent {len(out['inconsistent'])}", flush=True)
            for bad in out["inconsistent"][:5]:
                print("      ", bad, flush=True)
            grand["loaded"] += out["loaded"]; grand["goals"] += out["goals"]; grand["bad"] += len(out["inconsistent"])
    print("TOTAL", grand, flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    first = int(args[0]) if args else 2025
    last = int(args[1]) if len(args) > 1 else 2026
    leagues = [a.upper() for a in args[2:]] or sorted(LEAGUES)
    _load_env()
    if url := os.environ.get("DATABASE_URL"):
        with psycopg.connect(url) as c:
            run(c, first, last, leagues, load_results=False)
    else:
        import pgserver
        server = pgserver.get_server(Path(tempfile.mkdtemp()) / "pg")
        try:
            with psycopg.connect(server.get_uri()) as c:
                run(c, first, last, leagues, load_results=True)
                print("share of goals in the first half:",
                      c.execute("SELECT round(avg((period = 1)::int)::numeric, 4) FROM match_events").fetchone()[0])
        finally:
            server.cleanup()
