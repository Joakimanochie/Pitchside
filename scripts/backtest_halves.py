"""Half-time model: independent split vs empirical split table, on held-out matches.

Both splits sit on top of the same weekly walk-forward goals model. Their parameters (p1, the table) are learned on
seasons <= 2021 only, pooled over all five leagues, and frozen. Scored on 2022/23 onwards against league base rates.
Usage: uv run python scripts/backtest_halves.py [LEAGUE ...]      (default: all five)
"""
import sys

import numpy as np
import pandas as pd

from pitchside.ingest.footballdata import load_seasons
from pitchside.leagues import LEAGUES
from pitchside.models.backtest import iter_matrices
from pitchside.models.evaluate import log_loss
from pitchside.models.halves import (
    half_time_matrix,
    ht_ft_probabilities,
    second_half_matrix,
)
from pitchside.models.split_table import HalfSplitTable

HALF_LIFE_DAYS, RIDGE = 730, 2.0
TRAIN_END, TEST_SEASONS = 2021, [2022, 2023, 2024, 2025, 2026]
COLS = ["season", "match_date", "home", "away", "ft_home", "ft_away", "ht_home", "ht_away"]


def idx(h, a):
    return 0 if h > a else 1 if h == a else 2


def three(q):
    return [np.tril(q, -1).sum(), np.trace(q), np.triu(q, 1).sum()]


def binary_ll(p, y):
    p = np.clip(np.asarray(p), 1e-12, 1 - 1e-12)
    y = np.asarray(y)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def load_all() -> dict[str, pd.DataFrame]:
    out = {}
    for lid, lg in LEAGUES.items():
        m = load_seasons(lg.fd_code, list(range(2015, 2027)))
        out[lid] = m[m["ht_home"].notna() & m["ht_away"].notna()][COLS].copy()
    return out


def run(league_id: str, data: dict[str, pd.DataFrame], table: HalfSplitTable) -> dict:
    m = data[league_id]
    train = pd.concat(d[d["season"] <= TRAIN_END] for d in data.values())
    p1 = table.p1
    base = {
        "ht": np.bincount([idx(h, a) for h, a in zip(train.ht_home, train.ht_away, strict=True)], minlength=3) / len(train),
        "h2": np.bincount([idx(f - h, g - a) for f, g, h, a in zip(train.ft_home, train.ft_away, train.ht_home, train.ht_away, strict=True)], minlength=3) / len(train),
    }
    htft_base = np.zeros((3, 3))
    for f, g, h, a in zip(train.ft_home, train.ft_away, train.ht_home, train.ht_away, strict=True):
        htft_base[idx(h, a), idx(f, g)] += 1
    htft_base /= htft_base.sum()
    over_base = {k: float(((train.ht_home + train.ht_away) > k).mean()) for k in (0.5, 1.5)}

    acc = {k: {"ht": [], "h2": [], "htft": [], "o05": [], "o15": [], "pred": np.zeros((3, 3))} for k in ("indep", "table")}
    truth = {"ht": [], "h2": [], "htft": [], "o05": [], "o15": [], "actual": np.zeros((3, 3))}
    for r, p in iter_matrices(m, TEST_SEASONS, HALF_LIFE_DAYS, RIDGE):
        n = p.shape[0]
        tot = np.add.outer(np.arange(n), np.arange(n))
        for name, split in (("indep", p1), ("table", table)):
            q, s, j = half_time_matrix(p, split), second_half_matrix(p, split), ht_ft_probabilities(p, split)
            acc[name]["ht"].append(three(q)); acc[name]["h2"].append(three(s)); acc[name]["htft"].append(j.ravel())
            acc[name]["o05"].append(q[tot > 0.5].sum()); acc[name]["o15"].append(q[tot > 1.5].sum()); acc[name]["pred"] += j
        truth["ht"].append(idx(r.ht_home, r.ht_away)); truth["h2"].append(idx(r.ft_home - r.ht_home, r.ft_away - r.ht_away))
        truth["htft"].append(idx(r.ht_home, r.ht_away) * 3 + idx(r.ft_home, r.ft_away))
        truth["o05"].append(int(r.ht_home + r.ht_away > 0.5)); truth["o15"].append(int(r.ht_home + r.ht_away > 1.5))
        truth["actual"][idx(r.ht_home, r.ht_away), idx(r.ft_home, r.ft_away)] += 1
    n = len(truth["ht"])
    res = {"league": league_id, "n": n}
    for name in ("indep", "table"):
        a = acc[name]
        res[name] = {
            "ht": log_loss(np.array(a["ht"]), np.array(truth["ht"])), "h2": log_loss(np.array(a["h2"]), np.array(truth["h2"])),
            "htft": log_loss(np.array(a["htft"]), np.array(truth["htft"])),
            "o05": binary_ll(a["o05"], truth["o05"]), "o15": binary_ll(a["o15"], truth["o15"]), "pred": a["pred"] / n,
        }
    res["base"] = {"ht": log_loss(np.tile(base["ht"], (n, 1)), np.array(truth["ht"])), "h2": log_loss(np.tile(base["h2"], (n, 1)), np.array(truth["h2"])),
                   "htft": log_loss(np.tile(htft_base.ravel(), (n, 1)), np.array(truth["htft"])),
                   "o05": binary_ll([over_base[0.5]] * n, truth["o05"]), "o15": binary_ll([over_base[1.5]] * n, truth["o15"])}
    res["actual"] = truth["actual"] / n
    return res


if __name__ == "__main__":
    data = load_all()
    pooled = pd.concat(d[d["season"] <= TRAIN_END] for d in data.values())
    table = HalfSplitTable().fit(pooled.ht_home, pooled.ht_away, pooled.ft_home, pooled.ft_away)
    print(f"table trained on {len(pooled)} matches (2015-2021, five leagues pooled); p1 = {table.p1:.4f}")
    for lid in [a.upper() for a in sys.argv[1:]] or sorted(LEAGUES):
        r = run(lid, data, table)
        print(f"\n===== {lid}: {r['n']} test matches =====   log loss (lower is better)")
        print(f"  {'market':14} {'base rate':>10} {'independent':>12} {'table':>10}")
        for k, label in (("ht", "HT result"), ("h2", "2H result"), ("htft", "HT/FT (9-way)"), ("o05", "HT over 0.5"), ("o15", "HT over 1.5")):
            print(f"  {label:14} {r['base'][k]:10.4f} {r['indep'][k]:12.4f} {r['table'][k]:10.4f}")
        print("  comebacks / reversals (share of all matches), predicted independent | table | actual:")
        for (rh, ch, label) in ((0, 2, "leading at HT, lost"), (2, 0, "trailing at HT, won"), (0, 1, "leading at HT, drew"), (2, 1, "trailing at HT, drew")):
            print(f"    {label:22} {r['indep']['pred'][rh, ch]:.3f} | {r['table']['pred'][rh, ch]:.3f} | {r['actual'][rh, ch]:.3f}")
