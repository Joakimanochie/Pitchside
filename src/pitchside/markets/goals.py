"""Family A: result and goals markets, full time. Rules confirmed against SportyBet's market descriptions.

Conventions: `home`/`away` are goals scored; every market is a function of the final score only.
Handicap-style markets take `line` from the HOME team's perspective:
  - Asian handicap: line -1.5 means home gives 1.5 goals.
  - 3-way handicap: line = home head start - away head start, so SportyBet "0:1" is -1 and "1:0" is +1.
"""
import numpy as np

from pitchside.markets.base import LOST, PUSH, WON, Market, beats, won_if

FAMILY = "A"
YES_NO = ["yes", "no"]


def _fixed(options: list[str]):
    return lambda line: list(options)


def _market(id_, name, options, outcome, has_line=False, lines=(), exclusive=True):
    sel = options if callable(options) else _fixed(options)
    return Market(id_, FAMILY, name, sel, outcome, has_line, tuple(lines), exclusive)


# ---- result -----------------------------------------------------------------------------------------------

def _x12(sel, line, h, a):
    return won_if({"home": h > a, "draw": h == a, "away": h < a}[sel])


def _double_chance(sel, line, h, a):
    return won_if({"1x": h >= a, "12": h != a, "x2": h <= a}[sel])


def _draw_no_bet(sel, line, h, a):
    win = h > a if sel == "home" else h < a
    return np.where(win, WON, np.where(h == a, PUSH, LOST))


def _home_no_bet(sel, line, h, a):  # stake returned if HOME wins
    win = h == a if sel == "draw" else h < a
    return np.where(h > a, PUSH, np.where(win, WON, LOST))


def _away_no_bet(sel, line, h, a):  # stake returned if AWAY wins
    win = h == a if sel == "draw" else h > a
    return np.where(h < a, PUSH, np.where(win, WON, LOST))


def _handicap_3way(sel, line, h, a):
    d = (h - a) + line
    return won_if({"home": d > 0, "draw": d == 0, "away": d < 0}[sel])


def _asian_handicap(sel, line, h, a):
    return beats(h - a, -line) if sel == "home" else beats(a - h, line)


# ---- totals -----------------------------------------------------------------------------------------------

def _over_under(total_fn):
    def outcome(sel, line, h, a):
        x = total_fn(h, a)
        return beats(x, line) if sel == "over" else beats(-x, -line)
    return outcome


def _odd_even(total_fn):
    return lambda sel, line, h, a: won_if((total_fn(h, a) % 2 == 1) if sel == "odd" else (total_fn(h, a) % 2 == 0))


def _bucket(x: np.ndarray, label: str) -> np.ndarray:
    """Membership of x in a bucket label: '3' exact, '6+' at least, '2-3' inclusive range, '1-3+' at least 1."""
    if label.endswith("+") and "-" not in label:
        return x >= int(label[:-1])
    if "-" in label:
        lo, hi = label.split("-")
        return (x >= int(lo)) if hi.endswith("+") else (x >= int(lo)) & (x <= int(hi))
    return x == int(label)


def _bucketed(total_fn):
    return lambda sel, line, h, a: won_if(_bucket(total_fn(h, a), sel))


def _excluded(total_fn):
    """'Bet against' n goals: wins unless the count equals n; 'n+' wins only while the count is below n."""
    def outcome(sel, line, h, a):
        x = total_fn(h, a)
        return won_if(x < int(sel[:-1]) if sel.endswith("+") else x != int(sel))
    return outcome


TOTAL = lambda h, a: h + a
HOME = lambda h, a: h
AWAY = lambda h, a: a

# ---- both teams / clean sheets ---------------------------------------------------------------------------

def _yes_no(mask_fn):
    return lambda sel, line, h, a: won_if(mask_fn(h, a) if sel == "yes" else ~mask_fn(h, a))


