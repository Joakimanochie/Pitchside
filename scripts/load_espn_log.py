"""Backfill ESPN event ids, cards with minutes and per-player fouls/cards for finished matches from a first season on (default 2023/24).

    uv run python scripts/load_espn_log.py [first_season] [LEAGUE ...]

Idempotent and resumable: matches that already have a verdict (espn_log true/false) are skipped. Polite: four requests at a time.
Writes to the production database (DATABASE_URL), the same way the daily job does.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import requests

from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.ingest.espn_log import (
    BASE,
    attach_event_ids,
    parse_log,
    store_log,
    team_card_counts,
    verified,
)
from pitchside.leagues import LEAGUES


def fetch(args):
    code, event = args
    for attempt in range(3):
        try:
            r = requests.get(BASE.format(code=code) + "summary", params={"event": event}, timeout=40)
            r.raise_for_status()
            return parse_log(r.json())
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"giving up on event {event}: {e}", flush=True)
    return "failed"


def main(first_season: int, league_ids: list[str]) -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        apply_migrations(conn)
        conn.commit()
        for lid in league_ids:
            lg = LEAGUES[lid]
            days = [r[0] for r in conn.execute(
                "SELECT DISTINCT match_date FROM matches WHERE league_id = %s AND status = 'finished' AND season >= %s AND NOT (source_ids ? 'espn') ORDER BY 1", (lid, first_season))]
            print(f"{lid}: {len(days)} dates without ESPN ids", flush=True)
            got = 0
            for i in range(0, len(days), 20):
                got += attach_event_ids(conn, lid, lg.espn_code, days[i:i + 20])
                if i % 100 == 0:
                    print(f"  ids attached so far {got} ({i}/{len(days)} dates)", flush=True)
            left = conn.execute("SELECT count(*) FROM matches WHERE league_id = %s AND status = 'finished' AND season >= %s AND NOT (source_ids ? 'espn')", (lid, first_season)).fetchone()[0]
            if left:     # a late kickoff can sit on the next date in ESPN's calendar
                more = [d + timedelta(days=1) for d in days]
                for i in range(0, len(more), 20):
                    got += attach_event_ids(conn, lid, lg.espn_code, more[i:i + 20])
            print(f"{lid}: event ids attached {got}", flush=True)

            rows = conn.execute(
                "SELECT id, home_team_id, away_team_id, source_ids->>'espn' FROM matches WHERE league_id = %s AND status = 'finished' AND season >= %s "
                "AND source_ids ? 'espn' AND NOT (source_ids ? 'espn_log') ORDER BY match_date", (lid, first_season)).fetchall()
            print(f"{lid}: {len(rows)} match logs to fetch", flush=True)
            ok = bad = failed = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                for n, ((match_id, home_id, away_id, _event), parsed) in enumerate(zip(rows, pool.map(fetch, [(lg.espn_code, r[3]) for r in rows]), strict=True)):
                    if parsed == "failed" or parsed is None:
                        failed += 1
                        continue
                    good = verified(parsed, team_card_counts(conn, match_id))
                    store_log(conn, match_id, home_id, away_id, parsed, good)
                    ok += good
                    bad += not good
                    if n % 100 == 0:
                        conn.commit()
                        print(f"  {n}/{len(rows)}: verified {ok}, unverified {bad}, failed {failed}", flush=True)
            conn.commit()
            print(f"{lid}: verified {ok}, unverified {bad}, failed {failed}", flush=True)


if __name__ == "__main__":
    first = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 2023
    leagues = [a.upper() for a in sys.argv[1:] if not a.isdigit()] or sorted(LEAGUES)
    main(first, leagues)
