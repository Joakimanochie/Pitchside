import numpy as np
import pandas as pd
import pytest

from pitchside.models.players import (
    anytime_goal,
    at_least,
    goal_shares,
    shares,
    team_rates,
)


def shots(*rows):
    """rows: (match_id, player, result, xg, assist)"""
    return pd.DataFrame(rows, columns=["match_id", "player", "result", "xg", "assist"])


S = shots(
    (3, "Striker", "Goal", 0.4, "Winger"), (3, "Striker", "Saved Shot", 0.3, None), (3, "Winger", "Missed Shot", 0.1, None),
    (2, "Striker", "Goal", 0.5, None), (2, "Midfielder", "Goal", 0.1, "Striker"), (2, "Winger", "Saved Shot", 0.2, None),
    (1, "Striker", "Missed Shot", 0.2, None), (1, "Opponent", "Own Goal", 0.0, None), (1, "Midfielder", "Blocked Shot", 0.05, None),
)


def test_recent_matches_count_more_and_unlisted_matches_are_ignored():
    r = team_rates(S, [3, 2], half_life_matches=1.0)           # match 1 is not in the window
    assert r.weight == pytest.approx(1.5)
    # striker: goals 1 (match 3, weight 1) + 1 (match 2, weight 0.5)
    assert r.players.loc["Striker", "goals"] == pytest.approx(1.5)
    assert r.team["goals"] == pytest.approx(1 + 0.5 + 0.5)
    assert "Opponent" not in r.players.index


def test_own_goals_are_not_anyones_goals_and_shot_and_target_counts_are_kept():
    r = team_rates(S, [3, 2, 1], half_life_matches=1000.0)
    assert "Opponent" not in r.players.index and r.team["goals"] == pytest.approx(3.0, abs=0.01)
    assert r.players.loc["Striker", "shots"] == pytest.approx(4.0, abs=0.01)
    assert r.players.loc["Striker", "sot"] == pytest.approx(3.0, abs=0.01)      # goal, saved, goal
    assert r.players.loc["Winger", "assists"] == pytest.approx(1.0, abs=0.01) and r.players.loc["Striker", "assists"] == pytest.approx(1.0, abs=0.01)


def test_goal_shares_sum_to_one_and_blend_goals_with_chances():
    r = team_rates(S, [3, 2, 1], half_life_matches=1000.0)
    for a in (0.0, 0.5, 1.0):
        assert goal_shares(r, a).sum() == pytest.approx(1.0, abs=1e-6)
    assert goal_shares(r, 0.0)["Winger"] == pytest.approx(0.0) and goal_shares(r, 1.0)["Winger"] > 0     # no goals, but chances


def test_anytime_probability_follows_share_and_the_clubs_expected_goals():
    r = team_rates(S, [3, 2, 1], half_life_matches=1000.0)
    p1, p2 = anytime_goal(r, 1.0), anytime_goal(r, 2.5)
    assert (p2 > p1).all() and p1["Striker"] > p1["Midfielder"] > p1["Winger"]
    assert p1["Striker"] == pytest.approx(1 - np.exp(-goal_shares(r)["Striker"]))
    assert ((p1 >= 0) & (p1 <= 1)).all()


def test_shares_of_shots_and_a_club_with_no_goals_have_no_division_error():
    r = team_rates(S, [3, 2, 1], half_life_matches=1000.0)
    assert shares(r, "shots").sum() == pytest.approx(1.0, abs=1e-6)
    goalless = team_rates(shots((9, "X", "Missed Shot", 0.1, None), (9, "Y", "Missed Shot", 0.3, None)), [9])
    assert goal_shares(goalless).tolist() == pytest.approx([0.25, 0.75])          # no goals lately: the chances decide
    nothing = team_rates(shots((9, "X", "Missed Shot", 0.0, None)), [9])
    assert (goal_shares(nothing) == 0).all() and (anytime_goal(nothing, 1.5) == 0).all()


def test_at_least_is_a_proper_tail_probability():
    assert at_least(2.0, 0, 0.3) == pytest.approx(1.0)
    assert at_least(2.0, 1, 0.3) > at_least(2.0, 2, 0.3) > at_least(2.0, 3, 0.3)
    assert at_least(2.0, 1, 0.0) == pytest.approx(1 - np.exp(-2.0))
    assert at_least(np.array([1.0, 3.0]), 2, 0.2)[1] > at_least(np.array([1.0, 3.0]), 2, 0.2)[0]
