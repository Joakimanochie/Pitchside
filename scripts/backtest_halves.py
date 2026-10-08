"""Does the first-half / second-half split model fit real half-time scores?

p1 (share of goals scored before half-time) is estimated on seasons <= 2021 only and frozen; the goals model is
refit weekly on past matches only. Evaluated on 2022/23 onwards against league base rates.
Usage: uv run python scripts/backtest_halves.py [LEAGUE ...]
"""
import sys

import numpy as np

from pitchside.ingest.footballdata import load_seasons
from pitchside.leagues import LEAGUES
from pitchside.models.backtest import iter_matrices
from pitchside.models.evaluate import log_loss
from pitchside.models.halves import (
    estimate_p1,
    half_time_matrix,
    ht_ft_probabilities,
    second_half_matrix,
)

HALF_LIFE_DAYS, RIDGE = 730, 2.0
TRAIN_END, TEST_SEASONS = 2021, [2022, 2023, 2024, 2025, 2026]


def result_idx(h, a):
    return 0 if h > a else 1 if h == a else 2


def outcome_probs(q):
    return [np.tril(q, -1).sum(), np.trace(q), np.triu(q, 1).sum()]


def binary_ll(p, y):
    p = np.clip(np.asarray(p), 1e-12, 1 - 1e-12)
    y = np.asarray(y)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def run(league_id: str) -> dict:
    lg = LEAGUES[league_id]
    m = load_seasons(lg.fd_code, list(range(2015, 2027)))
    m = m[m["ht_home"].notna() & m["ht_away"].notna()].copy()
    train = m[m["season"] <= TRAIN_END]
    p1 = estimate_p1(train.ht_home.sum() + train.ht_away.sum(), train.ft_home.sum() + train.ft_away.sum())

    # base rates from the training seasons (expanding within the test period would be tidier; this is conservative)
    def freq(df, f):
        return np.array([f(df)(k) for k in range(3)], dtype=float)
    ht_base = np.bincount([result_idx(h, a) for h, a in zip(train.ht_home, train.ht_away, strict=True)], minlength=3) / len(train)
    h2_base = np.bincount([result_idx(f - h, g - a) for f, g, h, a in zip(train.ft_home, train.ft_away, train.ht_home, train.ht_away, strict=True)], minlength=3) / len(train)
    htft_base = np.zeros((3, 3))
    for f, g, h, a in zip(train.ft_home, train.ft_away, train.ht_home, train.ht_away, strict=True):
        htft_base[result_idx(h, a), result_idx(f, g)] += 1
    htft_base /= htft_base.sum()
    ht_over_base = {k: float(((train.ht_home + train.ht_away) > k).mean()) for k in (0.5, 1.5)}

    cols = ["season", "match_date", "home", "away", "ft_home", "ft_away", "ht_home", "ht_away"]
    rec = {"ht": [], "ht_b": [], "h2": [], "h2_b": [], "htft": [], "htft_b": [], "ov05": [], "ov15": [], "y_ht": [], "y_h2": [],
           "y_htft": [], "y05": [], "y15": [], "ht_draw_pred": [], "htft_pred": np.zeros((3, 3))}
    for r, p in iter_matrices(m[cols], TEST_SEASONS, HALF_LIFE_DAYS, RIDGE):
        q = half_time_matrix(p, p1)
        s = second_half_matrix(p, p1)
        j = ht_ft_probabilities(p, p1)
        rec["ht"].append(outcome_probs(q)); rec["ht_b"].append(ht_base)
        rec["h2"].append(outcome_probs(s)); rec["h2_b"].append(h2_base)
        rec["htft"].append(j.ravel()); rec["htft_b"].append(htft_base.ravel())
        n = q.shape[0]; tot = np.add.outer(np.arange(n), np.arange(n))
        rec["ov05"].append(q[tot > 0.5].sum()); rec["ov15"].append(q[tot > 1.5].sum())
        rec["y_ht"].append(result_idx(r.ht_home, r.ht_away)); rec["y_h2"].append(result_idx(r.ft_home - r.ht_home, r.ft_away - r.ht_away))
        rec["y_htft"].append(result_idx(r.ht_home, r.ht_away) * 3 + result_idx(r.ft_home, r.ft_away))
        rec["y05"].append(int(r.ht_home + r.ht_away > 0.5)); rec["y15"].append(int(r.ht_home + r.ht_away > 1.5))
        rec["htft_pred"] += j
    n = len(rec["y_ht"])
    out = {
        "league": league_id, "n": n, "p1": round(p1, 4),
        "ht_1x2_model": log_loss(np.array(rec["ht"]), np.array(rec["y_ht"])), "ht_1x2_base": log_loss(np.array(rec["ht_b"]), np.array(rec["y_ht"])),
        "h2_1x2_model": log_loss(np.array(rec["h2"]), np.array(rec["y_h2"])), "h2_1x2_base": log_loss(np.array(rec["h2_b"]), np.array(rec["y_h2"])),
        "htft_model": log_loss(np.array(rec["htft"]), np.array(rec["y_htft"])), "htft_base": log_loss(np.array(rec["htft_b"]), np.array(rec["y_htft"])),
        "ht_over05_model": binary_ll(rec["ov05"], rec["y05"]), "ht_over05_base": binary_ll([ht_over_base[0.5]] * n, rec["y05"]),
        "ht_over15_model": binary_ll(rec["ov15"], rec["y15"]), "ht_over15_base": binary_ll([ht_over_base[1.5]] * n, rec["y15"]),
        "calib_ht_over05": (float(np.mean(rec["ov05"])), float(np.mean(rec["y05"]))),
        "calib_ht_over15": (float(np.mean(rec["ov15"])), float(np.mean(rec["y15"]))),
        "calib_ht_draw": (float(np.mean(np.array(rec["ht"])[:, 1])), float(np.mean(np.array(rec["y_ht"]) == 1))),
    }
    pred = rec["htft_pred"] / n
    actual = np.bincount(rec["y_htft"], minlength=9).reshape(3, 3) / n
    out["htft_pred_vs_actual"] = (np.round(pred, 3).tolist(), np.round(actual, 3).tolist())
    return out


if __name__ == "__main__":
    for lid in sys.argv[1:] or ["EPL"]:
        r = run(lid)
        print(f"\n===== {lid}: {r['n']} test matches, p1 = {r['p1']} (share of goals before half-time) =====")
        for k in ("ht_1x2", "h2_1x2", "htft", "ht_over05", "ht_over15"):
            print(f"  {k:10} log loss: model {r[k + '_model']:.4f} | base rate {r[k + '_base']:.4f}")
        for k in ("calib_ht_over05", "calib_ht_over15", "calib_ht_draw"):
            print(f"  {k:16} predicted {r[k][0]:.3f} vs actual {r[k][1]:.3f}")
        pr, ac = r["htft_pred_vs_actual"]
        print("  HT/FT predicted (rows HT home/draw/away; cols FT home/draw/away):")
        for a, b in zip(pr, ac, strict=True):
            print("    ", a, " actual", b)
