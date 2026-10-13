"""Match a provider's odds to our scheduled matches and store the prices that changed since the last snapshot."""
from collections import defaultdict
from datetime import timedelta

import psycopg

from pitchside.db.teams import TeamResolver
from pitchside.odds.provider import OddsProvider

DATE_TOLERANCE_DAYS = 1   # a source may list a late kickoff under the neighbouring day


def store_odds(conn: psycopg.Connection, provider: OddsProvider) -> dict:
    """Write odds for fixtures we have scheduled. Unknown clubs and fixtures we do not have are reported, never guessed or created."""
    rows = provider.fetch()
    resolver = TeamResolver(conn)
    names = {n for r in rows for n in (r.home, r.away)}
    ids = {n: resolver.resolve(provider.name_source, n) for n in names}
    unmapped = sorted(n for n, i in ids.items() if i is None)

    scheduled: dict[tuple, int] = {}
    for mid, league, day, home_id, away_id in conn.execute(
            "SELECT id, league_id, match_date, home_team_id, away_team_id FROM matches WHERE status = 'scheduled'"):
        scheduled[(league, day, home_id, away_id)] = mid

    def find(r) -> int | None:
        home_id, away_id = ids.get(r.home), ids.get(r.away)
        if home_id is None or away_id is None:
            return None
        for shift in (0, -DATE_TOLERANCE_DAYS, DATE_TOLERANCE_DAYS):
            mid = scheduled.get((r.league_id, r.match_date + timedelta(days=shift), home_id, away_id))
            if mid is not None:
                return mid
        return None

    by_match: dict[int, list] = defaultdict(list)
    unmatched = set()
    for r in rows:
        mid = find(r)
        if mid is None:
            if ids.get(r.home) is not None and ids.get(r.away) is not None:
                unmatched.add((r.league_id, r.match_date.isoformat(), r.home, r.away))
        else:
            by_match[mid].append(r)

    latest = {(m, b, mk, None if ln is None else float(ln), s): float(o) for m, b, mk, ln, s, o in conn.execute(
        "SELECT match_id, bookmaker, market_id, line, selection, odds FROM v_latest_odds WHERE match_id = ANY(%s)", (list(by_match),))}
    new = []
    for mid, rs in by_match.items():
        for r in rs:
            key = (mid, r.bookmaker, r.market_id, r.line, r.selection)
            if latest.get(key) != float(r.odds):
                new.append((mid, provider.source, r.bookmaker, r.market_id, r.line, r.selection, r.odds))
    if new:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO odds_snapshots (match_id, source, bookmaker, market_id, line, selection, odds) VALUES (%s,%s,%s,%s,%s,%s,%s)", new)
    return {"fixtures": len(by_match), "rows_read": len(rows), "rows_written": len(new), "unmatched": sorted(unmatched), "unmapped_names": unmapped}
