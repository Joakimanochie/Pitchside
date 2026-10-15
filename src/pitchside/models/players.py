"""Player layer: how much of a club's scoring, shooting and creating each player has done lately, turned into probabilities for a coming match.

No lineup is used, because lineups are published about an hour before kickoff and the daily job runs days ahead. Instead a player's recent share of his
club's output over its last matches carries availability with it: someone who has not played lately has a share near zero, and a regular carries his full share.

For a coming match the club's expected goals come from the goals model (so the opponent and venue are accounted for) and the player gets his share of them:

    expected goals of the player   = club expected goals x player's share of the club's goals
    share = (a x expected-goal share + (1 - a) x actual-goal share), over the club's last N matches, recent ones counting more

Shares blend real goals with the xG of the shots taken, because goals alone are noisy for a player. P(scores at least once) = 1 - exp(-expected goals).
Shots, shots on target and assists use the same recent-share idea against the club's expected totals.

Experimental: lineups, injuries and rotation are not known, so these probabilities are always shown with that label.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom

# chosen on matches before 2026-01-01 only (scripts/backtest_players.py, scripts/backtest_player_counts.py) and then frozen
PLAYER_PARAMS = {
    "n_matches": 45, "half_life_matches": 14.0, "xg_weight": 1.0, "goal_scale": 0.8,
    "shots": {"scale": 0.9, "dispersion": 0.831}, "sot": {"scale": 0.9, "dispersion": 0.677}, "assists": {"scale": 0.7, "dispersion": 0.743},
}

ON_TARGET = {"Goal", "Saved Shot"}
OWN_GOAL = "Own Goal"


@dataclass
class TeamRates:
    """Recency-weighted totals over a club's recent matches."""
    weight: float                 # sum of the match weights: "per club match" is a total divided by this
    team: dict[str, float]        # the club's own goals, xg, shots, sot, assists (own goals by opponents excluded)
    players: pd.DataFrame         # index player; columns goals, xg, shots, sot, assists


def team_rates(shots: pd.DataFrame, recent_matches: list[int], half_life_matches: float = 8.0) -> TeamRates:
    """shots: this club's shots, columns match_id, player, assist, xg, result.
    recent_matches: the club's last matches with shot data, newest first. The k-th newest counts 0.5 ** (k / half_life_matches)."""
    w = {m: 0.5 ** (k / half_life_matches) for k, m in enumerate(recent_matches)}
    s = shots[shots["match_id"].isin(w) & (shots["result"] != OWN_GOAL)].copy()
    s["w"] = s["match_id"].map(w)
    s["goal"] = (s["result"] == "Goal").astype(float) * s["w"]
    s["xg_w"] = s["xg"].fillna(0.0) * s["w"]
    s["shot"] = s["w"]
    s["sot_w"] = s["result"].isin(ON_TARGET).astype(float) * s["w"]
    players = s.dropna(subset=["player"]).groupby("player").agg(goals=("goal", "sum"), xg=("xg_w", "sum"), shots=("shot", "sum"), sot=("sot_w", "sum"))
    assists = (s[(s["result"] == "Goal")].dropna(subset=["assist"]).assign(a=lambda d: d["w"]).groupby("assist")["a"].sum())
    players["assists"] = assists.reindex(players.index).fillna(0.0)
    missing = assists.index.difference(players.index)
    if len(missing):    # a player who only ever set goals up
        extra = pd.DataFrame({"goals": 0.0, "xg": 0.0, "shots": 0.0, "sot": 0.0, "assists": assists[missing]}, index=missing)
        players = pd.concat([players, extra])
    team = {"goals": float(s["goal"].sum()), "xg": float(s["xg_w"].sum()), "shots": float(s["shot"].sum()), "sot": float(s["sot_w"].sum()), "assists": float(s.loc[s["result"] == "Goal", "w"].sum())}
    return TeamRates(weight=float(sum(w.values())), team=team, players=players)


def goal_shares(rates: TeamRates, a: float = 0.5) -> pd.Series:
    """Each player's share of the club's goals: a x (his xG / club xG) + (1 - a) x (his goals / club goals)."""
    t, p = rates.team, rates.players
    if t["xg"] <= 0 and t["goals"] <= 0:
        return p["xg"] * 0.0
    if t["goals"] <= 0:       # a club that has not scored lately: chances are all there is to go on
        return p["xg"] / t["xg"]
    if t["xg"] <= 0:
        return p["goals"] / t["goals"]
    return a * (p["xg"] / t["xg"]) + (1 - a) * (p["goals"] / t["goals"])


def shares(rates: TeamRates, column: str) -> pd.Series:
    """Share of the club's total in one column (shots, sot or assists)."""
    total = rates.team[column]
    return rates.players[column] / total if total > 0 else rates.players[column] * 0.0


def anytime_goal(rates: TeamRates, club_goals: float, a: float = 0.5) -> pd.Series:
    """P(player scores at least once) given the club's expected goals in the match."""
    return 1.0 - np.exp(-club_goals * goal_shares(rates, a))


def at_least(mean: float | pd.Series, k: int, dispersion: float) -> float | pd.Series:
    """P(count >= k) for a negative binomial with this mean and spread (Poisson when the spread is zero)."""
    mean = np.asarray(mean, dtype=float)
    if dispersion < 1e-6:
        from scipy.stats import poisson
        return poisson.sf(k - 1, mean)
    r = 1.0 / dispersion
    return nbinom.sf(k - 1, r, r / (r + mean))
