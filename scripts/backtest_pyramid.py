"""Does rating clubs across leagues (models/pyramid.py) beat rating each league alone? Walk-forward, production 0.3.0 settings.

For the English pyramid (Premier League + Championship) it predicts every match of each league from 2022/23 on, twice: with the single-league
model in production and with the pyramid model fitted on both leagues. The key rows are matches involving a club that changed league
(few matches in this league lately, but matches in the other league within the previous 400 days).

    uv run python scripts/backtest_pyramid.py [step_days]
"""
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg

from pitchside.db.migrate import _load_env
from pitchside.models.evaluate import (
    btts_probability,
    log_loss,
    over_probability,
    result_probs,
)
from pitchside.models.pyramid import PyramidDixonColes
from pitchside.pipeline.weekly import MODEL_PARAMS, make_model

TEST_START = pd.Timestamp("2022-08-01").date()
LEAGUES = ["EPL", "CHAMP"]


def load(conn, leagues=LEAGUES) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT m.league_id, m.season, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id WHERE m.status = 'finished' AND m.league_id = ANY(%s) "
        "ORDER BY m.match_date", (list(leagues),)).fetchall()
    return pd.DataFrame(rows, columns=["league", "season", "match_date", "home", "away", "ft_home", "ft_away"])


def pyramid_model(target: str) -> PyramidDixonColes:
    return PyramidDixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"], level_window_days=MODEL_PARAMS["level_window_days"],
                             level_shrink=MODEL_PARAMS["level_shrink"], total_compression=MODEL_PARAMS["total_compression"], target_league=target)


def binary_ll(p, o):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return float(-(o * np.log(p) + (1 - o) * np.log(1 - p)).mean())


def main(step_days: int) -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        df = load(conn)
    rows = []
    end = df["match_date"].max()
    block = TEST_START
    while block <= end:
        nxt = block + timedelta(days=step_days)
        chunk = df[(df["match_date"] >= block) & (df["match_date"] < nxt)]
        hist = df[df["match_date"] < block]
        for lg in LEAGUES:
            tgt = chunk[chunk["league"] == lg]
            if tgt.empty:
                continue
            single = make_model().fit(df[df["league"] == lg], as_of=block)
            joint = pyramid_model(lg).fit(df, as_of=block)
            for r in tgt.itertuples(index=False):
                def mover(team, r=r, lg=lg, hist=hist):
                    h = hist[((hist["home"] == team) | (hist["away"] == team)) & (hist["match_date"] >= r.match_date - timedelta(days=400))]
                    return bool((h["league"] != lg).any() and (h["league"] == lg).sum() < 25)
                row = {"league": lg, "date": r.match_date, "mover": mover(r.home) or mover(r.away),
                       "y": 0 if r.ft_home > r.ft_away else 1 if r.ft_home == r.ft_away else 2,
                       "over": int(r.ft_home + r.ft_away > 2.5), "btts": int(r.ft_home > 0 and r.ft_away > 0)}
                for name, model in (("single", single), ("pyramid", joint)):
                    p = model.score_matrix(r.home, r.away)
                    row[f"{name}_1x2"] = result_probs(p)
                    row[f"{name}_over"], row[f"{name}_btts"] = over_probability(p, 2.5), btts_probability(p)
                rows.append(row)
        print(block, len(rows), flush=True)
        block = nxt
    out = pd.DataFrame(rows)
    out.to_pickle("data/processed/pyramid_backtest.pkl")
    report(out)


def summarise(d: pd.DataFrame) -> dict:
    y = d["y"].to_numpy()
    res = {"n": len(d)}
    for name in ("single", "pyramid"):
        res[f"{name}_1x2"] = log_loss(np.array(list(d[f"{name}_1x2"])), y)
        res[f"{name}_ou25"] = binary_ll(d[f"{name}_over"], d["over"])
        res[f"{name}_btts"] = binary_ll(d[f"{name}_btts"], d["btts"])
    return res


def report(out: pd.DataFrame) -> None:
    table = {}
    for lg in LEAGUES:
        sub = out[out["league"] == lg]
        table[f"{lg} all"] = summarise(sub)
        if sub["mover"].any():
            table[f"{lg} club changed league"] = summarise(sub[sub["mover"]])
    t = pd.DataFrame(table).T
    t["d_1x2"] = t["pyramid_1x2"] - t["single_1x2"]
    pd.set_option("display.width", 220)
    print(t.round(4).to_string())
    t.to_csv("data/processed/pyramid_backtest.csv")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 14)
