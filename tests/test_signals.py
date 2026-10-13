import datetime as dt

import numpy as np
import pytest

from pitchside.models.dixon_coles import DixonColes
from pitchside.models.signals import adjusted_lambdas, head_to_head, recent_form
from tests.test_dixon_coles import simulate

CUTOFF = dt.date(2020, 3, 1)


@pytest.fixture(scope="module")
def fitted():
    df, _, _ = simulate(seasons=3)
    return df, DixonColes().fit(df, as_of=CUTOFF)


def test_form_and_h2h_ignore_matches_on_or_after_as_of(fitted):
    df, model = fitted
    tampered = df.copy()
    tampered.loc[tampered["match_date"] >= CUTOFF, ["ft_home", "ft_away"]] = [9, 0]
    assert recent_form(model, df, 6, 5) == recent_form(model, tampered, 6, 5)
    assert head_to_head(model, df, 5, 5) == head_to_head(model, tampered, 5, 5)


def test_a_team_scoring_more_than_expected_is_in_form(fitted):
    df, model = fitted
    hot = df.copy()
    recent = (hot["match_date"] < CUTOFF) & (hot["match_date"] >= CUTOFF - dt.timedelta(days=60))
    hot.loc[recent & (hot["home"] == "T0"), "ft_home"] += 3
    hot.loc[recent & (hot["away"] == "T0"), "ft_away"] += 3
    assert recent_form(model, hot, 6, 2)["T0"][0] > recent_form(model, df, 6, 2)["T0"][0]


def test_heavier_shrinkage_moves_predictions_less(fitted):
    df, model = fitted
    base = np.array(model.lambdas("T0", "T1"))
    light = np.array(adjusted_lambdas(model, "T0", "T1", recent_form(model, df, 8, 2)))
    heavy = np.array(adjusted_lambdas(model, "T0", "T1", recent_form(model, df, 8, 200)))
    assert np.abs(np.log(heavy / base)).max() <= np.abs(np.log(light / base)).max()


def test_no_signals_means_unchanged_lambdas(fitted):
    _, model = fitted
    assert adjusted_lambdas(model, "T0", "T1") == model.lambdas("T0", "T1")
