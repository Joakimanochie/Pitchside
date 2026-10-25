import tempfile
from pathlib import Path

import pgserver
import psycopg
import pytest

from pitchside.db.migrate import apply_migrations


@pytest.fixture(scope="session")
def pg_uri():
    """One throwaway embedded Postgres for the whole test session."""
    server = pgserver.get_server(Path(tempfile.mkdtemp()) / "pg")
    yield server.get_uri()
    server.cleanup()


@pytest.fixture()
def conn(pg_uri):
    """A connection to a freshly migrated empty schema; rolled back/dropped after each test."""
    with psycopg.connect(pg_uri, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS public CASCADE")
        admin.execute("CREATE SCHEMA public")
    # The prediction guards (migration 011) are switched off for the fixtures, which insert predictions on matches of any date; test_prediction_guards turns them on.
    with psycopg.connect(pg_uri, options="-c pitchside.unsafe_writes=on") as c:
        apply_migrations(c)
        yield c
