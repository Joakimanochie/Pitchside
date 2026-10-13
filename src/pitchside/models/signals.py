"""Extra signals layered on a fitted Dixon-Coles model: recent form and head-to-head.

Both are residuals. The fitted model has a long memory (half-life two years), so for any past match we can ask
how many goals it expected and compare that with what happened. A team that has been scoring more than the model
expected lately is "in form"; two sides whose meetings keep producing more goals for one of them than the model
expected carry a head-to-head tilt. Each residual is a log ratio shrunk toward zero by m / (m + shrink), where m is
the number of matches behind it, so a few results cannot move a prediction much.

Only matches strictly before the model's `as_of` are read.
"""
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd

from pitchside.models.dixon_coles import DixonColes

PSEUDO_GOALS = 0.5  # keeps the log ratio finite when a side scored nothing in the window


def _expected(model: DixonColes, hist: pd.DataFrame) -> pd.DataFrame:
    """Goals the fitted model expected for every match in hist whose teams it knows."""
    hist = hist[hist["home"].isin(model.attack) & hist["away"].isin(model.attack)]
    a = model.attack
    d = model.defence
    ah = hist["home"].map(a).to_numpy()
    dh = hist["home"].map(d).to_numpy()
    aa = hist["away"].map(a).to_numpy()
    da = hist["away"].map(d).to_numpy()
    out = hist[["match_date", "home", "away", "ft_home", "ft_away"]].copy()
    out["exp_home"] = np.exp(model.mu + model.home_adv + ah - da)
    out["exp_away"] = np.exp(model.mu + aa - dh)
    return out


def _log_ratio(actual: float, expected: float, m: int, shrink: float) -> float:
    return float(np.log((actual + PSEUDO_GOALS) / (expected + PSEUDO_GOALS)) * m / (m + shrink))


def recent_form(model: DixonColes, matches: pd.DataFrame, n_matches: int, shrink: float) -> dict[str, tuple[float, float]]:
    """team -> (attack residual, defence residual) over its last `n_matches`.

    Attack residual > 0: scored more than expected. Defence residual > 0: conceded more than expected.
    """
    hist = _expected(model, matches[matches["match_date"] < model.as_of])
    rows: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)  # (date ordinal, gf, ef, ga, ea) per team
    for r in hist.sort_values("match_date").itertuples(index=False):
        rows[r.home].append((r.ft_home, r.exp_home, r.ft_away, r.exp_away))
        rows[r.away].append((r.ft_away, r.exp_away, r.ft_home, r.exp_home))
    out = {}
    for team, games in rows.items():
        last = np.array(games[-n_matches:], dtype=float)
        m = len(last)
        out[team] = (_log_ratio(last[:, 0].sum(), last[:, 1].sum(), m, shrink), _log_ratio(last[:, 2].sum(), last[:, 3].sum(), m, shrink))
    return out


def head_to_head(model: DixonColes, matches: pd.DataFrame, years: float, shrink: float) -> dict[tuple[str, str], tuple[float, float]]:
    """(team, opponent) -> (residual for team's goals, residual for opponent's goals) over their meetings in the last `years`."""
    start = model.as_of - timedelta(days=int(365 * years))
    hist = _expected(model, matches[(matches["match_date"] < model.as_of) & (matches["match_date"] >= start)])
    acc: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])  # goals team, exp team, goals opp, exp opp, n
    for r in hist.itertuples(index=False):
        for team, opp, g_t, e_t, g_o, e_o in ((r.home, r.away, r.ft_home, r.exp_home, r.ft_away, r.exp_away),
                                              (r.away, r.home, r.ft_away, r.exp_away, r.ft_home, r.exp_home)):
            a = acc[(team, opp)]
            a[0] += g_t
            a[1] += e_t
            a[2] += g_o
            a[3] += e_o
            a[4] += 1
    return {k: (_log_ratio(v[0], v[1], int(v[4]), shrink), _log_ratio(v[2], v[3], int(v[4]), shrink)) for k, v in acc.items()}


def adjusted_lambdas(model: DixonColes, home: str, away: str, form: dict | None = None, h2h: dict | None = None,
                     form_weight: float = 1.0, h2h_weight: float = 1.0) -> tuple[float, float]:
    """The model's expected goals, tilted by recent form and head-to-head where those are supplied."""
    lam_h, lam_a = model.lambdas(home, away)
    shift_h = shift_a = 0.0
    if form is not None:
        fh, fa = form.get(home, (0.0, 0.0)), form.get(away, (0.0, 0.0))
        shift_h += form_weight * (fh[0] + fa[1])   # home attack in form, away defence leaking
        shift_a += form_weight * (fa[0] + fh[1])
    if h2h is not None:
        r = h2h.get((home, away))
        if r is not None:
            shift_h += h2h_weight * r[0]
            shift_a += h2h_weight * r[1]
    return lam_h * float(np.exp(shift_h)), lam_a * float(np.exp(shift_a))
