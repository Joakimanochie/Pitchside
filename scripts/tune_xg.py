"""Does fitting team strengths partly to expected goals (xG) instead of only to goals improve the predictions?

Goals are noisy: a team can create three clear chances and lose 0-1. xG measures the chances, so blending it into what the model is fitted to
should give steadier attack and defence ratings. Tuned on 2019/20-2021/22 (five leagues pooled, weekly refits as in production, 0.3.0 settings
otherwise), then run once on the held-out seasons 2022/23 onwards.

    uv run python scripts/tune_xg.py                  # tuning seasons, several weights
    uv run python scripts/tune_xg.py --test 0,0.5      # held-out seasons, the named weights
"""
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

from pitchside.ingest.footballdata import load_seasons
from pitchside.ingest.understat_xg import attach_xg, load_xg
from pitchside.leagues import LEAGUES
from pitchside.models.dixon_coles import DixonColes
from pitchside.models.evaluate import (
    btts_probability,
    log_loss,
    over_probability,
    result_probs,
)
from pitchside.pipeline.weekly import MODEL_PARAMS

TUNE, TEST = [2019, 2020, 2021], [2022, 2023, 2024, 2025, 2026]
WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]


def binary_ll(p, o):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return float(-(o * np.log(p) + (1 - o) * np.log(1 - p)).mean())


def main() -> None:
    test = "--test" in sys.argv
    seasons = TEST if test else TUNE
    weights = [float(x) for x in sys.argv[sys.argv.index("--test") + 1].split(",")] if test else WEIGHTS
    xg = load_xg()
    store = {w: {"pr": [], "over": [], "btts": [], "y": [], "o": [], "b": []} for w in weights}
    covered = total = 0
    for lg in LEAGUES.values():
        m = load_seasons(lg.fd_code, list(range(2015, max(seasons) + 1)))[["season", "match_date", "home", "away", "ft_home", "ft_away"]]
        m = attach_xg(m, lg.id, xg).sort_values("match_date").reset_index(drop=True)
        target = m[m["season"].isin(seasons)]
        covered += int(target["xg_home"].notna().sum())
        total += len(target)
        t0, end = target["match_date"].min(), target["match_date"].max()
        while t0 <= end:
            t1 = t0 + timedelta(days=14)
            block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
            if len(block):
                for w in weights:
                    model = DixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"], level_window_days=MODEL_PARAMS["level_window_days"],
                                       level_shrink=MODEL_PARAMS["level_shrink"], total_compression=MODEL_PARAMS["total_compression"], xg_weight=w).fit(m, as_of=t0)
                    st = store[w]
                    for r in block.itertuples(index=False):
                        p = model.score_matrix(r.home, r.away)
                        st["pr"].append(result_probs(p))
                        st["over"].append(over_probability(p, 2.5))
                        st["btts"].append(btts_probability(p))
                        st["y"].append(0 if r.ft_home > r.ft_away else 1 if r.ft_home == r.ft_away else 2)
                        st["o"].append(int(r.ft_home + r.ft_away > 2.5))
                        st["b"].append(int(r.ft_home > 0 and r.ft_away > 0))
            t0 = t1
        print(f"done {lg.id}", flush=True)
    print(f"xG joined for {covered:,} of {total:,} matches in the scored seasons ({covered / total:.1%})")
    rows = [{"xg_weight": w, "1x2_ll": log_loss(np.array(s["pr"]), np.array(s["y"])), "ou25_ll": binary_ll(s["over"], np.array(s["o"])),
             "btts_ll": binary_ll(s["btts"], np.array(s["b"])), "n": len(s["y"])} for w, s in store.items()]
    res = pd.DataFrame(rows)
    res["d_1x2"] = res["1x2_ll"] - res.loc[res["xg_weight"] == 0.0, "1x2_ll"].iloc[0] if 0.0 in weights else np.nan
    res.to_csv("data/processed/xg_test.csv" if test else "data/processed/xg_tune.csv", index=False)
    print(res.round(5).to_string(index=False))


if __name__ == "__main__":
    main()
