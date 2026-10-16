"""Family G (cards), card timing: cards by half, which team gets the first card, and whether a card is shown by a given minute.

Priced from the cards count model (joint distribution of each side's cards) plus the typical share and timing of cards across a match
(models/cardtiming.py). Settled from the cards of the match with their minutes (`card_events`), and only when those were verified against the real
card counts, never from the totals alone.

    cards_h1_ou        1st half cards over/under (cards of both teams)
    cards_h2_ou        2nd half cards over/under
    cards_half_most    which half has more cards: 1st, 2nd or equal
    first_card_team    which team is shown the first card (home, away) or none
    first_card_by      a card is shown by minute `line`: yes / no
"""
from dataclasses import dataclass

from pitchside.markets.base import Market


def _unused_outcome(sel, line, h, a):
    raise ValueError("card timing markets are settled from the cards of the match, not from the score")


@dataclass(frozen=True)
class CardTimingMarket(Market):
    kind: str = ""


def _m(id_, name, kind, options, lines=()):
    return CardTimingMarket(id_, "G", name, (lambda line, o=options: list(o)), _unused_outcome, bool(lines), tuple(lines), True, None, kind)


MARKETS: dict[str, CardTimingMarket] = {m.id: m for m in [
    _m("cards_h1_ou", "1st Half Cards Over/Under", "h1", ["over", "under"], (0.5, 1.5, 2.5)),
    _m("cards_h2_ou", "2nd Half Cards Over/Under", "h2", ["over", "under"], (0.5, 1.5, 2.5, 3.5)),
    _m("cards_half_most", "Half With Most Cards", "half_most", ["1st", "2nd", "equal"]),
    _m("first_card_team", "First Card (team)", "first_team", ["home", "away", "none"]),
    _m("first_card_by", "Card Shown By Minute", "first_by", ["yes", "no"], (15, 30, 45)),
]}


def settle_card_timing(market: CardTimingMarket, line: float | None, selection: str, cards: list) -> dict:
    """cards: [[side, period, minute], ...] in the order they were shown. Returns {'result', 'outcome_value'}."""
    h1 = sum(1 for c in cards if c[1] == 1)
    h2 = sum(1 for c in cards if c[1] == 2)
    if market.kind == "h1":
        won = (h1 > line) if selection == "over" else (h1 < line)
    elif market.kind == "h2":
        won = (h2 > line) if selection == "over" else (h2 < line)
    elif market.kind == "half_most":
        won = selection == ("1st" if h1 > h2 else "2nd" if h2 > h1 else "equal")
    elif market.kind == "first_team":
        won = selection == (cards[0][0] if cards else "none")
    elif market.kind == "first_by":
        by = bool(cards) and min(c[2] for c in cards) <= line
        won = by if selection == "yes" else not by
    else:
        raise ValueError(f"unknown card timing market {market.id}")
    return {"result": "won" if won else "lost", "outcome_value": 1.0 if won else 0.0}
