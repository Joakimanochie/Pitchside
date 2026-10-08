"""football-data.co.uk: download season CSVs (cached) and parse them into one clean frame.

Output columns (one row per match): see COLUMNS. Missing values are NaN, never 0.
"""
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ROOT / "data" / "raw" / "footballdata"
URL = "https://www.football-data.co.uk/mmz4281/{code}/{div}.csv"

# football-data column -> our column
RENAME = {
    "HomeTeam": "home", "AwayTeam": "away", "Referee": "referee",
    "FTHG": "ft_home", "FTAG": "ft_away", "HTHG": "ht_home", "HTAG": "ht_away",
    "HS": "shots_h", "AS": "shots_a", "HST": "sot_h", "AST": "sot_a",
    "HC": "corners_h", "AC": "corners_a", "HF": "fouls_h", "AF": "fouls_a",
    "HY": "yellow_h", "AY": "yellow_a", "HR": "red_h", "AR": "red_a",
    "HxG": "xg_h", "AxG": "xg_a",
}
COLUMNS = ["match_date", "home", "away", "referee", *[c for c in RENAME.values() if c not in ("home", "away", "referee")]]


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def current_season(today: date | None = None) -> int:
    """European season start year: from July onwards we are in the season starting that year."""
    today = today or datetime.now(UTC).date()
    return today.year if today.month >= 7 else today.year - 1


def download_season(div: str, start_year: int, raw_dir: Path = RAW_DIR, refresh: bool | None = None) -> Path:
    """Return the cached CSV path, downloading if missing. The current season is always refreshed."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{season_code(start_year)}_{div}.csv"
    if refresh is None:
        refresh = start_year == current_season()
    if refresh or not dest.exists():
        url = URL.format(code=season_code(start_year), div=div)
        last_error = None
        for _ in range(3):
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                dest.write_bytes(r.content)
                return dest
            except requests.RequestException as e:
                last_error = e
        if not dest.exists():  # nothing cached to fall back on
            raise last_error
        log.warning("refresh of %s failed (%s); using the cached copy", url, last_error)
    return dest


def parse_season(path: Path) -> pd.DataFrame:
    """Parse one season CSV. Drops blank rows and rows without a result (unplayed)."""
    wanted = {"Date", *RENAME}
    df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip", usecols=lambda c: c in wanted).dropna(how="all")
    df = df.dropna(subset=["HomeTeam", "AwayTeam"])
    # Older files use dd/mm/yy, newer dd/mm/yyyy; try the long form first.
    raw_dates = df["Date"].astype(str).str.strip()
    long_form = pd.to_datetime(raw_dates, format="%d/%m/%Y", errors="coerce")
    dates = long_form.fillna(pd.to_datetime(raw_dates, format="%d/%m/%y", errors="coerce")).dt.date
    df = df.assign(match_date=dates).dropna(subset=["match_date"]).rename(columns=RENAME)
    df = df.reindex(columns=COLUMNS).copy()
    for col in COLUMNS:
        if col not in ("match_date", "home", "away", "referee"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("home", "away", "referee"):
        df[col] = df[col].astype("string").str.strip()
    df = df[df["ft_home"].notna() & df["ft_away"].notna()]
    return df.reset_index(drop=True)


def load_seasons(div: str, start_years: list[int]) -> pd.DataFrame:
    frames = []
    for y in start_years:
        f = parse_season(download_season(div, y))
        f.insert(0, "season", y)
        frames.append(f)
    return pd.concat(frames, ignore_index=True)
