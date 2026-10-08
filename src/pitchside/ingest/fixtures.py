"""Upcoming fixtures from ESPN's public scoreboard, written into `matches` as status 'scheduled'.

ESPN rejects date ranges for soccer, so we ask one day at a time. Kickoff times are UTC; the stored
match_date is the UK local date (the football-data convention), so scheduled rows line up with the result
rows that football-data publishes later. Unofficial API: it can change without notice.
"""
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import requests

from pitchside.db.teams import TeamResolver

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard"
UK = ZoneInfo("Europe/London")
SCHEDULED = "STATUS_SCHEDULED"
CALLED_OFF = {"STATUS_POSTPONED", "STATUS_CANCELED"}


def parse_scoreboard(payload: dict) -> list[dict]:
    """Events from one scoreboard response. Keeps scheduled matches and called-off ones; skips live and finished."""
    out = []
    for e in payload.get("events", []):
        status = e["status"]["type"]["name"]
        if status != SCHEDULED and status not in CALLED_OFF:
            continue
        comp = e["competitions"][0]
        home = next(c for c in comp["competitors"] if c["homeAway"] == "home")["team"]["displayName"]
        away = next(c for c in comp["competitors"] if c["homeAway"] == "away")["team"]["displayName"]
        kickoff = datetime.fromisoformat(e["date"]).astimezone(UTC)
        out.append({
            "espn_id": e["id"], "kickoff": kickoff, "match_date": kickoff.astimezone(UK).date(),
            "season": int(e["season"]["year"]), "home": home, "away": away,
            "status": "scheduled" if status == SCHEDULED else "postponed",
        })
    return out


def fetch_fixtures(espn_code: str, start: date, days: int, session: requests.Session | None = None) -> list[dict]:
    http = session or requests
    rows = []
    for i in range(days):
        day = start + timedelta(days=i)
        r = http.get(SCOREBOARD.format(code=espn_code), params={"dates": day.strftime("%Y%m%d")}, timeout=30)
        r.raise_for_status()
        rows.extend(parse_scoreboard(r.json()))
    seen, unique = set(), []
    for row in rows:  # a late-night match can appear under two days; keep one
        if row["espn_id"] not in seen:
            seen.add(row["espn_id"])
            unique.append(row)
    return unique


def upsert_fixtures(conn: psycopg.Connection, league_id: str, fixtures: list[dict]) -> dict:
    """Insert scheduled fixtures; mark called-off ones postponed. Never touches a finished match.
    Raises UnknownTeamsError (writing nothing) if ESPN uses a club name we have not mapped."""
    resolver = TeamResolver(conn)
    ids = resolver.resolve_all("espn", [n for f in fixtures for n in (f["home"], f["away"])])
    scheduled = postponed = 0
    for f in fixtures:
        home_id, away_id = ids[f["home"]], ids[f["away"]]
        if f["status"] == "scheduled":
            conn.execute(
                "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, source_ids) "
                "VALUES (%s,%s,%s,%s,%s,%s,'scheduled',%s) "
                "ON CONFLICT (league_id, season, home_team_id, away_team_id, match_date) DO UPDATE SET "
                "status = 'scheduled', kickoff = EXCLUDED.kickoff, source_ids = matches.source_ids || EXCLUDED.source_ids "
                "WHERE matches.status IN ('scheduled', 'postponed')",
                (league_id, f["season"], f["match_date"], f["kickoff"], home_id, away_id, json.dumps({"espn": f["espn_id"]})),
            )
            scheduled += 1
        else:
            cur = conn.execute(
                "UPDATE matches SET status = 'postponed' WHERE league_id = %s AND season = %s AND home_team_id = %s "
                "AND away_team_id = %s AND match_date = %s AND status = 'scheduled'",
                (league_id, f["season"], home_id, away_id, f["match_date"]),
            )
            postponed += cur.rowcount
    return {"scheduled": scheduled, "postponed": postponed}
