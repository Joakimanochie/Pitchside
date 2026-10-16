"""Dixon-Coles with a rating per club per league, and a prior that carries a club's rating to its next league with a discount.

The single-league model forgets a club's history when it changes league; `pyramid.py` (one rating for a club everywhere) remembers all of it and
rated promoted clubs too highly. This model sits between them. A club has a separate attack and defence rating for each league it has played in
(a "stint"), and its rating in a new league is *pulled toward* what it was in the previous one, not forced to equal it:

    first stint of a club                    attack ~ N(0, 1 / (2 ridge))                         (as in the single-league model)
    a later stint, previous stint in league P  attack ~ N(carry * attack_previous + gap[P -> L], 1 / (2 ridge))

`carry` (between 0 and 1) is how much of a club's standing carries over, chosen on past matches; `gap[P -> L]` is fitted: the typical change in rating
for a club going from league P to league L (a relegated club is usually near the bottom of the old league and near the top of the new one; a promoted
club the reverse). Attack and defence each have their own gap. With carry = 0 and no gap this is the single-league model.
A club with no matches yet in the target league (just promoted or relegated) is rated at its prior mean: carry * previous rating + gap.

Everything else (home advantage, the low-score correction, time decay, the level adjustment, scoreline matrices) is the ordinary DixonColes.
"""
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from pitchside.models.dixon_coles import RHO_BOUND, DixonColes, _tau


def neg_log_likelihood_stints(theta, hi, ai, li, hg, ag, w, n_stints, n_leagues, prev, pair, n_pairs, carry, ridge):
    """theta = [adv, rho, mu(K), attack(S), defence(S), gap_attack(P), gap_defence(P)]; hi/ai index stints. prev[s] is the previous stint (-1 if none), pair[s] its gap index."""
    adv, rho = theta[0], theta[1]
    mu = theta[2:2 + n_leagues]
    o = 2 + n_leagues
    att, dfn = theta[o:o + n_stints], theta[o + n_stints:o + 2 * n_stints]
    ga, gd = theta[o + 2 * n_stints:o + 2 * n_stints + n_pairs], theta[o + 2 * n_stints + n_pairs:]

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

    has = prev >= 0
    p, q = prev[has], pair[has]
    mean_a = np.zeros(n_stints)
    mean_d = np.zeros(n_stints)
    mean_a[has] = carry * att[p] + ga[q]
    mean_d[has] = carry * dfn[p] + gd[q]
    ra, rd = att - mean_a, dfn - mean_d
    penalty = ridge * (ra @ ra + rd @ rd)

    grad = np.zeros_like(theta)
    grad[0] = g_h.sum()
    grad[1] = (w * dr).sum()
    grad[2:2 + n_leagues] = np.bincount(li, g_h + g_a, n_leagues)
    grad[o:o + n_stints] = np.bincount(hi, g_h, n_stints) + np.bincount(ai, g_a, n_stints)
    grad[o + n_stints:o + 2 * n_stints] = -np.bincount(ai, g_h, n_stints) - np.bincount(hi, g_a, n_stints)
    grad = -grad
    grad[o:o + n_stints] += 2 * ridge * ra
    grad[o + n_stints:o + 2 * n_stints] += 2 * ridge * rd
    grad[o:o + n_stints] -= 2 * ridge * carry * np.bincount(p, ra[has], n_stints)
    grad[o + n_stints:o + 2 * n_stints] -= 2 * ridge * carry * np.bincount(p, rd[has], n_stints)
    grad[o + 2 * n_stints:o + 2 * n_stints + n_pairs] = -2 * ridge * np.bincount(q, ra[has], n_pairs)
    grad[o + 2 * n_stints + n_pairs:] = -2 * ridge * np.bincount(q, rd[has], n_pairs)
    return -ll.sum() + penalty, grad


