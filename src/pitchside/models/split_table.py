"""Empirical half-time split: P(half-time score | full-time score), learned from real matches.

The independent split in `halves.py` treats every goal as equally likely to fall in either half. Real football has more
comebacks than that allows (a side leading at half-time loses more often than independent goals imply). This table
fixes it directly: for each full-time score (h, a) it counts how the half-time score was distributed in training matches
and blends that with the independent split as a prior of `kappa` pseudo-matches, so rare scorelines stay sensible.

The full-time distribution is untouched: it still comes from the goals model, so family A prices stay exactly consistent.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import binom


def binomial_prior(h: int, a: int, p1: float) -> np.ndarray:
    return np.outer(binom.pmf(np.arange(h + 1), h, p1), binom.pmf(np.arange(a + 1), a, p1))


@dataclass
class HalfSplitTable:
    p1: float = 0.44
    kappa: float = 20.0
    counts: dict[tuple[int, int], np.ndarray] = field(default_factory=dict)
    _cache: dict[tuple[int, int], np.ndarray] = field(default_factory=dict, repr=False)

    def fit(self, ht_home, ht_away, ft_home, ft_away) -> "HalfSplitTable":
        ht_home, ht_away = np.asarray(ht_home, int), np.asarray(ht_away, int)
        ft_home, ft_away = np.asarray(ft_home, int), np.asarray(ft_away, int)
        if ((ht_home > ft_home) | (ht_away > ft_away)).any():
            raise ValueError("a half-time score exceeds its full-time score")
        self.p1 = float((ht_home + ht_away).sum() / (ft_home + ft_away).sum())
        self.counts, self._cache = {}, {}
        for h, a, i, j in zip(ft_home, ft_away, ht_home, ht_away, strict=True):
            cell = self.counts.setdefault((int(h), int(a)), np.zeros((h + 1, a + 1)))
            cell[i, j] += 1
        return self

    def conditional(self, h: int, a: int) -> np.ndarray:
        """Matrix C[i, j] = P(half-time i-j | full-time h-a); rows i = 0..h, columns j = 0..a; sums to 1."""
        cached = self._cache.get((h, a))
        if cached is None:
            prior = binomial_prior(h, a, self.p1)
            seen = self.counts.get((h, a))
            cached = prior if seen is None else (seen + self.kappa * prior) / (seen.sum() + self.kappa)
            self._cache[(h, a)] = cached
        return cached

    def tensor(self, p: np.ndarray) -> np.ndarray:
        """J[h, a, i, j] = P[h, a] * C_{h,a}[i, j] for a full-time scoreline matrix P."""
        n = p.shape[0]
        out = np.zeros((n, n, n, n))
        for h in range(n):
            for a in range(n):
                out[h, a, : h + 1, : a + 1] = p[h, a] * self.conditional(h, a)
        return out