def _teams_to_score(sel, line, h, a):
    return won_if({"none": (h == 0) & (a == 0), "only_home": (h > 0) & (a == 0),
                   "only_away": (h == 0) & (a > 0), "both": (h > 0) & (a > 0)}[sel])


def _winning_margin(sel, line, h, a):
    d = h - a
    return won_if({"home_1": d == 1, "home_2": d == 2, "home_3+": d >= 3, "away_1": d == -1, "away_2": d == -2,
                   "away_3+": d <= -3, "draw": d == 0}[sel])


# ---- scorelines --------------------------------------------------------------------------------------------

CORRECT_SCORES = [f"{i}:{j}" for j in range(5) for i in range(5)]


def _correct_score(sel, line, h, a):
    if sel == "other":
        return won_if((h > 4) | (a > 4))
    i, j = (int(x) for x in sel.split(":"))
    return won_if((h == i) & (a == j))


MULTISCORE_GROUPS = {
    "home_1-0_2-0_3-0": [(1, 0), (2, 0), (3, 0)],
    "away_0-1_0-2_0-3": [(0, 1), (0, 2), (0, 3)],
    "home_4-0_5-0_6-0": [(4, 0), (5, 0), (6, 0)],
    "away_0-4_0-5_0-6": [(0, 4), (0, 5), (0, 6)],
    "home_2-1_3-1_4-1": [(2, 1), (3, 1), (4, 1)],
    "away_1-2_1-3_1-4": [(1, 2), (1, 3), (1, 4)],
    "home_3-2_4-2_4-3_5-1": [(3, 2), (4, 2), (4, 3), (5, 1)],
    "away_2-3_2-4_3-4_1-5": [(2, 3), (2, 4), (3, 4), (1, 5)],
}


def _multiscores(sel, line, h, a):
    listed = np.zeros(np.broadcast(h, a).shape, dtype=bool)
    for cells in MULTISCORE_GROUPS.values():
        for i, j in cells:
            listed |= (h == i) & (a == j)
    if sel in MULTISCORE_GROUPS:
        hit = np.zeros_like(listed)
        for i, j in MULTISCORE_GROUPS[sel]:
            hit |= (h == i) & (a == j)
        return won_if(hit)
    if sel == "draw":
        return won_if(h == a)
    if sel == "other_home":
        return won_if((h > a) & ~listed)
    return won_if((a > h) & ~listed)  # other_away


# ---- registry ----------------------------------------------------------------------------------------------

OU_LINES = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5)
TEAM_OU_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
AH_LINES = tuple(x / 2 for x in range(-6, 7))        # -3.0 ... +3.0 in half steps
HANDICAP_3WAY_LINES = (-5.0, -4.0, -3.0, -2.0, -1.0, 1.0, 2.0)  # SportyBet 0:5 ... 0:1, 1:0, 2:0

GOAL_BOUNDS_TOTAL = ["0", "0-1", "0-2", "0-3", "0-4", "1", "1-2", "1-3", "1-4", "1-5+", "2", "2-3", "2-4", "2-5+",
                     "3", "3-4", "3-5+", "4", "4-5+", "5+"]
GOAL_BOUNDS_TEAM = ["0", "0-1", "0-2", "1", "1-2", "1-3+", "2", "2-3+", "3+"]  # away list assumed same as home

