import numpy as np
import pytest
from scipy.stats import poisson

from pitchside.models.halves import half_time_matrix
from pitchside.models.split_table import HalfSplitTable
from pitchside.sim.record import from_goals
from pitchside.sim.simulate import simulate
from pitchside.sim.timing import (
    FIRST_HALF_SUPPORT,
    SECOND_HALF_SUPPORT,
    GoalTimeProfile,
)


def matrix(lam_h=1.6, lam_a=1.1, n=11):
    g = np.arange(n)
    p = np.outer(poisson.pmf(g, lam_h), poisson.pmf(g, lam_a))
    return p / p.sum()


def profile(seed=0):
    """A profile fitted on synthetic goals: first half uniform over 0-47, second half uniform over 45-96."""
    rng = np.random.default_rng(seed)
    p1 = rng.integers(0, 48, 4000)
    p2 = rng.integers(45, 97, 5000)
    return GoalTimeProfile(sigma=1.0).fit(np.r_[np.ones(4000), np.full(5000, 2)], np.r_[p1, p2])


# ---- the record ---------------------------------------------------------------------------------------------------

def test_real_match_record_validates_and_orders_goals():
    rec = from_goals((2, 1), (1, 0), [("away", 2, 80), ("home", 1, 44), ("home", 2, 47)])
    assert rec.goal_side[0].tolist() == [1, 1, -1] and rec.goal_period[0].tolist() == [1, 2, 2]
    assert rec.lead_after_each_goal()[0].tolist() == [1, 2, 1]


def test_first_half_stoppage_goal_sorts_before_an_early_second_half_goal():
    rec = from_goals((2, 0), (1, 0), [("home", 2, 46), ("home", 1, 47)])   # minute 47 in half 1, minute 46 in half 2
    assert rec.goal_period[0].tolist() == [1, 2]


def test_a_record_that_contradicts_its_scores_is_rejected():
    with pytest.raises(ValueError, match="full-time"):
        from_goals((3, 0), (1, 0), [("home", 1, 10), ("home", 2, 60)])
    with pytest.raises(ValueError, match="half-time"):
        from_goals((2, 0), (2, 0), [("home", 1, 10), ("home", 2, 60)])


# ---- the profile ---------------------------------------------------------------------------------------------------

def test_profiles_are_distributions_with_the_right_support():
    prof = profile()
    for period, (lo, hi) in ((1, FIRST_HALF_SUPPORT), (2, SECOND_HALF_SUPPORT)):
        assert prof.pmf[period].sum() == pytest.approx(1.0)
        assert prof.pmf[period][:lo].sum() == 0 and prof.pmf[period][hi + 1:].sum() == 0
    assert prof.share_before(1, FIRST_HALF_SUPPORT[1]) == pytest.approx(1.0)


def test_profile_needs_enough_data():
    with pytest.raises(ValueError, match="at least 50"):
        GoalTimeProfile().fit([1] * 10 + [2] * 10, list(range(10)) + list(range(50, 60)))


def test_sampled_minutes_follow_the_profile():
    prof = profile()
    rng = np.random.default_rng(1)
    m = prof.sample(rng, 1, 200_000)
    assert m.min() >= 0 and m.max() < FIRST_HALF_SUPPORT[1] + 1
    freq = np.bincount(m.astype(int), minlength=120)[:65] / len(m)
    assert np.abs(freq - prof.pmf[1][:65]).max() < 0.004


# ---- the simulator -------------------------------------------------------------------------------------------------

def sim(split=0.44, n=60_000, seed=3, p=None):
    return simulate(matrix() if p is None else p, split, profile(), n, np.random.default_rng(seed))


def test_every_simulated_match_is_internally_consistent():
    rec = sim()
    rec.validate()                                    # goals add up to FT and HT scores, in match order
    assert (rec.ht_home <= rec.ft_home).all() and (rec.ht_away <= rec.ft_away).all()


def test_full_time_scores_follow_the_input_scoreline_matrix():
    p = matrix()
    rec = sim(n=200_000)
    freq = np.zeros_like(p)
    np.add.at(freq, (rec.ft_home, rec.ft_away), 1)
    freq /= rec.n
    assert np.abs(freq - p).max() < 0.003            # Monte Carlo error only: family A prices are preserved


def test_half_time_scores_match_the_exact_analytic_split():
    p = matrix()
    rec = sim(n=200_000)
    q = half_time_matrix(p, 0.44)
    freq = np.zeros_like(q)
    np.add.at(freq, (rec.ht_home, rec.ht_away), 1)
    freq /= rec.n
    assert np.abs(freq - q).max() < 0.003


def test_the_simulator_uses_a_table_split_when_given_one():
    rng = np.random.default_rng(0)
    # a world in which every 1-1 full-time draw was 1-0 at half-time
    table = HalfSplitTable(kappa=2).fit([1] * 500 + [0] * 500, [0] * 500 + [0] * 500, [1] * 500 + [0] * 500, [1] * 500 + [0] * 500)
    rec = simulate(np.array([[0.0, 0.0], [0.0, 1.0]]), table, profile(), 5000, rng)   # always a 1-1 full-time score
    assert (rec.ft_home == 1).all() and (rec.ft_away == 1).all()
    assert (rec.ht_home == 1).mean() > 0.9


def test_goal_minutes_fall_inside_their_half():
    rec = sim()
    real = rec.goal_side != 0
    assert (rec.goal_minute[real & (rec.goal_period == 1)] < 65).all()
    assert (rec.goal_minute[real & (rec.goal_period == 2)] >= 40).all()


def test_same_seed_same_matches_different_seed_different_matches():
    a, b, c = sim(seed=5, n=2000), sim(seed=5, n=2000), sim(seed=6, n=2000)
    assert np.array_equal(a.goal_minute, b.goal_minute) and not np.array_equal(a.goal_minute, c.goal_minute)


def test_a_goalless_scoreline_gives_empty_but_valid_records():
    p = np.zeros((3, 3))
    p[0, 0] = 1.0
    rec = simulate(p, 0.44, profile(), 100, np.random.default_rng(0))
    rec.validate()
    assert rec.n == 100 and (rec.goal_side == 0).all()


def test_many_real_matches_can_be_batched_into_one_record():
    from pitchside.sim.record import from_many

    rec = from_many([(3, 2), (0, 0), (1, 2)], [(1, 0), (0, 0), (1, 0)],
                    [[("home", 1, 20), ("away", 2, 50), ("home", 2, 60), ("away", 2, 70), ("home", 2, 88)], [],
                     [("home", 1, 30), ("away", 2, 55), ("away", 2, 80)]])
    assert rec.n == 3 and rec.goal_side.shape == (3, 5)
    assert rec.goal_side[2, :3].tolist() == [1, -1, -1] and (rec.goal_side[1] == 0).all()
    with pytest.raises(ValueError):
        from_many([(1, 0)], [(0, 0)], [[]])           # goal list does not add up to the score
