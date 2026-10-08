"""When goals happen: the distribution of a goal's minute within each half, learned from verified Understat goal events.

Within a half, goal minutes are treated as independent draws from a smoothed empirical distribution (late goals are more
common, and the first minutes of stoppage time carry real mass). This is the first, simple timing layer; whether it is good
enough is decided by testing path markets against real matches, not by assuming it.
"""
from dataclasses import dataclass, field

import numpy as np

MAX_MINUTE = 109  # real second-half stoppage goals reach minute 105; nothing in the data goes past that
FIRST_HALF_SUPPORT = (0, 64)    # a first-half goal cannot be later than this (the latest seen is minute 57)
SECOND_HALF_SUPPORT = (40, 109)  # nor a second-half goal earlier than this


@dataclass
class GoalTimeProfile:
    sigma: float = 1.0
    pmf: dict[int, np.ndarray] = field(default_factory=dict)  # period -> P(minute), length MAX_MINUTE + 1

    def fit(self, periods, minutes) -> "GoalTimeProfile":
        periods, minutes = np.asarray(periods, int), np.asarray(minutes, int)
        for period, (lo, hi) in ((1, FIRST_HALF_SUPPORT), (2, SECOND_HALF_SUPPORT)):
            counts = np.bincount(minutes[(periods == period) & (minutes >= lo) & (minutes <= hi)], minlength=MAX_MINUTE + 1).astype(float)
            counts = counts[: MAX_MINUTE + 1]
            if counts.sum() < 50:
                raise ValueError(f"need at least 50 goals in period {period} to estimate a profile, got {int(counts.sum())}")
            kernel_x = np.arange(-4, 5)
            kernel = np.exp(-0.5 * (kernel_x / self.sigma) ** 2) if self.sigma > 0 else np.array([1.0])
            kernel = kernel / kernel.sum()
            smooth = np.convolve(counts, kernel, mode="same")
            mask = np.zeros(MAX_MINUTE + 1)
            mask[lo:hi + 1] = 1.0
            smooth = (smooth + 1e-9) * mask
            self.pmf[period] = smooth / smooth.sum()
        return self

    def sample(self, rng: np.random.Generator, period: int, shape) -> np.ndarray:
        """Minutes with a fractional tie-break: float array, integer part = displayed minute."""
        cdf = np.cumsum(self.pmf[period])
        u = rng.random(shape)
        minute = np.minimum(np.searchsorted(cdf, u, side="right"), MAX_MINUTE)
        return minute + rng.random(shape) * 0.999

    def share_before(self, period: int, minute: int) -> float:
        """P(a goal in this half happens in a minute <= `minute`)."""
        return float(self.pmf[period][: minute + 1].sum())
