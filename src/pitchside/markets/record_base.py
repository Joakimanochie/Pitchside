"""Markets that need more than a final score: they read a whole MatchRecord (halves, order and minute of goals).

Same contract as the score-based markets in `base.py`: one function per market, used to price (over many simulated
matches) and to settle (over the one real match), so the two can never disagree about a rule.
"""
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from pitchside.markets.base import HALF_LOST, HALF_WON, LOST, RESULT_NAMES, WON, Market
from pitchside.sim.record import MatchRecord

FIRST_HALF_END = 45   # first-half stoppage-time goals count as minute 45 for interval markets
FULL_TIME_END = 90    # second-half stoppage-time goals count as minute 90


@dataclass(frozen=True)
class RecordMarket:
    id: str
    family: str
    name: str
    selections: Callable[[float | None], list[str]]
    outcome: Callable[[str, float | None, MatchRecord], np.ndarray]
    has_line: bool = False
    lines: tuple[float, ...] = ()
    exclusive: bool = True
    needs_minutes: bool = False  # True when the rule depends on the order or minute of goals, not just the half scores

    def codes(self, selection: str, line: float | None, rec: MatchRecord) -> np.ndarray:
        if selection not in self.selections(line):
            raise ValueError(f"{self.id}: unknown selection {selection!r} for line {line}")
        return self.outcome(selection, line, rec)


def price_record(market: RecordMarket, line: float | None, rec: MatchRecord) -> list[dict]:
    """Price every selection from simulated matches: the share of matches in which it is won, lost or pushed."""
    rows = []
    for sel in market.selections(line):
        c = market.codes(sel, line, rec)
        n = len(c)
        p_win = float(((c == WON).sum() + 0.5 * (c == HALF_WON).sum()) / n)
        p_lose = float(((c == LOST).sum() + 0.5 * (c == HALF_LOST).sum()) / n)
        live = p_win + p_lose
        rows.append({"market_id": market.id, "line": line, "selection": sel,
                     "probability": p_win / live if live > 0 else float("nan"),
                     "p_win": p_win, "p_lose": p_lose, "p_push": max(0.0, 1.0 - live)})
    return rows


def settle_record(market: RecordMarket, line: float | None, selection: str, rec: MatchRecord) -> dict:
    """Settle one selection against the real match record (N = 1)."""
    code = int(market.codes(selection, line, rec)[0])
    value = None if RESULT_NAMES[code] == "push" else (1.0 if code in (WON, HALF_WON) else 0.0)
    return {"result": RESULT_NAMES[code], "outcome_value": value}


# ---- views of a record -----------------------------------------------------------------------------------------

def view(rec: MatchRecord, which: str) -> tuple[np.ndarray, np.ndarray]:
    """(home goals, away goals) for the whole match ('ft'), the first half ('ht') or the second half ('h2')."""
    return {"ft": (rec.ft_home, rec.ft_away), "ht": (rec.ht_home, rec.ht_away), "h2": (rec.h2_home, rec.h2_away)}[which]


def wrap_score_market(base: Market, which: str, new_id: str, name: str, family: str, *, options: list[str] | None = None,
                      lines: tuple[float, ...] | None = None, exclusive: bool | None = None) -> RecordMarket:
    """Reuse a score-based market's rules on the first-half or second-half score."""
    sel = (lambda line: list(options)) if options is not None else base.selections
    return RecordMarket(new_id, family, name, sel, lambda s, line, rec: base.outcome(s, line, *view(rec, which)),
                        base.has_line, base.lines if lines is None else lines, base.exclusive if exclusive is None else exclusive)


# ---- facts about the order of goals ----------------------------------------------------------------------------

def n_goals(rec: MatchRecord) -> np.ndarray:
    return (rec.goal_side != 0).sum(axis=1)


def first_goal_side(rec: MatchRecord) -> np.ndarray:
    """+1 home, -1 away, 0 no goal."""
    return rec.goal_side[:, 0] if rec.goal_side.shape[1] else np.zeros(rec.n, dtype=int)


def last_goal_side(rec: MatchRecord) -> np.ndarray:
    if not rec.goal_side.shape[1]:
        return np.zeros(rec.n, dtype=int)
    idx = np.maximum(n_goals(rec) - 1, 0)
    return np.where(n_goals(rec) > 0, rec.goal_side[np.arange(rec.n), idx], 0)


def max_lead(rec: MatchRecord, team: int) -> np.ndarray:
    """Largest lead the team (+1 home, -1 away) ever had, counted after each goal. 0 if it never led."""
    if not rec.goal_side.shape[1]:
        return np.zeros(rec.n, dtype=int)
    return np.maximum((team * rec.lead_after_each_goal()).max(axis=1), 0)


def max_deficit(rec: MatchRecord, team: int) -> np.ndarray:
    """Largest deficit the team ever had. 0 if it never trailed."""
    return max_lead(rec, -team)


def longest_run(rec: MatchRecord, team: int) -> np.ndarray:
    """Most goals in a row by the team (+1 home, -1 away) with no goal from the other side in between."""
    best = np.zeros(rec.n, dtype=int)
    run = np.zeros(rec.n, dtype=int)
    for t in range(rec.goal_side.shape[1]):
        s = rec.goal_side[:, t]
        run = np.where(s == team, run + 1, 0)
        best = np.maximum(best, run)
    return best


def clock(rec: MatchRecord) -> np.ndarray:
    """Minute used by interval markets: the displayed minute, with stoppage time counted as 45 / 90 and at least 1."""
    shown = np.floor(rec.goal_minute)
    capped = np.where(rec.goal_period == 1, np.minimum(shown, FIRST_HALF_END), np.minimum(shown, FULL_TIME_END))
    return np.maximum(capped, 1)


def goals_by_minute(rec: MatchRecord, minute: int) -> tuple[np.ndarray, np.ndarray]:
    """(home, away) goals scored up to and including `minute` on the interval-market clock."""
    seen = (rec.goal_side != 0) & (clock(rec) <= minute)
    return ((rec.goal_side == 1) & seen).sum(axis=1), ((rec.goal_side == -1) & seen).sum(axis=1)
