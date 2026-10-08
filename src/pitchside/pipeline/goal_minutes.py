"""Daily step: fetch goal minutes (Understat) for matches that just finished and verify them against the real scores.

Polite by design: it asks Understat only for matches we do not have verified minutes for, never the whole season.
  - A match whose shot data is not published yet is left untouched and retried on the next run.
  - A match whose goals do not add up to the real score is flagged unverified (its goal-minute markets stay
    'not_scorable'); matches that finished in the last RETRY_DAYS days are retried, in case Understat was still updating.
"""
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg

from pitchside.db.teams import TeamResolver
from pitchside.ingest.footballdata import current_season
from pitchside.ingest.understat_goals import SOURCE, load_goals
from pitchside.leagues import LEAGUES

RETRY_DAYS = 3
log = logging.getLogger(__name__)


def understat_client(league_name: str, season: int):
    import soccerdata as sd  # imported here: only this step needs it

    return sd.Understat(league_name, str(season))


def pending_matches(conn: psycopg.Connection, league_id: str, season: int) -> set[tuple[int, int]]:
    """(home_team_id, away_team_id) of finished matches still needing verified goal minutes."""
    retry_from = (datetime.now(UTC) - timedelta(days=RETRY_DAYS)).date()
    rows = conn.execute(
        "SELECT home_team_id, away_team_id FROM matches WHERE league_id = %s AND season = %s AND status = 'finished' "
        "AND ht_home IS NOT NULL AND (NOT (source_ids ? 'goal_minutes') "
        "OR (source_ids ->> 'goal_minutes' = 'false' AND match_date >= %s))", (league_id, season, retry_from)).fetchall()
    return {(h, a) for h, a in rows}


def ingest_goal_minutes(conn: psycopg.Connection, league_id: str, season: int | None = None,
                        client_factory: Callable = understat_client) -> dict:
    season = current_season() if season is None else season
    pending = pending_matches(conn, league_id, season)
    if not pending:
        return {"pending": 0, "fetched": 0, "loaded": 0}

    us = client_factory(LEAGUES[league_id].understat, season)
    schedule = us.read_schedule().reset_index()
    resolver = TeamResolver(conn)
    ids = resolver.resolve_all(SOURCE, [*schedule["home_team"], *schedule["away_team"]])
    wanted = schedule[[(ids[h], ids[a]) in pending for h, a in zip(schedule["home_team"], schedule["away_team"], strict=True)]]

    frames, unavailable = [], 0
    for game_id in wanted["game_id"]:
        try:
            ev = us.read_shot_events(match_id=int(game_id)).reset_index()
        except Exception:  # noqa: BLE001 - one unreadable match must not stop the others
            unavailable += 1
            continue
        if ev.empty:
            unavailable += 1      # not published yet: leave the match untouched, try again next run
            continue
        frames.append(ev)
    if not frames:
        return {"pending": len(pending), "fetched": 0, "loaded": 0, "unavailable": unavailable}
    events = pd.concat(frames, ignore_index=True)
    have = wanted[wanted["game_id"].isin(events["game_id"])]
    out = load_goals(conn, league_id, season, events, have)
    conn.commit()
    return {"pending": len(pending), "fetched": len(have), "loaded": out["loaded"], "unverified": len(out["inconsistent"]),
            "unavailable": unavailable}


def read_season_events(us, schedule: pd.DataFrame) -> pd.DataFrame:
    """Shot events for a whole season. If soccerdata cannot parse one match (it aborts the whole season), read match by
    match and skip only the broken ones; those matches stay unverified, which is the safe outcome."""
    try:
        return us.read_shot_events().reset_index()
    except Exception:  # noqa: BLE001
        frames = []
        for game_id in schedule["game_id"]:
            try:
                frames.append(us.read_shot_events(match_id=int(game_id)).reset_index())
            except Exception as e:  # noqa: BLE001
                log.warning("skipping unreadable Understat match %s: %s", game_id, e)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
