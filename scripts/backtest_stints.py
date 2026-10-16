"""Does carrying a club's rating to its next league with a discount (models/stints.py) beat rating each league alone? Walk-forward, 0.3.0 settings.

Premier League + Championship, every match from 2022/23 on, refit every `step_days`. Compared: the single-league model in production, and the stint model
with several `carry` values (0 = nothing carried over; 1 = the full standing carried over). Scored on all matches and on the matches of clubs that changed league.
The carry is chosen on 2022/23 and 2023/24 and then reported on 2024/25 onward, so the winner is not picked on the matches it is judged on.

    uv run python scripts/backtest_stints.py [step_days]
"""
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, os.path.dirname(__file__))
from backtest_pyramid import LEAGUES, TEST_START, binary_ll, load

from pitchside.db.migrate import _load_env
from pitchside.models.evaluate import (
    btts_probability,
    log_loss,
    over_probability,
    result_probs,
)
from pitchside.models.stints import StintDixonColes
from pitchside.pipeline.weekly import MODEL_PARAMS, make_model

CARRIES = [0.0, 0.5, 0.75, 1.0]
SELECTION_END = pd.Timestamp("2024-07-31").date()      # carry chosen on matches before this, judged on matches after


def stint_model(target: str, carry: float) -> StintDixonColes:
    return StintDixonColes(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"], level_window_days=MODEL_PARAMS["level_window_days"],
                           level_shrink=MODEL_PARAMS["level_shrink"], total_compression=MODEL_PARAMS["total_compression"], target_league=target, carry=carry)


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
            models = {"single": make_model().fit(df[df["league"] == lg], as_of=block)}
            for c in CARRIES:
                models[f"carry{c}"] = stint_model(lg, c).fit(df, as_of=block)
            for r in tgt.itertuples(index=False):
                h = hist[((hist["home"] == r.home) | (hist["away"] == r.home) | (hist["home"] == r.away) | (hist["away"] == r.away)) & (hist["match_date"] >= r.match_date - timedelta(days=400))]
                def moved(team, lg=lg, r=r, h=h):
                    t = h[(h["home"] == team) | (h["away"] == team)]
                    return bool((t["league"] != lg).any() and (t["league"] == lg).sum() < 25)
                row = {"league": lg, "date": r.match_date, "mover": moved(r.home) or moved(r.away),
                       "y": 0 if r.ft_home > r.ft_away else 1 if r.ft_home == r.ft_away else 2,
                       "over": int(r.ft_home + r.ft_away > 2.5), "btts": int(r.ft_home > 0 and r.ft_away > 0)}
                for name, model in models.items():
                    p = model.score_matrix(r.home, r.away)
                    row[f"{name}_1x2"] = result_probs(p)
                    row[f"{name}_over"], row[f"{name}_btts"] = over_probability(p, 2.5), btts_probability(p)
                rows.append(row)
        print(block, len(rows), flush=True)
        block = nxt
    out = pd.DataFrame(rows)
    out.to_pickle("data/processed/stints_backtest.pkl")
    report(out)


def summarise(d: pd.DataFrame, names: list[str]) -> dict:
    y = d["y"].to_numpy()
    res = {"n": len(d)}
    for name in names:
        res[f"{name}"] = log_loss(np.array(list(d[f"{name}_1x2"])), y)
    for name in names:
        res[f"{name}_ou"] = binary_ll(d[f"{name}_over"], d["over"])
    return res


def report(out: pd.DataFrame) -> None:
    names = ["single", *[f"carry{c}" for c in CARRIES]]
    pd.set_option("display.width", 250)
    for label, sub_all in (("SELECTION period (to July 2024)", out[out["date"] <= SELECTION_END]), ("JUDGED period (from August 2024)", out[out["date"] > SELECTION_END])):
        table = {}
        for lg in LEAGUES:
            sub = sub_all[sub_all["league"] == lg]
            table[f"{lg} all"] = summarise(sub, names)
            table[f"{lg} club changed league"] = summarise(sub[sub["mover"]], names)
        print(f"\n{label}: match-result log loss (lower is better), then over/under 2.5")
        print(pd.DataFrame(table).T.round(4).to_string())


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 14)
