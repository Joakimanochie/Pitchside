from itertools import pairwise

import numpy as np
import pytest
from scipy.stats import poisson

from pitchside.db.markets import seed_markets
from pitchside.markets.base import (
    HALF_LOST,
    HALF_WON,
    LOST,
    PUSH,
    WON,
    beats,
    price,
    score_grid,
    settle,
)
from pitchside.markets.goals import MARKETS, MULTISCORE_GROUPS, price_match

CODE_NAMES = {LOST: "lost", HALF_LOST: "half_lost", PUSH: "push", HALF_WON: "half_won", WON: "won"}


def random_matrix(seed=0, n=11):
    rng = np.random.default_rng(seed)
    lam_h, lam_a = rng.uniform(0.6, 2.4), rng.uniform(0.4, 2.0)
    g = np.arange(n)
    p = np.outer(poisson.pmf(g, lam_h), poisson.pmf(g, lam_a))
    return p / p.sum()


def probs(market_id, line, matrix):
    return {r["selection"]: r["probability"] for r in price(MARKETS[market_id], line, matrix)}


def result(market_id, line, selection, h, a):
    return settle(MARKETS[market_id], line, selection, h, a)["result"]


# ---- settlement against real scores (worked by hand) -----------------------------------------------------------

@pytest.mark.parametrize("market,line,sel,h,a,expected", [
    ("1x2", None, "home", 2, 1, "won"), ("1x2", None, "draw", 2, 1, "lost"),
    ("double_chance", None, "x2", 1, 1, "won"), ("double_chance", None, "x2", 2, 1, "lost"),
    ("draw_no_bet", None, "home", 1, 1, "push"), ("draw_no_bet", None, "away", 0, 2, "won"),
    ("home_no_bet", None, "draw", 3, 0, "push"), ("home_no_bet", None, "away", 1, 1, "lost"),
    ("away_no_bet", None, "home", 0, 1, "push"), ("away_no_bet", None, "draw", 1, 1, "won"),
    ("ou_total", 2.5, "over", 2, 1, "won"), ("ou_total", 2.5, "under", 2, 1, "lost"),
    ("ou_total", 3.0, "over", 2, 1, "push"), ("ou_total", 3.0, "under", 2, 1, "push"),
    ("ou_total", 2.75, "over", 2, 1, "half_won"), ("ou_total", 3.25, "over", 2, 1, "half_lost"),
    ("ou_total", 2.75, "under", 2, 1, "half_lost"), ("ou_total", 2.25, "under", 1, 1, "half_won"),
    ("ou_home", 1.5, "over", 2, 1, "won"), ("ou_away", 1.5, "under", 2, 1, "won"),
    ("asian_handicap", -1.0, "home", 2, 1, "push"), ("asian_handicap", -1.5, "home", 2, 1, "lost"),
    ("asian_handicap", -1.5, "home", 3, 1, "won"), ("asian_handicap", -1.5, "away", 2, 1, "won"), ("asian_handicap", 1.5, "away", 2, 1, "lost"),
    ("asian_handicap", -0.75, "home", 2, 1, "half_won"), ("asian_handicap", -0.25, "home", 1, 1, "half_lost"),
    ("asian_handicap", 0.25, "home", 1, 1, "half_won"), ("asian_handicap", 0.0, "home", 1, 1, "push"),
    ("handicap_3way", -1.0, "draw", 1, 0, "won"),   # SportyBet 0:1 gives away a head start, so 1-0 becomes 1-1
    ("handicap_3way", -1.0, "home", 2, 0, "won"), ("handicap_3way", -1.0, "away", 0, 0, "won"),
    ("handicap_3way", 1.0, "home", 0, 0, "won"),    # SportyBet 1:0 gives home a head start
    ("btts", None, "yes", 1, 1, "won"), ("btts", None, "no", 2, 0, "won"),
    ("btts_2plus", None, "yes", 2, 2, "won"), ("btts_2plus", None, "yes", 2, 1, "lost"),
    ("btts_2plus", None, "no", 2, 1, "won"),
    ("odd_even", None, "odd", 2, 1, "won"), ("odd_even", None, "even", 0, 0, "won"),
    ("odd_even_home", None, "even", 0, 3, "won"), ("odd_even_away", None, "odd", 0, 3, "won"),
    ("exact_goals", None, "6+", 4, 3, "won"), ("exact_goals", None, "3", 2, 1, "won"),
    ("goal_range", None, "4-6", 3, 2, "won"), ("goal_range", None, "7+", 4, 3, "won"),
    ("goals_home", None, "3+", 5, 0, "won"), ("goals_away", None, "0", 5, 0, "won"),
    ("teams_to_score", None, "only_home", 2, 0, "won"), ("teams_to_score", None, "none", 0, 0, "won"),
    ("clean_sheet_home", None, "yes", 2, 0, "won"), ("clean_sheet_home", None, "yes", 2, 1, "lost"),
    ("clean_sheet_away", None, "yes", 0, 1, "won"),
    ("win_to_nil_home", None, "yes", 2, 0, "won"), ("win_to_nil_home", None, "yes", 0, 0, "lost"),
    ("winning_margin", None, "home_3+", 4, 0, "won"), ("winning_margin", None, "away_2", 0, 2, "won"),
    ("winning_margin", None, "draw", 0, 0, "won"),
    ("excluded_goals", None, "2", 2, 1, "won"), ("excluded_goals", None, "3", 2, 1, "lost"),
    ("excluded_goals", None, "5+", 3, 2, "lost"), ("excluded_goals", None, "5+", 2, 2, "won"),
    ("excluded_goals_home", None, "3+", 2, 0, "won"),
    ("goal_bounds", None, "1-5+", 0, 0, "lost"), ("goal_bounds", None, "1-5+", 2, 3, "won"),
    ("goal_bounds", None, "2-3", 2, 1, "won"), ("goal_bounds", None, "0-1", 1, 1, "lost"),
    ("goal_bounds_home", None, "1-3+", 4, 0, "won"), ("goal_bounds_home", None, "1-3+", 0, 4, "lost"),
    ("no_draw_btts", None, "yes", 2, 1, "won"), ("no_draw_btts", None, "yes", 1, 1, "lost"),
    ("correct_score", None, "2:1", 2, 1, "won"), ("correct_score", None, "other", 5, 0, "won"),
    ("correct_score", None, "other", 4, 4, "lost"),
    ("multiscores", None, "home_3-2_4-2_4-3_5-1", 5, 1, "won"), ("multiscores", None, "other_home", 7, 0, "won"),
    ("multiscores", None, "other_home", 2, 0, "lost"), ("multiscores", None, "draw", 3, 3, "won"),
])
def test_settlement_examples(market, line, sel, h, a, expected):
    assert result(market, line, sel, h, a) == expected


