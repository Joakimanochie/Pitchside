"""Apply SQL migrations from db/migrations/ in filename order. Each file runs once, in its own transaction.

CLI: uv run python -m pitchside.db.migrate        (uses DATABASE_URL from the environment or .env)
"""
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"


def apply_migrations(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply any migration not yet recorded. Returns the names applied this call."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    conn.commit()
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    conn.commit()  # end the read transaction so each migration below is a real transaction, not a savepoint
    applied = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def _load_env() -> None:
    env = Path(__file__).resolve().parents[3] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


if __name__ == "__main__":
    _load_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (put it in .env or the environment)")
    with psycopg.connect(url) as c:
        print("applied:", apply_migrations(c) or "nothing new")
