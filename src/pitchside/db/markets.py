"""Register the market catalogue in the `markets` table."""
import psycopg

from pitchside.markets.goals import MARKETS as GOALS_MARKETS


def seed_markets(conn: psycopg.Connection) -> int:
    n = 0
    for m in GOALS_MARKETS.values():
        conn.execute(
            "INSERT INTO markets (id, family, name, has_line, scorable) VALUES (%s,%s,%s,%s,true) "
            "ON CONFLICT (id) DO UPDATE SET family = EXCLUDED.family, name = EXCLUDED.name, has_line = EXCLUDED.has_line",
            (m.id, m.family, m.name, m.has_line),
        )
        n += 1
    return n
