"""Phase 0 audit: football-data.co.uk. What columns exist, per league, and how complete are they?

Writes raw CSVs to data/raw/footballdata/ and a coverage table to data/processed/audit_footballdata.csv.
"""
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "footballdata"
OUT = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

LEAGUES = {"Premier League": "E0", "La Liga": "SP1", "Bundesliga": "D1", "Serie A": "I1", "Ligue 1": "F1"}
SEASONS = {"2025/26": "2526", "2026/27": "2627"}

# Columns that decide our market families.
KEY_COLS = {
    "results": ["FTHG", "FTAG", "FTR"],
    "halves": ["HTHG", "HTAG", "HTR"],
    "shots": ["HS", "AS", "HST", "AST"],
    "fouls": ["HF", "AF"],
    "corners": ["HC", "AC"],
    "cards": ["HY", "AY", "HR", "AR"],
    "referee": ["Referee"],
    "odds_1x2": ["B365H", "B365D", "B365A"],
    "odds_ou": ["B365>2.5", "B365<2.5"],
    "odds_closing": ["B365CH", "B365CD", "B365CA"],
}


def fetch(season_code: str, league_code: str) -> Path | None:
    dest = RAW / f"{season_code}_{league_code}.csv"
    if not dest.exists():
        url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv"
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  FAIL {url} -> HTTP {r.status_code}")
            return None
        dest.write_bytes(r.content)
    return dest


rows = []
all_cols = {}
for season, scode in SEASONS.items():
    for league, lcode in LEAGUES.items():
        path = fetch(scode, lcode)
        if path is None:
            rows.append({"season": season, "league": league, "matches": None})
            continue
        df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip").dropna(how="all")
        df = df[df["HomeTeam"].notna()] if "HomeTeam" in df else df
        row = {"season": season, "league": league, "matches": len(df), "n_columns": df.shape[1]}
        played = df[df["FTHG"].notna()] if "FTHG" in df else df
        row["played"] = len(played)
        for fam, cols in KEY_COLS.items():
            present = [c for c in cols if c in played.columns]
            row[fam] = "missing" if not present else f"{round(played[present].notna().all(axis=1).mean() * 100)}%"
        rows.append(row)
        all_cols[(season, league)] = list(df.columns)
        print(f"{season} {league}: {len(df)} rows, {len(played)} played, {df.shape[1]} cols")

report = pd.DataFrame(rows)
report.to_csv(OUT / "audit_footballdata.csv", index=False)
print("\n", report.to_string(index=False))

# Columns never mentioned in KEY_COLS, to spot extra stats we did not expect.
extra = sorted(set(c for cols in all_cols.values() for c in cols) - {c for v in KEY_COLS.values() for c in v})
print("\nOther columns present:", ", ".join(extra[:80]))
