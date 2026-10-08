"""Family B: half-time and second-half markets. Rules confirmed against SportyBet's market descriptions.

Two kinds:
  - the first-half and second-half versions of full-time markets reuse the very same rule functions on the half's score;
  - markets that compare the two halves (HT/FT, highest scoring half, win either half, ...) read the whole record.
"""
import numpy as np

from pitchside.markets.base import won_if
from pitchside.markets.goals import MARKETS as A
from pitchside.markets.record_base import RecordMarket, view, wrap_score_market
from pitchside.sim.record import MatchRecord

FAMILY = "B"
YES_NO = ["yes", "no"]

HALF_OU_LINES = (0.5, 1.0, 1.5, 2.0, 2.5)
HALF_AH_LINES = (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5)
HALF_HANDICAP_LINES = (-2.0, -1.0, 1.0)            # SportyBet 0:2, 0:1, 1:0
HALF_CORRECT_SCORES = ["0:0", "1:1", "2:2", "1:0", "2:0", "2:1", "0:1", "0:2", "1:2"]
HALF_MULTIGOALS = ["1-2", "1-3", "2-3", "4+", "no_goal"]
RESULTS = ["home", "draw", "away"]


def _half_correct_score(which: str):
    def outcome(sel, line, rec: MatchRecord):
        h, a = view(rec, which)
        if sel == "other":
            listed = np.zeros(h.shape, dtype=bool)
            for s in HALF_CORRECT_SCORES:
                i, j = (int(x) for x in s.split(":"))
                listed |= (h == i) & (a == j)
            return won_if(~listed)
        i, j = (int(x) for x in sel.split(":"))
        return won_if((h == i) & (a == j))
    return outcome


def _half_multigoals(which: str):
    def outcome(sel, line, rec: MatchRecord):
        h, a = view(rec, which)
        x = h + a
        return won_if({"1-2": (x >= 1) & (x <= 2), "1-3": (x >= 1) & (x <= 3), "2-3": (x >= 2) & (x <= 3),
                       "4+": x >= 4, "no_goal": x == 0}[sel])
    return outcome


def _half_markets(which: str, tag: str, label: str) -> list[RecordMarket]:
    w = lambda base, name, **kw: wrap_score_market(A[base], which, f"{base}_{tag}", f"{label} - {name}", FAMILY, **kw)
    return [
        w("1x2", "1X2"),
        w("double_chance", "Double Chance"),
        w("draw_no_bet", "Draw No Bet"),
        w("ou_total", "Over/Under", lines=HALF_OU_LINES),
        w("handicap_3way", "Handicap", lines=HALF_HANDICAP_LINES),
        w("asian_handicap", "Asian Handicap", lines=HALF_AH_LINES),
        w("ou_home", "Home Team Over/Under", lines=(0.5, 1.5)),
        w("ou_away", "Away Team Over/Under", lines=(0.5, 1.5)),
        w("btts", "GG/NG"),
        w("clean_sheet_home", "Home Team Clean Sheet"),
        w("clean_sheet_away", "Away Team Clean Sheet"),
        w("win_to_nil_home", "Home Team to Win to Nil"),
        w("win_to_nil_away", "Away Team to Win to Nil"),
        w("odd_even", "Odd/Even"),
        w("odd_even_home", "Home Team Odd/Even"),
        w("odd_even_away", "Away Team Odd/Even"),
        w("exact_goals", "Exact Goals", options=["0", "1", "2", "3+"]),
        RecordMarket(f"correct_score_{tag}", FAMILY, f"{label} - Correct Score", lambda line: [*HALF_CORRECT_SCORES, "other"],
                     _half_correct_score(which)),
        RecordMarket(f"multigoals_{tag}", FAMILY, f"{label} - Multigoals", lambda line: list(HALF_MULTIGOALS), _half_multigoals(which),
                     exclusive=False),
    ]


# ---- markets that compare the two halves -----------------------------------------------------------------------

def _result(h: np.ndarray, a: np.ndarray) -> np.ndarray:
    """0 home win, 1 draw, 2 away win."""
    return np.where(h > a, 0, np.where(h == a, 1, 2))


HT_FT = [f"{a}/{b}" for a in RESULTS for b in RESULTS]


def _ht_ft(sel, line, rec):
    ht, ft = sel.split("/")
    return won_if((_result(rec.ht_home, rec.ht_away) == RESULTS.index(ht)) & (_result(rec.ft_home, rec.ft_away) == RESULTS.index(ft)))


def _both_halves_total(over: bool):
    def outcome(sel, line, rec):
        both = ((rec.ht_home + rec.ht_away) > 1.5) & ((rec.h2_home + rec.h2_away) > 1.5) if over else \
               ((rec.ht_home + rec.ht_away) < 1.5) & ((rec.h2_home + rec.h2_away) < 1.5)
        return won_if(both if sel == "yes" else ~both)
    return outcome


