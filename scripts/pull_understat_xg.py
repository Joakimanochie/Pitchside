"""Pull match-level expected goals (xG) for the five leagues from Understat's season schedules into data/raw/understat_xg.csv.

One request per league-season (far lighter than the shot-by-shot pull), so the whole 2014/15 to now history takes a few minutes. Resumable:
soccerdata caches each response, and a league-season that fails is logged while the rest continue.

Usage: uv run python scripts/pull_understat_xg.py [first_season] [last_season]      (default 2014 2026; season 2026 means 2026/27)
"""
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SOCCERDATA_DIR", str(ROOT / "data" / "raw" / "soccerdata"))
logging.disable(logging.CRITICAL)

import pandas as pd
import soccerdata as sd

from pitchside.leagues import LEAGUES

OUT = ROOT / "data" / "raw" / "understat_xg.csv"

if __name__ == "__main__":
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 2014
    last = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    frames = []
    for season in range(first, last + 1):
        for league_id, lg in LEAGUES.items():
            t = time.time()
            try:
                sch = sd.Understat(lg.understat, str(season)).read_schedule().reset_index()
                keep = [c for c in ("date", "home_team", "away_team", "home_goals", "away_goals", "home_xg", "away_xg", "is_result") if c in sch.columns]
                df = sch[keep].assign(league=league_id, season=season)
                frames.append(df)
                print(f"OK   {league_id} {season}: {len(df)} matches, {df['home_xg'].notna().sum()} with xG, {time.time() - t:.0f}s", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {league_id} {season}: {type(e).__name__}: {str(e)[:150]}", flush=True)
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(OUT, index=False)
        print(f"wrote {OUT}")
    print("DONE", flush=True)
