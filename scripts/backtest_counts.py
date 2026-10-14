"""Backtest the corners, cards, shots and shots-on-target markets (families F-H) on matches the models never saw.

Walk-forward as in production: each week the count model of every statistic is refit on matches before it (per league) and prices every market of that
statistic for the week's matches; each selection is then settled from the real counts. Held-out seasons 2022/23 to 2026/27, all five leagues.

Writes data/raw/count_backtest.csv.gz (match_id, date, league, market_id, family, line, selection, p, y; not committed) for the confidence ratings, and prints
calibration and skill over how often each selection usually happens (log loss, model against the earlier-matches base rate) per statistic.
Usage: uv run python scripts/backtest_counts.py [sample_matches]      |   uv run python scripts/backtest_counts.py --summary
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from pitchside.confidence import base_rates, score_rows
from pitchside.ingest.footballdata import load_seasons
from pitchside.leagues import LEAGUES
from pitchside.markets.base import HALF_WON, PUSH, WON, price
from pitchside.markets.counts import MARKETS, STATS
from pitchside.models.counts import COUNT_PARAMS, CountModel

TEST_SEASONS = [2022, 2023, 2024, 2025, 2026]
OUT = Path("data/raw/count_backtest.csv.gz")
SUMMARY = Path("data/processed/count_validation.json")   # committed: what the track-record page shows for families F-H
COLS = {"corners": ("corners_h", "corners_a"), "cards": (("yellow_h", "red_h"), ("yellow_a", "red_a")), "shots": ("shots_h", "shots_a"), "sot": ("sot_h", "sot_a")}


def counts(m: pd.DataFrame, stat: str) -> tuple[pd.Series, pd.Series]:
    h, a = COLS[stat]
    return (m[h[0]] + m[h[1]], m[a[0]] + m[a[1]]) if stat == "cards" else (m[h], m[a])


def main(sample: int) -> None:
    rows = []
    for lg in LEAGUES.values():
        m = load_seasons(lg.fd_code, list(range(2015, 2027))).sort_values("match_date").reset_index(drop=True)
        target = m[m["season"].isin(TEST_SEASONS)]
        t0, end = target["match_date"].min(), target["match_date"].max()
        while t0 <= end:
            t1 = t0 + timedelta(days=7)
            block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
            if len(block):
                for stat, cfg in STATS.items():
                    ch, ca = counts(m, stat)
                    data = m.assign(count_home=ch, count_away=ca)
                    p = COUNT_PARAMS[stat]
                    model = CountModel(half_life_days=p["half_life_days"], ridge=p["ridge"], max_count=cfg["max"]).fit(data, as_of=t0)
                    bh, ba = counts(block, stat)
                    for r, y1, y2 in zip(block.itertuples(index=False), bh.to_numpy(), ba.to_numpy(), strict=True):
                        if np.isnan(y1) or np.isnan(y2):
                            continue
                        matrix = model.count_matrix(r.home, r.away)
                        for market in (mk for mk in MARKETS.values() if mk.stat == stat):
                            for line in market.lines if market.has_line else (None,):
                                for pr in price(market, line, matrix):
                                    code = int(market.codes(pr["selection"], line, np.array([y1]), np.array([y2]))[0])
                                    y = None if code == PUSH else float(code in (WON, HALF_WON))
                                    rows.append((f"{lg.id}-{r.match_date}-{r.home}", r.match_date, lg.id, market.id, market.family, line, pr["selection"], pr["probability"], y))
            t0 = t1
        print(f"done {lg.id}", flush=True)
    df = pd.DataFrame(rows, columns=["match_id", "date", "league", "market_id", "family", "line", "selection", "p", "y"])
    keep = df["match_id"].drop_duplicates().sample(n=min(sample, df["match_id"].nunique()), random_state=3)
    df = df[df["match_id"].isin(keep)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(df):,} rows, {df['match_id'].nunique():,} matches)")

    summarise(df)


def summarise(df: pd.DataFrame) -> None:
    """Skill over the usual frequency on the later half of the matches (the earlier half supplies the usual frequencies), by statistic and market."""
    df = df.dropna(subset=["y"]).assign(date=lambda d: pd.to_datetime(d["date"]))
    cut = df["date"].sort_values().iloc[int(len(df) * 0.5)]
    fit, test = df[df["date"] < cut], df[df["date"] >= cut]
    scored = score_rows(test, base_rates(fit))
    scored["stat"] = scored["market_id"].str.split("_").str[0]
    print("\nHELD-OUT: skill over the usual frequency (positive is better)")
    for stat, g in scored.groupby("stat"):
        print(f"  {stat:8} selections {len(g):7,}  skill {1 - g['ll_model'].sum() / g['ll_base'].sum():+.4f}")
    for mid, g in scored.groupby("market_id"):
        print(f"    {mid:20} skill {1 - g['ll_model'].sum() / g['ll_base'].sum():+.4f}  n={len(g):,}")
    families = [{"family": fam, "selections": len(g), "model": round(float(g["ll_model"].mean()), 4), "base": round(float(g["ll_base"].mean()), 4),
                 "skill": round(float(1 - g["ll_model"].sum() / g["ll_base"].sum()), 4)} for fam, g in scored.groupby("family")]
    calib = [{"from": float(b), "to": float(b) + 0.1, "n": len(g), "predicted": round(float(g["p"].mean()), 4), "actual": round(float(g["y"].mean()), 4)}
             for b, g in scored.assign(band=(np.minimum(scored["p"], 0.9999) * 10).astype(int) / 10).groupby("band")]
    SUMMARY.write_text(json.dumps({"matches": int(df["match_id"].nunique()), "families": families, "calibration": calib}, indent=1), encoding="utf-8")
    print(f"wrote {SUMMARY}")


if __name__ == "__main__":
    if "--summary" in sys.argv:      # re-summarise the saved backtest without re-running it
        summarise(pd.read_csv(OUT))
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 3000)
