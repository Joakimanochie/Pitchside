import numpy as np
import pytest
from scipy.stats import poisson

from pitchside.markets.halves import HT_FT, MARKETS, RESULTS
from pitchside.markets.record_base import price_record, settle_record
from pitchside.models.halves import (
    half_time_matrix,
    ht_ft_probabilities,
    second_half_matrix,
)
from pitchside.sim.record import from_goals
from pitchside.sim.simulate import simulate
from pitchside.sim.timing import GoalTimeProfile


def real(ft, ht, goals):
    return from_goals(ft, ht, goals)


def result(market_id, selection, rec, line=None):
    return settle_record(MARKETS[market_id], line, selection, rec)["result"]


# Arsenal 3-2 Leeds: 1-0 at half-time. Goals: A 20', L 50', A 60', L 70', A 88'
MATCH = real((3, 2), (1, 0), [("home", 1, 20), ("away", 2, 50), ("home", 2, 60), ("away", 2, 70), ("home", 2, 88)])
GOALLESS = real((0, 0), (0, 0), [])
COMEBACK = real((1, 2), (1, 0), [("home", 1, 30), ("away", 2, 55), ("away", 2, 80)])   # led at half-time, lost


@pytest.mark.parametrize("market,line,sel,rec,expected", [
    ("1x2_h1", None, "home", MATCH, "won"), ("1x2_h2", None, "draw", MATCH, "won"), ("1x2_h2", None, "home", MATCH, "lost"),   # second half ended 2-2
    ("1x2_h2", None, "draw", real((2, 2), (0, 0), [("home", 2, 50), ("home", 2, 60), ("away", 2, 70), ("away", 2, 80)]), "won"),
    ("ou_total_h1", 0.5, "over", MATCH, "won"), ("ou_total_h1", 1.5, "over", MATCH, "lost"), ("ou_total_h2", 3.5, "over", MATCH, "won"),
    ("ou_total_h1", 1.0, "over", MATCH, "push"),
    ("btts_h1", None, "no", MATCH, "won"),
    ("btts_h2", None, "yes", MATCH, "won"),
    ("clean_sheet_home_h1", None, "yes", MATCH, "won"), ("clean_sheet_away_h1", None, "yes", MATCH, "lost"), ("win_to_nil_home_h1", None, "yes", MATCH, "won"),
    ("exact_goals_h1", None, "1", MATCH, "won"), ("exact_goals_h2", None, "3+", MATCH, "won"),
    ("correct_score_h1", None, "1:0", MATCH, "won"), ("correct_score_h1", None, "other", GOALLESS, "lost"),
    ("correct_score_h1", None, "0:0", GOALLESS, "won"),
    ("multigoals_h2", None, "4+", MATCH, "won"), ("multigoals_h2", None, "2-3", MATCH, "lost"), ("multigoals_h2", None, "4+", real((4, 0), (0, 0), [("home", 2, 50 + i) for i in range(4)]), "won"),
    ("multigoals_h1", None, "no_goal", GOALLESS, "won"),
    ("asian_handicap_h1", -0.5, "home", MATCH, "won"), ("handicap_3way_h1", -1.0, "draw", MATCH, "won"),
    ("ht_ft", None, "home/home", MATCH, "won"), ("ht_ft", None, "home/draw", MATCH, "lost"),
    ("ht_ft", None, "home/away", COMEBACK, "won"), ("ht_ft", None, "draw/draw", GOALLESS, "won"),
    ("both_halves_over_15", None, "yes", MATCH, "lost"), ("both_halves_under_15", None, "yes", GOALLESS, "won"),
    ("both_halves_over_15", None, "yes", real((4, 0), (2, 0), [("home", 1, 10), ("home", 1, 20), ("home", 2, 60), ("home", 2, 70)]), "won"),
    ("gg_ng_each_half", None, "no/yes", MATCH, "won"), ("gg_ng_each_half", None, "yes/yes", MATCH, "lost"),
    ("home_scores_both_halves", None, "yes", MATCH, "won"), ("away_scores_both_halves", None, "yes", MATCH, "lost"),
    ("btts_both_halves", None, "yes", MATCH, "lost"),
    ("highest_scoring_half", None, "2nd", MATCH, "won"), ("highest_scoring_half_home", None, "2nd", MATCH, "won"),
    ("highest_scoring_half_away", None, "2nd", MATCH, "won"), ("highest_scoring_half", None, "equal", GOALLESS, "won"),
    ("home_wins_either_half", None, "yes", COMEBACK, "won"), ("home_wins_both_halves", None, "yes", COMEBACK, "lost"),
    ("home_wins_both_halves", None, "yes", MATCH, "lost"), ("home_wins_both_halves", None, "yes", real((2, 0), (1, 0), [("home", 1, 10), ("home", 2, 60)]), "won"), ("away_wins_either_half", None, "yes", MATCH, "lost"),
    ("ht_or_ft_result", None, "home", COMEBACK, "won"), ("ht_or_ft_result", None, "away", COMEBACK, "won"),
    ("ht_or_ft_result", None, "draw", COMEBACK, "lost"),
])
def test_settlement_examples(market, line, sel, rec, expected):
    assert result(market, sel, rec, line) == expected


