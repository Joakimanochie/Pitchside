"""Does comparing our probabilities with the bookmakers' prices help, and would backing the "value" gaps have paid?

Held-out design: the production goals model (0.3.0 settings) is refit weekly on matches before the week being predicted, for the five leagues over
2022/23 to 2026/27. Each match is compared with football-data.co.uk's prices for the match result and over/under 2.5 goals, at two moments:
the OPENING prices (published a few days before the match, which is what a user sees when reading our page) and the CLOSING prices (just before
kickoff, the sharpest). For each: the market average and the best price. Two questions, both answered on matches the model never saw:

  1. Information. Does a blend of the model and the bookmakers' own probabilities beat the bookmakers alone? (Geometric pooling, weights fitted on
     the earlier 60% of matches by date and scored on the later 40%.) If not, our model adds nothing the price does not already contain.
  2. Betting. If one unit is staked on every selection whose edge (our probability minus the bookmakers' de-margined probability) is at least a
     threshold, what did that return per unit staked? Overall and by confidence tier, with a 95% interval, next to the cost of backing everything.

Writes data/processed/value_backtest.json (read by the web app's track-record page). Usage: uv run python scripts/backtest_value.py
"""
import functools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from pitchside.confidence import load_rules, tier_for
from pitchside.ingest.footballdata import load_seasons
from pitchside.ingest.odds_history import load_closing_odds
from pitchside.leagues import LEAGUES
from pitchside.models.backtest import iter_matrices
from pitchside.models.dixon_coles import DixonColes
from pitchside.models.evaluate import over_probability, result_probs
from pitchside.odds.compare import demargin
from pitchside.pipeline.weekly import MODEL_PARAMS

TEST_SEASONS = [2022, 2023, 2024, 2025, 2026]
THRESHOLDS = (0.0, 0.02, 0.05, 0.08, 0.12)
OUT = Path("data/processed/value_backtest.json")
SUFFIXES = ("h", "d", "a", "over25", "under25")
# timing -> (average-price columns, best-price columns), in the order home, draw, away, over 2.5, under 2.5
TIMINGS = {
    "opening": ([f"open_{s}" for s in SUFFIXES], [f"openmax_{s}" for s in SUFFIXES]),
    "closing": ([f"odds_{s}" for s in SUFFIXES], [f"max_{s}" for s in SUFFIXES]),
}


def build() -> pd.DataFrame:
    model_cls = functools.partial(DixonColes, level_window_days=MODEL_PARAMS["level_window_days"], level_shrink=MODEL_PARAMS["level_shrink"],
                                  total_compression=MODEL_PARAMS["total_compression"])
    price_cols = [c for avg, best in TIMINGS.values() for c in (*avg, *best)]
    rows = []
    for lg in LEAGUES.values():
        years = list(range(2015, 2027))
        m = load_seasons(lg.fd_code, years)[["season", "match_date", "home", "away", "ft_home", "ft_away"]]
        o = load_closing_odds(lg.fd_code, years, with_max=True, with_opening=True)
        m = m.merge(o, on=["season", "match_date", "home", "away"], how="left")
        for r, matrix in iter_matrices(m, TEST_SEASONS, MODEL_PARAMS["half_life_days"], MODEL_PARAMS["ridge"], step_days=7, model_cls=model_cls):
            ph, pd_, pa = result_probs(matrix)
            rows.append({"league": lg.id, "date": r.match_date, "ft_home": r.ft_home, "ft_away": r.ft_away,
                         "p_h": ph, "p_d": pd_, "p_a": pa, "p_over": over_probability(matrix, 2.5), **{c: getattr(r, c) for c in price_cols}})
        print(f"done {lg.id}", flush=True)
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def pooled(fair: np.ndarray, model: np.ndarray, a: float, b: float) -> np.ndarray:
    """Geometric pooling of two probability vectors per row, renormalised: fair^a * model^b."""
    z = np.exp(a * np.log(np.clip(fair, 1e-9, 1)) + b * np.log(np.clip(model, 1e-9, 1)))
    return z / z.sum(axis=1, keepdims=True)


def ll(prob: np.ndarray, outcome: np.ndarray) -> float:
    return float(-np.log(np.clip(prob[np.arange(len(outcome)), outcome], 1e-9, 1)).mean())


def _blend(fair: np.ndarray, model: np.ndarray, y: np.ndarray) -> dict:
    tr = np.arange(len(y)) < int(len(y) * 0.6)
    a, b = minimize(lambda w: ll(pooled(fair[tr], model[tr], w[0], w[1]), y[tr]), [1.0, 0.1], method="Nelder-Mead").x
    return {"matches": len(y), "checked_on": int((~tr).sum()), "market": ll(fair[~tr], y[~tr]), "model": ll(model[~tr], y[~tr]),
            "blend": ll(pooled(fair[~tr], model[~tr], a, b), y[~tr]), "weight_market": float(a), "weight_model": float(b)}


