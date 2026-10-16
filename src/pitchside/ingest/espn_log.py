"""Cards (with minute and player) and per-player fouls and cards of finished matches, from ESPN's public match summary.

Unofficial API, so everything is checked before it is used. A match's log is only trusted (`matches.source_ids.espn_log = true`) when the cards ESPN lists
for each side add up to the yellow plus red cards football-data recorded for that side, and the players' own cards add up to the same. Otherwise it is
stored as false and nothing that depends on card minutes or players' cards is settled for that match.

Conventions: a card in stoppage time keeps the minute it was added to (45'+3' is minute 45, 90'+2' is 90); the half is ESPN's own period number.
A second yellow is a yellow card followed by a red card, so it counts as two cards, as in football-data.
"""
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import requests

from pitchside.db.teams import TeamResolver

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/"
UK = ZoneInfo("Europe/London")
MINUTE = re.compile(r"(\d+)")


def _minute(display: str) -> int | None:
    m = MINUTE.match(display or "")
    return int(m.group(1)) if m else None


def parse_log(payload: dict) -> dict | None:
    """{'cards': [...], 'players': [...], 'sides': {'home': name, 'away': name}} from one summary, or None when it lacks the rosters or the events."""
    comps = (payload.get("header", {}).get("competitions") or [{}])[0].get("competitors") or []
    sides = {c["homeAway"]: c["team"]["displayName"] for c in comps}
    rosters = payload.get("rosters")
    if set(sides) != {"home", "away"} or not rosters or payload.get("keyEvents") is None:
        return None
    cards = []
    for e in payload["keyEvents"]:
        kind = e.get("type", {}).get("type", "")
        if kind not in ("yellow-card", "red-card"):
            continue
        team = e.get("team", {}).get("displayName")
        minute = _minute(e.get("clock", {}).get("displayValue", ""))
        period = e.get("period", {}).get("number")
        if team not in sides.values() or minute is None or period not in (1, 2):
            return None
        who = (e.get("participants") or [{}])[0].get("athlete", {}).get("displayName")
        cards.append({"side": "home" if team == sides["home"] else "away", "card": "yellow" if kind == "yellow-card" else "red", "period": period, "minute": minute, "player": who})
    players = []
    for r in rosters:
        for p in r.get("roster") or []:
            stats = {s["name"]: s.get("value") for s in p.get("stats") or []}
            starter, played = bool(p.get("starter")), bool(p.get("starter")) or (stats.get("appearances") or 0) > 0
            players.append({"side": r["homeAway"], "player": p["athlete"]["displayName"], "starter": starter, "played": played,
                            "fouls_committed": int(stats.get("foulsCommitted") or 0), "fouls_suffered": int(stats.get("foulsSuffered") or 0),
                            "yellow": int(stats.get("yellowCards") or 0), "red": int(stats.get("redCards") or 0)})
    return {"cards": cards, "players": players, "sides": sides}


def verified(parsed: dict, team_cards: dict[str, int | None]) -> bool:
    """Cards listed per side, and the players' own cards per side, both equal the real per-side counts."""
    for side in ("home", "away"):
        real = team_cards.get(side)
        if real is None:
            return False
        if sum(1 for c in parsed["cards"] if c["side"] == side) != real:
            return False
        if sum(p["yellow"] + p["red"] for p in parsed["players"] if p["side"] == side) != real:
            return False
    return True


