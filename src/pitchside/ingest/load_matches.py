"""Write parsed football-data matches and team stats into Postgres. Idempotent: re-running updates in place.

Batched: bulk upsert of matches, one lookup of their ids, bulk upsert of stats. This keeps a remote
database (Supabase) to a handful of round trips instead of one per row.
"""
from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg

from pitchside.db.teams import TeamResolver

SOURCE = "footballdata"


def _v(x):
    """pandas NA/NaN -> None, numpy numbers -> python numbers."""
    if x is None or pd.isna(x):
        return None
    return x.item() if hasattr(x, "item") else x


def load_footballdata(conn: psycopg.Connection, league_id: str, df: pd.DataFrame) -> dict:
    """df is the output of ingest.footballdata.load_seasons. Raises UnknownTeamsError before writing anything."""
    resolver = TeamResolver(conn)
    ids = resolver.resolve_all(SOURCE, [*df["home"], *df["away"]])
    rows = list(df.itertuples(index=False))

    _reconcile_scheduled(conn, league_id, rows, ids)

    match_params = [
        (league_id, int(r.season), r.match_date, ids[r.home], ids[r.away], _v(r.ft_home), _v(r.ft_away),
         _v(r.ht_home), _v(r.ht_away), _v(r.referee))
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, "
            "ft_home, ft_away, ht_home, ht_away, referee) VALUES (%s,%s,%s,%s,%s,'finished',%s,%s,%s,%s,%s) "
            "ON CONFLICT (league_id, season, home_team_id, away_team_id, match_date) DO UPDATE SET "
            "status = 'finished', ft_home = EXCLUDED.ft_home, ft_away = EXCLUDED.ft_away, "
            "ht_home = EXCLUDED.ht_home, ht_away = EXCLUDED.ht_away, referee = EXCLUDED.referee",
            match_params,
        )

    seasons = sorted({int(r.season) for r in rows})
    match_ids = {
        (season, date, home, away): mid
        for mid, season, date, home, away in conn.execute(
            "SELECT id, season, match_date, home_team_id, away_team_id FROM matches "
            "WHERE league_id = %s AND season = ANY(%s)",
            (league_id, seasons),
        )
    }

    stat_params = []
    for r in rows:
        mid = match_ids[(int(r.season), r.match_date, ids[r.home], ids[r.away])]
        for team_id, is_home, side in ((ids[r.home], True, "h"), (ids[r.away], False, "a")):
            stat_params.append((
                mid, team_id, is_home, _v(getattr(r, f"shots_{side}")), _v(getattr(r, f"sot_{side}")),
                _v(getattr(r, f"corners_{side}")), _v(getattr(r, f"fouls_{side}")),
                _v(getattr(r, f"yellow_{side}")), _v(getattr(r, f"red_{side}")), _v(getattr(r, f"xg_{side}")), SOURCE,
            ))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO team_match_stats (match_id, team_id, is_home, shots, shots_on_target, corners, fouls, "
            "yellow_cards, red_cards, xg, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (match_id, team_id) DO UPDATE SET shots = EXCLUDED.shots, "
            "shots_on_target = EXCLUDED.shots_on_target, corners = EXCLUDED.corners, fouls = EXCLUDED.fouls, "
            "yellow_cards = EXCLUDED.yellow_cards, red_cards = EXCLUDED.red_cards, xg = EXCLUDED.xg",
            stat_params,
        )
    return {"matches": len(match_params), "team_stats": len(stat_params)}


RECONCILE_DAYS = 45  # only recent results can belong to a fixture we scheduled earlier
MAX_DATE_SHIFT = 7   # a rescheduled match is matched to its fixture if the date moved by at most this many days


def _reconcile_scheduled(conn: psycopg.Connection, league_id: str, rows: list, ids: dict) -> None:
    """If a fixture we scheduled has been played on a different date, move it to the real date first so the
    result updates that row instead of creating a second one (which would leave the first unsettled forever)."""
    cutoff = (datetime.now(UTC) - timedelta(days=RECONCILE_DAYS)).date()
    params = [
        (r.match_date, league_id, int(r.season), ids[r.home], ids[r.away], r.match_date, r.match_date, MAX_DATE_SHIFT)
        for r in rows if r.match_date >= cutoff
    ]
    if params:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE matches SET match_date = %s WHERE league_id = %s AND season = %s AND home_team_id = %s "
                "AND away_team_id = %s AND status IN ('scheduled', 'postponed') AND match_date <> %s "
                "AND abs(match_date - %s::date) <= %s",
                params,
            )
