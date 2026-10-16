"""Every market the system knows, across families. Pricing, settling and seeding all read from here.

Two kinds of market:
  SCORE_MARKETS   family A: a function of the final score only; priced exactly from the scoreline matrix.
  COUNT_MARKETS   families F-H: counts of corners, cards, shots and shots on target, priced from count models.
  RECORD_MARKETS  families B-E: a function of the whole match record (halves, order and minute of goals); priced
                  from simulated matches. Those flagged `needs_minutes` can only be settled for matches whose goal
                  minutes were verified.
"""
from pitchside.markets.base import Market
from pitchside.markets.cardtiming import MARKETS as FAMILY_G_TIMING
from pitchside.markets.combos import MARKETS as FAMILY_E
from pitchside.markets.counts import MARKETS as FAMILY_FGH
from pitchside.markets.goals import MARKETS as FAMILY_A
from pitchside.markets.halves import MARKETS as FAMILY_B
from pitchside.markets.path import MARKETS as FAMILY_CD
from pitchside.markets.players import MARKETS as FAMILY_I
from pitchside.markets.record_base import RecordMarket

SCORE_MARKETS: dict[str, Market] = {**FAMILY_A}
PLAYER_MARKETS = {**FAMILY_I}   # I: one selection per player, settled from the player's own counts (experimental)
COUNT_MARKETS: dict[str, Market] = {**FAMILY_FGH}   # F-H: counts of corners, cards, shots; priced from their own count models
CARD_TIMING_MARKETS = {**FAMILY_G_TIMING}           # G: cards by half, first card; priced from the cards count model plus the card timing profile
RECORD_MARKETS: dict[str, RecordMarket] = {**FAMILY_B, **FAMILY_CD, **FAMILY_E}
MARKETS: dict[str, Market | RecordMarket] = {**SCORE_MARKETS, **RECORD_MARKETS, **COUNT_MARKETS, **CARD_TIMING_MARKETS, **PLAYER_MARKETS}

if len(MARKETS) != len(SCORE_MARKETS) + len(RECORD_MARKETS) + len(COUNT_MARKETS) + len(CARD_TIMING_MARKETS) + len(PLAYER_MARKETS):
    raise RuntimeError("two markets share an id")
