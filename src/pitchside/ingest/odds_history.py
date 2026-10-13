"""Historical closing odds from football-data.co.uk, used ONLY as a benchmark in backtests.

Market-average closing odds (AvgC*) are complete from 2019/20. They are never a model input.
"""
import pandas as pd

from pitchside.ingest.footballdata import download_season

WANTED = {"Date", "HomeTeam", "AwayTeam"}
ODDS_COLS = {"AvgCH": "odds_h", "AvgCD": "odds_d", "AvgCA": "odds_a", "AvgC>2.5": "odds_over25", "AvgC<2.5": "odds_under25"}
# best closing price across bookmakers: what a bettor who shops around could have taken
MAX_COLS = {"MaxCH": "max_h", "MaxCD": "max_d", "MaxCA": "max_a", "MaxC>2.5": "max_over25", "MaxC<2.5": "max_under25"}
# the prices published when the file was made, typically a few days before the match: what the site shows before kickoff
OPEN_COLS = {"AvgH": "open_h", "AvgD": "open_d", "AvgA": "open_a", "Avg>2.5": "open_over25", "Avg<2.5": "open_under25",
             "MaxH": "openmax_h", "MaxD": "openmax_d", "MaxA": "openmax_a", "Max>2.5": "openmax_over25", "Max<2.5": "openmax_under25"}


def load_closing_odds(div: str, start_years: list[int], with_max: bool = False, with_opening: bool = False) -> pd.DataFrame:
    cols = {**ODDS_COLS, **(MAX_COLS if with_max else {}), **(OPEN_COLS if with_opening else {})}
    frames = []
    for y in start_years:
        path = download_season(div, y)
        df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip", usecols=lambda c: c in WANTED | cols.keys())
        df = df.dropna(subset=["HomeTeam", "AwayTeam"])
        raw = df["Date"].astype(str).str.strip()
        dates = pd.to_datetime(raw, format="%d/%m/%Y", errors="coerce").fillna(pd.to_datetime(raw, format="%d/%m/%y", errors="coerce"))
        df = df.assign(match_date=dates.dt.date).rename(columns={"HomeTeam": "home", "AwayTeam": "away", **cols})
        df = df.reindex(columns=["match_date", "home", "away", *cols.values()])
        for c in cols.values():
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.insert(0, "season", y)
        frames.append(df.dropna(subset=["match_date"]))
    return pd.concat(frames, ignore_index=True)
