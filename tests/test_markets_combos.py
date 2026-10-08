import numpy as np
import pytest
from scipy.stats import poisson

from pitchside.markets.combos import MARKETS
from pitchside.markets.record_base import price_record, settle_record
from pitchside.sim.record import from_goals
from pitchside.sim.simulate import simulate
from pitchside.sim.timing import GoalTimeProfile

# 3-2, 1-0 at half-time
SEESAW = from_goals((3, 2), (1, 0), [("home", 1, 20), ("away", 2, 50), ("home", 2, 60), ("away", 2, 70), ("home", 2, 88)])
GOALLESS = from_goals((0, 0), (0, 0), [])
COMEBACK = from_goals((1, 2), (1, 0), [("home", 1, 30), ("away", 2, 55), ("away", 2, 80)])


def result(market_id, selection, rec):
    return settle_record(MARKETS[market_id], None, selection, rec)["result"]


@pytest.mark.parametrize("market,sel,rec,expected", [
    ("x12_ou_25", "home&over", SEESAW, "won"), ("x12_ou_25", "home&under", SEESAW, "lost"), ("x12_ou_25", "draw&under", GOALLESS, "won"),
    ("x12_ou_45", "home&over", SEESAW, "won"), ("x12_ou_45", "home&under", SEESAW, "lost"), ("x12_ou_15", "away&over", COMEBACK, "won"),
    ("x12_btts", "home&yes", SEESAW, "won"), ("x12_btts", "draw&no", GOALLESS, "won"), ("x12_btts", "away&yes", COMEBACK, "won"),
    ("ou_25_btts", "over&yes", SEESAW, "won"), ("ou_25_btts", "under&no", GOALLESS, "won"), ("ou_25_btts", "under&yes", COMEBACK, "lost"),
    ("first_goal_x12", "home_goal&home", SEESAW, "won"), ("first_goal_x12", "home_goal&away", COMEBACK, "won"),
    ("first_goal_x12", "no_goal", GOALLESS, "won"), ("first_goal_x12", "away_goal&home", SEESAW, "lost"),
    ("htft_ou_25", "home/home&over", SEESAW, "won"), ("htft_ou_15", "draw/draw&under", GOALLESS, "won"),
    ("htft_ou_25", "home/away&over", COMEBACK, "won"), ("htft_ou_25", "home/away&under", COMEBACK, "lost"),
    ("htft_h1ou_05", "home/home&over", SEESAW, "won"), ("htft_h1ou_15", "home/home&under", SEESAW, "won"),
    ("dc_ou_25", "1x&over", SEESAW, "won"), ("dc_ou_25", "x2&over", SEESAW, "lost"), ("dc_ou_15", "12&under", GOALLESS, "lost"),
    ("dc_btts", "1x&yes", SEESAW, "won"), ("dc_btts_h1", "1x&no", SEESAW, "won"), ("dc_btts_h2", "1x&yes", SEESAW, "won"),
    ("h1_dc_ou_15", "1x&under", SEESAW, "won"), ("h1_dc_btts", "1x&no", SEESAW, "won"),
    ("h1_x12_btts", "home&no", SEESAW, "won"), ("h1_x12_ou_15", "home&under", SEESAW, "won"),
    ("h2_x12_ou_15", "draw&over", SEESAW, "won"), ("h2_x12_btts", "draw&yes", SEESAW, "won"),
    ("h2_dc_ou_15", "x2&over", SEESAW, "won"), ("h2_dc_btts", "12&yes", SEESAW, "lost"),
    ("or_home_over25", "yes", SEESAW, "won"), ("or_home_over25", "yes", COMEBACK, "won"), ("or_home_over25", "yes", GOALLESS, "lost"), ("or_home_over25", "no", GOALLESS, "won"),
    ("or_away_under25", "yes", COMEBACK, "won"), ("or_draw_btts", "yes", COMEBACK, "won"), ("or_draw_btts", "no", GOALLESS, "lost"),
    ("or_home_clean_sheet", "yes", GOALLESS, "won"), ("or_away_clean_sheet", "no", SEESAW, "won"), ("or_home_clean_sheet", "yes", SEESAW, "won"),
])
def test_settlement_examples(market, sel, rec, expected):
    assert result(market, sel, rec) == expected