MARKETS: dict[str, Market] = {m.id: m for m in [
    _market("1x2", "1X2", ["home", "draw", "away"], _x12),
    _market("double_chance", "Double Chance", ["1x", "12", "x2"], _double_chance, exclusive=False),
    _market("draw_no_bet", "Draw No Bet", ["home", "away"], _draw_no_bet),
    _market("home_no_bet", "Home No Bet", ["draw", "away"], _home_no_bet),
    _market("away_no_bet", "Away No Bet", ["home", "draw"], _away_no_bet),
    _market("handicap_3way", "Handicap (3-way)", ["home", "draw", "away"], _handicap_3way, True, HANDICAP_3WAY_LINES),
    _market("asian_handicap", "Asian Handicap", ["home", "away"], _asian_handicap, True, AH_LINES),
    _market("ou_total", "Over/Under", ["over", "under"], _over_under(TOTAL), True, OU_LINES),
    _market("ou_home", "Home Team Over/Under", ["over", "under"], _over_under(HOME), True, TEAM_OU_LINES),
    _market("ou_away", "Away Team Over/Under", ["over", "under"], _over_under(AWAY), True, TEAM_OU_LINES),
    _market("btts", "GG/NG", YES_NO, _yes_no(lambda h, a: (h > 0) & (a > 0))),
    _market("btts_2plus", "GG/NG 2+", YES_NO, _yes_no(lambda h, a: (h >= 2) & (a >= 2))),
    _market("odd_even", "Odd/Even", ["odd", "even"], _odd_even(TOTAL)),
    _market("odd_even_home", "Home Team Odd/Even", ["odd", "even"], _odd_even(HOME)),
    _market("odd_even_away", "Away Team Odd/Even", ["odd", "even"], _odd_even(AWAY)),
    _market("exact_goals", "Exact Goals", ["0", "1", "2", "3", "4", "5", "6+"], _bucketed(TOTAL)),
    _market("goal_range", "Goal Range", ["0-1", "2-3", "4-6", "7+"], _bucketed(TOTAL)),
    _market("goals_home", "Home Team Goals", ["0", "1", "2", "3+"], _bucketed(HOME)),
    _market("goals_away", "Away Team Goals", ["0", "1", "2", "3+"], _bucketed(AWAY)),
    _market("teams_to_score", "Teams to Score", ["none", "only_home", "only_away", "both"], _teams_to_score),
    _market("clean_sheet_home", "Home Team Clean Sheet", YES_NO, _yes_no(lambda h, a: a == 0)),
    _market("clean_sheet_away", "Away Team Clean Sheet", YES_NO, _yes_no(lambda h, a: h == 0)),
    _market("win_to_nil_home", "Home Team to Win to Nil", YES_NO, _yes_no(lambda h, a: (h > a) & (a == 0))),
    _market("win_to_nil_away", "Away Team to Win to Nil", YES_NO, _yes_no(lambda h, a: (a > h) & (h == 0))),
    _market("winning_margin", "Winning Margin",
            ["home_1", "home_2", "home_3+", "away_1", "away_2", "away_3+", "draw"], _winning_margin),
    _market("excluded_goals", "Excluded Number of Goals", ["0", "1", "2", "3", "4", "5+"], _excluded(TOTAL), exclusive=False),
    _market("excluded_goals_home", "Excluded Number of Goals - Home", ["0", "1", "2", "3+"], _excluded(HOME), exclusive=False),
    _market("excluded_goals_away", "Excluded Number of Goals - Away", ["0", "1", "2", "3+"], _excluded(AWAY), exclusive=False),
    _market("goal_bounds", "Goal Bounds", GOAL_BOUNDS_TOTAL, _bucketed(TOTAL), exclusive=False),
    _market("goal_bounds_home", "Goal Bounds - Home", GOAL_BOUNDS_TEAM, _bucketed(HOME), exclusive=False),
    _market("goal_bounds_away", "Goal Bounds - Away", GOAL_BOUNDS_TEAM, _bucketed(AWAY), exclusive=False),
    _market("no_draw_btts", "No Draw Both Teams To Score", YES_NO, _yes_no(lambda h, a: (h > 0) & (a > 0) & (h != a))),
    _market("correct_score", "Correct Score", CORRECT_SCORES + ["other"], _correct_score),
    _market("multiscores", "Multiscores", [*MULTISCORE_GROUPS, "other_home", "other_away", "draw"], _multiscores),
]}


def price_match(matrix: np.ndarray) -> list[dict]:
    """Price every family A market at its default lines from one scoreline matrix."""
    from pitchside.markets.base import price

    rows = []
    for m in MARKETS.values():
        for line in (m.lines if m.has_line else (None,)):
            rows.extend(price(m, line, matrix))
    return rows