# ---- the simulator and the exact half-time maths must agree -------------------------------------------------------------

def scoreline(lam_h=1.7, lam_a=1.1, n=11):
    g = np.arange(n)
    p = np.outer(poisson.pmf(g, lam_h), poisson.pmf(g, lam_a))
    return p / p.sum()


def profile():
    rng = np.random.default_rng(0)
    return GoalTimeProfile().fit(np.r_[np.ones(4000), np.full(5000, 2)], np.r_[rng.integers(0, 48, 4000), rng.integers(45, 97, 5000)])


@pytest.fixture(scope="module")
def sim_and_matrix():
    p = scoreline()
    return p, simulate(p, 0.44, profile(), 300_000, np.random.default_rng(11))


def probs(market_id, line, rec):
    return {r["selection"]: r["probability"] for r in price_record(MARKETS[market_id], line, rec)}


def test_simulated_half_time_prices_match_the_exact_analytic_split(sim_and_matrix):
    p, rec = sim_and_matrix
    q, s = half_time_matrix(p, 0.44), second_half_matrix(p, 0.44)
    ht = probs("1x2_h1", None, rec)
    assert ht["home"] == pytest.approx(np.tril(q, -1).sum(), abs=0.005)
    assert ht["draw"] == pytest.approx(np.trace(q), abs=0.005)
    h2 = probs("1x2_h2", None, rec)
    assert h2["away"] == pytest.approx(np.triu(s, 1).sum(), abs=0.005)
    tot = np.add.outer(np.arange(q.shape[0]), np.arange(q.shape[0]))
    assert probs("ou_total_h1", 1.5, rec)["over"] == pytest.approx(q[tot > 1.5].sum(), abs=0.005)
    j = ht_ft_probabilities(p, 0.44)
    htft = probs("ht_ft", None, rec)
    for r, ha in enumerate(RESULTS):
        for c, fa in enumerate(RESULTS):
            assert htft[f"{ha}/{fa}"] == pytest.approx(j[r, c], abs=0.004), (ha, fa)


def test_exclusive_selections_of_every_half_market_sum_to_one(sim_and_matrix):
    _, rec = sim_and_matrix
    for m in MARKETS.values():
        if not m.exclusive:
            continue
        for line in (m.lines if m.has_line else (None,)):
            assert sum(probs(m.id, line, rec).values()) == pytest.approx(1.0, abs=1e-9), (m.id, line)


def test_logical_relations_between_half_markets(sim_and_matrix):
    _, rec = sim_and_matrix
    htft = probs("ht_ft", None, rec)
    assert sum(htft.values()) == pytest.approx(1.0)
    both_o = probs("both_halves_over_15", None, rec)["yes"]
    assert both_o < probs("ou_total_h1", 1.5, rec)["over"]
    assert probs("home_wins_both_halves", None, rec)["yes"] < probs("home_wins_either_half", None, rec)["yes"]
    # "half-time or full-time result" contains both the half-time and the full-time result events
    ft_home = sum(v for k, v in htft.items() if k.endswith("/home"))
    ht_home = sum(v for k, v in htft.items() if k.startswith("home/"))
    assert probs("ht_or_ft_result", None, rec)["home"] >= max(ft_home, ht_home) - 1e-12
    assert probs("ht_or_ft_result", None, rec)["home"] == pytest.approx(ft_home + ht_home - htft["home/home"], abs=1e-12)


def test_every_listed_ht_ft_pair_exists():
    assert len(HT_FT) == 9 and set(MARKETS["ht_ft"].selections(None)) == set(HT_FT)


def test_unknown_selection_is_rejected():
    with pytest.raises(ValueError, match="unknown selection"):
        settle_record(MARKETS["ht_ft"], None, "home/sideways", MATCH)
