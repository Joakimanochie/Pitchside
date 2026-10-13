"""Would "how often has each team hit this market in its last 5 / 10 / 15 matches" improve the predictions?

For every match in the held-out goals backtest (2022/23 to 2026/27, five leagues, model probabilities stored before kickoff) we compute each
team's hit rate over its previous N matches (any venue) for the market, then ask two questions:

  1. Used on its own (what a bettor does when reading "over 2.5 in 4 of the last 5"): is it as good as the model's probability?
  2. Added to the model: does a logistic regression on [model probability, recent hit rates] beat the model probability alone,
     fitted on the earlier 60% of matches and scored on the later 40%?

Markets tested are the ones the backtest stored model probabilities for: home win, draw, away win, over 2.5 goals, both teams to score.
Reads data/processed/backtest_goals_*_predictions.csv and the cached football-data files (no database).
Usage: uv run python scripts/test_recent_hit_rates.py
"""
import glob
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from pitchside.ingest.footballdata import load_seasons
from pitchside.leagues import LEAGUES

WINDOWS = (5, 10, 15)
EPS = 1e-6


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def log_loss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def fit_logistic(X, y, l2=1.0):
    """Logistic regression with an intercept; returns coefficients and their standard errors."""
    X1 = np.column_stack([np.ones(len(X)), X])

    def nll(w):
        z = X1 @ w
        return np.sum(np.logaddexp(0, z) - y * z) + 0.5 * l2 * np.sum(w[1:] ** 2)

    def grad(w):
        return X1.T @ (1 / (1 + np.exp(-(X1 @ w))) - y) + l2 * np.r_[0, w[1:]]

    w = minimize(nll, np.zeros(X1.shape[1]), jac=grad, method="L-BFGS-B").x
    p = 1 / (1 + np.exp(-(X1 @ w)))
    cov = np.linalg.inv(X1.T @ (X1 * (p * (1 - p))[:, None]) + l2 * np.diag(np.r_[0, np.ones(X1.shape[1] - 1)]))
    return w, np.sqrt(np.diag(cov))


def predict(w, X):
    return 1 / (1 + np.exp(-(np.column_stack([np.ones(len(X)), X]) @ w)))


def team_logs(all_matches: pd.DataFrame) -> dict:
    """team -> chronological arrays of (date, win, draw, loss, over25, btts) from that team's point of view."""
    logs = defaultdict(list)
    for r in all_matches.sort_values("match_date").itertuples(index=False):
        total, btts = r.ft_home + r.ft_away, int(r.ft_home > 0 and r.ft_away > 0)
        hw, d = int(r.ft_home > r.ft_away), int(r.ft_home == r.ft_away)
        logs[r.home].append((r.match_date, hw, d, 1 - hw - d, int(total > 2.5), btts))
        logs[r.away].append((r.match_date, 1 - hw - d, d, hw, int(total > 2.5), btts))
    return {t: (np.array([x[0] for x in v]), np.array([x[1:] for x in v], dtype=float)) for t, v in logs.items()}


def recent(logs: dict, team: str, date, n: int, col: int) -> float:
    dates, vals = logs[team]
    k = np.searchsorted(dates, date)          # matches strictly before `date`
    window = vals[max(0, k - n):k, col]
    return float(window.mean()) if len(window) >= max(3, n // 2) else np.nan


def main() -> None:
    preds = pd.concat([pd.read_csv(f, parse_dates=["match_date"]).assign(league=f.split("goals_")[1].split("_")[0].upper())
                       for f in sorted(glob.glob("data/processed/backtest_goals_*_predictions.csv"))], ignore_index=True)
    preds["match_date"] = preds["match_date"].dt.date
    frames = []
    for lg in LEAGUES.values():
        m = load_seasons(lg.fd_code, list(range(2014, 2027)))[["match_date", "home", "away", "ft_home", "ft_away"]]
        frames.append(m)
    logs = team_logs(pd.concat(frames, ignore_index=True))
    preds = preds.sort_values("match_date").reset_index(drop=True)

    # target -> (model probability column, outcome, [(home-team column index, away-team column index)] feature pairs)
    # columns in the logs: 0 win, 1 draw, 2 loss, 3 over25, 4 btts
    y_total = preds.ft_home + preds.ft_away
    targets = {
        "home win": ("p_h", (preds.ft_home > preds.ft_away).astype(float), [("home", 0), ("away", 2)]),
        "draw": ("p_d", (preds.ft_home == preds.ft_away).astype(float), [("home", 1), ("away", 1)]),
        "away win": ("p_a", (preds.ft_home < preds.ft_away).astype(float), [("away", 0), ("home", 2)]),
        "over 2.5 goals": ("p_over25", (y_total > 2.5).astype(float), [("home", 3), ("away", 3)]),
        "both teams score": ("p_btts", ((preds.ft_home > 0) & (preds.ft_away > 0)).astype(float), [("home", 4), ("away", 4)]),
    }
    cut = int(len(preds) * 0.6)
    rows = []
    for name, (pcol, y, feats) in targets.items():
        p = preds[pcol].to_numpy()
        for n in WINDOWS:
            X = np.column_stack([[recent(logs, (r.home if side == "home" else r.away), r.match_date, n, col) for r in preds.itertuples()]
                                 for side, col in feats])
            ok = ~np.isnan(X).any(axis=1)
            yv, pv, Xv = y.to_numpy()[ok], p[ok], X[ok]
            train = np.arange(len(yv)) < int(len(yv) * 0.6)
            test = ~train
            base_w, _ = fit_logistic(logit(pv)[:, None][train], yv[train])
            base = predict(base_w, logit(pv)[:, None][test])
            Z = np.column_stack([logit(pv), Xv - Xv[train].mean(axis=0)])
            aug_w, _ = fit_logistic(Z[train], yv[train])
            aug = predict(aug_w, Z[test])
            _, se = fit_logistic(Z, yv)
            w_all, _ = fit_logistic(Z, yv)
            raw = np.clip(Xv.mean(axis=1), 0.03, 0.97)
            rows.append({"market": name, "last N": n, "matches": int(ok.sum()),
                         "model alone": log_loss(pv[test], yv[test]), "model recalibrated": log_loss(base, yv[test]),
                         "model + recent rates": log_loss(aug, yv[test]), "recent rates alone": log_loss(raw[test], yv[test]),
                         "gain from rates": log_loss(base, yv[test]) - log_loss(aug, yv[test]),
                         "z of rates": " / ".join(f"{w_all[i + 2] / se[i + 2]:+.1f}" for i in range(Z.shape[1] - 1))})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(out.round(4).to_string(index=False))
    out.to_csv("data/processed/recent_hit_rates_test.csv", index=False)
    print(f"\ntrain on the first {cut:,} matches by date, score on the rest; positive 'gain from rates' means the rates helped")


if __name__ == "__main__":
    main()