def store_log(conn: psycopg.Connection, match_id: int, home_id: int, away_id: int, parsed: dict, ok: bool) -> None:
    team = {"home": home_id, "away": away_id}
    conn.execute("DELETE FROM card_events WHERE match_id = %s", (match_id,))
    conn.execute("DELETE FROM player_match_log WHERE match_id = %s", (match_id,))
    if ok:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO card_events (match_id, team_id, player_name, card, period, minute) VALUES (%s,%s,%s,%s,%s,%s)",
                            [(match_id, team[c["side"]], c["player"], c["card"], c["period"], c["minute"]) for c in parsed["cards"]])
            cur.executemany(
                "INSERT INTO player_match_log (match_id, team_id, player_name, starter, played, fouls_committed, fouls_suffered, yellow, red) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                [(match_id, team[p["side"]], p["player"], p["starter"], p["played"], p["fouls_committed"], p["fouls_suffered"], p["yellow"], p["red"]) for p in parsed["players"]])
    conn.execute("UPDATE matches SET source_ids = source_ids || jsonb_build_object('espn_log', %s::boolean) WHERE id = %s", (ok, match_id))


def team_card_counts(conn: psycopg.Connection, match_id: int) -> dict[str, int | None]:
    out: dict[str, int | None] = {"home": None, "away": None}
    for is_home, y, r in conn.execute("SELECT is_home, yellow_cards, red_cards FROM team_match_stats WHERE match_id = %s", (match_id,)):
        out["home" if is_home else "away"] = None if y is None or r is None else int(y) + int(r)
    return out


def ingest_log(conn: psycopg.Connection, league_id: str, espn_code: str, since: date, retry_from: date, session: requests.Session | None = None, limit: int | None = None) -> dict:
    """Fetch the log of this league's finished matches (played on or after `since`) that have an ESPN id and no verdict yet, or a failed one since `retry_from`."""
    rows = conn.execute(
        "SELECT m.id, m.home_team_id, m.away_team_id, m.source_ids->>'espn' FROM matches m "
        "WHERE m.league_id = %s AND m.status = 'finished' AND m.source_ids ? 'espn' AND m.match_date >= %s "
        "AND (NOT (m.source_ids ? 'espn_log') OR (m.source_ids->>'espn_log' = 'false' AND m.match_date >= %s)) ORDER BY m.match_date", (league_id, since, retry_from)).fetchall()
    if limit:
        rows = rows[:limit]
    http = session or requests
    loaded = unverified = unavailable = 0
    for match_id, home_id, away_id, event in rows:
        try:
            r = http.get(BASE.format(code=espn_code) + "summary", params={"event": event}, timeout=30)
            r.raise_for_status()
            parsed = parse_log(r.json())
        except Exception as e:  # noqa: BLE001 - one match must not stop the others; it is retried on the next run
            print(f"espn log: match {match_id}: {e}")
            unavailable += 1
            continue
        if parsed is None:
            unavailable += 1
            continue
        ok = verified(parsed, team_card_counts(conn, match_id))
        store_log(conn, match_id, home_id, away_id, parsed, ok)
        loaded += ok
        unverified += not ok
        conn.commit()
    return {"pending": len(rows), "loaded": loaded, "unverified": unverified, "unavailable": unavailable}


def attach_event_ids(conn: psycopg.Connection, league_id: str, espn_code: str, days: list[date], session: requests.Session | None = None) -> int:
    """For past dates, ask ESPN's scoreboard which event is which of our matches and record its id. Returns how many matches got an id."""
    http = session or requests
    resolver = TeamResolver(conn)
    attached = 0
    for day in days:
        r = http.get(BASE.format(code=espn_code) + "scoreboard", params={"dates": day.strftime("%Y%m%d")}, timeout=30)
        r.raise_for_status()
        for e in r.json().get("events", []):
            comp = e["competitions"][0]
            names = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
            home, away = resolver.resolve("espn", names["home"]), resolver.resolve("espn", names["away"])
            if home is None or away is None:
                continue
            local = datetime.fromisoformat(e["date"]).astimezone(UTC).astimezone(UK).date()
            cur = conn.execute(
                "UPDATE matches SET source_ids = source_ids || jsonb_build_object('espn', %s::text) WHERE league_id = %s AND home_team_id = %s AND away_team_id = %s "
                "AND match_date BETWEEN %s AND %s AND NOT (source_ids ? 'espn')", (e["id"], league_id, home, away, local - timedelta(days=1), local + timedelta(days=1)))
            attached += cur.rowcount
        conn.commit()
    return attached
