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
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import nbinom, poisson

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


def neg_log_likelihood(theta, hi, ai, hg, ag, w, n_teams, ridge, hg_t=None, ag_t=None):
    """Penalised negative weighted log-likelihood and its exact gradient.

    hg, ag are the real goals (they decide where the low-score correction applies). hg_t, ag_t are the targets the Poisson part is fitted to; they
    default to the goals and can be goals blended with expected goals (xG), which are less noisy than goals themselves."""
    hg_t = hg if hg_t is None else hg_t
    ag_t = ag if ag_t is None else ag_t
    mu, adv, rho = theta[0], theta[1], theta[2]
    att, dfn = theta[3:3 + n_teams], theta[3 + n_teams:]
    eta_h = mu + adv + att[hi] - dfn[ai]
    eta_a = mu + att[ai] - dfn[hi]
    lam_h, lam_a = np.exp(eta_h), np.exp(eta_a)

    tau, (m00, m01, m10, m11) = _tau(hg, ag, lam_h, lam_a, rho)
    ll = w * (hg_t * eta_h - lam_h + ag_t * eta_a - lam_a + np.log(tau))

    # d log(tau) / d lambda_h, d lambda_a, d rho
    dh = np.where(m00, -lam_a * rho / tau, 0.0) + np.where(m01, rho / tau, 0.0)
    da = np.where(m00, -lam_h * rho / tau, 0.0) + np.where(m10, rho / tau, 0.0)
    dr = (np.where(m00, -lam_h * lam_a / tau, 0.0) + np.where(m01, lam_h / tau, 0.0)
          + np.where(m10, lam_a / tau, 0.0) + np.where(m11, -1.0 / tau, 0.0))

    g_h = w * (hg_t - lam_h + lam_h * dh)  # d ll / d eta_home
    g_a = w * (ag_t - lam_a + lam_a * da)

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
    level_window_days: float = 0.0  # 0 = off; see level_adjustment
    level_shrink: float = 60.0
    xg_weight: float = 0.0  # 0 = fit to goals; w > 0 fits to (1 - w) * goals + w * xG where the matches carry xg_home / xg_away
    total_compression: float = 1.0  # < 1 pulls each match's expected total goals toward the league's typical total (ratio kept)
    dispersion: float = 0.0  # 0 = Poisson goals; alpha > 0 gives variance lam + alpha * lam^2 (negative binomial), same mean
    # fitted state
    teams: list[str] = field(default_factory=list)
    mu: float = 0.0
    home_adv: float = 0.0
    rho: float = 0.0
    attack: dict[str, float] = field(default_factory=dict)
    defence: dict[str, float] = field(default_factory=dict)
    as_of: date | None = None
    n_matches: int = 0
    level_shift: float = 0.0
    ref_log_total: float = 0.0
    default_attack: float = 0.0    # rating of a club never seen in training (0 = the league average for a single-league fit)
    default_defence: float = 0.0

    def fit(self, matches: pd.DataFrame, as_of: date) -> "DixonColes":
        """matches: columns match_date, home, away, ft_home, ft_away (and optionally xg_home, xg_away). Uses only rows dated before as_of."""
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
        hg_t, ag_t = hg, ag
        if self.xg_weight > 0 and {"xg_home", "xg_away"} <= set(m.columns):
            xh, xa = m["xg_home"].to_numpy(dtype=float), m["xg_away"].to_numpy(dtype=float)
            have = ~(np.isnan(xh) | np.isnan(xa))
            hg_t = np.where(have, (1 - self.xg_weight) * hg + self.xg_weight * np.nan_to_num(xh), hg)
            ag_t = np.where(have, (1 - self.xg_weight) * ag + self.xg_weight * np.nan_to_num(xa), ag)
        age = np.array([(as_of - d).days for d in m["match_date"]], dtype=float)
        w = 0.5 ** (age / self.half_life_days)

        theta0 = np.zeros(3 + 2 * n)
        theta0[0] = np.log((hg_t @ w + ag_t @ w) / (2 * w.sum()))
        bounds = [(None, None), (None, None), (-RHO_BOUND, RHO_BOUND)] + [(None, None)] * (2 * n)
        res = minimize(neg_log_likelihood, theta0, args=(hi, ai, hg, ag, w, n, self.ridge, hg_t, ag_t),
                       jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
        if not res.success and res.status != 1:  # status 1 = iteration limit, still usable
            raise RuntimeError(f"Dixon-Coles fit failed: {res.message}")
        self.mu, self.home_adv, self.rho = float(res.x[0]), float(res.x[1]), float(res.x[2])
        self.attack = dict(zip(self.teams, res.x[3:3 + n].tolist(), strict=True))
        self.defence = dict(zip(self.teams, res.x[3 + n:].tolist(), strict=True))
        self.level_shift = self.level_adjustment(m, self.level_window_days, self.level_shrink)
        self.mu += self.level_shift
        eta_h = self.mu + self.home_adv + res.x[3:3 + n][hi] - res.x[3 + n:][ai]
        eta_a = self.mu + res.x[3:3 + n][ai] - res.x[3 + n:][hi]
        self.ref_log_total = float(np.log(np.exp(eta_h) + np.exp(eta_a)) @ w / w.sum())
        return self

    def level_adjustment(self, matches: pd.DataFrame, window_days: float, shrink: float) -> float:
        """Log-ratio of goals actually scored to goals the fitted model expected, over the last `window_days` before as_of.

        Team strength changes slowly (long half-life) but the league's scoring level can move within a season, so
        this follows it faster. The ratio is shrunk toward 1 by n / (n + shrink) so a short run of matches cannot swing it.
        """
        if self.as_of is None or window_days <= 0:
            return 0.0
        m = matches[(matches["match_date"] < self.as_of) & (matches["match_date"] >= self.as_of - timedelta(days=window_days))]
        m = m[m["home"].isin(self.attack) & m["away"].isin(self.attack)]
        if m.empty:
            return 0.0
        saved, self.total_compression = self.total_compression, 1.0
        try:
            expected = sum(sum(self.lambdas(r.home, r.away)) for r in m.itertuples(index=False))
        finally:
            self.total_compression = saved
        actual = float((m["ft_home"] + m["ft_away"]).sum())
        n = len(m)
        return float(np.log(actual / expected) * n / (n + shrink))

    def lambdas(self, home: str, away: str) -> tuple[float, float]:
        """Expected goals. A team never seen in training gets the league-average rating (0, 0)."""
        a_h, d_h = self.attack.get(home, self.default_attack), self.defence.get(home, self.default_defence)
        a_a, d_a = self.attack.get(away, self.default_attack), self.defence.get(away, self.default_defence)
        lam_h, lam_a = float(np.exp(self.mu + self.home_adv + a_h - d_a)), float(np.exp(self.mu + a_a - d_h))
        if self.total_compression != 1.0:
            k = float(np.exp((self.total_compression - 1.0) * (np.log(lam_h + lam_a) - self.ref_log_total)))
            lam_h, lam_a = lam_h * k, lam_a * k
        return lam_h, lam_a

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        """P[i, j] = probability the match ends home i - away j, i, j in 0..max_goals. Sums to 1."""
        return self.matrix_from_lambdas(*self.lambdas(home, away))

    def matrix_from_lambdas(self, lam_h: float, lam_a: float) -> np.ndarray:
        """Scoreline matrix for given expected goals (so adjusted lambdas can be priced the same way)."""
        g = np.arange(self.max_goals + 1)
        p = np.outer(self._pmf(g, lam_h), self._pmf(g, lam_a))
        p[0, 0] *= 1 - lam_h * lam_a * self.rho
        p[0, 1] *= 1 + lam_h * self.rho
        p[1, 0] *= 1 + lam_a * self.rho
        p[1, 1] *= 1 - self.rho
        return p / p.sum()

    def _pmf(self, g: np.ndarray, lam: float) -> np.ndarray:
        if self.dispersion <= 0:
            return poisson.pmf(g, lam)
        r = 1.0 / self.dispersion
        return nbinom.pmf(g, r, r / (r + lam))

    def known(self, team: str) -> bool:
        return team in self.attack
