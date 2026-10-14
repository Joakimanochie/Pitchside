"""Match-level expected goals from Understat (data/raw/understat_xg.csv, made by scripts/pull_understat_xg.py), joined to football-data results.

Understat and football-data spell clubs differently. Both spellings are reduced to one comparison key: the canonical club name from
data/team_aliases.csv when the club is listed there, otherwise the name itself; then lower-cased with accents removed (umlauts spelled out, as
Understat does). A few older clubs are spelled differently by the two sources and are listed in OLD_CLUBS. A pairing happens once per season in
each orientation, so (league, season, home, away) identifies a match without needing the date.
"""
import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
XG_CSV = ROOT / "data" / "raw" / "understat_xg.csv"
ALIASES_CSV = ROOT / "data" / "team_aliases.csv"

# football-data spelling (as a comparison key) -> Understat spelling (as a comparison key), for clubs seen only in older seasons
OLD_CLUBS = {
    "huesca": "sd huesca", "spal": "spal 2013", "bastia": "sc bastia", "gazelec ajaccio": "gfc ajaccio", "1 fc nuernberg": "nuernberg",
    "ajaccio": "ac ajaccio", "evian": "evian thonon gaillard", "evian tg": "evian thonon gaillard", "auxerre": "aj auxerre", "le havre": "le havre ac",
    "qpr": "queens park rangers", "nott m forest": "nottingham forest", "nottm forest": "nottingham forest", "luton": "luton town", "ipswich": "ipswich town",
    "coventry": "coventry city", "cordoba": "cordoba", "oviedo": "real oviedo", "kiel": "holstein kiel", "holstein kiel": "holstein kiel",
}
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def _alias_map() -> dict[str, str]:
    with ALIASES_CSV.open(encoding="utf-8", newline="") as f:
        return {r["alias"]: r["canonical"] for r in csv.DictReader(f)}


def _key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.translate(_UMLAUTS)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def canonical(names: pd.Series) -> pd.Series:
    """Comparison keys for club names (see the module note)."""
    amap = _alias_map()
    return names.map(lambda n: OLD_CLUBS.get(_key(amap.get(n, n)), _key(amap.get(n, n))))


def load_xg(path: Path = XG_CSV) -> pd.DataFrame:
    """Columns league, season, home_c, away_c (comparison keys), xg_home, xg_away. Only played matches with both xG values."""
    df = pd.read_csv(path).dropna(subset=["home_xg", "away_xg"])
    df = df.assign(home_c=canonical(df["home_team"]), away_c=canonical(df["away_team"]))
    return df.rename(columns={"home_xg": "xg_home", "away_xg": "xg_away"})[["league", "season", "home_c", "away_c", "xg_home", "xg_away"]]


def attach_xg(matches: pd.DataFrame, league_id: str, xg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add xg_home / xg_away to football-data matches (columns season, home, away). Missing where Understat has no matching row."""
    xg = load_xg() if xg is None else xg
    x = xg[xg["league"] == league_id].drop(columns="league")
    m = matches.assign(home_c=canonical(matches["home"]), away_c=canonical(matches["away"]))
    return m.merge(x, on=["season", "home_c", "away_c"], how="left").drop(columns=["home_c", "away_c"])
