"""Prints how many matches of the five rated leagues kick off in the next 24 hours (a read-only count). The odds probe workflow uses it to skip a day with no fixtures,
so no OddsPapi request is spent then.

    uv run python scripts/fixture_count.py
"""
import os

import psycopg

from pitchside.confidence import RATED_LEAGUES
from pitchside.db.migrate import _load_env


def main() -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        (n,) = conn.execute(
            "SELECT count(*) FROM matches WHERE status = 'scheduled' AND league_id = ANY(%s) AND kickoff > now() AND kickoff < now() + interval '24 hours'",
            (list(RATED_LEAGUES),)).fetchone()
    print(n)


if __name__ == "__main__":
    main()
