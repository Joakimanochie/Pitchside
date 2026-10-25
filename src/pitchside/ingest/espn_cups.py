"""Finished Champions League and Europa League matches from ESPN: the 90-minute score, the half-time score and the team statistics.

No football-data file exists for the European cups, so a finished match is read from ESPN's match summary. A knockout match can go to extra time and penalties,
but every market is settled on the 90 minutes, so the score of record is built from the goals ESPN dates to the first and second half (periods 1 and 2); goals in
extra time and the shoot-out are left out. The match is stored only when those goals equal ESPN's own final score for a match that did not go to extra time
(for one that did, there is nothing to check them against, so it is kept only if both halves are present).
"""
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import requests

from pitchside.ingest.espn_goals import parse_goals

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/"
UK = ZoneInfo("Europe/London")
FINAL = {"STATUS_FULL_TIME": False, "STATUS_FINAL_AET": True, "STATUS_FINAL_PEN": True}      # status -> went beyond 90 minutes
STAT_COLUMNS = {"corners": "wonCorners", "yellow_cards": "yellowCards", "red_cards": "redCards", "shots": "totalShots", "shots_on_target": "shotsOnTarget", "fouls": "foulsCommitted"}


def _stat(box: dict, name: str):
    v = box.get(name)
    try:
        return None if v in (None, "") else int(float(v))
    except ValueError:
        return None


def parse_result(payload: dict, beyond_90: bool) -> dict | None:
    """{'home', 'away', 'ft', 'ht', 'stats': {'home': {...}, 'away': {...}}} for one finished match, or None when it cannot be trusted."""
    comps = (payload.get("header", {}).get("competitions") or [{}])[0].get("competitors") or []
    names = {c["homeAway"]: c["team"]["displayName"] for c in comps}
    scores = {c["homeAway"]: c.get("score") for c in comps}
    if set(names) != {"home", "away"}:
        return None
    goals = parse_goals(payload, names["home"], names["away"])
    if goals is None:
        return None
    ft = (sum(1 for g in goals if g["side"] == "home"), sum(1 for g in goals if g["side"] == "away"))
    ht = (sum(1 for g in goals if g["side"] == "home" and g["period"] == 1), sum(1 for g in goals if g["side"] == "away" and g["period"] == 1))
    if not beyond_90:
        try:
            if (int(scores["home"]), int(scores["away"])) != ft:
                return None
        except (TypeError, ValueError):
            return None
    stats = {}
    for t in ([] if beyond_90 else payload.get("boxscore", {}).get("teams", [])):      # ESPN's totals include extra time: a match that went beyond 90 minutes gets no corners, cards or shots
        side = "home" if t["team"]["displayName"] == names["home"] else "away"
        box = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
        stats[side] = {col: _stat(box, name) for col, name in STAT_COLUMNS.items()}
    return {"home": names["home"], "away": names["away"], "ft": ft, "ht": ht, "stats": stats}


def fetch_finished(espn_code: str, day: date, session: requests.Session | None = None) -> list[dict]:
    """Finished events of one day: {'id', 'kickoff', 'home', 'away', 'beyond_90'}."""
    http = session or requests
    r = http.get(BASE.format(code=espn_code) + "scoreboard", params={"dates": day.strftime("%Y%m%d")}, timeout=30)
    r.raise_for_status()
    out = []
    for e in r.json().get("events", []):
        status = e["status"]["type"]["name"]
        if status not in FINAL:
            continue
        comp = e["competitions"][0]
        names = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        out.append({"id": e["id"], "kickoff": datetime.fromisoformat(e["date"]).astimezone(UTC), "home": names["home"], "away": names["away"], "beyond_90": FINAL[status]})
    return out


def fetch_summary(espn_code: str, event_id: str, session: requests.Session | None = None) -> dict:
    r = (session or requests).get(BASE.format(code=espn_code) + "summary", params={"event": event_id}, timeout=30)
    r.raise_for_status()
    return r.json()


def store_result(conn: psycopg.Connection, league_id: str, season: int, event: dict, parsed: dict, home_id: int, away_id: int) -> int:
    """Insert or update the finished match and its team statistics. Returns the match id."""
    local = event["kickoff"].astimezone(UK).date()
    row = conn.execute(
        "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, ft_home, ft_away, ht_home, ht_away, source_ids) "
        "VALUES (%s,%s,%s,%s,%s,%s,'finished',%s,%s,%s,%s, jsonb_build_object('espn', %s::text)) "
        "ON CONFLICT (league_id, season, home_team_id, away_team_id, match_date) DO UPDATE SET status = 'finished', kickoff = EXCLUDED.kickoff, "
        "ft_home = EXCLUDED.ft_home, ft_away = EXCLUDED.ft_away, ht_home = EXCLUDED.ht_home, ht_away = EXCLUDED.ht_away, "
        "source_ids = matches.source_ids || EXCLUDED.source_ids RETURNING id",
        (league_id, season, local, event["kickoff"], home_id, away_id, parsed["ft"][0], parsed["ft"][1], parsed["ht"][0], parsed["ht"][1], event["id"])).fetchone()
    match_id = row[0]
    for side, team_id in (("home", home_id), ("away", away_id)):
        s = parsed["stats"].get(side)
        if not s:
            continue
        conn.execute(
            "INSERT INTO team_match_stats (match_id, team_id, is_home, shots, shots_on_target, corners, fouls, yellow_cards, red_cards, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'espn') "
            "ON CONFLICT (match_id, team_id) DO UPDATE SET shots = EXCLUDED.shots, shots_on_target = EXCLUDED.shots_on_target, corners = EXCLUDED.corners, fouls = EXCLUDED.fouls, "
            "yellow_cards = EXCLUDED.yellow_cards, red_cards = EXCLUDED.red_cards, source = 'espn'",
            (match_id, team_id, side == "home", s["shots"], s["shots_on_target"], s["corners"], s["fouls"], s["yellow_cards"], s["red_cards"]))
    return match_id


def season_of(day: date) -> int:
    """The season a cup match belongs to, named by the year it started (2026 for October 2026 to May 2027)."""
    return day.year if day.month >= 7 else day.year - 1


def recent_days(today: date, days: int) -> list[date]:
    return [today - timedelta(days=i) for i in range(days)]
