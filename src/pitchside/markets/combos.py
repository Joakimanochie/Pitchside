"""Family E: combinations. Each is the joint event of two simple markets on the same simulated (or real) match, so a
combination can never be priced above either of its parts and the parts always add back up to the whole.

Two shapes, as on SportyBet:
  - "A & B": one selection per pair of outcomes, e.g. 'home&over' for 1X2 & Over/Under 2.5;
  - "Team or ...": a yes/no market that wins if at least one of two events happens, e.g. Home Team or Over 2.5.
"""
from itertools import product

import numpy as np

from pitchside.markets.base import won_if
from pitchside.markets.record_base import RecordMarket, view
from pitchside.sim.record import MatchRecord

FAMILY = "E"
RESULTS = ["home", "draw", "away"]


# ---- the parts: each is {label: function(record) -> boolean array} -----------------------------------------------

def x12(which: str):
    def f(op):
        return lambda r: op(*view(r, which))
    return {"home": f(lambda h, a: h > a), "draw": f(lambda h, a: h == a), "away": f(lambda h, a: h < a)}


def double_chance(which: str):
    def f(op):
        return lambda r: op(*view(r, which))
    return {"1x": f(lambda h, a: h >= a), "12": f(lambda h, a: h != a), "x2": f(lambda h, a: h <= a)}


def total(which: str, line: float):
    return {"over": lambda r: sum(view(r, which)) > line, "under": lambda r: sum(view(r, which)) < line}


def btts(which: str):
    return {"yes": lambda r: (view(r, which)[0] > 0) & (view(r, which)[1] > 0),
            "no": lambda r: ~((view(r, which)[0] > 0) & (view(r, which)[1] > 0))}


def ht_ft():
    def result(h, a):
        return np.where(h > a, 0, np.where(h == a, 1, 2))

    def f(ht, ft):
        return lambda r: (result(r.ht_home, r.ht_away) == ht) & (result(r.ft_home, r.ft_away) == ft)

    return {f"{RESULTS[i]}/{RESULTS[j]}": f(i, j) for i in range(3) for j in range(3)}


# ---- builders --------------------------------------------------------------------------------------------------

def both(id_: str, name: str, part_a: dict, part_b: dict, exclusive: bool = True) -> RecordMarket:
    """'A & B': selections are every pairing, written 'a&b'."""
    options = [f"{a}&{b}" for a, b in product(part_a, part_b)]

    def outcome(sel, line, rec: MatchRecord):
        a, b = sel.split("&")
        return won_if(part_a[a](rec) & part_b[b](rec))

    return RecordMarket(id_, FAMILY, name, lambda line: list(options), outcome, exclusive=exclusive)


def either(id_: str, name: str, event_a, event_b) -> RecordMarket:
    """'Team or ...': yes if at least one of two events happens."""
    def outcome(sel, line, rec: MatchRecord):
        hit = event_a(rec) | event_b(rec)
        return won_if(hit if sel == "yes" else ~hit)

    return RecordMarket(id_, FAMILY, name, lambda line: ["yes", "no"], outcome)


def _first_goal_and_result() -> RecordMarket:
    options = [f"{g}&{r}" for g in ("home_goal", "away_goal") for r in RESULTS] + ["no_goal"]
    res = x12("ft")

    def outcome(sel, line, rec: MatchRecord):
        first = rec.goal_side[:, 0] if rec.goal_side.shape[1] else np.zeros(rec.n, dtype=int)
        if sel == "no_goal":
            return won_if(first == 0)
        g, r = sel.split("&")
        return won_if((first == (1 if g == "home_goal" else -1)) & res[r](rec))

    return RecordMarket("first_goal_x12", FAMILY, "1st Goal & 1X2", lambda line: list(options), outcome)


def _label(line: float) -> str:
    return str(line).replace(".", "")


def _build() -> list[RecordMarket]:
    out: list[RecordMarket] = []
    for line in (1.5, 2.5, 3.5, 4.5):
        out.append(both(f"x12_ou_{_label(line)}", f"1X2 & Over/Under {line}", x12("ft"), total("ft", line)))
        out.append(both(f"htft_ou_{_label(line)}", f"Halftime/Fulltime & Over/Under {line}", ht_ft(), total("ft", line)))
        out.append(both(f"dc_ou_{_label(line)}", f"Double Chance & Over/Under {line}", double_chance("ft"), total("ft", line), exclusive=False))
    out.append(both("x12_btts", "1X2 & GG/NG", x12("ft"), btts("ft")))
    out.append(both("ou_25_btts", "Over/Under 2.5 & GG/NG", total("ft", 2.5), btts("ft")))
    out.append(_first_goal_and_result())
    for line in (0.5, 1.5, 2.5):
        out.append(both(f"htft_h1ou_{_label(line)}", f"Halftime/Fulltime & 1st Half Over/Under {line}", ht_ft(), total("ht", line)))
    out.append(both("dc_btts", "Double Chance & GG/NG", double_chance("ft"), btts("ft"), exclusive=False))
    out.append(both("dc_btts_h1", "Double Chance & 1st Half GG/NG", double_chance("ft"), btts("ht"), exclusive=False))
    out.append(both("dc_btts_h2", "Double Chance & 2nd Half GG/NG", double_chance("ft"), btts("h2"), exclusive=False))
    out.append(both("h1_dc_ou_15", "Half-time Double Chance & Total Goals", double_chance("ht"), total("ht", 1.5), exclusive=False))
    out.append(both("h1_dc_btts", "1st Half - Double Chance & GG/NG", double_chance("ht"), btts("ht"), exclusive=False))
    out.append(both("h1_x12_btts", "1st Half - 1X2 & GG/NG", x12("ht"), btts("ht")))
    out.append(both("h1_x12_ou_15", "1st Half - 1X2 & Over/Under 1.5", x12("ht"), total("ht", 1.5)))
    out.append(both("h2_x12_ou_15", "2nd Half - 1X2 & Over/Under 1.5", x12("h2"), total("h2", 1.5)))
    out.append(both("h2_x12_btts", "2nd Half - 1X2 & GG/NG", x12("h2"), btts("h2")))
    out.append(both("h2_dc_ou_15", "2nd Half Double Chance & Total Goals", double_chance("h2"), total("h2", 1.5), exclusive=False))
    out.append(both("h2_dc_btts", "2nd Half - Double Chance & GG/NG", double_chance("h2"), btts("h2"), exclusive=False))

    ft = x12("ft")
    any_clean_sheet = lambda r: ~((r.ft_home > 0) & (r.ft_away > 0))
    for team, label in (("home", "Home Team"), ("draw", "Draw"), ("away", "Away Team")):
        out.append(either(f"or_{team}_over25", f"{label} or Over 2.5", ft[team], total("ft", 2.5)["over"]))
        out.append(either(f"or_{team}_under25", f"{label} or Under 2.5", ft[team], total("ft", 2.5)["under"]))
        out.append(either(f"or_{team}_btts", f"{label} or GG", ft[team], btts("ft")["yes"]))
        out.append(either(f"or_{team}_clean_sheet", f"{label} or Any Clean Sheet", ft[team], any_clean_sheet))
    return out


MARKETS: dict[str, RecordMarket] = {m.id: m for m in _build()}
