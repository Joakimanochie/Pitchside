"""Every market the system knows, across families. Pricing, settling and seeding all read from here."""
from pitchside.markets.base import Market
from pitchside.markets.goals import MARKETS as FAMILY_A

MARKETS: dict[str, Market] = {**FAMILY_A}
