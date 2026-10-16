"""Goal events with minutes from ESPN's match summary, for leagues Understat does not cover (the Championship).

Same rule as the Understat route (ingest/understat_goals.py): goals are kept only if they can be trusted. The goals credited to each side must add up to
the real full-time score and to the real half-time score (ESPN gives the half of every goal), else the match is flagged `goal_minutes = false`
and no minute-dependent market is settled for it. ESPN names the side CREDITED with a goal, own goals included.
A goal in stoppage time (45'+3', 90'+5') keeps the minute it was added to (45, 90): bookmaker minute windows count it there.
"""
import json
import re

import psycopg
import requests

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/summary"
MINUTE = re.compile(r"(\d+)")


def _minute(display: str) -> int | None:
    m = MINUTE.match(display or "")
    return int(m.group(1)) if m else None


def parse_goals(payload: dict, home: str, away: str) -> list[dict] | None:
    """Goals of one finished match as {side, period, minute, player, type}; None if the summary has no usable key events."""
    events = payload.get("keyEvents")
    if not events:
        return None
    out = []
    for e in events:
        kind = e.get("type", {}).get("type", "")
        if not (kind.startswith("goal") or kind in ("own-goal", "penalty---scored")):
            continue
        team = e.get("team", {}).get("displayName")
        minute = _minute(e.get("clock", {}).get("displayValue", ""))
        period = e.get("period", {}).get("number")
        if team not in (home, away) or minute is None or period not in (1, 2):
            return None                         # a goal we cannot place: do not guess
        who = (e.get("participants") or [{}])[0].get("athlete", {}).get("displayName")
        out.append({"side": "home" if team == home else "away", "period": period, "minute": minute, "player": who,
                    "type": "own_goal" if kind == "own-goal" else "penalty_goal" if kind == "penalty---scored" else "goal"})
    return out


def verified(goals: list[dict], ft: tuple[int, int], ht: tuple[int, int]) -> bool:
    for side, ft_n, ht_n in (("home", ft[0], ht[0]), ("away", ft[1], ht[1])):
        mine = [g for g in goals if g["side"] == side]
        if len(mine) != ft_n or sum(1 for g in mine if g["period"] == 1) != ht_n:
            return False
    return True


def ingest_espn_goals(conn: psycopg.Connection, league_id: str, espn_code: str, retry_from, session: requests.Session | None = None) -> dict:
    """Fetch goal minutes for this league's finished matches that have an ESPN id and no verdict yet (or a failed one in the last days)."""
    rows = conn.execute(
        "SELECT m.id, m.home_team_id, m.away_team_id, m.ft_home, m.ft_away, m.ht_home, m.ht_away, m.source_ids->>'espn', th.canonical_name, ta.canonical_name "
        "FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.league_id = %s AND m.status = 'finished' AND m.source_ids ? 'espn' AND m.ht_home IS NOT NULL "
        "AND (NOT (m.source_ids ? 'goal_minutes') OR (m.source_ids->>'goal_minutes' = 'false' AND m.match_date >= %s))", (league_id, retry_from)).fetchall()
    http = session or requests
    loaded = unverified = unavailable = 0
    for match_id, home_id, away_id, fh, fa, hh, ha, event, home, away in rows:
        try:
            r = http.get(SUMMARY.format(code=espn_code), params={"event": event}, timeout=30)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:  # noqa: BLE001 - one match must not stop the others; it is retried on the next run
            print(f"espn goals: match {match_id}: {e}")
            unavailable += 1
            continue
        # ESPN's names for the clubs come from the same summary: map by home/away order, not by spelling
        comps = {c["homeAway"]: c["team"]["displayName"] for c in payload.get("header", {}).get("competitions", [{}])[0].get("competitors", [])}
        goals = parse_goals(payload, comps.get("home", home), comps.get("away", away)) if comps else None
        if goals is None:
            unavailable += 1
            continue
        conn.execute("DELETE FROM match_events WHERE match_id = %s AND source = 'espn' AND event_type IN ('goal', 'own_goal', 'penalty_goal')", (match_id,))
        ok = verified(goals, (fh, fa), (hh, ha))
        if ok:
            for g in goals:
                conn.execute(
                    "INSERT INTO match_events (match_id, team_id, event_type, period, minute, player_name, details, source) VALUES (%s,%s,%s,%s,%s,%s,%s,'espn')",
                    (match_id, home_id if g["side"] == "home" else away_id, g["type"], g["period"], g["minute"], g["player"], json.dumps({"side": g["side"]})))
            loaded += 1
        else:
            unverified += 1
        conn.execute("UPDATE matches SET source_ids = source_ids || jsonb_build_object('goal_minutes', %s::boolean) WHERE id = %s", (ok, match_id))
    conn.commit()
    return {"pending": len(rows), "loaded": loaded, "unverified": unverified, "unavailable": unavailable}