def test_push_has_no_outcome_value_and_wins_are_one():
    assert settle(MARKETS["ou_total"], 3.0, "over", 2, 1) == {"result": "push", "outcome_value": None}
    assert settle(MARKETS["ou_total"], 2.5, "over", 2, 1)["outcome_value"] == 1.0
    assert settle(MARKETS["ou_total"], 2.5, "under", 2, 1)["outcome_value"] == 0.0
    assert settle(MARKETS["asian_handicap"], -0.75, "home", 2, 1)["outcome_value"] == 1.0  # half won
    assert settle(MARKETS["asian_handicap"], -0.25, "home", 1, 1)["outcome_value"] == 0.0  # half lost


def test_quarter_line_codes():
    x = np.array([0, 1, 2, 3, 4])
    # "x beats 2.25" splits over 2.0 and 2.5: x=2 pushes on 2.0 and loses on 2.5 -> half lost
    assert beats(x, 2.25).tolist() == [LOST, LOST, HALF_LOST, WON, WON]
    # "x beats 2.75" splits over 2.5 and 3.0: x=3 wins on 2.5 and pushes on 3.0 -> half won
    assert beats(x, 2.75).tolist() == [LOST, LOST, LOST, HALF_WON, WON]


def test_unknown_selection_is_rejected():
    with pytest.raises(ValueError, match="unknown selection"):
        settle(MARKETS["1x2"], None, "home_or_draw", 1, 0)


# ---- partitions and identities on a model matrix ---------------------------------------------------------------

PARTITIONS = ["1x2", "exact_goals", "goal_range", "goals_home", "goals_away", "teams_to_score", "winning_margin",
              "correct_score", "multiscores"]


@pytest.mark.parametrize("market_id", PARTITIONS)
def test_exclusive_outcomes_sum_to_one(market_id):
    for seed in range(5):
        assert sum(probs(market_id, None, random_matrix(seed)).values()) == pytest.approx(1.0)


def test_two_way_markets_sum_to_one_even_with_pushes():
    m = random_matrix(2)
    for mid, line in [("ou_total", 3.0), ("ou_total", 2.5), ("asian_handicap", -1.0), ("asian_handicap", -0.75),
                      ("draw_no_bet", None), ("btts", None), ("odd_even", None), ("ou_home", 1.5)]:
        assert sum(probs(mid, line, m).values()) == pytest.approx(1.0), (mid, line)


