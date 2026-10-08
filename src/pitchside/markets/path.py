"""Families C and D: game flow and the minutes tab. Rules confirmed against SportyBet's market descriptions.

C (game flow): 1UP / 2UP / Never Down, double chance 1UP, first and last goal, leading by N at any time, goals in a row,
winning from behind.  D (timeline): the result and goals within the first N minutes, and the interval of the first goal.
All of them read the order and minute of goals, so they need a full MatchRecord.
"""
import numpy as np

from pitchside.markets.base import won_if
from pitchside.markets.goals import MARKETS as A
from pitchside.markets.record_base import (
    RecordMarket,
    clock,
    first_goal_side,
    goals_by_minute,
    last_goal_side,
    longest_run,
    max_deficit,
    max_lead,
    n_goals,
)
from pitchside.sim.record import MatchRecord

YES_NO = ["yes", "no"]
RESULTS = ["home", "draw", "away"]
TEAM = {"home": 1, "away": -1}


def _ft_result(rec: MatchRecord) -> np.ndarray:
    return np.where(rec.ft_home > rec.ft_away, 0, np.where(rec.ft_home == rec.ft_away, 1, 2))


# ---- C: game flow ------------------------------------------------------------------------------------------------

def _up(k: int):
    """1UP / 2UP: a side's bet is won as soon as it leads by k at any moment; otherwise it is a normal 1X2 bet."""
    def outcome(sel, line, rec):
        res = _ft_result(rec)
        if sel == "draw":
            return won_if(res == 1)
        team = TEAM[sel]
        return won_if((max_lead(rec, team) >= k) | (res == RESULTS.index(sel)))
    return outcome


def _never_down(sel, line, rec):
    res = _ft_result(rec)
    if sel == "draw":
        return won_if(res == 1)
    team = TEAM[sel]
    return won_if((res == RESULTS.index(sel)) & (max_deficit(rec, team) == 0))


def _double_chance_1up(sel, line, rec):
    res = _ft_result(rec)
    if sel == "1x":
        return won_if((max_lead(rec, 1) >= 1) | (res <= 1))
    if sel == "x2":
        return won_if((max_lead(rec, -1) >= 1) | (res >= 1))
    return won_if(res != 1)  # 12 is not affected by 1UP


def _goal_side(which):
    def outcome(sel, line, rec):
        side = first_goal_side(rec) if which == "first" else last_goal_side(rec)
        return won_if({"home": side == 1, "away": side == -1, "none": side == 0}[sel])
    return outcome


def _lead_by(scope: str):
    def outcome(sel, line, rec):
        k = int(line)
        lead = np.maximum(max_lead(rec, 1), max_lead(rec, -1)) if scope == "any" else max_lead(rec, TEAM[scope])
        hit = lead >= k
        return won_if(hit if sel == "yes" else ~hit)
    return outcome


def _in_a_row(scope: str):
    def outcome(sel, line, rec):
        k = int(line)
        run = np.maximum(longest_run(rec, 1), longest_run(rec, -1)) if scope == "any" else longest_run(rec, TEAM[scope])
        hit = run >= k
        return won_if(hit if sel == "yes" else ~hit)
    return outcome


def _win_from_behind(team: str):
    def outcome(sel, line, rec):
        won = _ft_result(rec) == RESULTS.index(team)
        hit = won & (max_deficit(rec, TEAM[team]) >= 1)
        return won_if(hit if sel == "yes" else ~hit)
    return outcome


def _market(id_, family, name, options, outcome, lines=(), exclusive=True):
    return RecordMarket(id_, family, name, lambda line: list(options), outcome, bool(lines), tuple(lines), exclusive, needs_minutes=True)


GAME_FLOW = [
    _market("x12_1up", "C", "1X2 - 1UP", RESULTS, _up(1), exclusive=False),   # both sides can lead in one match
    _market("x12_2up", "C", "1X2 - 2UP", RESULTS, _up(2), exclusive=False),
    _market("x12_never_down", "C", "1X2 - Never Down", RESULTS, _never_down),
    _market("double_chance_1up", "C", "Double Chance - 1UP", ["1x", "12", "x2"], _double_chance_1up, exclusive=False),
    _market("first_goal", "C", "1st Goal", ["home", "none", "away"], _goal_side("first")),
    _market("last_goal", "C", "Last Goal", ["home", "none", "away"], _goal_side("last")),
    *[_market(f"lead_by_{scope}", "C", f"{label} to lead by N Goals at any time", YES_NO, _lead_by(scope), (1, 2, 3))
      for scope, label in (("any", "Any Team"), ("home", "Home Team"), ("away", "Away Team"))],
    *[_market(f"goals_in_a_row_{scope}", "C", f"{label} To Score N or More Goals in a Row", YES_NO, _in_a_row(scope), (2, 3))
      for scope, label in (("any", "Any Team"), ("home", "Home Team"), ("away", "Away Team"))],
    _market("home_win_from_behind", "C", "Home Team To Win From Behind", YES_NO, _win_from_behind("home")),
    _market("away_win_from_behind", "C", "Away Team To Win From Behind", YES_NO, _win_from_behind("away")),
]


# ---- D: the minutes tab ---------------------------------------------------------------------------------------------

MINUTES = (5, 10, 15, 20, 25, 30, 35, 40, 50, 55, 60, 65, 70, 75, 80, 85)   # as listed by SportyBet (no 45)
FIRST_GOAL_10 = [f"{lo}-{lo + 9}" for lo in range(1, 90, 10)]               # 1-10 ... 81-90
FIRST_GOAL_15 = [f"{lo}-{lo + 14}" for lo in range(1, 90, 15)]              # 1-15 ... 76-90


def _result_by_minute(n: int):
    def outcome(sel, line, rec):
        h, a = goals_by_minute(rec, n)
        return A["1x2"].outcome(sel, None, h, a)
    return outcome


def _total_by_minute(n: int):
    def outcome(sel, line, rec):
        h, a = goals_by_minute(rec, n)
        return A["ou_total"].outcome(sel, line, h, a)
    return outcome


def _first_goal_interval(labels: list[str]):
    def outcome(sel, line, rec):
        any_goal = n_goals(rec) > 0
        first_minute = clock(rec)[:, 0] if rec.goal_side.shape[1] else np.zeros(rec.n)
        if sel == "none":
            return won_if(~any_goal)
        lo, hi = (int(x) for x in sel.split("-"))
        return won_if(any_goal & (first_minute >= lo) & (first_minute <= hi))
    return outcome


TIMELINE = [
    *[_market(f"x12_by_min_{n}", "D", f"1X2 from 1 to {n} minute", RESULTS, _result_by_minute(n)) for n in MINUTES],
    *[_market(f"ou_by_min_{n}", "D", f"Total Goals Over/Under from 1 to {n} minute", ["over", "under"], _total_by_minute(n),
              lines=(0.5, 1.5, 2.5)) for n in MINUTES],
    _market("first_goal_10", "D", "When will the 1st goal be scored (10 min interval)", [*FIRST_GOAL_10, "none"], _first_goal_interval(FIRST_GOAL_10)),
    _market("first_goal_15", "D", "When will the 1st goal be scored (15 min interval)", [*FIRST_GOAL_15, "none"], _first_goal_interval(FIRST_GOAL_15)),
]

MARKETS: dict[str, RecordMarket] = {m.id: m for m in [*GAME_FLOW, *TIMELINE]}
