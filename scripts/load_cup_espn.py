"""Attach ESPN event ids to the Champions League and Europa League matches already loaded, then fetch team statistics, cards and players' fouls for them.

    uv run python scripts/load_cup_espn.py [first_season]        (default 2020, the first Europa League season we hold)

For each date on which we hold a cup match, ESPN's scoreboard says which event is which match; the match summary then gives corners, shots, shots on target, fouls and
cards per team (`team_match_stats`) and every card with its minute and each player's fouls and cards (`card_events`, `player_match_log`, verified against the team card counts).
The scores themselves stay as loaded from openfootball. Idempotent and resumable. Writes to the production database (DATABASE_URL).
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import requests

from pitchside.db.cup_teams import CupTeams
from pitchside.db.migrate import _load_env
from pitchside.ingest.espn_cups import BASE, STAT_COLUMNS, _stat
from pitchside.ingest.espn_log import parse_log, store_log, team_card_counts, verified
from pitchside.leagues import LEAGUES


def fetch(args):
    code, event = args
    for attempt in range(3):
        try:
            r = requests.get(BASE.format(code=code) + "summary", params={"event": event}, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"giving up on event {event}: {e}", flush=True)
    return None


def team_stats(payload: dict) -> dict:
    comps = (payload.get("header", {}).get("competitions") or [{}])[0].get("competitors") or []
    names = {c["homeAway"]: c["team"]["displayName"] for c in comps}
    out = {}
    for t in payload.get("boxscore", {}).get("teams", []):
        side = "home" if t["team"]["displayName"] == names.get("home") else "away"
        box = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
        out[side] = {col: _stat(box, name) for col, name in STAT_COLUMNS.items()}
    return out


def main(first_season: int) -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        teams = CupTeams(conn)
        for lid in ("CL", "EL"):
            code = LEAGUES[lid].espn_code
            days = [r[0] for r in conn.execute("SELECT DISTINCT match_date FROM matches WHERE league_id = %s AND season >= %s AND status = 'finished' ORDER BY 1", (lid, first_season))]
            print(f"{lid}: {len(days)} dates", flush=True)
            attached = 0
            for i, day in enumerate(days):
                for d in (day, day + timedelta(days=1)):
                    try:
                        events = requests.get(BASE.format(code=code) + "scoreboard", params={"dates": d.strftime("%Y%m%d")}, timeout=30).json().get("events", [])
                    except Exception as e:  # noqa: BLE001
                        print(f"scoreboard {d}: {e}", flush=True)
                        continue
                    for e in events:
                        names = {c["homeAway"]: c["team"]["displayName"] for c in e["competitions"][0]["competitors"]}
                        home, away = teams.resolve("espn", names["home"]), teams.resolve("espn", names["away"])
                        attached += conn.execute(
                            "UPDATE matches SET source_ids = source_ids || jsonb_build_object('espn', %s::text) WHERE league_id = %s AND home_team_id = %s AND away_team_id = %s "
                            "AND match_date BETWEEN %s AND %s AND NOT (source_ids ? 'espn')", (e["id"], lid, home, away, day - timedelta(days=1), day + timedelta(days=1))).rowcount
                if i % 25 == 0:
                    conn.commit()
                    print(f"  {lid} dates {i}/{len(days)}, ids attached {attached}", flush=True)
            conn.commit()
            print(f"{lid}: ids attached {attached}", flush=True)

            rows = conn.execute(
                "SELECT id, home_team_id, away_team_id, source_ids->>'espn' FROM matches WHERE league_id = %s AND season >= %s AND status = 'finished' "
                "AND source_ids ? 'espn' AND NOT (source_ids ? 'espn_log') ORDER BY match_date", (lid, first_season)).fetchall()
            print(f"{lid}: {len(rows)} summaries to fetch", flush=True)
            ok = bad = failed = 0
            with ThreadPoolExecutor(max_workers=12) as pool:
                for n, ((match_id, home_id, away_id, _event), payload) in enumerate(zip(rows, pool.map(fetch, [(code, r[3]) for r in rows]), strict=True)):
                    if payload is None:
                        failed += 1
                        continue
                    stats = team_stats(payload)
                    for side, team_id in (("home", home_id), ("away", away_id)):
                        s = stats.get(side)
                        if s:
                            conn.execute(
                                "INSERT INTO team_match_stats (match_id, team_id, is_home, shots, shots_on_target, corners, fouls, yellow_cards, red_cards, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'espn') "
                                "ON CONFLICT (match_id, team_id) DO UPDATE SET shots = EXCLUDED.shots, shots_on_target = EXCLUDED.shots_on_target, corners = EXCLUDED.corners, "
                                "fouls = EXCLUDED.fouls, yellow_cards = EXCLUDED.yellow_cards, red_cards = EXCLUDED.red_cards, source = 'espn'",
                                (match_id, team_id, side == "home", s["shots"], s["shots_on_target"], s["corners"], s["fouls"], s["yellow_cards"], s["red_cards"]))
                    parsed = parse_log(payload)
                    if parsed is None:
                        failed += 1
                        continue
                    good = verified(parsed, team_card_counts(conn, match_id))
                    store_log(conn, match_id, home_id, away_id, parsed, good)
                    ok += good
                    bad += not good
                    if n % 50 == 0:
                        conn.commit()
                        print(f"  {n}/{len(rows)}: verified {ok}, unverified {bad}, failed {failed}", flush=True)
            conn.commit()
            print(f"{lid}: verified {ok}, unverified {bad}, failed {failed}", flush=True)
        print("ESPN spellings merged into existing clubs by name similarity (check once):")
        print("; ".join(teams.merged))
        print("new clubs created:", ", ".join(teams.created))
        conn.commit()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2020)
