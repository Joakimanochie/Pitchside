"""Fit the simulator's two data-driven inputs from the database: the half-time split and the goal-timing profile."""
import numpy as np
import psycopg

from pitchside.models.split_table import HalfSplitTable
from pitchside.sim.timing import GoalTimeProfile

MIN_SPLIT_MATCHES = 1000


def fit_split_table(conn: psycopg.Connection) -> HalfSplitTable:
    """P(half-time score | full-time score) from every finished match with a half-time score, all leagues pooled."""
    rows = conn.execute(
        "SELECT ht_home, ht_away, ft_home, ft_away FROM matches "
        "WHERE status = 'finished' AND ht_home IS NOT NULL AND ht_away IS NOT NULL").fetchall()
    if len(rows) < MIN_SPLIT_MATCHES:
        raise ValueError(f"only {len(rows)} matches with a half-time score; need at least {MIN_SPLIT_MATCHES}")
    a = np.array(rows, dtype=int)
    return HalfSplitTable().fit(a[:, 0], a[:, 1], a[:, 2], a[:, 3])


def fit_time_profile(conn: psycopg.Connection) -> GoalTimeProfile | None:
    """Within-half goal-minute distribution from goals of matches whose goal minutes were verified. None if too few."""
    rows = conn.execute(
        "SELECT e.period, e.minute FROM match_events e JOIN matches m ON m.id = e.match_id "
        "WHERE e.source = 'understat' AND e.event_type IN ('goal', 'own_goal', 'penalty_goal') "
        "AND m.source_ids ->> 'goal_minutes' = 'true' AND e.period IS NOT NULL AND e.minute IS NOT NULL").fetchall()
    if not rows:
        return None
    a = np.array(rows, dtype=int)
    try:
        return GoalTimeProfile().fit(a[:, 0], a[:, 1])
    except ValueError:
        return None
