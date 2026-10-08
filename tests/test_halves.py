import numpy as np
import pytest
from scipy.stats import poisson

from pitchside.models.halves import (
    estimate_p1,
    half_time_matrix,
    ht_ft_probabilities,
    second_half_matrix,
    split_tensor,
)


def matrix(lam_h=1.6, lam_a=1.1, n=11):
    g = np.arange(n)
    p = np.outer(poisson.pmf(g, lam_h), poisson.pmf(g, lam_a))
    return p / p.sum()


def test_joint_sums_to_one_and_marginalises_back_to_full_time():
    p = matrix()
    j = split_tensor(p, 0.45)
    assert j.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(j.sum(axis=(2, 3)), p, atol=1e-12)


def test_half_time_goals_never_exceed_full_time_goals():
    j = split_tensor(matrix(), 0.45)
    n = j.shape[0]
    h, a, i, k = np.indices((n, n, n, n))
    assert j[(i > h) | (k > a)].sum() == pytest.approx(0.0)


def test_poisson_thinning_gives_the_known_half_time_distribution():
    # With independent Poisson full-time goals, first-half goals are Poisson(p1 * lambda): an exact identity.
    lam_h, lam_a, p1 = 1.7, 1.2, 0.44
    n = 25
    p = matrix(lam_h, lam_a, n)
    q = half_time_matrix(p, p1)
    expected = np.outer(poisson.pmf(np.arange(n), lam_h * p1), poisson.pmf(np.arange(n), lam_a * p1))
    np.testing.assert_allclose(q[:8, :8], expected[:8, :8], atol=1e-7)


def test_second_half_is_poisson_with_the_remaining_share():
    lam_h, lam_a, p1 = 1.7, 1.2, 0.44
    n = 25
    s = second_half_matrix(matrix(lam_h, lam_a, n), p1)
    expected = np.outer(poisson.pmf(np.arange(n), lam_h * (1 - p1)), poisson.pmf(np.arange(n), lam_a * (1 - p1)))
    np.testing.assert_allclose(s[:8, :8], expected[:8, :8], atol=1e-7)
    assert s.sum() == pytest.approx(1.0)


def test_ht_ft_matrix_is_a_distribution_and_its_margins_are_right():
    p = matrix()
    m = ht_ft_probabilities(p, 0.45)
    assert m.sum() == pytest.approx(1.0)
    n = p.shape[0]
    full_time = np.array([np.tril(p, -1).sum(), np.trace(p), np.triu(p, 1).sum()])
    np.testing.assert_allclose(m.sum(axis=0), full_time, atol=1e-12)
    q = half_time_matrix(p, 0.45)
    half_time = np.array([np.tril(q, -1).sum(), np.trace(q), np.triu(q, 1).sum()])
    np.testing.assert_allclose(m.sum(axis=1), half_time, atol=1e-12)
    assert n == 11


def test_home_leading_at_half_time_rarely_ends_as_an_away_win():
    m = ht_ft_probabilities(matrix(), 0.45)
    assert m[0, 2] < 0.05 < m[0, 0]  # home/away is rare, home/home is common


def test_all_goals_in_one_half_is_handled():
    p = matrix()
    np.testing.assert_allclose(half_time_matrix(p, 1.0), p, atol=1e-12)          # every goal before the break
    q0 = half_time_matrix(p, 0.0)
    assert q0[0, 0] == pytest.approx(1.0)                                         # none before the break


def test_estimate_p1():
    assert estimate_p1(450, 1000) == pytest.approx(0.45)
