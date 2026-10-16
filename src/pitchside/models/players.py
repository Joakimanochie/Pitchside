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


# Lineup adjustment. Not validated: we have no history of announced lineups yet (they are stored from now on so it can be tested).
BENCH_WEIGHT = 0.3      # a substitute plays about a quarter of a match
MAX_BOOST = 1.35


def apply_lineup(rates: TeamRates, starters: set[str], bench: set[str]) -> TeamRates:
    """Rates with the lineup applied: starters keep their share, named substitutes count 0.3, everyone else not in the squad is out.
    The club's total output is unchanged, so what absent players would have done passes to those who play (by at most 35%)."""
    players = rates.players
    weight = pd.Series([1.0 if n in starters else BENCH_WEIGHT if n in bench else 0.0 for n in players.index], index=players.index)
    scaled = players.mul(weight, axis=0)
    before, after = players.sum(), scaled.sum()
    boost = (before / after.where(after > 0)).fillna(1.0).clip(upper=MAX_BOOST).clip(lower=1.0)
    return TeamRates(weight=rates.weight, team=rates.team, players=scaled.mul(boost, axis=1))


# ---- cards and fouls, from the ESPN match log (no shot data needed) ---------------------------------------------------------------------
# Chosen on matches before 2026-01-01 (scripts/backtest_player_cards.py) and then frozen, as for the shot-based markets. Cards: a player's own rate is pulled
# 20% of the way toward the average rate (a player with a high rate is carded less often than that rate says), and scaled for rotation and injuries.
LOG_PARAMS = {
    "n_matches": 30, "half_life_matches": 10.0,
    "cards": {"scale": 0.8, "dispersion": 0.0, "shrink": 0.2, "prior": 0.117},
    "fouls": {"scale": 0.9, "dispersion": 0.827}, "fouled": {"scale": 0.9, "dispersion": 0.804},
}


@dataclass
class LogRates:
    """Recency-weighted fouls and cards of a club's players over its last matches (the club's matches with a verified log)."""
    weight: float                 # sum of the match weights
    team_cards: float             # the club's own cards, weighted: "per club match" is this divided by weight
    players: pd.DataFrame         # index player; columns cards, fouls, fouled (weighted counts)


def log_rates(log: pd.DataFrame, recent_matches: list[int], half_life_matches: float = 10.0) -> LogRates:
    """log: this club's rows of player_match_log, columns match_id, player, cards (yellow + red), fouls, fouled.
    recent_matches: the club's last matches with a log, newest first. The k-th newest counts 0.5 ** (k / half_life_matches)."""
    w = {m: 0.5 ** (k / half_life_matches) for k, m in enumerate(recent_matches)}
    d = log[log["match_id"].isin(w)].copy()
    d["w"] = d["match_id"].map(w)
    for c in ("cards", "fouls", "fouled"):
        d[c] = d[c] * d["w"]
    players = d.groupby("player")[["cards", "fouls", "fouled"]].sum()
    return LogRates(weight=float(sum(w.values())), team_cards=float(d["cards"].sum()), players=players)


def card_rate(rates: LogRates, club_expected_cards: float) -> pd.Series:
    """Each player's expected cards in the coming match: his recent cards per club match, scaled by how many cards the club is expected to get
    in this match compared with its recent average (a strict referee or a derby raises everyone's)."""
    per_match = rates.team_cards / rates.weight if rates.weight > 0 else 0.0
    factor = club_expected_cards / per_match if per_match > 0 else 1.0
    return rates.players["cards"] / rates.weight * factor


def shrunk_card_rate(rates: LogRates, club_expected_cards: float, shrink: float, prior: float) -> pd.Series:
    """card_rate pulled `shrink` of the way toward the average rate `prior`."""
    return (1 - shrink) * card_rate(rates, club_expected_cards) + shrink * prior


def apply_lineup_log(rates: LogRates, starters: set[str], bench: set[str]) -> LogRates:
    """Same rule as apply_lineup: starters keep their share, named substitutes count BENCH_WEIGHT, others are out; the club's total passes on to those who play."""
    players = rates.players
    weight = pd.Series([1.0 if n in starters else BENCH_WEIGHT if n in bench else 0.0 for n in players.index], index=players.index)
    scaled = players.mul(weight, axis=0)
    boost = (players.sum() / scaled.sum().where(scaled.sum() > 0)).fillna(1.0).clip(upper=MAX_BOOST).clip(lower=1.0)
    return LogRates(rates.weight, rates.team_cards, scaled.mul(boost, axis=1))
