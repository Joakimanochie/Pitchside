"""Choose the count model's memory (half-life) and shrinkage (ridge) for corners, cards, shots and shots on target, on 2019/20-2021/22 only.

Walk-forward, five leagues pooled: refit before each 4-week block and score the counts that followed by their mean negative log-likelihood under the fitted
negative binomial (lower is better). The held-out seasons (2022/23 onwards) are not read here.
Usage: uv run python scripts/tune_counts.py
"""
import itertools
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson

from pitchside.ingest.footballdata import load_seasons
from pitchside.leagues import LEAGUES
from pitchside.models.counts import CountModel

TUNE = [2019, 2020, 2021]
HALF_LIVES = [365, 730, 1460]
RIDGES = [1.0, 4.0, 16.0]
STATS = {"corners": ("corners_h", "corners_a"), "cards": (("yellow_h", "red_h"), ("yellow_a", "red_a")), "shots": ("shots_h", "shots_a"), "sot": ("sot_h", "sot_a")}


def counts(m: pd.DataFrame, stat: str) -> tuple[pd.Series, pd.Series]:
    h, a = STATS[stat]
    if stat == "cards":
        return m[h[0]] + m[h[1]], m[a[0]] + m[a[1]]
    return m[h], m[a]


def nll(model: CountModel, home: str, away: str, ch: float, ca: float) -> float:
    lam_h, lam_a = model.means(home, away)
    total = 0.0
    for lam, y in ((lam_h, ch), (lam_a, ca)):
        if model.dispersion < 1e-6:
            total -= poisson.logpmf(y, lam)
        else:
            r = 1.0 / model.dispersion
            total -= nbinom.logpmf(y, r, r / (r + lam))
    return float(total) / 2


def main() -> None:
    results = {(s, hl, rg): [] for s in STATS for hl, rg in itertools.product(HALF_LIVES, RIDGES)}
    for lg in LEAGUES.values():
        m = load_seasons(lg.fd_code, list(range(2015, max(TUNE) + 1))).sort_values("match_date").reset_index(drop=True)
        target = m[m["season"].isin(TUNE)]
        t0, end = target["match_date"].min(), target["match_date"].max()
        while t0 <= end:
            t1 = t0 + timedelta(days=28)
            block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
            for stat in STATS:
                ch, ca = counts(m, stat)
                data = m.assign(count_home=ch, count_away=ca)
                bh, ba = counts(block, stat)
                rows = [(r.home, r.away, y1, y2) for r, y1, y2 in zip(block.itertuples(index=False), bh.to_numpy(), ba.to_numpy(), strict=True) if not (np.isnan(y1) or np.isnan(y2))]
                for hl, rg in itertools.product(HALF_LIVES, RIDGES):
                    model = CountModel(half_life_days=hl, ridge=rg).fit(data, as_of=t0)
                    results[(stat, hl, rg)].extend(nll(model, home, away, y1, y2) for home, away, y1, y2 in rows)
            t0 = t1
        print(f"done {lg.id}", flush=True)
    rows = [{"stat": s, "half_life": hl, "ridge": rg, "nll": float(np.mean(v)), "n": len(v)} for (s, hl, rg), v in results.items()]
    res = pd.DataFrame(rows)
    res.to_csv("data/processed/tune_counts.csv", index=False)
    for stat, g in res.groupby("stat"):
        print(f"\n{stat}\n", g.sort_values("nll").head(4).round(4).to_string(index=False))


if __name__ == "__main__":
    main()
