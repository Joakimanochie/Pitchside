"""Every market the system knows, across families. Pricing, settling and seeding all read from here.

Two kinds of market:
  SCORE_MARKETS   family A: a function of the final score only; priced exactly from the scoreline matrix.
  RECORD_MARKETS  families B-E: a function of the whole match record (halves, order and minute of goals); priced
                  from simulated matches. Those flagged `needs_minutes` can only be settled for matches whose goal
                  minutes were verified.
"""
from pitchside.markets.base import Market
from pitchside.markets.combos import MARKETS as FAMILY_E
from pitchside.markets.goals import MARKETS as FAMILY_A
from pitchside.markets.halves import MARKETS as FAMILY_B
from pitchside.markets.path import MARKETS as FAMILY_CD
from pitchside.markets.record_base import RecordMarket

SCORE_MARKETS: dict[str, Market] = {**FAMILY_A}
RECORD_MARKETS: dict[str, RecordMarket] = {**FAMILY_B, **FAMILY_CD, **FAMILY_E}
MARKETS: dict[str, Market | RecordMarket] = {**SCORE_MARKETS, **RECORD_MARKETS}

if len(MARKETS) != len(SCORE_MARKETS) + len(RECORD_MARKETS):
    raise RuntimeError("two markets share an id: " + ", ".join(sorted(set(SCORE_MARKETS) & set(RECORD_MARKETS))))
