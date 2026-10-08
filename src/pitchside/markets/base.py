"""Market machinery shared by every family.

A market is one function: given arrays of home and away goals, return a settlement code per scoreline for
one selection. The same function prices a market from the model's scoreline matrix and settles it from a
real final score, so prediction and settlement can never disagree about a market's rules.

Settlement codes (ordered so that two half-stakes add up):
    LOST 0, HALF_LOST 1, PUSH 2, HALF_WON 3, WON 4
HALF_WON means half the stake won and half was returned; HALF_LOST means half lost and half returned.

Probability convention for a selection (see BUILD.md section 9):
    p_win  = P(WON) + 0.5 * P(HALF_WON)
    p_lose = P(LOST) + 0.5 * P(HALF_LOST)
    p_push = 1 - p_win - p_lose
    probability = p_win / (p_win + p_lose)      # the win chance on the stake that is actually at risk
Complementary selections of one market therefore sum to 1 even when pushes are possible.
"""
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

LOST, HALF_LOST, PUSH, HALF_WON, WON = 0, 1, 2, 3, 4
RESULT_NAMES = {LOST: "lost", HALF_LOST: "half_lost", PUSH: "push", HALF_WON: "half_won", WON: "won"}


def won_if(mask: np.ndarray) -> np.ndarray:
    """Yes/no selection: WON where mask is true, LOST elsewhere."""
    return np.where(mask, WON, LOST)


def _threshold_unit(x: np.ndarray, t: float) -> np.ndarray:
    """Single (half or whole) line: 'x > t' wins, 'x == t' pushes, 'x < t' loses."""
    return np.where(x > t, WON, np.where(x == t, PUSH, LOST))


def beats(x: np.ndarray, t: float) -> np.ndarray:
    """Settlement of the bet 'x is greater than t'. Quarter lines (t = k + 0.25 or 0.75) split the stake
    over the two adjacent half-lines, which produces HALF_WON / HALF_LOST."""
    if (t * 2) == int(t * 2):
        return _threshold_unit(x, t)
    # Each half-stake is LOST 0, PUSH 2 or WON 4; their sum halved is the combined code
    # (LOST+PUSH=2 -> HALF_LOST 1, PUSH+WON=6 -> HALF_WON 3). LOST+WON cannot happen on integer goals.
    return (_threshold_unit(x, t - 0.25) + _threshold_unit(x, t + 0.25)) // 2


@dataclass(frozen=True)
class Market:
    id: str
    family: str
    name: str
    selections: Callable[[float | None], list[str]]
    outcome: Callable[[str, float | None, np.ndarray, np.ndarray], np.ndarray]
    has_line: bool = False
    lines: tuple[float, ...] = ()  # default lines to price (empty for markets without a line)

    def codes(self, selection: str, line: float | None, home: np.ndarray, away: np.ndarray) -> np.ndarray:
        if selection not in self.selections(line):
            raise ValueError(f"{self.id}: unknown selection {selection!r} for line {line}")
        return self.outcome(selection, line, np.asarray(home), np.asarray(away))


def score_grid(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Home and away goals for every cell of an (n, n) scoreline matrix (index = goals)."""
    return np.meshgrid(np.arange(n), np.arange(n), indexing="ij")


def price(market: Market, line: float | None, matrix: np.ndarray) -> list[dict]:
    """Price every selection of a market from a scoreline matrix P[home_goals, away_goals]."""
    h, a = score_grid(matrix.shape[0])
    rows = []
    for sel in market.selections(line):
        c = market.codes(sel, line, h, a)
        p_win = float(matrix[c == WON].sum() + 0.5 * matrix[c == HALF_WON].sum())
        p_lose = float(matrix[c == LOST].sum() + 0.5 * matrix[c == HALF_LOST].sum())
        live = p_win + p_lose
        rows.append({
            "market_id": market.id, "line": line, "selection": sel,
            "probability": p_win / live if live > 0 else float("nan"),
            "p_win": p_win, "p_lose": p_lose, "p_push": max(0.0, 1.0 - live),
        })
    return rows


def settle(market: Market, line: float | None, selection: str, home_goals: int, away_goals: int) -> dict:
    """Settle one selection against a real final score. outcome_value is 1/0 on the stake at risk, None for a push."""
    code = int(market.codes(selection, line, np.array([home_goals]), np.array([away_goals]))[0])
    value = None if code == PUSH else (1.0 if code in (WON, HALF_WON) else 0.0)
    return {"result": RESULT_NAMES[code], "outcome_value": value}
