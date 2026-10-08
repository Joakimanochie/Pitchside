from itertools import pairwise

import numpy as np
import pytest
from scipy.stats import poisson

from pitchside.markets.path import FIRST_GOAL_10, FIRST_GOAL_15, MARKETS, MINUTES
from pitchside.markets.record_base import price_record, settle_record
from pitchside.sim.record import from_goals
from pitchside.sim.simulate import simulate
from pitchside.sim.timing import GoalTimeProfile


def result(market_id, selection, rec, line=None):
    return settle_record(MARKETS[market_id], line, selection, rec)["result"]


# 3-2: goals at 20, 50, 60, 70, 88 minutes -> 1-0, 1-1, 2-1, 2-2, 3-2. The home side never trailed. Half-time 1-0.
SEESAW = from_goals((3, 2), (1, 0), [("home", 1, 20), ("away", 2, 50), ("home", 2, 60), ("away", 2, 70), ("home", 2, 88)])
# 1-2: home leads 1-0, then the away side scores twice (a win from behind)
COMEBACK = from_goals((1, 2), (1, 0), [("home", 1, 30), ("away", 2, 55), ("away", 2, 80)])
GOALLESS = from_goals((0, 0), (0, 0), [])
ROUT = from_goals((4, 0), (2, 0), [("home", 1, 5), ("home", 1, 30), ("home", 2, 60), ("home", 2, 75)])
STOPPAGE = from_goals((1, 0), (1, 0), [("home", 1, 47)])      # a first-half stoppage-time goal, shown as 45+2


@pytest.mark.parametrize("market,sel,rec,expected,line", [
    # 1UP: won the moment a side leads, whatever happens next
    ("x12_1up", "home", SEESAW, "won", None), ("x12_1up", "away", SEESAW, "lost", None), ("x12_1up", "draw", SEESAW, "lost", None),
    ("x12_1up", "home", COMEBACK, "won", None),            # led 1-0, then lost the match: still paid
    ("x12_1up", "away", COMEBACK, "won", None),            # also led 2-1 at the end
    ("x12_1up", "draw", GOALLESS, "won", None),
    # 2UP: needs a two-goal lead at some point, else it is a normal 1X2 bet
    ("x12_2up", "home", SEESAW, "won", None),              # never led by 2 but won the match: the normal bet wins
    ("x12_2up", "home", COMEBACK, "lost", None),           # never led by 2 and lost
    ("x12_2up", "home", ROUT, "won", None),
    # Never Down: win without ever trailing
    ("x12_never_down", "home", SEESAW, "won", None), ("x12_never_down", "away", COMEBACK, "lost", None),
    ("x12_never_down", "draw", GOALLESS, "won", None), ("x12_never_down", "home", COMEBACK, "lost", None),
    # double chance with 1UP
    ("double_chance_1up", "1x", COMEBACK, "won", None), ("double_chance_1up", "x2", COMEBACK, "won", None),
    ("double_chance_1up", "x2", SEESAW, "lost", None), ("double_chance_1up", "12", GOALLESS, "lost", None),
    # first and last goal
    ("first_goal", "home", SEESAW, "won", None), ("first_goal", "none", GOALLESS, "won", None), ("first_goal", "away", COMEBACK, "lost", None),
    ("last_goal", "home", SEESAW, "won", None), ("last_goal", "away", COMEBACK, "won", None), ("last_goal", "none", GOALLESS, "won", None),
    # leading by N at any time
    ("lead_by_any", "yes", SEESAW, "won", 1), ("lead_by_any", "yes", SEESAW, "lost", 2), ("lead_by_home", "yes", ROUT, "won", 3),
    ("lead_by_away", "yes", COMEBACK, "won", 1), ("lead_by_away", "yes", COMEBACK, "lost", 2), ("lead_by_any", "no", GOALLESS, "won", 1),
    # goals in a row
    ("goals_in_a_row_any", "yes", SEESAW, "lost", 2), ("goals_in_a_row_any", "yes", COMEBACK, "won", 2),
    ("goals_in_a_row_away", "yes", COMEBACK, "won", 2), ("goals_in_a_row_home", "yes", ROUT, "won", 3),
    ("goals_in_a_row_home", "yes", COMEBACK, "lost", 2),
    # winning from behind
    ("away_win_from_behind", "yes", COMEBACK, "won", None), ("home_win_from_behind", "yes", SEESAW, "lost", None),
    ("home_win_from_behind", "no", SEESAW, "won", None), ("away_win_from_behind", "yes", GOALLESS, "lost", None),
    # the minutes tab: result and totals counting every goal up to and including minute N
    ("x12_by_min_25", "home", SEESAW, "won", None), ("x12_by_min_40", "home", SEESAW, "won", None),
    ("x12_by_min_50", "draw", SEESAW, "won", None),         # the goal at minute 50 is included
    ("x12_by_min_55", "draw", SEESAW, "won", None), ("x12_by_min_65", "home", SEESAW, "won", None),
    ("x12_by_min_85", "draw", SEESAW, "won", None), ("x12_by_min_5", "draw", SEESAW, "won", None),
    ("ou_by_min_85", "over", SEESAW, "won", 3.5), ("ou_by_min_10", "under", SEESAW, "won", 0.5), ("ou_by_min_25", "over", SEESAW, "won", 0.5),
    ("first_goal_10", "11-20", SEESAW, "won", None), ("first_goal_10", "1-10", ROUT, "won", None), ("first_goal_10", "none", GOALLESS, "won", None),
    ("first_goal_15", "16-30", SEESAW, "won", None), ("first_goal_15", "31-45", STOPPAGE, "won", None), ("first_goal_10", "41-50", STOPPAGE, "won", None),
])
def test_settlement_examples(market, sel, rec, expected, line):
    assert result(market, sel, rec, line) == expected


