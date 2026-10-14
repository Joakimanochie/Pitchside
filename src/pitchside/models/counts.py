"""Count model for corners, cards, shots and shots on target.

Same idea as the goals model: each club has an attack rate (how many it produces) and a defence rate (how many it allows), plus a home advantage,
all on a log scale and shrunk toward the league average, with older matches counting less. For counts that vary more than a Poisson allows
(corners and shots do) the spread is estimated from the training data and the distribution is a negative binomial with the same mean:

    log mean_home = mu + home_adv + attack[home] - defence[away]
    log mean_away = mu +            attack[away] - defence[home]
    variance = mean + dispersion * mean^2

The two teams' counts are treated as independent; the backtest checks the calibration of the match total, which is where a shared effect would show.
Only matches strictly before `as_of` are used.
"""
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import nbinom, poisson

from pitchside.models.dixon_coles import neg_log_likelihood

# memory and shrinkage per statistic, chosen on 2019/20-2021/22 only (scripts/tune_counts.py) and then frozen
COUNT_PARAMS = {
    "corners": {"half_life_days": 365.0, "ridge": 16.0},
    "cards": {"half_life_days": 365.0, "ridge": 16.0},
    "shots": {"half_life_days": 365.0, "ridge": 16.0},
    "sot": {"half_life_days": 365.0, "ridge": 16.0},
}


@dataclass
class CountModel:
    half_life_days: float = 730.0
    ridge: float = 2.0
    max_count: int = 30
    teams: list[str] = field(default_factory=list)
    mu: float = 0.0
    home_adv: float = 0.0
    dispersion: float = 0.0
    attack: dict[str, float] = field(default_factory=dict)
    defence: dict[str, float] = field(default_factory=dict)
    as_of: date | None = None
    n_matches: int = 0

    def fit(self, matches: pd.DataFrame, as_of: date) -> "CountModel":
        """matches: columns match_date, home, away, count_home, count_away (rows without a count are ignored)."""
        m = matches[(matches["match_date"] < as_of)].dropna(subset=["count_home", "count_away"])
        if len(m) < 50:
            raise ValueError(f"need at least 50 matches with counts before {as_of}, got {len(m)}")
        self.as_of, self.n_matches = as_of, len(m)
        self.teams = sorted(set(m["home"]) | set(m["away"]))
        idx = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)
        hi, ai = m["home"].map(idx).to_numpy(), m["away"].map(idx).to_numpy()
        hc, ac = m["count_home"].to_numpy(dtype=float), m["count_away"].to_numpy(dtype=float)
        w = 0.5 ** (np.array([(as_of - d).days for d in m["match_date"]], dtype=float) / self.half_life_days)

        theta0 = np.zeros(3 + 2 * n)
        theta0[0] = np.log((hc @ w + ac @ w) / (2 * w.sum()))
        bounds = [(None, None), (None, None), (0.0, 0.0)] + [(None, None)] * (2 * n)   # no low-score correction for counts: rho fixed at 0
        res = minimize(neg_log_likelihood, theta0, args=(hi, ai, hc, ac, w, n, self.ridge), jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
        if not res.success and res.status != 1:
            raise RuntimeError(f"count model fit failed: {res.message}")
        self.mu, self.home_adv = float(res.x[0]), float(res.x[1])
        att, dfn = res.x[3:3 + n], res.x[3 + n:]
        self.attack, self.defence = dict(zip(self.teams, att.tolist(), strict=True)), dict(zip(self.teams, dfn.tolist(), strict=True))
        lam_h = np.exp(self.mu + self.home_adv + att[hi] - dfn[ai])
        lam_a = np.exp(self.mu + att[ai] - dfn[hi])
        y, lam = np.concatenate([hc, ac]), np.concatenate([lam_h, lam_a])
        ww = np.concatenate([w, w])
        # method of moments for the spread: var = lam + alpha * lam^2
        self.dispersion = float(max(0.0, (ww @ ((y - lam) ** 2 - lam)) / (ww @ lam ** 2)))
        return self

    def means(self, home: str, away: str) -> tuple[float, float]:
        """Expected counts. A club never seen in training gets the league-average rating."""
        a_h, d_h = self.attack.get(home, 0.0), self.defence.get(home, 0.0)
        a_a, d_a = self.attack.get(away, 0.0), self.defence.get(away, 0.0)
        return float(np.exp(self.mu + self.home_adv + a_h - d_a)), float(np.exp(self.mu + a_a - d_h))

    def _pmf(self, k: np.ndarray, mean: float) -> np.ndarray:
        if self.dispersion < 1e-6:
            return poisson.pmf(k, mean)
        r = 1.0 / self.dispersion
        return nbinom.pmf(k, r, r / (r + mean))

    def count_matrix(self, home: str, away: str) -> np.ndarray:
        """P[i, j] = probability the home side has i and the away side j, for 0..max_count each. Sums to 1."""
        lam_h, lam_a = self.means(home, away)
        k = np.arange(self.max_count + 1)
        p = np.outer(self._pmf(k, lam_h), self._pmf(k, lam_a))
        return p / p.sum()

    def known(self, team: str) -> bool:
        return team in self.attack
