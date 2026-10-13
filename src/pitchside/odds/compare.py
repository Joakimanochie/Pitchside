"""Comparing our probability with a bookmaker price.

A bookmaker's odds contain a margin (the overround): the implied probabilities of all outcomes of a market add up to more than 1.
`demargin` removes it proportionally to get the bookmaker's own view of each outcome ("fair" probability). Then:

    edge = our probability - fair probability                (in probability points)
    EV   = our probability * odds - 1                          (expected profit per unit staked, if our probability were right)

Neither says the bet is good. Backtests show the bookmakers' closing prices beat our probabilities on the match result, so a large edge is
more often our error than theirs (scripts/backtest_value.py). The comparison is information, not advice.
"""
from collections.abc import Sequence


def implied(odds: float) -> float:
    return 1.0 / odds


def overround(odds: Sequence[float]) -> float:
    """Sum of implied probabilities of a complete market minus 1 (the bookmaker's margin, e.g. 0.05 = 5%)."""
    return sum(1.0 / o for o in odds) - 1.0


def demargin(odds: Sequence[float]) -> list[float]:
    """Proportional de-margin: implied probabilities rescaled to add up to 1. Needs every outcome of the market."""
    inv = [1.0 / o for o in odds]
    total = sum(inv)
    return [x / total for x in inv]


def edge(p: float, fair: float) -> float:
    return p - fair


def expected_value(p: float, odds: float) -> float:
    return p * odds - 1.0


def kelly_fraction(p: float, odds: float) -> float:
    """Growth-optimal stake as a share of bankroll if p were exactly right; 0 when there is no edge. Shown only to explain why it is not advice."""
    b = odds - 1.0
    return max(0.0, (p * b - (1.0 - p)) / b) if b > 0 else 0.0
