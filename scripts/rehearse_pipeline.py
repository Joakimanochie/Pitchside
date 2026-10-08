"""Dress rehearsal of the whole daily pipeline on a throwaway embedded Postgres (never touches the real database).

Loads history and verified goal minutes from local caches, then runs the real five-league pipeline against the live
fixtures feed, and prints what it produced. Use it before changing anything the daily job depends on.

Usage: uv run python scripts/rehearse_pipeline.py [n_sims]
"""
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SOCCERDATA_DIR", str(ROOT / "data" / "raw" / "soccerdata"))
logging.disable(logging.CRITICAL)
os.environ["DATABASE_URL"] = ""      # make sure nothing below can fall through to the real database

import pgserver
import psycopg
import soccerdata as sd

from pitchside.db.migrate import apply_migrations
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.footballdata import load_seasons
from pitchside.ingest.load_matches import load_footballdata
from pitchside.ingest.understat_goals import load_goals
from pitchside.leagues import LEAGUES
from pitchside.pipeline import weekly
from pitchside.pipeline.goal_minutes import read_season_events

if __name__ == "__main__":
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else weekly.N_SIMS
    server = pgserver.get_server(Path(tempfile.mkdtemp()) / "pg")
    try:
        with psycopg.connect(server.get_uri()) as c:
            apply_migrations(c); seed_leagues(c); load_aliases(c); c.commit()
            t = time.time()
            for lid, lg in LEAGUES.items():
                load_footballdata(c, lid, load_seasons(lg.fd_code, list(range(2015, 2027)))); c.commit()
                for season in (2023, 2024, 2025, 2026):
                    us = sd.Understat(lg.understat, str(season))
                    schedule = us.read_schedule().reset_index()
                    events = read_season_events(us, schedule)
                    load_goals(c, lid, season, events, schedule); c.commit()
            print(f"loaded history and goal minutes in {time.time() - t:.0f}s", flush=True)

            weekly.N_SIMS = n_sims
            t = time.time()
            report, errors = weekly.run_leagues(c, sorted(LEAGUES), days=8)
            print(f"pipeline ran in {time.time() - t:.0f}s | errors: {errors}", flush=True)
            for lid in sorted(LEAGUES):
                print(f"  {lid:10} goal_minutes={report[lid].get('goal_minutes')} | predictions={report[lid].get('predictions')}")
            print("settle:", report.get("settle"))
            q = lambda sql: c.execute(sql).fetchall()
            print("\nrows by family:", q("SELECT mk.family, count(*) FROM predictions p JOIN markets mk ON mk.id = p.market_id GROUP BY 1 ORDER BY 1"))
            print("runs:", q("SELECT notes FROM prediction_runs ORDER BY created_at"))
            print("context rows:", q("SELECT count(*) FROM prediction_context")[0][0], "| predictions:", q("SELECT count(*) FROM predictions")[0][0])
            print("table size:", q("SELECT pg_size_pretty(pg_total_relation_size('predictions'))")[0][0],
                  "| per row bytes:", q("SELECT pg_total_relation_size('predictions') / greatest(count(*), 1) FROM predictions")[0][0])
            print("\nArsenal v Leeds, selected markets:")
            for r in q("""SELECT p.market_id, p.line, p.selection, round(p.probability::numeric, 3) FROM predictions p
                JOIN matches m ON m.id = p.match_id JOIN teams th ON th.id = m.home_team_id
                WHERE th.canonical_name = 'Arsenal' AND ((p.market_id IN ('1x2', 'ht_ft', 'first_goal', 'x12_1up', 'x12_never_down', 'home_win_from_behind', 'highest_scoring_half'))
                  OR (p.market_id = 'first_goal_15') OR (p.market_id = 'ou_total' AND p.line = 2.5))
                ORDER BY p.market_id, p.selection"""):
                print("   ", r)
    finally:
        server.cleanup()

