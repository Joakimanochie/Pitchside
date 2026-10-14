"""Families F, G and H: count markets (corners, cards, shots, shots on target), full time.

A count market is a goals market with a different thing being counted: over/under on the match total or one team's count, which team had more
(the "1X2" of that statistic), a handicap on the difference, odd/even and ranges. So the rules are the goals rules, applied to the counts of the
statistic: `home` and `away` in every outcome function are that statistic for each team, and a market's `stat` says which one to read when it is
settled from the real match statistics.

    F corners   (corners won)
    G cards     (yellow cards plus red cards shown to the team)
    H shots and shots on target

Only full-time versions exist: football-data records full-match totals, not halves. Handicap lines are half lines so a stake is never returned.
"""
from pitchside.markets import goals as g
from pitchside.markets.base import Market

CARDS = "cards"

# per statistic: family, display name, the largest count priced per team, and the lines of each market
STATS: dict[str, dict] = {
    "corners": {"family": "F", "name": "Corners", "max": 30,
                "total": (6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5), "team": (2.5, 3.5, 4.5, 5.5, 6.5, 7.5),
                "handicap": (-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5), "range": ["0-8", "9-11", "12+"], "odd_even": True},
    "cards": {"family": "G", "name": "Cards", "max": 12,
              "total": (1.5, 2.5, 3.5, 4.5, 5.5, 6.5), "team": (0.5, 1.5, 2.5, 3.5),
              "handicap": (-1.5, -0.5, 0.5, 1.5), "range": ["0-2", "3-4", "5+"], "odd_even": True},
    "shots": {"family": "H", "name": "Shots", "max": 45,
              "total": (20.5, 22.5, 24.5, 26.5, 28.5, 30.5), "team": (8.5, 10.5, 12.5, 14.5, 16.5),
              "handicap": (-4.5, -3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5, 4.5), "range": None, "odd_even": False},
    "sot": {"family": "H", "name": "Shots on Target", "max": 25,
            "total": (5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5), "team": (2.5, 3.5, 4.5, 5.5, 6.5),
            "handicap": (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5), "range": None, "odd_even": False},
}


def _build(stat: str, cfg: dict) -> dict[str, Market]:
    fam, name = cfg["family"], cfg["name"]
    OU = ["over", "under"]

    def mk(suffix, title, options, outcome, lines=(), exclusive=True):
        sel = (lambda line, o=options: list(o)) if not callable(options) else options
        return Market(f"{stat}_{suffix}", fam, title, sel, outcome, bool(lines), tuple(lines), exclusive, stat)

    out = [
        mk("ou_total", f"{name} Over/Under", OU, g._over_under(g.TOTAL), cfg["total"]),
        mk("ou_home", f"Home Team {name} Over/Under", OU, g._over_under(g.HOME), cfg["team"]),
        mk("ou_away", f"Away Team {name} Over/Under", OU, g._over_under(g.AWAY), cfg["team"]),
        mk("x12", f"{name} 1X2 (who has more)", ["home", "draw", "away"], g._x12),
        mk("ah", f"{name} Handicap", ["home", "away"], g._asian_handicap, cfg["handicap"]),
    ]
    if cfg["odd_even"]:
        out.append(mk("odd_even", f"{name} Odd/Even", ["odd", "even"], g._odd_even(g.TOTAL)))
    if cfg["range"]:
        out.append(mk("range", f"{name} Range", cfg["range"], g._bucketed(g.TOTAL)))
    return {m.id: m for m in out}


MARKETS: dict[str, Market] = {}
for _stat, _cfg in STATS.items():
    MARKETS.update(_build(_stat, _cfg))


def stat_value(stat: str, row: dict | None) -> float | None:
    """One team's count of a statistic from a stored stats record, or None when it is missing."""
    if not row:
        return None
    if stat == CARDS:
        y, r = row.get("yellow_cards"), row.get("red_cards")
        return None if y is None or r is None else y + r
    column = {"corners": "corners", "shots": "shots", "sot": "shots_on_target"}[stat]
    v = row.get(column)
    return None if v is None else v