def test_asian_and_total_identities():
    m = random_matrix(3)
    p12 = probs("1x2", None, m)
    assert probs("asian_handicap", -0.5, m)["home"] == pytest.approx(p12["home"])
    assert probs("asian_handicap", 0.5, m)["home"] == pytest.approx(p12["home"] + p12["draw"])
    assert probs("asian_handicap", 0.0, m)["home"] == pytest.approx(probs("draw_no_bet", None, m)["home"])
    assert probs("handicap_3way", 0.0, m) == pytest.approx(p12)
    assert probs("double_chance", None, m)["1x"] == pytest.approx(p12["home"] + p12["draw"])
    assert probs("double_chance", None, m)["12"] == pytest.approx(1 - p12["draw"])
    ex = probs("exact_goals", None, m)
    assert probs("ou_total", 0.5, m)["under"] == pytest.approx(ex["0"])
    assert probs("ou_total", 1.5, m)["under"] == pytest.approx(ex["0"] + ex["1"])
    assert probs("excluded_goals", None, m)["2"] == pytest.approx(1 - ex["2"])
    wm = probs("winning_margin", None, m)
    assert wm["home_1"] + wm["home_2"] + wm["home_3+"] == pytest.approx(p12["home"])
    tts = probs("teams_to_score", None, m)
    assert probs("btts", None, m)["yes"] == pytest.approx(tts["both"])
    assert probs("clean_sheet_home", None, m)["yes"] == pytest.approx(tts["none"] + tts["only_home"])
    assert probs("clean_sheet_away", None, m)["yes"] == pytest.approx(tts["none"] + tts["only_away"])


def test_correct_score_cells_equal_the_matrix():
    m = random_matrix(4)
    cs = probs("correct_score", None, m)
    assert cs["2:1"] == pytest.approx(m[2, 1])
    assert cs["0:3"] == pytest.approx(m[0, 3])


def test_over_probability_falls_as_the_line_rises():
    m = random_matrix(5)
    lines = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5]
    overs = [probs("ou_total", ln, m)["over"] for ln in lines]
    assert all(a >= b for a, b in pairwise(overs))


def test_asian_handicap_home_probability_rises_as_home_gets_more_help():
    m = random_matrix(6)
    vals = [probs("asian_handicap", x / 4, m)["home"] for x in range(-12, 13)]
    assert all(a <= b + 1e-12 for a, b in pairwise(vals))


def test_multiscore_groups_do_not_overlap():
    seen = set()
    for cells in MULTISCORE_GROUPS.values():
        for c in cells:
            assert c not in seen
            seen.add(c)


# ---- pricing and settling use the same rules --------------------------------------------------------------------

def test_priced_probabilities_match_simulated_settlement():
    """Draw scorelines from the matrix, settle each, and compare with the priced value."""
    m = random_matrix(7)
    rng = np.random.default_rng(0)
    cells = rng.choice(m.size, size=200_000, p=m.ravel())
    h, a = np.unravel_index(cells, m.shape)
    for mid, line, sel in [("ou_total", 2.5, "over"), ("ou_total", 3.0, "over"), ("asian_handicap", -0.75, "home"),
                           ("asian_handicap", 0.25, "away"), ("btts", None, "yes"), ("handicap_3way", -1.0, "draw"),
                           ("home_no_bet", None, "draw"), ("goal_bounds", None, "1-5+"), ("excluded_goals", None, "5+")]:
        c = MARKETS[mid].codes(sel, line, h, a)
        win = ((c == WON).sum() + 0.5 * (c == HALF_WON).sum()) / len(c)
        lose = ((c == LOST).sum() + 0.5 * (c == HALF_LOST).sum()) / len(c)
        assert win / (win + lose) == pytest.approx(probs(mid, line, m)[sel], abs=0.006), (mid, line, sel)
    # the scalar settle() path agrees with the array path
    for i in range(300):
        got = settle(MARKETS["asian_handicap"], -0.75, "home", int(h[i]), int(a[i]))["result"]
        code = MARKETS["asian_handicap"].codes("home", -0.75, h[i:i + 1], a[i:i + 1])[0]
        assert got == CODE_NAMES[int(code)]


def test_price_match_covers_every_market_with_valid_probabilities():
    rows = price_match(random_matrix(8))
    assert {r["market_id"] for r in rows} == set(MARKETS)
    assert all(0.0 <= r["probability"] <= 1.0 for r in rows)
    keys = [(r["market_id"], r["line"], r["selection"]) for r in rows]
    assert len(keys) == len(set(keys))


def test_score_grid_shape():
    h, a = score_grid(4)
    assert h.shape == a.shape == (4, 4) and h[2, 1] == 2 and a[2, 1] == 1


def test_seed_markets_registers_every_family_and_is_idempotent(conn):
    from pitchside.markets.goals import MARKETS as FAMILY_A
    from pitchside.markets.registry import MARKETS as EVERY_MARKET

    n = seed_markets(conn)
    seed_markets(conn)
    assert n == len(EVERY_MARKET) > len(FAMILY_A)
    assert conn.execute("SELECT count(*) FROM markets").fetchone()[0] == len(EVERY_MARKET)
    assert conn.execute("SELECT count(*) FROM markets WHERE family = 'A'").fetchone()[0] == len(FAMILY_A)
    assert {r[0] for r in conn.execute("SELECT DISTINCT family FROM markets")} == {"A", "B", "C", "D", "E"}
