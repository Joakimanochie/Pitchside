"""Test recent-form and head-to-head signals on top of the 0.3.0 goals model.

Tuning mode (default) reads only 2019/20-2021/22. Test mode (--test NAME,NAME) runs the named settings on 2022/23 onwards and is
run once, after the settings are chosen. All five leagues are pooled; hyperparameters of the base model are frozen.
Usage: uv run python scripts/tune_signals.py            |   uv run python scripts/tune_signals.py --test base,form_5_15
"""
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
from pitchside.models.signals import adjusted_lambdas, head_to_head, recent_form

TUNE, TEST = [2019, 2020, 2021], [2022, 2023, 2024, 2025, 2026]
FORMS = {"form_5_5": (5, 5), "form_5_15": (5, 15), "form_10_10": (10, 10), "form_10_30": (10, 30), "form_10_100": (10, 100), "form_20_100": (20, 100), "form_20_300": (20, 300)}
H2HS = {"h2h_6_5": (6, 5), "h2h_6_15": (6, 15), "h2h_6_40": (6, 40), "h2h_10_100": (10, 100), "h2h_10_300": (10, 300)}
COMBOS = {f"{f}+{h}": (f, h) for f in ("form_5_15", "form_10_30") for h in ("h2h_6_15", "h2h_6_40")}
COMBOS = {}  # combinations only make sense if a single signal helps; none did in the first grid
CONFIGS = ["base", *FORMS, *H2HS, *COMBOS]


def binary_ll(p, o):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return float(-(o * np.log(p) + (1 - o) * np.log(1 - p)).mean())


def main() -> None:
    test = "--test" in sys.argv
    seasons = TEST if test else TUNE
    names = sys.argv[sys.argv.index("--test") + 1].split(",") if test else CONFIGS
    store = {n: {"pr": [], "over": [], "btts": [], "y": [], "o": [], "b": []} for n in names}
    for code in ("E0", "SP1", "D1", "I1", "F1"):
        m = load_seasons(code, list(range(2015, max(seasons) + 1)))[["season", "match_date", "home", "away", "ft_home", "ft_away"]]
        m = m.sort_values("match_date").reset_index(drop=True)
        target = m[m["season"].isin(seasons)]
        t0, end = target["match_date"].min(), target["match_date"].max()
        while t0 <= end:
            t1 = t0 + timedelta(days=14)
            block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
            if len(block):
                model = DixonColes(half_life_days=730, ridge=2.0, level_window_days=240, level_shrink=60).fit(m, as_of=t0)
                forms = {n: recent_form(model, m, *FORMS[n]) for n in FORMS if n in names or any(n in COMBOS[c] for c in COMBOS if c in names)}
                h2hs = {n: head_to_head(model, m, *H2HS[n]) for n in H2HS if n in names or any(n in COMBOS[c] for c in COMBOS if c in names)}
                for r in block.itertuples(index=False):
                    outcome = 0 if r.ft_home > r.ft_away else 1 if r.ft_home == r.ft_away else 2
                    for n in names:
                        f, h = (None, None)
                        if n in FORMS:
                            f = forms[n]
                        elif n in H2HS:
                            h = h2hs[n]
                        elif n in COMBOS:
                            f, h = forms[COMBOS[n][0]], h2hs[COMBOS[n][1]]
                        p = model.matrix_from_lambdas(*adjusted_lambdas(model, r.home, r.away, f, h))
                        st = store[n]
                        st["pr"].append(result_probs(p)); st["over"].append(over_probability(p, 2.5)); st["btts"].append(btts_probability(p))
                        st["y"].append(outcome); st["o"].append(int(r.ft_home + r.ft_away > 2.5)); st["b"].append(int(r.ft_home > 0 and r.ft_away > 0))
            t0 = t1
        print(f"done {code}", flush=True)
    rows = [{"config": n, "1x2_ll": log_loss(np.array(s["pr"]), np.array(s["y"])), "ou25_ll": binary_ll(s["over"], np.array(s["o"])),
             "btts_ll": binary_ll(s["btts"], np.array(s["b"])), "n": len(s["y"])} for n, s in store.items()]
    res = pd.DataFrame(rows)
    res["d_1x2"] = res["1x2_ll"] - res.loc[res["config"] == "base", "1x2_ll"].iloc[0] if "base" in names else np.nan
    res.to_csv("data/processed/signals_test.csv" if test else "data/processed/signals_tune.csv", index=False)
    print(res.round(5).to_string(index=False))


if __name__ == "__main__":
    main()