def information(df: pd.DataFrame, timing: str) -> dict:
    avg, _best = TIMINGS[timing]
    out = {}
    d = df[df[avg[:3]].notna().all(axis=1)].reset_index(drop=True)
    y = np.where(d.ft_home > d.ft_away, 0, np.where(d.ft_home == d.ft_away, 1, 2))
    out["1x2"] = _blend(np.array([demargin(r) for r in d[avg[:3]].to_numpy()]), d[["p_h", "p_d", "p_a"]].to_numpy(), y)
    d = df[df[avg[3:]].notna().all(axis=1)].reset_index(drop=True)
    y = np.where(d.ft_home + d.ft_away > 2.5, 0, 1)
    out["ou25"] = _blend(np.array([demargin(r) for r in d[avg[3:]].to_numpy()]), np.column_stack([d.p_over, 1 - d.p_over]), y)
    return out


def bets(df: pd.DataFrame, rules: dict, timing: str) -> pd.DataFrame:
    """One row per selection: our probability, the average and best price, the edge against the de-margined average price, the outcome, the tier."""
    avg, best_cols = TIMINGS[timing]
    specs = [("1x2", ["home", "draw", "away"], ["p_h", "p_d", "p_a"], slice(0, 3)), ("ou_total", ["over", "under"], ["p_over", None], slice(3, 5))]
    rows = []
    for market, sels, pcols, sl in specs:
        a_cols, b_cols = avg[sl], best_cols[sl]
        d = df[df[a_cols].notna().all(axis=1)]
        for r in d.itertuples(index=False):
            odds = [getattr(r, c) for c in a_cols]
            best = [getattr(r, c) if not pd.isna(getattr(r, c)) else odds[i] for i, c in enumerate(b_cols)]
            fair = demargin(odds)
            total = r.ft_home + r.ft_away
            win = ({"home": r.ft_home > r.ft_away, "draw": r.ft_home == r.ft_away, "away": r.ft_home < r.ft_away} if market == "1x2"
                   else {"over": total > 2.5, "under": total < 2.5})
            for i, sel in enumerate(sels):
                p = getattr(r, pcols[i]) if pcols[i] else 1 - r.p_over
                rows.append({"market": market, "selection": sel, "p": p, "fair": fair[i], "odds_avg": odds[i], "odds_max": best[i], "won": bool(win[sel]),
                             "tier": tier_for(rules, market, "A", p)})
    out = pd.DataFrame(rows)
    out["edge"] = out["p"] - out["fair"]
    return out


def summarise(b: pd.DataFrame, group: str, mask: pd.Series, timing: str) -> list[dict]:
    rows = []
    for t in THRESHOLDS:
        sel = b[mask & (b["edge"] >= t)] if t > 0 else b[mask & (b["edge"] > 0)]
        if not len(sel):
            continue
        for price in ("odds_avg", "odds_max"):
            profit = np.where(sel["won"], sel[price] - 1.0, -1.0)
            n = len(sel)
            rows.append({"timing": timing, "group": group, "min_edge": t, "price": "average" if price == "odds_avg" else "best", "bets": int(n),
                         "hit_rate": float(sel["won"].mean()), "avg_odds": float(sel[price].mean()), "roi": float(profit.mean()),
                         "roi_ci": float(1.96 * profit.std(ddof=1) / np.sqrt(n)) if n > 1 else None})
    return rows


def main() -> None:
    df = build()
    rules = load_rules()
    result: dict = {"period": {"from": str(df["date"].min()), "to": str(df["date"].max()), "matches": len(df)}, "information": {}, "back_everything": [], "roi": []}
    for timing in TIMINGS:
        result["information"][timing] = information(df, timing)
        b = bets(df, rules, timing)
        for price in ("odds_avg", "odds_max"):
            profit = np.where(b["won"], b[price] - 1.0, -1.0)
            result["back_everything"].append({"timing": timing, "price": "average" if price == "odds_avg" else "best", "bets": len(b), "roi": float(profit.mean())})
        for market in ("1x2", "ou_total"):
            result["roi"] += summarise(b, market, b["market"] == market, timing)
        result["roi"] += summarise(b, "all", b["market"].notna(), timing)
        for tier in ("High", "Medium", "Low"):
            result["roi"] += summarise(b, f"tier:{tier}", b["tier"] == tier, timing)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    pd.set_option("display.width", 200)
    print(json.dumps(result["period"]))
    for timing, info in result["information"].items():
        for market, v in info.items():
            print(f"{timing:8} {market:5} market {v['market']:.4f}  model {v['model']:.4f}  blend {v['blend']:.4f}  "
                  f"weights market {v['weight_market']:+.2f} model {v['weight_model']:+.2f}  (n={v['checked_on']})")
    print(pd.DataFrame(result["back_everything"]).round(4).to_string(index=False))
    roi = pd.DataFrame(result["roi"])
    print(roi[roi["group"].isin(["all", "tier:High"])].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