@dataclass
class StintDixonColes(DixonColes):
    """matches needs a `league` column. Predicts for `target_league`; other leagues only inform clubs' ratings through the carry."""
    target_league: str = ""
    carry: float = 0.5
    gaps: dict[str, tuple[float, float]] = field(default_factory=dict)      # "FROM>TO" -> (attack gap, defence gap)

    def fit(self, matches: pd.DataFrame, as_of: date) -> "StintDixonColes":
        m = matches[matches["match_date"] < as_of]
        if len(m) < 50:
            raise ValueError(f"need at least 50 matches before {as_of}, got {len(m)}")
        self.as_of, self.n_matches = as_of, len(m)
        leagues = sorted(set(m["league"]))
        lidx = {lg: i for i, lg in enumerate(leagues)}
        k = len(leagues)

        # stints: one per (club, league), ordered in time per club by the first match played in that league
        first: dict[tuple[str, str], object] = {}
        for r in m.sort_values("match_date", kind="stable").itertuples(index=False):
            for t in (r.home, r.away):
                first.setdefault((t, r.league), r.match_date)
        stints = sorted(first, key=lambda s: (s[0], first[s]))
        sidx = {s: i for i, s in enumerate(stints)}
        n_s = len(stints)
        prev = np.full(n_s, -1)
        pair_of: dict[tuple[str, str], int] = {}
        pair = np.zeros(n_s, dtype=int)
        last_for_team: dict[str, tuple[str, str]] = {}
        for s in stints:
            if s[0] in last_for_team:
                p = last_for_team[s[0]]
                prev[sidx[s]] = sidx[p]
                pair[sidx[s]] = pair_of.setdefault((p[1], s[1]), len(pair_of))
            last_for_team[s[0]] = s
        n_p = max(len(pair_of), 1)

        hi = np.array([sidx[(t, lg)] for t, lg in zip(m["home"], m["league"], strict=True)])
        ai = np.array([sidx[(t, lg)] for t, lg in zip(m["away"], m["league"], strict=True)])
        li = m["league"].map(lidx).to_numpy()
        hg, ag = m["ft_home"].to_numpy(dtype=float), m["ft_away"].to_numpy(dtype=float)
        age = np.array([(as_of - d).days for d in m["match_date"]], dtype=float)
        w = 0.5 ** (age / self.half_life_days)

        theta0 = np.zeros(2 + k + 2 * n_s + 2 * n_p)
        theta0[2:2 + k] = np.log((hg @ w + ag @ w) / (2 * w.sum()))
        bounds = [(None, None), (-RHO_BOUND, RHO_BOUND)] + [(None, None)] * (k + 2 * n_s + 2 * n_p)
        res = minimize(neg_log_likelihood_stints, theta0, args=(hi, ai, li, hg, ag, w, n_s, k, prev, pair, n_p, self.carry, self.ridge),
                       jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 800})
        if not res.success and res.status != 1:
            raise RuntimeError(f"stint fit failed: {res.message}")
        x = res.x
        o = 2 + k
        self.home_adv, self.rho = float(x[0]), float(x[1])
        att, dfn = x[o:o + n_s], x[o + n_s:o + 2 * n_s]
        ga, gd = x[o + 2 * n_s:o + 2 * n_s + n_p], x[o + 2 * n_s + n_p:]
        self.gaps = {f"{a}>{b}": (float(ga[i]), float(gd[i])) for (a, b), i in pair_of.items()}
        self.mu = float(x[2 + lidx[self.target_league]])

        # ratings used for the target league: the club's stint there, or (no matches yet in it) its prior mean from the latest stint elsewhere
        self.teams, self.attack, self.defence = [], {}, {}
        for team, latest in last_for_team.items():
            if (team, self.target_league) in sidx:
                s = sidx[(team, self.target_league)]
                self.attack[team], self.defence[team] = float(att[s]), float(dfn[s])
            else:
                p = sidx[latest]
                g = self.gaps.get(f"{latest[1]}>{self.target_league}")
                if g is None:               # no club has made this move before: the average gap over all moves into the target league, else none
                    into = [v for key, v in self.gaps.items() if key.endswith(f">{self.target_league}")]
                    g = tuple(np.mean(into, axis=0)) if into else (0.0, 0.0)
                self.attack[team], self.defence[team] = float(self.carry * att[p] + g[0]), float(self.carry * dfn[p] + g[1])
            self.teams.append(team)

        own = m[m["league"] == self.target_league]
        self.level_shift = self.level_adjustment(own, self.level_window_days, self.level_shrink)
        self.mu += self.level_shift
        sel = li == lidx[self.target_league]
        eta_h = self.mu + self.home_adv + att[hi[sel]] - dfn[ai[sel]]
        eta_a = self.mu + att[ai[sel]] - dfn[hi[sel]]
        self.ref_log_total = float(np.log(np.exp(eta_h) + np.exp(eta_a)) @ w[sel] / w[sel].sum())
        return self
