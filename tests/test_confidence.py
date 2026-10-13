import numpy as np
import pandas as pd
import pytest

from pitchside.confidence import MIN_CELL, band_of, fit_rules, tier_for, tier_from_stats


def synthetic(n=6000, seed=0):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.05, 0.95, n)
    informative = pd.DataFrame({"market_id": "m_info", "family": "A", "line": np.nan, "selection": "yes", "p": p, "y": (rng.random(n) < p).astype(float)})
    flat = pd.DataFrame({"market_id": "m_flat", "family": "A", "line": np.nan, "selection": "yes", "p": 0.5, "y": (rng.random(n) < 0.5).astype(float)})
    overconfident = pd.DataFrame({"market_id": "m_over", "family": "B", "line": np.nan, "selection": "yes", "p": p, "y": (rng.random(n) < 0.5).astype(float)})
    return pd.concat([informative, flat, overconfident], ignore_index=True)


def test_bands_cover_zero_to_one():
    assert band_of(0.0) == 0 and band_of(0.099) == 0 and band_of(0.10) == 1
    assert band_of(0.999) == band_of(1.0) == 6


def test_thresholds_need_sample_skill_and_calibration():
    assert tier_from_stats(MIN_CELL - 1, 0.5, 0.0) == "Low"
    assert tier_from_stats(MIN_CELL, 0.06, 0.02) == "High"
    assert tier_from_stats(MIN_CELL, 0.06, 0.04) == "Medium"   # skilled but a little miscalibrated
    assert tier_from_stats(MIN_CELL, 0.02, 0.01) == "Medium"
    assert tier_from_stats(MIN_CELL, 0.005, 0.0) == "Low"
    assert tier_from_stats(MIN_CELL, 0.06, 0.05, se=0.03) == "High"   # a gap inside the cell's own sampling noise is not held against it


def test_a_market_that_is_informative_and_calibrated_reaches_high_far_from_the_base_rate():
    rules = fit_rules(synthetic())
    assert tier_for(rules, "m_info", "A", 0.88) == "High"
    assert tier_for(rules, "m_info", "A", 0.12) == "High"


def test_a_market_that_only_repeats_the_base_rate_is_low():
    assert tier_for(fit_rules(synthetic()), "m_flat", "A", 0.5) == "Low"


def test_overconfident_probabilities_are_never_high():
    rules = fit_rules(synthetic())
    assert all(tier_for(rules, "m_over", "B", p) == "Low" for p in (0.1, 0.3, 0.5, 0.7, 0.9))


def test_unknown_market_falls_back_to_its_family_then_to_low():
    rules = fit_rules(synthetic())
    assert tier_for(rules, "never_seen", "B", 0.5) == "Low"
    assert tier_for(rules, "never_seen", "ZZ", 0.5) == "Low"


def test_rules_serialise_to_json():
    import json
    json.dumps(fit_rules(synthetic()))
    assert pytest.approx(1.0) == fit_rules(synthetic())["thresholds"]["band_edges"][-1]
