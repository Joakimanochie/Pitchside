"""Card timing: how a match's cards split between the halves and when the first one comes.

The cards count model gives the joint distribution of the home side's and the away side's cards (independent negative binomials). Two facts about a
typical match turn that into the timing markets, both measured from past cards (`card_events`, pooled over leagues):

  - first_half_share s: the share of cards shown in the first half. Given N cards in the match, the first-half count is Binomial(N, s).
  - minute profile G(t): the share of cards shown by minute t. A match with N cards has no card by minute t with probability (1 - G(t)) ** N.

Which team gets the first card follows the two sides' expected counts: given i home and j away cards, each card is equally likely to be first, so the
first is the home side's with probability i / (i + j). Cards are assumed to land in halves, minutes and teams independently of each other; the backtest checks
that this holds well enough to rate the markets.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import binom

MAX_MINUTE = 100


@dataclass
class CardProfile:
    first_half_share: float = 0.4
    by_minute: np.ndarray = field(default_factory=lambda: np.linspace(0, 1, MAX_MINUTE + 1))   # G[t] = share of cards shown by minute t
    n_cards: int = 0

    @classmethod
    def fit(cls, periods: np.ndarray, minutes: np.ndarray) -> "CardProfile":
        """periods (1 or 2) and minutes of past cards."""
        n = len(periods)
        if n < 500:
            raise ValueError(f"only {n} cards to fit the timing profile from")
        counts = np.bincount(np.clip(minutes, 0, MAX_MINUTE), minlength=MAX_MINUTE + 1).astype(float)
        g = np.cumsum(counts) / counts.sum()
        return cls(first_half_share=float((periods == 1).mean()), by_minute=g, n_cards=n)

    def to_dict(self) -> dict:
        return {"first_half_share": round(self.first_half_share, 4), "n_cards": self.n_cards, "by_minute": [round(float(x), 5) for x in self.by_minute]}

    @classmethod
    def from_dict(cls, d: dict) -> "CardProfile":
        return cls(d["first_half_share"], np.array(d["by_minute"]), d["n_cards"])


def total_distribution(matrix: np.ndarray) -> np.ndarray:
    """P(total cards = n) from the joint matrix of the two sides' counts."""
    i, j = np.indices(matrix.shape)
    return np.bincount((i + j).ravel(), weights=matrix.ravel())


def half_grid(matrix: np.ndarray, share: float) -> np.ndarray:
    """P[a, b] = P(a first-half and b second-half cards)."""
    total = total_distribution(matrix)
    n_max = len(total) - 1
    grid = np.zeros((n_max + 1, n_max + 1))
    for n, pn in enumerate(total):
        a = np.arange(n + 1)
        grid[a, n - a] = pn * binom.pmf(a, n, share)
    return grid


def price_card_timing(matrix: np.ndarray, profile: CardProfile, markets: dict) -> list[dict]:
    """Rows (market_id, line, selection, probability, p_win, p_lose, p_push) for every card timing market."""
    grid = half_grid(matrix, profile.first_half_share)
    a, b = np.indices(grid.shape)
    total = total_distribution(matrix)
    n = np.arange(len(total))
    i, j = np.indices(matrix.shape)
    with np.errstate(invalid="ignore", divide="ignore"):
        home_first = np.where(i + j > 0, i / (i + j), 0.0)
    p_home = float((matrix * home_first).sum())
    p_none = float(matrix[0, 0])
    out = []

    def add(market_id, line, selection, p):
        p = float(min(max(p, 0.0), 1.0))
        out.append({"market_id": market_id, "line": line, "selection": selection, "probability": p, "p_win": p, "p_lose": 1 - p, "p_push": 0.0})

    for mid, which in (("cards_h1_ou", a), ("cards_h2_ou", b)):
        for line in markets[mid].lines:
            over = float(grid[which > line].sum())
            add(mid, line, "over", over)
            add(mid, line, "under", 1 - over)
    first, second = float(grid[a > b].sum()), float(grid[b > a].sum())
    add("cards_half_most", None, "1st", first)
    add("cards_half_most", None, "2nd", second)
    add("cards_half_most", None, "equal", 1 - first - second)
    add("first_card_team", None, "home", p_home)
    add("first_card_team", None, "away", 1 - p_none - p_home)
    add("first_card_team", None, "none", p_none)
    for line in markets["first_card_by"].lines:
        g = float(profile.by_minute[min(int(line), MAX_MINUTE)])
        by = 1.0 - float((total * (1.0 - g) ** n).sum())
        add("first_card_by", line, "yes", by)
        add("first_card_by", line, "no", 1 - by)
    return out
