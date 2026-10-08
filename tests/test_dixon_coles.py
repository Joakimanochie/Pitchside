import datetime as dt

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import approx_fprime

from pitchside.models.dixon_coles import DixonColes, neg_log_likelihood


def simulate(n_teams=12, seasons=3, seed=0, adv=0.25, mu=0.15):
    """Double round-robin seasons from known attack/defence strengths (independent Poisson goals)."""
    rng = np.random.default_rng(seed)
    att = rng.normal(0, 0.3, n_teams)
    dfn = rng.normal(0, 0.25, n_teams)
    att -= att.mean()
    dfn -= dfn.mean()
    rows, day = [], dt.date(2018, 8, 1)
    for s in range(seasons):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                lam_h, lam_a = np.exp(mu + adv + att[i] - dfn[j]), np.exp(mu + att[j] - dfn[i])
                rows.append((day + dt.timedelta(days=int(rng.integers(0, 280)) + 365 * s), f"T{i}", f"T{j}",
                             int(rng.poisson(lam_h)), int(rng.poisson(lam_a))))
    df = pd.DataFrame(rows, columns=["match_date", "home", "away", "ft_home", "ft_away"])
    return df.sort_values("match_date").reset_index(drop=True), att, dfn


def arrays(df, teams):
    idx = {t: i for i, t in enumerate(teams)}
    return (df["home"].map(idx).to_numpy(), df["away"].map(idx).to_numpy(),
            df["ft_home"].to_numpy(float), df["ft_away"].to_numpy(float))


def test_gradient_matches_numerical_gradient():
    df, _, _ = simulate(n_teams=6, seasons=1)
    teams = sorted(set(df["home"]))
    hi, ai, hg, ag = arrays(df, teams)
    w = np.linspace(0.3, 1.0, len(df))
    rng = np.random.default_rng(1)
    theta = np.concatenate([[0.1, 0.2, -0.1], rng.normal(0, 0.2, 2 * len(teams))])
    args = (hi, ai, hg, ag, w, len(teams), 1.5)
    _, analytic = neg_log_likelihood(theta, *args)
    numeric = approx_fprime(theta, lambda t: neg_log_likelihood(t, *args)[0], 1e-6)
    np.testing.assert_allclose(analytic, numeric, rtol=1e-4, atol=1e-4)


def test_recovers_known_team_strengths():
    df, att, dfn = simulate(n_teams=14, seasons=6, seed=3)
    model = DixonColes(half_life_days=10_000, ridge=0.5).fit(df, as_of=dt.date(2030, 1, 1))
    fit_att = np.array([model.attack[f"T{i}"] for i in range(14)])
    fit_dfn = np.array([model.defence[f"T{i}"] for i in range(14)])
    fit_att, fit_dfn = fit_att - fit_att.mean(), fit_dfn - fit_dfn.mean()
    assert np.corrcoef(fit_att, att)[0, 1] > 0.9
    assert np.corrcoef(fit_dfn, dfn)[0, 1] > 0.85
    assert model.home_adv == pytest.approx(0.25, abs=0.08)


def test_score_matrix_is_a_probability_distribution():
    df, _, _ = simulate()
    model = DixonColes().fit(df, as_of=dt.date(2030, 1, 1))
    p = model.score_matrix("T0", "T1")
    assert p.shape == (11, 11)
    assert p.sum() == pytest.approx(1.0)
    assert (p >= 0).all()


def test_unknown_team_gets_league_average_not_an_error():
    df, _, _ = simulate()
    model = DixonColes().fit(df, as_of=dt.date(2030, 1, 1))
    assert not model.known("Newly Promoted FC")
    p = model.score_matrix("Newly Promoted FC", "T1")
    assert p.sum() == pytest.approx(1.0)


def test_no_leakage_results_after_as_of_are_ignored():
    df, _, _ = simulate(seasons=3)
    cutoff = dt.date(2019, 12, 1)
    base = DixonColes().fit(df, as_of=cutoff).score_matrix("T0", "T1")
    tampered = df.copy()
    future = tampered["match_date"] >= cutoff
    tampered.loc[future, "ft_home"] = 9  # wildly different future results
    tampered.loc[future, "ft_away"] = 0
    again = DixonColes().fit(tampered, as_of=cutoff).score_matrix("T0", "T1")
    np.testing.assert_array_equal(base, again)


def test_recent_matches_weigh_more_with_short_half_life():
    # T0 was terrible long ago and excellent recently; a short half-life must rate it higher than a long one.
    df, _, _ = simulate(seasons=4, seed=5)
    asof = dt.date(2022, 6, 1)
    old = df["match_date"] < dt.date(2020, 6, 1)
    df = df.copy()
    df.loc[old & (df["home"] == "T0"), "ft_home"] = 0
    df.loc[old & (df["away"] == "T0"), "ft_away"] = 0
    short = DixonColes(half_life_days=120).fit(df, as_of=asof)
    long = DixonColes(half_life_days=3000).fit(df, as_of=asof)
    assert short.attack["T0"] > long.attack["T0"]


def test_needs_enough_history():
    df, _, _ = simulate(n_teams=6, seasons=1)
    with pytest.raises(ValueError, match="at least 50"):
        DixonColes().fit(df, as_of=dt.date(2018, 8, 2))
