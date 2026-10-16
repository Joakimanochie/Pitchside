"""Backtest the card timing markets (cards by half, first card, a card by a minute) on matches the models never saw.

Walk-forward, as in production: each week the cards count model of every league is refit on matches before it, the card profile (first-half share and
minute pattern) is refit on the cards logged before it, every market is priced for the week's matches and settled from the real cards of the match with the
production settlement function. Only matches whose ESPN log was verified against the real card counts are used.

Writes data/raw/cardtiming_backtest.csv.gz (match_id, date, league, market_id, family, line, selection, p, y; not committed) for the confidence ratings and
prints calibration and skill over how often each selection usually happens (the earlier half of the matches supplies the usual frequencies).
Reads the production database (SELECT only).   Usage: uv run python scripts/backtest_cardtiming.py [first_date]
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import psycopg

from pitchside.confidence import base_rates, score_rows
from pitchside.db.migrate import _load_env
from pitchside.markets.cardtiming import MARKETS, settle_card_timing
from pitchside.markets.counts import STATS
from pitchside.models.cardtiming import CardProfile, price_card_timing
from pitchside.models.counts import COUNT_PARAMS, CountModel
from pitchside.pipeline.weekly import load_count_history

OUT = Path("data/raw/cardtiming_backtest.csv.gz")


def main(first: str) -> None:
    _load_env()
    start = pd.Timestamp(first).date()
    rows = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        leagues = [r[0] for r in conn.execute("SELECT DISTINCT league_id FROM matches WHERE source_ids ->> 'espn_log' = 'true'")]
        logged = pd.DataFrame(conn.execute(
            "SELECT m.id, m.league_id, m.match_date, th.canonical_name, ta.canonical_name, m.home_team_id FROM matches m JOIN teams th ON th.id = m.home_team_id "
            "JOIN teams ta ON ta.id = m.away_team_id WHERE m.source_ids ->> 'espn_log' = 'true' ORDER BY m.match_date, m.id").fetchall(),
            columns=["id", "league", "date", "home", "away", "home_id"])
        events = pd.DataFrame(conn.execute(
            "SELECT c.match_id, c.team_id, c.period, c.minute FROM card_events c ORDER BY c.id").fetchall(), columns=["match_id", "team_id", "period", "minute"])
        histories = {lg: load_count_history(conn, lg) for lg in leagues}
    by_match = {mid: g for mid, g in events.groupby("match_id")}
    home_of = dict(zip(logged["id"], logged["home_id"], strict=True))
    event_dates = events.merge(logged[["id", "date"]], left_on="match_id", right_on="id")
    end = logged["date"].max()
    for lg in leagues:
        h = histories[lg]
        data = h.assign(count_home=h["cards_h"], count_away=h["cards_a"])
        block = start
        while block <= end:
            nxt = block + timedelta(days=7)
            week = logged[(logged["league"] == lg) & (logged["date"] >= block) & (logged["date"] < nxt)]
            past = event_dates[event_dates["date"] < block]
            if len(week) and len(past) >= 500:
                profile = CardProfile.fit(past["period"].to_numpy(), past["minute"].to_numpy())
                model = CountModel(half_life_days=COUNT_PARAMS["cards"]["half_life_days"], ridge=COUNT_PARAMS["cards"]["ridge"], max_count=STATS["cards"]["max"]).fit(data, as_of=block)
                for r in week.itertuples(index=False):
                    g = by_match.get(r.id)
                    cards = [] if g is None else [["home" if t == home_of[r.id] else "away", p, m] for t, p, m in zip(g["team_id"], g["period"], g["minute"], strict=True)]
                    for pr in price_card_timing(model.count_matrix(r.home, r.away), profile, MARKETS):
                        res = settle_card_timing(MARKETS[pr["market_id"]], pr["line"], pr["selection"], cards)
                        rows.append((r.id, r.date, lg, pr["market_id"], "G", pr["line"], pr["selection"], pr["probability"], res["outcome_value"]))
            block = nxt
        print(f"done {lg}", flush=True)
    df = pd.DataFrame(rows, columns=["match_id", "date", "league", "market_id", "family", "line", "selection", "p", "y"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(df):,} rows, {df['match_id'].nunique():,} matches)")
    summarise(df)


def summarise(df: pd.DataFrame) -> None:
    df = df.dropna(subset=["y"]).assign(date=lambda d: pd.to_datetime(d["date"]))
    cut = df["date"].sort_values().iloc[int(len(df) * 0.5)]
    fit, test = df[df["date"] < cut], df[df["date"] >= cut]
    scored = score_rows(test, base_rates(fit))
    print(f"\nHELD-OUT (earlier half before {cut.date()} supplies the usual frequencies): skill over the usual frequency")
    for mid, g in scored.groupby("market_id"):
        print(f"  {mid:18} skill {1 - g['ll_model'].sum() / g['ll_base'].sum():+.4f}  n={len(g):,}  predicted {g['p'].mean():.3f} happened {g['y'].mean():.3f}")
    band = pd.cut(scored["p"], [0, 0.1, 0.25, 0.4, 0.6, 0.75, 0.9, 1.0])
    print(scored.assign(band=band).groupby("band", observed=True).agg(n=("p", "size"), predicted=("p", "mean"), happened=("y", "mean")).round(3).to_string())


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summarise(pd.read_csv(OUT))
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "2024-02-01")
