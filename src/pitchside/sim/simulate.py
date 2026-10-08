"""Match simulator: from a full-time scoreline distribution to full match records (halves and goal minutes).

    1. sample a full-time score (h, a) from the goals model's scoreline matrix      -> family A prices stay exact
    2. sample the half-time score given (h, a) from the half-time split              -> halves, comebacks
    3. place every goal inside its half with the goal-timing profile, then order them -> game flow, minutes

The first step is the only place the goals model enters, so a better model later just supplies a better matrix.
"""
import numpy as np

from pitchside.models.split_table import binomial_prior
from pitchside.sim.record import MatchRecord
from pitchside.sim.timing import GoalTimeProfile

PAD_KEY = 1e9


def _conditional(split, h: int, a: int) -> np.ndarray:
    """P(half-time score | full-time h-a) from a HalfSplitTable, or from a plain first-half share p1."""
    return split.conditional(h, a) if hasattr(split, "conditional") else binomial_prior(h, a, float(split))


def simulate(scoreline: np.ndarray, split, profile: GoalTimeProfile, n_sims: int, rng: np.random.Generator) -> MatchRecord:
    """Simulate `n_sims` matches. `scoreline[h, a]` is P(full-time h-a); `split` is a HalfSplitTable or a first-half share."""
    n = scoreline.shape[0]
    flat = scoreline.ravel() / scoreline.sum()
    cells = rng.choice(n * n, size=n_sims, p=flat)
    ft_home, ft_away = np.divmod(cells, n)

    ht_home = np.zeros(n_sims, dtype=int)
    ht_away = np.zeros(n_sims, dtype=int)
    for cell in np.unique(cells):
        h, a = divmod(int(cell), n)
        rows = np.nonzero(cells == cell)[0]
        cond = _conditional(split, h, a)
        pick = rng.choice(cond.size, size=len(rows), p=cond.ravel() / cond.sum())
        ht_home[rows], ht_away[rows] = np.divmod(pick, a + 1)

    width = max(int((ft_home + ft_away).max()), 1)
    # goal slots per match, in this order: home 1st half, away 1st half, home 2nd half, away 2nd half
    counts = np.stack([ht_home, ht_away, ft_home - ht_home, ft_away - ht_away], axis=1)
    cum = np.cumsum(counts, axis=1)
    slot = np.arange(width)[None, :]
    group = sum((slot >= cum[:, [k]]).astype(int) for k in range(4))        # 0..3 real goals, 4 = padding
    side = np.select([group == 0, group == 1, group == 2, group == 3], [1, -1, 1, -1], 0).astype(np.int8)
    period = np.select([group <= 1, group <= 3], [1, 2], 0).astype(np.int8)

    minute = np.where(period == 1, profile.sample(rng, 1, (n_sims, width)), profile.sample(rng, 2, (n_sims, width)))
    key = np.where(side == 0, PAD_KEY, period.astype(float) * 1000 + minute)
    order = np.argsort(key, axis=1, kind="stable")
    take = lambda x: np.take_along_axis(x, order, axis=1)
    return MatchRecord(ft_home, ft_away, ht_home, ht_away, take(side), take(period), np.where(take(side) == 0, 0.0, take(minute)))
