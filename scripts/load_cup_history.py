"""Load Champions League and Europa League results (90-minute score and half-time score) from openfootball into `matches`.

    uv run python scripts/load_cup_history.py

Clubs of the five leagues and the Championship are matched to the clubs already in the database; every other club is created (canonical name = the cup spelling, country from
the code openfootball gives). Idempotent: a match already loaded is updated, never duplicated. Prints the clubs it created, to be read once.
Writes to the production database (DATABASE_URL).
"""
import os
import sys

import psycopg

from pitchside.db.cup_teams import CupTeams
from pitchside.db.migrate import _load_env, apply_migrations
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.openfootball import fetch

CUPS = {"cl": ("CL", range(2015, 2026)), "el": ("EL", range(2020, 2026))}


def main() -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        apply_migrations(conn)
        seed_leagues(conn)
        load_aliases(conn)
        conn.commit()
        teams = CupTeams(conn)
        total = 0
        for comp, (league, seasons) in CUPS.items():
            for season in seasons:
                matches = fetch(season, comp)
                for m in matches:
                    home, away = teams.resolve("openfootball", m.home, m.home_country), teams.resolve("openfootball", m.away, m.away_country)
                    ht = m.ht or (None, None)
                    conn.execute(
                        "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away, ht_home, ht_away, source_ids) "
                        "VALUES (%s,%s,%s,%s,%s,'finished',%s,%s,%s,%s,'{\"openfootball\": true}') "
                        "ON CONFLICT (league_id, season, home_team_id, away_team_id, match_date) DO UPDATE SET status = 'finished', ft_home = EXCLUDED.ft_home, "
                        "ft_away = EXCLUDED.ft_away, ht_home = EXCLUDED.ht_home, ht_away = EXCLUDED.ht_away, source_ids = matches.source_ids || EXCLUDED.source_ids",
                        (league, season, m.day, home, away, m.ft[0], m.ft[1], ht[0], ht[1]))
                conn.commit()
                total += len(matches)
                print(f"{league} {season}/{str(season + 1)[2:]}: {len(matches)} matches", flush=True)
        print(f"{total} matches loaded; {len(teams.created)} clubs created:")
        print(", ".join(sorted(teams.created)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
