"""Walk-forward backtest for the goals model.

For each block of `step_days`, refit on matches strictly before the block starts, then predict every match
in the block. Nothing from the block (or later) is visible to the fit. Predictions are compared with a
league base-rate baseline (expanding window) and, where available, the de-margined closing odds.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from pitchside.models.dixon_coles import DixonColes
from pitchside.models.evaluate import (
    brier,
    btts_probability,
    demargin,
    log_loss,
    over_probability,
    result_probs,
    rps,
)


def outcome_index(ft_home: pd.Series, ft_away: pd.Series) -> np.ndarray:
    """0 = home win, 1 = draw, 2 = away win."""
    return np.where(ft_home > ft_away, 0, np.where(ft_home == ft_away, 1, 2))


def walk_forward(matches: pd.DataFrame, eval_seasons: list[int], half_life_days: float, ridge: float,
                 step_days: int = 7, model_cls=DixonColes) -> pd.DataFrame:
    """Return one row per evaluated match with model, base-rate and (if present) bookmaker probabilities."""
    matches = matches.sort_values("match_date").reset_index(drop=True)
    target = matches[matches["season"].isin(eval_seasons)]
    start, end = target["match_date"].min(), target["match_date"].max()
    out = []
    block_start = start
    while block_start <= end:
        block_end = block_start + timedelta(days=step_days)
        block = target[(target["match_date"] >= block_start) & (target["match_date"] < block_end)]
        if len(block):
            model = model_cls(half_life_days=half_life_days, ridge=ridge).fit(matches, as_of=block_start)
            history = matches[matches["match_date"] < block_start]
            base = np.array([
                (history["ft_home"] > history["ft_away"]).mean(),
                (history["ft_home"] == history["ft_away"]).mean(),
                (history["ft_home"] < history["ft_away"]).mean(),
            ])
            base_over = ((history["ft_home"] + history["ft_away"]) > 2.5).mean()
            base_btts = ((history["ft_home"] > 0) & (history["ft_away"] > 0)).mean()
            for r in block.itertuples(index=False):
                p = model.score_matrix(r.home, r.away)
                ph, pd_, pa = result_probs(p)
                out.append({
                    "season": r.season, "match_date": r.match_date, "home": r.home, "away": r.away,
                    "ft_home": r.ft_home, "ft_away": r.ft_away,
                    "p_h": ph, "p_d": pd_, "p_a": pa,
                    "p_over25": over_probability(p, 2.5), "p_btts": btts_probability(p),
                    "b_h": base[0], "b_d": base[1], "b_a": base[2], "b_over25": base_over, "b_btts": base_btts,
                    "known_teams": model.known(r.home) and model.known(r.away),
                    **{c: getattr(r, c) for c in ("odds_h", "odds_d", "odds_a", "odds_over25", "odds_under25") if hasattr(r, c)},
                })
        block_start = block_end
    return pd.DataFrame(out)


def score(pred: pd.DataFrame) -> dict:
    """Aggregate metrics for a block of predictions. Bookmaker metrics only on rows with complete odds."""
    y = outcome_index(pred["ft_home"], pred["ft_away"])
    model = pred[["p_h", "p_d", "p_a"]].to_numpy()
    base = pred[["b_h", "b_d", "b_a"]].to_numpy()
    total = pred["ft_home"] + pred["ft_away"]
    over = (total > 2.5).astype(int).to_numpy()
    btts = ((pred["ft_home"] > 0) & (pred["ft_away"] > 0)).astype(int).to_numpy()

    def binary_ll(p, outcome):
        p = np.clip(p, 1e-12, 1 - 1e-12)
        return float(-(outcome * np.log(p) + (1 - outcome) * np.log(1 - p)).mean())

    res = {
        "n": len(pred),
        "1x2_logloss_model": log_loss(model, y), "1x2_logloss_base": log_loss(base, y),
        "1x2_brier_model": brier(model, y), "1x2_brier_base": brier(base, y),
        "1x2_rps_model": rps(model, y), "1x2_rps_base": rps(base, y),
        "1x2_accuracy_model": float((model.argmax(axis=1) == y).mean()),
        "ou25_logloss_model": binary_ll(pred["p_over25"].to_numpy(), over),
        "ou25_logloss_base": binary_ll(pred["b_over25"].to_numpy(), over),
        "btts_logloss_model": binary_ll(pred["p_btts"].to_numpy(), btts),
        "btts_logloss_base": binary_ll(pred["b_btts"].to_numpy(), btts),
    }
    if {"odds_h", "odds_d", "odds_a"} <= set(pred.columns):
        has = pred[["odds_h", "odds_d", "odds_a"]].notna().all(axis=1).to_numpy()
        if has.sum():
            book = demargin(pred.loc[has, ["odds_h", "odds_d", "odds_a"]].to_numpy())
            res.update({
                "n_odds": int(has.sum()),
                "1x2_logloss_book": log_loss(book, y[has]), "1x2_brier_book": brier(book, y[has]),
                "1x2_rps_book": rps(book, y[has]), "1x2_accuracy_book": float((book.argmax(axis=1) == y[has]).mean()),
                "1x2_logloss_model_same_rows": log_loss(model[has], y[has]),
                "1x2_rps_model_same_rows": rps(model[has], y[has]),
            })
    if {"odds_over25", "odds_under25"} <= set(pred.columns):
        has = pred[["odds_over25", "odds_under25"]].notna().all(axis=1).to_numpy()
        if has.sum():
            book_over = demargin(pred.loc[has, ["odds_over25", "odds_under25"]].to_numpy())[:, 0]
            res["ou25_logloss_book"] = binary_ll(book_over, over[has])
            res["ou25_logloss_model_same_rows"] = binary_ll(pred.loc[has, "p_over25"].to_numpy(), over[has])
    return res


def iter_matrices(matches: pd.DataFrame, eval_seasons: list[int], half_life_days: float, ridge: float,
                  step_days: int = 7, model_cls=DixonColes):
    """Walk-forward like `walk_forward`, but yield (match_row, full_time_matrix) so any market can be evaluated.
    Every fit uses only matches strictly before the block it predicts."""
    matches = matches.sort_values("match_date").reset_index(drop=True)
    target = matches[matches["season"].isin(eval_seasons)]
    block_start, end = target["match_date"].min(), target["match_date"].max()
    while block_start <= end:
        block_end = block_start + timedelta(days=step_days)
        block = target[(target["match_date"] >= block_start) & (target["match_date"] < block_end)]
        if len(block):
            model = model_cls(half_life_days=half_life_days, ridge=ridge).fit(matches, as_of=block_start)
            for r in block.itertuples(index=False):
                yield r, model.score_matrix(r.home, r.away)
        block_start = block_end
