"""Price every market for one match.

Family A comes exactly from the goals model's scoreline matrix. Families B-E come from simulated matches that share
that same matrix, so the two always agree up to Monte Carlo error (about 0.1 percentage points at 100,000 simulations).
"""
import numpy as np

from pitchside.markets.base import price
from pitchside.markets.record_base import price_record
from pitchside.markets.registry import RECORD_MARKETS, SCORE_MARKETS
from pitchside.sim.simulate import simulate
from pitchside.sim.timing import GoalTimeProfile

DEFAULT_SIMS = 100_000


def price_all(scoreline: np.ndarray, split, profile: GoalTimeProfile, n_sims: int = DEFAULT_SIMS, seed: int | None = None) -> list[dict]:
    """Rows {market_id, line, selection, probability, p_win, p_lose, p_push} for every market and line."""
    rows: list[dict] = []
    for m in SCORE_MARKETS.values():
        for line in (m.lines if m.has_line else (None,)):
            rows.extend(price(m, line, scoreline))
    record = simulate(scoreline, split, profile, n_sims, np.random.default_rng(seed))
    for m in RECORD_MARKETS.values():
        for line in (m.lines if m.has_line else (None,)):
            rows.extend(price_record(m, line, record))
    return rows