# ---- identities in a simulation ----------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sim():
    rng = np.random.default_rng(0)
    prof = GoalTimeProfile().fit(np.r_[np.ones(4000), np.full(5000, 2)], np.r_[rng.integers(0, 48, 4000), rng.integers(45, 97, 5000)])
    g = np.arange(11)
    p = np.outer(poisson.pmf(g, 1.7), poisson.pmf(g, 1.1))
    p /= p.sum()
    return p, simulate(p, 0.44, prof, 300_000, np.random.default_rng(9))


def probs(market_id, rec):
    return {r["selection"]: r["probability"] for r in price_record(MARKETS[market_id], None, rec)}


def test_exclusive_combinations_partition_the_probability(sim):
    _, rec = sim
    for m in MARKETS.values():
        if m.exclusive and m.id != "first_goal_x12" and not m.id.startswith("or_"):
            assert sum(probs(m.id, rec).values()) == pytest.approx(1.0, abs=1e-9), m.id
    assert sum(probs("first_goal_x12", rec).values()) == pytest.approx(1.0, abs=1e-9)


def test_parts_add_back_up_to_the_whole(sim):
    p, rec = sim
    c = probs("x12_ou_25", rec)
    assert c["home&over"] + c["home&under"] == pytest.approx(np.tril(p, -1).sum(), abs=0.004)
    assert c["draw&over"] + c["draw&under"] == pytest.approx(np.trace(p), abs=0.004)
    b = probs("x12_btts", rec)
    assert b["home&yes"] + b["draw&yes"] + b["away&yes"] == pytest.approx(p[1:, 1:].sum(), abs=0.004)
    tot = np.add.outer(np.arange(11), np.arange(11))
    assert sum(v for k, v in probs("ou_25_btts", rec).items() if k.startswith("over")) == pytest.approx(p[tot > 2.5].sum(), abs=0.004)
    assert probs("first_goal_x12", rec)["no_goal"] == pytest.approx(p[0, 0], abs=0.004)


def test_a_combination_is_never_more_likely_than_its_parts(sim):
    _, rec = sim
    c = probs("x12_ou_25", rec)
    home = sum(v for k, v in c.items() if k.startswith("home&"))
    assert c["home&over"] <= home and c["home&over"] <= sum(v for k, v in c.items() if k.endswith("&over"))
    d = probs("dc_ou_25", rec)
    assert d["1x&over"] <= sum(v for k, v in d.items() if k.endswith("&over"))


def test_either_is_the_union_of_its_events(sim):
    _, rec = sim
    x = probs("x12_ou_25", rec)
    p_home = sum(v for k, v in x.items() if k.startswith("home&"))
    p_over = sum(v for k, v in x.items() if k.endswith("&over"))
    both_events = x["home&over"]
    assert probs("or_home_over25", rec)["yes"] == pytest.approx(p_home + p_over - both_events, abs=1e-9)
    assert probs("or_home_over25", rec)["yes"] + probs("or_home_over25", rec)["no"] == pytest.approx(1.0)


def test_any_clean_sheet_is_the_opposite_of_both_teams_scoring(sim):
    p, rec = sim
    # "draw or any clean sheet" is lost only when both teams score and the match is not a draw
    b = probs("x12_btts", rec)
    assert probs("or_draw_clean_sheet", rec)["no"] == pytest.approx(b["home&yes"] + b["away&yes"], abs=1e-9)
    assert probs("or_home_clean_sheet", rec)["no"] == pytest.approx(b["draw&yes"] + b["away&yes"], abs=1e-9)
    assert p.sum() == pytest.approx(1.0)


def test_unknown_selection_is_rejected():
    with pytest.raises((ValueError, KeyError)):
        settle_record(MARKETS["x12_ou_25"], None, "home&sideways", SEESAW)
