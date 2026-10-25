"""Same-day results: finish the matches that have been played and score their predictions without waiting for the next morning.

    uv run python -m pitchside.pipeline.results

football-data.co.uk publishes a day late, so the daily job only scored yesterday's matches this morning. This job asks ESPN about every
scheduled match whose kickoff is more than 110 minutes ago, and when ESPN says it is over it stores the full-time and half-time score
(built from the goals ESPN dates to each half and checked against ESPN's own final score, as for the cups) and settles. Everything that
is decided by the score is settled at once: result, totals, both teams to score, correct score, halves, handicaps.

Corners, cards, shots and player markets wait for the full statistics, which football-data and Understat publish the next day; those predictions
stay "not yet scored" until the daily job brings them in, and are then settled by the same function. The score stored here is replaced by the
football-data one when it arrives (and the predictions are re-settled if the two ever differed). Prints `finished=N` for the workflow, which only
exports and deploys when something changed.
"""
import json
import os
from datetime import UTC, datetime, timedelta

import psycopg

from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.ingest.espn_cups import fetch_summary, parse_result
from pitchside.leagues import LEAGUES
from pitchside.settle.settle import settle_all

OVER_AFTER = timedelta(minutes=110)    # 90 minutes, the interval, stoppage time and a margin
GIVE_UP_AFTER = timedelta(days=4)      # the daily job takes over from here
FINAL = "STATUS_FULL_TIME"
FINAL_BEYOND_90 = ("STATUS_FINAL_AET", "STATUS_FINAL_PEN")
CALLED_OFF = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED")


def status_of(payload: dict) -> str | None:
    comp = (payload.get("header", {}).get("competitions") or [{}])[0]
    return comp.get("status", {}).get("type", {}).get("name")


def finish_matches(conn: psycopg.Connection, now: datetime | None = None, fetch=fetch_summary) -> dict:
    """Store the score of every scheduled match that ESPN reports as finished. Returns {'checked', 'finished', 'skipped', 'matches'}."""
    now = now or datetime.now(UTC)
    rows = conn.execute(
        "SELECT m.id, m.league_id, m.source_ids->>'espn' FROM matches m "
        "WHERE m.status = 'scheduled' AND m.source_ids ? 'espn' AND m.kickoff < %s AND m.kickoff > %s ORDER BY m.kickoff",
        (now - OVER_AFTER, now - GIVE_UP_AFTER)).fetchall()
    finished: list[int] = []
    skipped = 0
    for match_id, league_id, event in rows:
        try:
            payload = fetch(LEAGUES[league_id].espn_code, event)
        except Exception as e:  # noqa: BLE001 - one match's feed trouble must not stop the others; it is retried on the next run
            print(f"results: match {match_id}: {e}")
            skipped += 1
            continue
        status = status_of(payload)
        if status not in (FINAL, *FINAL_BEYOND_90):
            if status in CALLED_OFF:
                print(f"results: match {match_id} is {status}; left for the daily job")
            continue
        parsed = parse_result(payload, beyond_90=status in FINAL_BEYOND_90)
        if parsed is None:         # goals that do not add up to ESPN's own score: do not guess; football-data settles it tomorrow
            print(f"results: match {match_id}: goals do not match the final score; left for the daily job")
            skipped += 1
            continue
        conn.execute(
            "UPDATE matches SET status = 'finished', ft_home = %s, ft_away = %s, ht_home = %s, ht_away = %s WHERE id = %s AND status = 'scheduled'",
            (parsed["ft"][0], parsed["ft"][1], parsed["ht"][0], parsed["ht"][1], match_id))
        finished.append(match_id)
    conn.commit()
    return {"checked": len(rows), "finished": len(finished), "skipped": skipped, "matches": finished}


def run(conn: psycopg.Connection) -> dict:
    apply_migrations(conn)
    done = finish_matches(conn)
    settled = settle_all(conn) if done["finished"] else {}
    return {**done, "settled": settled}


if __name__ == "__main__":
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        result = run(c)
    print(json.dumps(result, default=str))
    print(f"finished={result['finished']}")