def _gg_each_half(sel, line, rec):
    first = (rec.ht_home > 0) & (rec.ht_away > 0)
    second = (rec.h2_home > 0) & (rec.h2_away > 0)
    a, b = sel.split("/")
    return won_if((first == (a == "yes")) & (second == (b == "yes")))


def _scores_in_both_halves(side: str):
    def outcome(sel, line, rec):
        mine_ht = rec.ht_home if side == "home" else rec.ht_away
        mine_h2 = rec.h2_home if side == "home" else rec.h2_away
        both = (mine_ht > 0) & (mine_h2 > 0)
        return won_if(both if sel == "yes" else ~both)
    return outcome


def _both_teams_score_in_both_halves(sel, line, rec):
    both = (rec.ht_home > 0) & (rec.ht_away > 0) & (rec.h2_home > 0) & (rec.h2_away > 0)
    return won_if(both if sel == "yes" else ~both)


def _highest_scoring_half(scope: str):
    def outcome(sel, line, rec):
        if scope == "match":
            first, second = rec.ht_home + rec.ht_away, rec.h2_home + rec.h2_away
        elif scope == "home":
            first, second = rec.ht_home, rec.h2_home
        else:
            first, second = rec.ht_away, rec.h2_away
        return won_if({"1st": first > second, "2nd": second > first, "equal": first == second}[sel])
    return outcome


def _wins_half(side: str, which: str, rec) -> np.ndarray:
    h, a = view(rec, which)
    return h > a if side == "home" else a > h


def _win_either_half(side: str):
    def outcome(sel, line, rec):
        hit = _wins_half(side, "ht", rec) | _wins_half(side, "h2", rec)
        return won_if(hit if sel == "yes" else ~hit)
    return outcome


def _win_both_halves(side: str):
    def outcome(sel, line, rec):
        hit = _wins_half(side, "ht", rec) & _wins_half(side, "h2", rec)
        return won_if(hit if sel == "yes" else ~hit)
    return outcome


def _ht_or_ft_result(sel, line, rec):
    r = RESULTS.index(sel)
    return won_if((_result(rec.ht_home, rec.ht_away) == r) | (_result(rec.ft_home, rec.ft_away) == r))


def _yes_no_market(id_, name, outcome):
    return RecordMarket(id_, FAMILY, name, lambda line: list(YES_NO), outcome)


COMPARING = [
    RecordMarket("ht_ft", FAMILY, "Half Time/Full Time", lambda line: list(HT_FT), _ht_ft),
    _yes_no_market("both_halves_over_15", "Both Halves Over 1.5", _both_halves_total(True)),
    _yes_no_market("both_halves_under_15", "Both Halves Under 1.5", _both_halves_total(False)),
    RecordMarket("gg_ng_each_half", FAMILY, "1st/2nd Half GG/NG", lambda line: ["no/no", "yes/no", "yes/yes", "no/yes"], _gg_each_half),
    _yes_no_market("home_scores_both_halves", "Home Team to Score In Both Halves", _scores_in_both_halves("home")),
    _yes_no_market("away_scores_both_halves", "Away Team to Score In Both Halves", _scores_in_both_halves("away")),
    _yes_no_market("btts_both_halves", "Both Teams to Score in Both Halves", _both_teams_score_in_both_halves),
    RecordMarket("highest_scoring_half", FAMILY, "Highest Scoring Half", lambda line: ["1st", "2nd", "equal"], _highest_scoring_half("match")),
    RecordMarket("highest_scoring_half_home", FAMILY, "Home Team Highest Scoring Half", lambda line: ["1st", "2nd", "equal"], _highest_scoring_half("home")),
    RecordMarket("highest_scoring_half_away", FAMILY, "Away Team Highest Scoring Half", lambda line: ["1st", "2nd", "equal"], _highest_scoring_half("away")),
    _yes_no_market("home_wins_either_half", "Home Team to Win Either Half", _win_either_half("home")),
    _yes_no_market("away_wins_either_half", "Away Team to Win Either Half", _win_either_half("away")),
    _yes_no_market("home_wins_both_halves", "Home Team to Win Both Halves", _win_both_halves("home")),
    _yes_no_market("away_wins_both_halves", "Away Team to Win Both Halves", _win_both_halves("away")),
    RecordMarket("ht_or_ft_result", FAMILY, "1st Half Result or Match Result", lambda line: list(RESULTS), _ht_or_ft_result, exclusive=False),
]

MARKETS: dict[str, RecordMarket] = {
    m.id: m for m in [*_half_markets("ht", "h1", "1st Half"), *_half_markets("h2", "h2", "2nd Half"), *COMPARING]
}
