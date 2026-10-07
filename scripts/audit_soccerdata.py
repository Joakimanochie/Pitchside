"""Phase 0 audit: soccerdata sources. Each source is tried independently; failures are recorded, not hidden.

Usage: uv run python scripts/audit_soccerdata.py [source ...]   (default: all)
Writes data/processed/audit_soccerdata.json
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SOCCERDATA_DIR", str(ROOT / "data" / "raw" / "soccerdata"))

import soccerdata as sd

LEAGUE = "ENG-Premier League"
SEASON = "2025"  # soccerdata: 2025 = 2025/26
OUT = ROOT / "data" / "processed" / "audit_soccerdata.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
results = json.loads(OUT.read_text()) if OUT.exists() else {}


def describe(df):
    df = df.reset_index()
    return {"rows": len(df), "columns": [str(c) for c in df.columns], "non_null_pct": {str(c): round(df[c].notna().mean() * 100) for c in df.columns}}


def run(name, fn):
    t = time.time()
    try:
        results[name] = {"ok": True, "seconds": round(time.time() - t, 1), **fn()}
        print(f"OK   {name}: {results[name].get('rows')} rows, {len(results[name].get('columns', []))} cols")
    except Exception as e:  # noqa: BLE001
        results[name] = {"ok": False, "seconds": round(time.time() - t, 1), "error": f"{type(e).__name__}: {str(e)[:300]}"}
        print(f"FAIL {name}: {results[name]['error']}")
        traceback.print_exc(limit=2)
    OUT.write_text(json.dumps(results, indent=2))


def understat_team():
    return describe(sd.Understat(LEAGUE, SEASON).read_team_match_stats())


def understat_schedule():
    return describe(sd.Understat(LEAGUE, SEASON).read_schedule())


def understat_player_match():
    return describe(sd.Understat(LEAGUE, SEASON).read_player_match_stats())


def understat_shots():
    return describe(sd.Understat(LEAGUE, SEASON).read_shot_events())


def clubelo():
    return describe(sd.ClubElo().read_by_date("2026-10-01"))


def fotmob_schedule():
    return describe(sd.FotMob(LEAGUE, SEASON).read_schedule())


def fotmob_team():
    return describe(sd.FotMob(LEAGUE, SEASON).read_team_match_stats())


def whoscored_schedule():
    return describe(sd.WhoScored(LEAGUE, SEASON).read_schedule())


def whoscored_events():
    ws = sd.WhoScored(LEAGUE, SEASON)
    sched = ws.read_schedule().reset_index()
    game_id = int(sched["game_id"].dropna().iloc[0])
    return describe(ws.read_events(match_id=game_id))


TESTS = {
    "understat_schedule": understat_schedule,
    "understat_team_match_stats": understat_team,
    "understat_player_match_stats": understat_player_match,
    "understat_shot_events": understat_shots,
    "clubelo": clubelo,
    "fotmob_schedule": fotmob_schedule,
    "fotmob_team_match_stats": fotmob_team,
    "whoscored_schedule": whoscored_schedule,
    "whoscored_events_one_match": whoscored_events,
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(TESTS)
    for n in wanted:
        run(n, TESTS[n])
