"""Seed leagues and team aliases, and resolve a source's club spelling to a team id."""
import csv
from pathlib import Path

import psycopg

from pitchside.leagues import LEAGUES

ALIASES_CSV = Path(__file__).resolve().parents[3] / "data" / "team_aliases.csv"


class UnknownTeamsError(ValueError):
    """Raised when a source uses club names that are not in team_aliases. Never guessed."""

    def __init__(self, source: str, names: set[str]):
        self.source, self.names = source, names
        super().__init__(f"{len(names)} unmapped club name(s) from {source}: {sorted(names)}. Add them to data/team_aliases.csv.")


def seed_leagues(conn: psycopg.Connection) -> None:
    for lg in LEAGUES.values():
        conn.execute(
            "INSERT INTO leagues (id, name, country, tier, fd_code, understat, espn_code) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, fd_code = EXCLUDED.fd_code, "
            "understat = EXCLUDED.understat, espn_code = EXCLUDED.espn_code",
            (lg.id, lg.name, lg.country, lg.tier, lg.fd_code, lg.understat, lg.espn_code),
        )


def load_aliases(conn: psycopg.Connection, path: Path = ALIASES_CSV) -> int:
    """Create teams and aliases from the curated CSV. Idempotent. Returns alias rows read."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    countries = {lid: lg.country for lid, lg in LEAGUES.items()}
    for r in rows:
        team_id = conn.execute(
            "INSERT INTO teams (canonical_name, country) VALUES (%s, %s) "
            "ON CONFLICT (canonical_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name RETURNING id",
            (r["canonical"], countries.get(r["league"])),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO team_aliases (source, alias, team_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (source, alias) DO UPDATE SET team_id = EXCLUDED.team_id",
            (r["source"], r["alias"], team_id),
        )
    return len(rows)


class TeamResolver:
    """Map (source, spelling) -> team id. A '*' alias applies to every source."""

    def __init__(self, conn: psycopg.Connection):
        self._map = {(s, a): t for s, a, t in conn.execute("SELECT source, alias, team_id FROM team_aliases")}

    def resolve(self, source: str, alias: str) -> int | None:
        return self._map.get((source, alias)) or self._map.get(("*", alias))

    def resolve_all(self, source: str, names) -> dict[str, int]:
        found, missing = {}, set()
        for n in set(names):
            tid = self.resolve(source, n)
            if tid is None:
                missing.add(n)
            else:
                found[n] = tid
        if missing:
            raise UnknownTeamsError(source, missing)
        return found
