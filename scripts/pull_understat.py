"""Pull Understat shot events (which include every goal with its minute) for the five leagues into the soccerdata cache.

Slow by design: about 4-5 minutes per league-season, one polite request per match. Resumable: soccerdata caches each
match, so re-running skips what is already there. A failure in one league-season is logged and the rest continue.

Usage: uv run python scripts/pull_understat.py [first_season] [last_season]      (default 2023 2026)
"""
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SOCCERDATA_DIR", str(ROOT / "data" / "raw" / "soccerdata"))
logging.disable(logging.CRITICAL)

import soccerdata as sd

from pitchside.leagues import LEAGUES

if __name__ == "__main__":
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 2023
    last = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    for season in range(last, first - 1, -1):          # newest first: the current season matters most
        for league_id, lg in LEAGUES.items():
            t = time.time()
            try:
                ev = sd.Understat(lg.understat, str(season)).read_shot_events()
                goals = int(ev["result"].isin(["Goal", "Own Goal"]).sum())
                print(f"OK   {league_id} {season}: {len(ev)} shots, {goals} goals, {time.time() - t:.0f}s", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {league_id} {season}: {type(e).__name__}: {str(e)[:150]}", flush=True)
    print("DONE", flush=True)
