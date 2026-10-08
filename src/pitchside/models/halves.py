"""Half-time model: split a full-time scoreline distribution into halves.

Each goal falls in the first half independently with probability p1 (about 0.45: late goals are more common).
Given a full-time score (h, a), half-time goals are Binomial(h, p1) for the home side and Binomial(a, p1) for the
away side, so the whole joint distribution follows from the full-time scoreline matrix P[h, a]:

    J[h, a, i, j] = P[h, a] * Bin(i; h, p1) * Bin(j; a, p1)          (half-time score i-j)

This is exact for the independent-goals assumption. It is the analytic reference that the simulator must agree
with, and the first thing the real half-time scores are tested against.
"""
import numpy as np
from scipy.stats import binom


def split_tensor(p: np.ndarray, p1) -> np.ndarray:
    """J[h, a, i, j]: joint probability of full-time score h-a and half-time score i-j.
    `p1` is either the first-half goal share (independent split) or a HalfSplitTable (empirical split)."""
    if hasattr(p1, "tensor"):
        return p1.tensor(p)
    n = p.shape[0]
    g = np.arange(n)
    b = binom.pmf(g[None, :], g[:, None], p1)  # b[h, i] = P(i first-half goals | h goals)
    return np.einsum("ha,hi,aj->haij", p, b, b)


def half_time_matrix(p: np.ndarray, p1: float) -> np.ndarray:
    """Q[i, j]: probability of half-time score i-j."""
    return split_tensor(p, p1).sum(axis=(0, 1))


def second_half_matrix(p: np.ndarray, p1: float) -> np.ndarray:
    """S[x, y]: probability that the second half ends x-y (full-time goals minus half-time goals)."""
    j = split_tensor(p, p1)
    n = p.shape[0]
    h, a, i, k = np.indices((n, n, n, n))
    valid = (i <= h) & (k <= a)
    s = np.zeros((n, n))
    np.add.at(s, (h[valid] - i[valid], a[valid] - k[valid]), j[valid])
    return s


def result_onehot(n: int) -> np.ndarray:
    """one_hot[x, y, r]: 1 where score x-y is a home win (r=0), draw (r=1) or away win (r=2)."""
    x, y = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    return np.eye(3)[np.select([x > y, x == y], [0, 1], 2)]


def ht_ft_probabilities(p: np.ndarray, p1: float) -> np.ndarray:
    """3x3 matrix: rows = half-time result (home, draw, away), columns = full-time result."""
    one_hot = result_onehot(p.shape[0])
    return np.einsum("haij,hac,ijr->rc", split_tensor(p, p1), one_hot, one_hot)


def estimate_p1(ht_goals: float, ft_goals: float) -> float:
    """Share of goals scored in the first half, from totals over a training set."""
    return float(ht_goals) / float(ft_goals)
