"""Dixon-Coles fitted across several leagues at once, so a club that changes league keeps its rating.

The single-league model rates a club only on matches in that league. A club just relegated from the Premier League is then judged on a handful of
Championship games, and a promoted club on a handful of Premier League games, while years of evidence from the other league are ignored.

Here every club has ONE attack and ONE defence rating shared across leagues, fitted on all the leagues' matches together (same time decay as before).
What differs between leagues is only the typical rating of the clubs in it, which is how a promoted or relegated club's old form carries over:

    log lambda_home = mu[league] + home_adv + attack[home] - defence[away]
    log lambda_away = mu[league] +            attack[away] - defence[home]
    ridge pulls each club toward the average rating of ITS league (the league it played in most recently), not toward zero;
    those league averages are free parameters, except the target league's, which is fixed at 0 (only differences between leagues mean anything).

`target_league` is the league being predicted: it picks mu and the goal level used by the level adjustment and the total compression.
The rest (scoreline matrix, simulator, pricing) is the ordinary DixonColes machinery.
"""
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from pitchside.models.dixon_coles import RHO_BOUND, DixonColes, _tau


def neg_log_likelihood_pyramid(theta, hi, ai, li, hg, ag, w, n_teams, n_comps, team_league, ridge, n_groups=None):
    """Penalised negative weighted log-likelihood and exact gradient.

    theta = [adv, rho, mu(C), attack(n), defence(n), mean_attack(G-1), mean_defence(G-1)] for C competitions (each match carries one, `li`) and G groups of clubs
    (`team_league` gives each club's group); group 0's mean ratings are fixed at 0. G defaults to C (a league is its own group)."""
    n_leagues = n_comps if n_groups is None else n_groups
    adv, rho = theta[0], theta[1]
    mu = theta[2:2 + n_comps]
    o = 2 + n_comps
    att, dfn = theta[o:o + n_teams], theta[o + n_teams:o + 2 * n_teams]
    ma = np.concatenate([[0.0], theta[o + 2 * n_teams:o + 2 * n_teams + n_leagues - 1]])
    md = np.concatenate([[0.0], theta[o + 2 * n_teams + n_leagues - 1:]])

    eta_h = mu[li] + adv + att[hi] - dfn[ai]
    eta_a = mu[li] + att[ai] - dfn[hi]
    lam_h, lam_a = np.exp(eta_h), np.exp(eta_a)
    tau, (m00, m01, m10, m11) = _tau(hg, ag, lam_h, lam_a, rho)
    ll = w * (hg * eta_h - lam_h + ag * eta_a - lam_a + np.log(tau))

    dh = np.where(m00, -lam_a * rho / tau, 0.0) + np.where(m01, rho / tau, 0.0)
    da = np.where(m00, -lam_h * rho / tau, 0.0) + np.where(m10, rho / tau, 0.0)
    dr = (np.where(m00, -lam_h * lam_a / tau, 0.0) + np.where(m01, lam_h / tau, 0.0)
          + np.where(m10, lam_a / tau, 0.0) + np.where(m11, -1.0 / tau, 0.0))
    g_h = w * (hg - lam_h + lam_h * dh)
    g_a = w * (ag - lam_a + lam_a * da)

    dev_a, dev_d = att - ma[team_league], dfn - md[team_league]
    penalty = ridge * (dev_a @ dev_a + dev_d @ dev_d)

    grad = np.zeros_like(theta)
    grad[0] = g_h.sum()
    grad[1] = (w * dr).sum()
    grad[2:2 + n_comps] = np.bincount(li, g_h + g_a, n_comps)
    grad[o:o + n_teams] = np.bincount(hi, g_h, n_teams) + np.bincount(ai, g_a, n_teams)
    grad[o + n_teams:o + 2 * n_teams] = -np.bincount(ai, g_h, n_teams) - np.bincount(hi, g_a, n_teams)
    grad = -grad
    grad[o:o + n_teams] += 2 * ridge * dev_a
    grad[o + n_teams:o + 2 * n_teams] += 2 * ridge * dev_d
    grad[o + 2 * n_teams:o + 2 * n_teams + n_leagues - 1] = -2 * ridge * np.bincount(team_league, dev_a, n_leagues)[1:]
    grad[o + 2 * n_teams + n_leagues - 1:] = -2 * ridge * np.bincount(team_league, dev_d, n_leagues)[1:]
    return -ll.sum() + penalty, grad


