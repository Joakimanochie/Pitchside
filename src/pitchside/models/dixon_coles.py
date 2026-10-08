"""Dixon-Coles goals model with time decay and ridge shrinkage.

    log lambda_home = mu + home_adv + attack[home] - defence[away]
    log lambda_away = mu +            attack[away] - defence[home]

Goals are Poisson given the lambdas, with the Dixon-Coles correction `tau` on the four low scorelines
(0-0, 1-0, 0-1, 1-1). Attack/defence are estimated jointly, so a result against a strong opponent
says more than the same result against a weak one (opponent-strength adjustment). Older matches get
weight 0.5 ** (age_days / half_life_days). Ridge shrinks every team toward the league average, which
is what protects teams with few matches (promoted sides, early season).

Only matches strictly before `as_of` are used. This is the leakage rule from BUILD.md section 8.
"""
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

RHO_BOUND = 0.25
MAX_GOALS = 10


def _tau(hg, ag, lam_h, lam_a, rho):
    t = np.ones_like(lam_h)
    m00, m01, m10, m11 = (hg == 0) & (ag == 0), (hg == 0) & (ag == 1), (hg == 1) & (ag == 0), (hg == 1) & (ag == 1)
    t = np.where(m00, 1 - lam_h * lam_a * rho, t)
    t = np.where(m01, 1 + lam_h * rho, t)
    t = np.where(m10, 1 + lam_a * rho, t)
    t = np.where(m11, 1 - rho, t)
    return np.clip(t, 1e-10, None), (m00, m01, m10, m11)


def neg_log_likelihood(theta, hi, ai, hg, ag, w, n_teams, ridge):
    """Penalised negative weighted log-likelihood and its exact gradient."""
    mu, adv, rho = theta[0], theta[1], theta[2]
    att, dfn = theta[3:3 + n_teams], theta[3 + n_teams:]
    eta_h = mu + adv + att[hi] - dfn[ai]
    eta_a = mu + att[ai] - dfn[hi]
    lam_h, lam_a = np.exp(eta_h), np.exp(eta_a)

    tau, (m00, m01, m10, m11) = _tau(hg, ag, lam_h, lam_a, rho)
    ll = w * (hg * eta_h - lam_h + ag * eta_a - lam_a + np.log(tau))

    # d log(tau) / d lambda_h, d lambda_a, d rho
    dh = np.where(m00, -lam_a * rho / tau, 0.0) + np.where(m01, rho / tau, 0.0)
    da = np.where(m00, -lam_h * rho / tau, 0.0) + np.where(m10, rho / tau, 0.0)
    dr = (np.where(m00, -lam_h * lam_a / tau, 0.0) + np.where(m01, lam_h / tau, 0.0)
          + np.where(m10, lam_a / tau, 0.0) + np.where(m11, -1.0 / tau, 0.0))

    g_h = w * (hg - lam_h + lam_h * dh)  # d ll / d eta_home
    g_a = w * (ag - lam_a + lam_a * da)

    grad = np.empty_like(theta)
    grad[0] = g_h.sum() + g_a.sum()
    grad[1] = g_h.sum()
    grad[2] = (w * dr).sum()
    grad[3:3 + n_teams] = np.bincount(hi, g_h, n_teams) + np.bincount(ai, g_a, n_teams)
    grad[3 + n_teams:] = -np.bincount(ai, g_h, n_teams) - np.bincount(hi, g_a, n_teams)

    penalty = ridge * (att @ att + dfn @ dfn)
    grad_pen = np.zeros_like(theta)
    grad_pen[3:3 + n_teams] = 2 * ridge * att
    grad_pen[3 + n_teams:] = 2 * ridge * dfn
    return -ll.sum() + penalty, -grad + grad_pen


@dataclass
class DixonColes:
    half_life_days: float = 365.0
    ridge: float = 2.0
    max_goals: int = MAX_GOALS
    # fitted state
    teams: list[str] = field(default_factory=list)
    mu: float = 0.0
    home_adv: float = 0.0
    rho: float = 0.0
    attack: dict[str, float] = field(default_factory=dict)
    defence: dict[str, float] = field(default_factory=dict)
    as_of: date | None = None
    n_matches: int = 0

    def fit(self, matches: pd.DataFrame, as_of: date) -> "DixonColes":
        """matches: columns match_date, home, away, ft_home, ft_away. Uses only rows dated before as_of."""
        m = matches[matches["match_date"] < as_of]
        if len(m) < 50:
            raise ValueError(f"need at least 50 matches before {as_of}, got {len(m)}")
        self.as_of, self.n_matches = as_of, len(m)
        self.teams = sorted(set(m["home"]) | set(m["away"]))
        idx = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)
        hi = m["home"].map(idx).to_numpy()
        ai = m["away"].map(idx).to_numpy()
        hg = m["ft_home"].to_numpy(dtype=float)
        ag = m["ft_away"].to_numpy(dtype=float)
        age = np.array([(as_of - d).days for d in m["match_date"]], dtype=float)
        w = 0.5 ** (age / self.half_life_days)

        theta0 = np.zeros(3 + 2 * n)
        theta0[0] = np.log((hg @ w + ag @ w) / (2 * w.sum()))
        bounds = [(None, None), (None, None), (-RHO_BOUND, RHO_BOUND)] + [(None, None)] * (2 * n)
        res = minimize(neg_log_likelihood, theta0, args=(hi, ai, hg, ag, w, n, self.ridge),
                       jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
        if not res.success and res.status != 1:  # status 1 = iteration limit, still usable
            raise RuntimeError(f"Dixon-Coles fit failed: {res.message}")
        self.mu, self.home_adv, self.rho = float(res.x[0]), float(res.x[1]), float(res.x[2])
        self.attack = dict(zip(self.teams, res.x[3:3 + n].tolist(), strict=True))
        self.defence = dict(zip(self.teams, res.x[3 + n:].tolist(), strict=True))
        return self

    def lambdas(self, home: str, away: str) -> tuple[float, float]:
        """Expected goals. A team never seen in training gets the league-average rating (0, 0)."""
        a_h, d_h = self.attack.get(home, 0.0), self.defence.get(home, 0.0)
        a_a, d_a = self.attack.get(away, 0.0), self.defence.get(away, 0.0)
        return (float(np.exp(self.mu + self.home_adv + a_h - d_a)), float(np.exp(self.mu + a_a - d_h)))

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        """P[i, j] = probability the match ends home i - away j, i, j in 0..max_goals. Sums to 1."""
        lam_h, lam_a = self.lambdas(home, away)
        g = np.arange(self.max_goals + 1)
        p = np.outer(poisson.pmf(g, lam_h), poisson.pmf(g, lam_a))
        p[0, 0] *= 1 - lam_h * lam_a * self.rho
        p[0, 1] *= 1 + lam_h * self.rho
        p[1, 0] *= 1 + lam_a * self.rho
        p[1, 1] *= 1 - self.rho
        return p / p.sum()

    def known(self, team: str) -> bool:
        return team in self.attack
