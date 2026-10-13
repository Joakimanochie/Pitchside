"""Pre-match odds for the next round of fixtures, from football-data.co.uk/fixtures.csv.

The file is published for the coming days only and carries, per fixture, the market average and best price of many bookmakers for the match result,
over/under 2.5 goals and the main Asian handicap, plus Bet365's own prices. The same site's historical files are what our backtests use for closing odds.
Terms are on football-data.co.uk (free to use with credit); see docs/odds-sources.md. Closing-price columns in this file are ignored: we want what was
available before kickoff, not at it.
"""
import csv
import io
from datetime import UTC, datetime

import requests

from pitchside.leagues import LEAGUES
from pitchside.odds.provider import OddsRow

URL = "https://football-data.co.uk/fixtures.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Pitchside odds snapshot)"}
BOOKMAKERS = {"avg": "Avg", "max": "Max", "b365": "B365"}
FD_TO_LEAGUE = {lg.fd_code: lg.id for lg in LEAGUES.values()}


def _num(row: dict, col: str) -> float | None:
    try:
        v = float(row.get(col, "") or "")
    except ValueError:
        return None
    return v if v > 1 else None


def parse(text: str) -> list[OddsRow]:
    """Rows for fixtures of the leagues we cover. A market is kept for a bookmaker only if every outcome of it has a price."""
    out: list[OddsRow] = []
    for row in csv.DictReader(io.StringIO(text.removeprefix(chr(0xFEFF)))):
        league = FD_TO_LEAGUE.get((row.get("Div") or "").strip())
        if league is None:
            continue
        try:
            day = datetime.strptime(row["Date"].strip(), "%d/%m/%Y").replace(tzinfo=UTC).date()  # a calendar date, not an instant
        except (KeyError, ValueError):
            continue
        home, away = row["HomeTeam"].strip(), row["AwayTeam"].strip()

        def add(bookmaker, market, line, prices, league=league, day=day, home=home, away=away):
            if all(p is not None for p in prices.values()):
                out.extend(OddsRow(league, day, home, away, bookmaker, market, line, sel, p) for sel, p in prices.items())

        line = None
        try:
            line = float(row["AHh"]) if row.get("AHh", "") != "" else None
        except ValueError:
            line = None
        for key, prefix in BOOKMAKERS.items():
            add(key, "1x2", None, {"home": _num(row, f"{prefix}H"), "draw": _num(row, f"{prefix}D"), "away": _num(row, f"{prefix}A")})
            add(key, "ou_total", 2.5, {"over": _num(row, f"{prefix}>2.5"), "under": _num(row, f"{prefix}<2.5")})
            if line is not None:
                add(key, "asian_handicap", line, {"home": _num(row, f"{prefix}AHH"), "away": _num(row, f"{prefix}AHA")})
    return out


class FootballDataFixtures:
    source = "footballdata_fixtures"
    name_source = "footballdata"

    def __init__(self, session: requests.Session | None = None):
        self._http = session or requests

    def fetch(self) -> list[OddsRow]:
        r = self._http.get(URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return parse(r.content.decode("latin-1"))