@dataclass
class PyramidDixonColes(DixonColes):
    """matches needs a `league` column. Predicts for `target_league`; every other league only informs the ratings."""
    target_league: str = ""
    leagues: list[str] = field(default_factory=list)
    league_mean_attack: dict[str, float] = field(default_factory=dict)
    league_mean_defence: dict[str, float] = field(default_factory=dict)
    team_group: dict[str, str] | None = None     # club -> its domestic league (the group its ridge pulls toward); None: the league it played in most recently
    ref_group: str = ""                          # the group whose mean rating is fixed at 0 (default: the target league)

    def fit(self, matches: pd.DataFrame, as_of: date) -> "PyramidDixonColes":
        m = matches[matches["match_date"] < as_of]
        if len(m) < 50:
            raise ValueError(f"need at least 50 matches before {as_of}, got {len(m)}")
        self.as_of, self.n_matches = as_of, len(m)
        self.teams = sorted(set(m["home"]) | set(m["away"]))
        comps = sorted(set(m["league"]), key=lambda x: (x != self.target_league, x))      # competitions, each with its own goal level mu
        cidx = {c: i for i, c in enumerate(comps)}
        tidx = {t: i for i, t in enumerate(self.teams)}
        n, k = len(self.teams), len(comps)
        hi, ai = m["home"].map(tidx).to_numpy(), m["away"].map(tidx).to_numpy()
        li = m["league"].map(cidx).to_numpy()
        hg, ag = m["ft_home"].to_numpy(dtype=float), m["ft_away"].to_numpy(dtype=float)
        age = np.array([(as_of - d).days for d in m["match_date"]], dtype=float)
        w = 0.5 ** (age / self.half_life_days)

        if self.team_group is None:       # a club belongs to the league it played in most recently
            latest: dict[str, str] = {}
            for r in m.sort_values("match_date", kind="stable").itertuples(index=False):
                latest[r.home] = r.league
                latest[r.away] = r.league
            group_of = latest
            ref = self.target_league
        else:
            group_of = {t: self.team_group.get(t, "OTHER") for t in self.teams}
            ref = self.ref_group or self.target_league
        self.leagues = sorted(set(group_of.values()) | {ref}, key=lambda x: (x != ref, x))       # group 0 = the reference group
        gidx = {g: i for i, g in enumerate(self.leagues)}
        g_n = len(self.leagues)
        team_league = np.array([gidx[group_of[t]] for t in self.teams])

        theta0 = np.zeros(2 + k + 2 * n + 2 * (g_n - 1))
        theta0[2:2 + k] = np.log((hg @ w + ag @ w) / (2 * w.sum()))
        bounds = [(None, None), (-RHO_BOUND, RHO_BOUND)] + [(None, None)] * (k + 2 * n + 2 * (g_n - 1))
        res = minimize(neg_log_likelihood_pyramid, theta0, args=(hi, ai, li, hg, ag, w, n, k, team_league, self.ridge, g_n),
                       jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 800})
        if not res.success and res.status != 1:
            raise RuntimeError(f"pyramid fit failed: {res.message}")
        x = res.x
        o = 2 + k
        self.home_adv, self.rho = float(x[0]), float(x[1])
        att, dfn = x[o:o + n], x[o + n:o + 2 * n]
        self.attack, self.defence = dict(zip(self.teams, att.tolist(), strict=True)), dict(zip(self.teams, dfn.tolist(), strict=True))
        ma = np.concatenate([[0.0], x[o + 2 * n:o + 2 * n + g_n - 1]])
        md = np.concatenate([[0.0], x[o + 2 * n + g_n - 1:]])
        self.league_mean_attack = dict(zip(self.leagues, ma.tolist(), strict=True))
        self.league_mean_defence = dict(zip(self.leagues, md.tolist(), strict=True))
        self.mu = float(x[2 + cidx[self.target_league]])
        # a club never seen is rated at the average of the group it would join: "OTHER" (clubs without domestic data) when groups are given, else 0
        if self.team_group is not None and "OTHER" in gidx:
            self.default_attack, self.default_defence = float(ma[gidx["OTHER"]]), float(md[gidx["OTHER"]])

        own = m[m["league"] == self.target_league]
        self.level_shift = self.level_adjustment(own, self.level_window_days, self.level_shrink)
        self.mu += self.level_shift
        sel = li == cidx[self.target_league]
        eta_h = self.mu + self.home_adv + att[hi[sel]] - dfn[ai[sel]]
        eta_a = self.mu + att[ai[sel]] - dfn[hi[sel]]
        self.ref_log_total = float(np.log(np.exp(eta_h) + np.exp(eta_a)) @ w[sel] / w[sel].sum())
        return self
