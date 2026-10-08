"""Historical closing odds from football-data.co.uk, used ONLY as a benchmark in backtests.

Market-average closing odds (AvgC*) are complete from 2019/20. They are never a model input.
"""
import pandas as pd

from pitchside.ingest.footballdata import download_season

WANTED = {"Date", "HomeTeam", "AwayTeam"}
ODDS_COLS = {"AvgCH": "odds_h", "AvgCD": "odds_d", "AvgCA": "odds_a", "AvgC>2.5": "odds_over25", "AvgC<2.5": "odds_under25"}


def load_closing_odds(div: str, start_years: list[int]) -> pd.DataFrame:
    frames = []
    for y in start_years:
        path = download_season(div, y)
        df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip", usecols=lambda c: c in WANTED | ODDS_COLS.keys())
        df = df.dropna(subset=["HomeTeam", "AwayTeam"])
        raw = df["Date"].astype(str).str.strip()
        dates = pd.to_datetime(raw, format="%d/%m/%Y", errors="coerce").fillna(pd.to_datetime(raw, format="%d/%m/%y", errors="coerce"))
        df = df.assign(match_date=dates.dt.date).rename(columns={"HomeTeam": "home", "AwayTeam": "away", **ODDS_COLS})
        df = df.reindex(columns=["match_date", "home", "away", *ODDS_COLS.values()])
        for c in ODDS_COLS.values():
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.insert(0, "season", y)
        frames.append(df.dropna(subset=["match_date"]))
    return pd.concat(frames, ignore_index=True)
