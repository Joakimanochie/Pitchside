"""MatchRecord: everything about a match (or many simulated matches) that the path-dependent markets need.

One structure for both worlds: the simulator produces N matches at once, a real finished match is N = 1. Markets are
resolved from this structure only, so a prediction and its settlement can never disagree about the rules.

Arrays have one row per match. Goals are listed in match order, padded to a common width G:
    goal_side    +1 home goal, -1 away goal, 0 padding
    goal_period  1 or 2 (0 for padding)
    goal_minute  minute of the match as shown (0-99) plus a fractional tie-break, so goals in the same minute keep a
                 definite order; first-half stoppage-time goals (e.g. minute 47) still sort before second-half goals.
"""
from dataclasses import dataclass

import numpy as np

PAD = 0


@dataclass
class MatchRecord:
    ft_home: np.ndarray
    ft_away: np.ndarray
    ht_home: np.ndarray
    ht_away: np.ndarray
    goal_side: np.ndarray
    goal_period: np.ndarray
    goal_minute: np.ndarray

    @property
    def n(self) -> int:
        return len(self.ft_home)

    @property
    def h2_home(self) -> np.ndarray:
        return self.ft_home - self.ht_home

    @property
    def h2_away(self) -> np.ndarray:
        return self.ft_away - self.ht_away

    def validate(self) -> None:
        """Internal consistency: the goal list must reproduce the scores. Raises ValueError otherwise."""
        real = self.goal_side != PAD
        home = ((self.goal_side == 1) & real).sum(axis=1)
        away = ((self.goal_side == -1) & real).sum(axis=1)
        h1 = ((self.goal_side == 1) & (self.goal_period == 1)).sum(axis=1)
        a1 = ((self.goal_side == -1) & (self.goal_period == 1)).sum(axis=1)
        if not (np.array_equal(home, self.ft_home) and np.array_equal(away, self.ft_away)):
            raise ValueError("goal list does not add up to the full-time score")
        if not (np.array_equal(h1, self.ht_home) and np.array_equal(a1, self.ht_away)):
            raise ValueError("goal list does not add up to the half-time score")
        key = np.where(real, self.goal_period.astype(float) * 1000 + self.goal_minute, 1e9)
        if (np.diff(key, axis=1) < 0).any():
            raise ValueError("goals are not in match order")

    # ---- running state, used by the game-flow markets -------------------------------------------------------

    def lead_after_each_goal(self) -> np.ndarray:
        """Home goals minus away goals after each listed goal (0 for padding)."""
        return np.cumsum(self.goal_side, axis=1)


def from_scores(ft: tuple[int, int], ht: tuple[int, int]) -> MatchRecord:
    """A real match known only by its full-time and half-time scores. Markets that read the order or minute of goals
    must not be resolved from this (they are flagged `needs_minutes`); half and combination markets can."""
    if ht[0] > ft[0] or ht[1] > ft[1]:
        raise ValueError("half-time score exceeds full-time score")
    return MatchRecord(np.array([ft[0]]), np.array([ft[1]]), np.array([ht[0]]), np.array([ht[1]]),
                       np.zeros((1, 1), dtype=np.int8), np.zeros((1, 1), dtype=np.int8), np.zeros((1, 1)))


def from_goals(ft: tuple[int, int], ht: tuple[int, int], goals: list[tuple[str, int, float]]) -> MatchRecord:
    """Build the record of one real match. goals: (side 'home'|'away', period 1|2, minute), any order."""
    ordered = sorted(goals, key=lambda g: (g[1], g[2]))
    width = max(len(ordered), 1)
    side = np.zeros((1, width), dtype=np.int8)
    period = np.zeros((1, width), dtype=np.int8)
    minute = np.zeros((1, width))
    for k, (s, p, m) in enumerate(ordered):
        side[0, k] = 1 if s == "home" else -1
        period[0, k] = p
        minute[0, k] = m
    rec = MatchRecord(np.array([ft[0]]), np.array([ft[1]]), np.array([ht[0]]), np.array([ht[1]]), side, period, minute)
    rec.validate()
    return rec


def from_many(ft: list[tuple[int, int]], ht: list[tuple[int, int]], goals: list[list[tuple[str, int, float]]]) -> MatchRecord:
    """Many real matches as one record (one row each), so a market can be resolved for all of them at once.
    goals[i] lists match i's goals as (side 'home'|'away', period 1|2, minute)."""
    n = len(ft)
    width = max(max((len(g) for g in goals), default=0), 1)
    side = np.zeros((n, width), dtype=np.int8)
    period = np.zeros((n, width), dtype=np.int8)
    minute = np.zeros((n, width))
    for i, match_goals in enumerate(goals):
        for k, (sd, pd_, mn) in enumerate(sorted(match_goals, key=lambda g: (g[1], g[2]))):
            side[i, k], period[i, k], minute[i, k] = (1 if sd == "home" else -1), pd_, mn
    rec = MatchRecord(np.array([f[0] for f in ft]), np.array([f[1] for f in ft]), np.array([h[0] for h in ht]),
                      np.array([h[1] for h in ht]), side, period, minute)
    rec.validate()
    return rec
