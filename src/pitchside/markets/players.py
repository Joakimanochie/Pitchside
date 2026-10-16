"""Family I: player markets (experimental): anytime goalscorer, shots, shots on target and assists, per player.

A player market has one selection per player, named after the player as Understat spells him, and each selection is a single yes-style bet ("this player scores",
"this player has more than 1.5 shots"), so the selections of one market do not add up to 1 and no "pick" is flagged. They are settled from the player's real counts in
the match (shot events), never from team totals. A player who took no shot in the match is settled as a loss; lineups are not used, so a player who did not play is
not voided (bookmakers would void a bet on him). That is one reason the family is labelled experimental.
"""
from dataclasses import dataclass

from pitchside.markets.base import Market


def _no_selections(line):
    return []


def _not_scored_from_scores(sel, line, h, a):
    raise ValueError("player markets are settled from player counts, not from the score")


@dataclass(frozen=True)
class PlayerMarket(Market):
    player_stat: str = ""           # goals, shots, sot, assists (from shot events) or cards, fouls, fouled (from the ESPN match log): which count decides the bet


def _market(id_, name, player_stat, lines=()):
    return PlayerMarket(id_, "I", name, _no_selections, _not_scored_from_scores, bool(lines), tuple(lines), False, None, player_stat)


MARKETS: dict[str, PlayerMarket] = {m.id: m for m in [
    _market("player_anytime_goal", "Anytime Goalscorer", "goals"),
    _market("player_assist", "Anytime Assist", "assists"),
    _market("player_shots", "Player Shots Over", "shots", (0.5, 1.5, 2.5)),
    _market("player_sot", "Player Shots on Target Over", "sot", (0.5, 1.5)),
    _market("player_carded", "Player To Be Carded", "cards"),
    _market("player_fouls", "Player Fouls Committed Over", "fouls", (0.5, 1.5)),
    _market("player_fouled", "Player Fouls Won Over", "fouled", (0.5, 1.5)),
]}

LOG_STATS = {"cards", "fouls", "fouled"}     # counted from the ESPN match log: settled only for matches whose log was verified


def settle_player(market: PlayerMarket, line: float | None, player: str, players: dict) -> dict:
    """Won if the player's count beats the line (or is at least 1 when there is no line); anything he did not record counts as 0."""
    n = players.get(player, {}).get(market.player_stat, 0)
    won = n > line if line is not None else n >= 1
    return {"result": "won" if won else "lost", "outcome_value": 1.0 if won else 0.0}
