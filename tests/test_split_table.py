import numpy as np
import pytest
from scipy.stats import poisson

from pitchside.models.halves import (
    half_time_matrix,
    ht_ft_probabilities,
    second_half_matrix,
    split_tensor,
)
from pitchside.models.split_table import HalfSplitTable, binomial_prior


def matrix(lam_h=1.6, lam_a=1.1, n=11):
    g = np.arange(n)
    p = np.outer(poisson.pmf(g, lam_h), poisson.pmf(g, lam_a))
    return p / p.sum()


def synthetic(n=4000, seed=0, comeback=0.0):
    """Matches whose goals fall in the first half with prob 0.44 independently."""
    rng = np.random.default_rng(seed)
    ft_h, ft_a = rng.poisson(1.5, n), rng.poisson(1.2, n)
    ht_h, ht_a = rng.binomial(ft_h, 0.44), rng.binomial(ft_a, 0.44)
    return ht_h, ht_a, ft_h, ft_a


def test_conditional_is_a_distribution_for_seen_and_unseen_scores():
    t = HalfSplitTable().fit(*synthetic())
    for h, a in [(0, 0), (2, 1), (4, 3), (9, 9)]:      # (9, 9) was never observed: falls back to the prior
        c = t.conditional(h, a)
        assert c.shape == (h + 1, a + 1) and c.sum() == pytest.approx(1.0) and (c >= 0).all()


def test_p1_is_estimated_from_the_training_goals():
    ht_h, ht_a, ft_h, ft_a = synthetic()
    assert HalfSplitTable().fit(ht_h, ht_a, ft_h, ft_a).p1 == pytest.approx((ht_h + ht_a).sum() / (ft_h + ft_a).sum())


def test_with_independent_goals_the_table_agrees_with_the_independent_split():
    t = HalfSplitTable(kappa=20).fit(*synthetic(n=60000))
    for h, a in [(1, 0), (2, 1), (2, 2)]:
        np.testing.assert_allclose(t.conditional(h, a), binomial_prior(h, a, t.p1), atol=0.01)


def test_the_table_learns_comebacks_that_independent_goals_cannot_produce():
    # data where a 1-1 full-time draw is always 1-0 at half-time (never 0-1, 0-0 or 1-1): strong structure
    n = 400
    t = HalfSplitTable(p1=0.44, kappa=5).fit([1] * n, [0] * n, [1] * n, [1] * n)
    assert t.conditional(1, 1)[1, 0] > 0.9
    assert binomial_prior(1, 1, 0.44)[1, 0] < 0.3


def test_a_huge_kappa_ignores_the_data():
    t = HalfSplitTable(kappa=1e9).fit(*synthetic())
    np.testing.assert_allclose(t.conditional(2, 1), binomial_prior(2, 1, t.p1), atol=1e-6)


def test_tensor_is_a_joint_distribution_that_marginalises_back():
    t = HalfSplitTable().fit(*synthetic())
    p = matrix()
    j = t.tensor(p)
    assert j.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(j.sum(axis=(2, 3)), p, atol=1e-12)


def test_halves_helpers_accept_a_table_as_well_as_a_plain_p1():
    t = HalfSplitTable().fit(*synthetic())
    p = matrix()
    for q in (half_time_matrix(p, t), second_half_matrix(p, t)):
        assert q.sum() == pytest.approx(1.0)
    assert ht_ft_probabilities(p, t).sum() == pytest.approx(1.0)
    np.testing.assert_allclose(split_tensor(p, t), t.tensor(p))


def test_inconsistent_training_data_is_rejected():
    with pytest.raises(ValueError, match="exceeds"):
        HalfSplitTable().fit([3], [0], [2], [0])
