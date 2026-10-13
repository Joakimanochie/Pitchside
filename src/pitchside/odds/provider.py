"""The shape every odds source returns. A provider only turns its own format into OddsRow values for our market ids; matching rows to our
matches and storing them is shared (store.py), so a new source (a licensed API, or a manual paste from a betting site) is one small class.

Sources in use are recorded in docs/odds-sources.md (licence and terms) before they are switched on.
"""
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class OddsRow:
    """One price for one selection of one market, for a fixture identified by league, date and club names as the source spells them."""
    league_id: str
    match_date: date
    home: str
    away: str
    bookmaker: str          # 'avg', 'max', 'b365', ...
    market_id: str          # our id: 1x2, ou_total, asian_handicap
    line: float | None
    selection: str          # our code: home, draw, away, over, under
    odds: float


class OddsProvider(Protocol):
    source: str             # stored with every snapshot
    name_source: str        # which column of team_aliases spells this source's clubs

    def fetch(self) -> list[OddsRow]: ...
