"""Tune the total-goals compression factor beta on 2019/20-2021/22, or run named values once on 2022/23 onwards.

Each block is fitted once (0.3.0 settings); only the scoreline matrix differs between alphas. Five leagues pooled.
Usage: uv run python scripts/tune_totals.py        |   uv run python scripts/tune_totals.py --test 0,0.05
"""
import copy
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

from pitchside.ingest.footballdata import load_seasons
from pitchside.models.dixon_coles import DixonColes
from pitchside.models.evaluate import (
    btts_probability,
    log_loss,
    over_probability,
    result_probs,
)

TUNE, TEST = [2019, 2020, 2021], [2022, 2023, 2024, 2025, 2026]
ALPHAS = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]  # now the total-compression factor beta


def binary_ll(p, o):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return float(-(o * np.log(p) + (1 - o) * np.log(1 - p)).mean())


def main() -> None:
    test = "--test" in sys.argv
    seasons = TEST if test else TUNE
    alphas = [float(x) for x in sys.argv[sys.argv.index("--test") + 1].split(",")] if test else ALPHAS
    store = {a: {"pr": [], "over": [], "btts": [], "y": [], "o": [], "b": [], "line": []} for a in alphas}
    for code in ("E0", "SP1", "D1", "I1", "F1"):
        m = load_seasons(code, list(range(2015, max(seasons) + 1)))[["season", "match_date", "home", "away", "ft_home", "ft_away"]]
        m = m.sort_values("match_date").reset_index(drop=True)
        target = m[m["season"].isin(seasons)]
        t0, end = target["match_date"].min(), target["match_date"].max()
        while t0 <= end:
            t1 = t0 + timedelta(days=14)
            block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
            if len(block):
                base = DixonColes(half_life_days=730, ridge=2.0, level_window_days=240, level_shrink=60).fit(m, as_of=t0)
                for a in alphas:
                    mod = copy.copy(base)
                    mod.total_compression = a
                    st = store[a]
                    for r in block.itertuples(index=False):
                        p = mod.score_matrix(r.home, r.away)
                        st["pr"].append(result_probs(p)); st["over"].append(over_probability(p, 2.5)); st["btts"].append(btts_probability(p))
                        st["y"].append(0 if r.ft_home > r.ft_away else 1 if r.ft_home == r.ft_away else 2)
                        st["o"].append(int(r.ft_home + r.ft_away > 2.5)); st["b"].append(int(r.ft_home > 0 and r.ft_away > 0))
            t0 = t1
        print(f"done {code}", flush=True)
    rows, low = [], []
    for a, s in store.items():
        o, p = np.array(s["o"]), np.array(s["over"])
        rows.append({"alpha": a, "1x2_ll": log_loss(np.array(s["pr"]), np.array(s["y"])), "ou25_ll": binary_ll(p, o),
                     "btts_ll": binary_ll(s["btts"], np.array(s["b"])), "mean_over": p.mean(), "actual_over": o.mean()})
        for lo, hi in ((0, .40), (.40, .50), (.50, .60), (.60, 1)):
            sel = (p >= lo) & (p < hi)
            low.append({"alpha": a, "band": f"{lo:.2f}-{hi:.2f}", "n": int(sel.sum()), "predicted": p[sel].mean(), "actual": o[sel].mean()})
    res = pd.DataFrame(rows)
    res.to_csv("data/processed/totals_test.csv" if test else "data/processed/totals_tune.csv", index=False)
    print(res.round(5).to_string(index=False))
    print(pd.DataFrame(low).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