def test_a_second_half_stoppage_goal_counts_as_minute_90():
    rec = from_goals((1, 0), (0, 0), [("home", 2, 94)])     # shown as 90+4
    assert result("first_goal_10", "81-90", rec) == "won" and result("first_goal_15", "76-90", rec) == "won"
    assert result("ou_by_min_85", "over", rec, 0.5) == "lost"


def test_interval_lists_cover_the_match_without_gaps():
    assert FIRST_GOAL_10[0] == "1-10" and FIRST_GOAL_10[-1] == "81-90" and len(FIRST_GOAL_10) == 9
    assert FIRST_GOAL_15[0] == "1-15" and FIRST_GOAL_15[-1] == "76-90" and len(FIRST_GOAL_15) == 6
    assert MINUTES == (5, 10, 15, 20, 25, 30, 35, 40, 50, 55, 60, 65, 70, 75, 80, 85)


# ---- logical identities that must hold in a simulation ------------------------------------------------------------------

def scoreline(lam_h=1.7, lam_a=1.1, n=11):
    g = np.arange(n)
    p = np.outer(poisson.pmf(g, lam_h), poisson.pmf(g, lam_a))
    return p / p.sum()


@pytest.fixture(scope="module")
def sim():
    rng = np.random.default_rng(0)
    prof = GoalTimeProfile().fit(np.r_[np.ones(4000), np.full(5000, 2)], np.r_[rng.integers(0, 48, 4000), rng.integers(45, 97, 5000)])
    p = scoreline()
    return p, simulate(p, 0.44, prof, 300_000, np.random.default_rng(5))


def probs(market_id, rec, line=None):
    return {r["selection"]: r["probability"] for r in price_record(MARKETS[market_id], line, rec)}


def test_win_with_and_without_trailing_adds_up_to_the_win(sim):
    p, rec = sim
    home_win = np.tril(p, -1).sum()
    never_down = probs("x12_never_down", rec)["home"]
    from_behind = probs("home_win_from_behind", rec)["yes"]
    assert never_down + from_behind == pytest.approx(home_win, abs=0.004)
    assert never_down < home_win


def test_someone_leads_exactly_when_a_goal_is_scored(sim):
    p, rec = sim
    assert probs("lead_by_any", rec, 1)["yes"] == pytest.approx(1 - p[0, 0], abs=0.004)
    assert probs("first_goal", rec)["none"] == pytest.approx(p[0, 0], abs=0.004)
    assert probs("last_goal", rec)["none"] == pytest.approx(p[0, 0], abs=0.004)
    for sel_probs in (probs("first_goal", rec), probs("last_goal", rec)):
        assert sum(sel_probs.values()) == pytest.approx(1.0)


def test_up_markets_are_at_least_the_plain_result(sim):
    p, rec = sim
    home_win, away_win, draw = np.tril(p, -1).sum(), np.triu(p, 1).sum(), np.trace(p)
    up1, up2 = probs("x12_1up", rec), probs("x12_2up", rec)
    assert up1["home"] >= home_win and up1["away"] >= away_win and up1["draw"] == pytest.approx(draw, abs=0.004)
    assert up1["home"] >= up2["home"] >= home_win - 1e-12      # a bigger lead is needed, so it pays early less often


def test_lead_and_streak_probabilities_fall_with_the_threshold(sim):
    _, rec = sim
    for scope in ("any", "home", "away"):
        leads = [probs(f"lead_by_{scope}", rec, k)["yes"] for k in (1, 2, 3)]
        assert all(a >= b for a, b in pairwise(leads)), scope
        runs = [probs(f"goals_in_a_row_{scope}", rec, k)["yes"] for k in (2, 3)]
        assert runs[0] >= runs[1], scope
    assert probs("lead_by_any", rec, 2)["yes"] >= probs("lead_by_home", rec, 2)["yes"]


def test_goals_by_minute_grow_with_the_minute_and_end_at_full_time(sim):
    p, rec = sim
    over = [probs(f"ou_by_min_{n}", rec, 0.5)["over"] for n in MINUTES]
    assert all(a <= b + 1e-12 for a, b in pairwise(over))
    assert over[-1] <= 1 - p[0, 0] + 1e-12
    assert 0.0 < over[0] < 0.2          # almost no first-five-minute goals


def test_first_goal_intervals_partition_the_match(sim):
    p, rec = sim
    for mid in ("first_goal_10", "first_goal_15"):
        d = probs(mid, rec)
        assert sum(d.values()) == pytest.approx(1.0) and d["none"] == pytest.approx(p[0, 0], abs=0.004)


def test_exclusive_selections_never_add_up_to_more_than_one(sim):
    """Exclusive means two selections cannot win together. The sum is 1 when one of them must win."""
    _, rec = sim
    for m in MARKETS.values():
        if m.exclusive:
            for line in (m.lines if m.has_line else (None,)):
                assert sum(probs(m.id, rec, line).values()) <= 1.0 + 1e-9, (m.id, line)
    for mid, line in [("first_goal", None), ("last_goal", None), ("first_goal_10", None), ("first_goal_15", None),
                      ("lead_by_any", 2), ("goals_in_a_row_home", 2), ("home_win_from_behind", None), ("x12_by_min_30", None),
                      ("ou_by_min_60", 1.5)]:
        assert sum(probs(mid, rec, line).values()) == pytest.approx(1.0, abs=1e-9), mid


def test_never_down_misses_exactly_the_matches_won_from_behind(sim):
    _, rec = sim
    nd = probs("x12_never_down", rec)
    behind = probs("home_win_from_behind", rec)["yes"] + probs("away_win_from_behind", rec)["yes"]
    assert sum(nd.values()) == pytest.approx(1.0 - behind, abs=1e-9)
