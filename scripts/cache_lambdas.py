"""Walk-forward cache of the goals model's expected goals, so calibration, rest-day and lineup ideas can be tested without refitting the model each time.

For each 14-day block from 2019/20 on, refit the production goals model (0.3.0 settings) on matches strictly before the block, then store for every match in the block
the expected goals before and after the total-goals compression, plus the fit's low-score parameter and reference total. Matches are read from the database
(`matches`, finished only), read-only.

    uv run python scripts/cache_lambdas.py EPL        # one league -> data/processed/lambdas_EPL.pkl
Run the five rated leagues in parallel, then `scripts/improve_totals.py` and the other experiments read the pickles.
"""
import copy
import os
import sys
from datetime import timedelta

import pandas as pd
import psycopg

from pitchside.db.migrate import _load_env
from pitchside.pipeline.weekly import load_history, make_model

FIRST = 2019     # first evaluated season (2019/20); 2015 to 2018 are history only
STEP_DAYS = 14


def main(league: str) -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        m = load_history(conn, league).sort_values("match_date").reset_index(drop=True)
    target = m[m["season"] >= FIRST]
    t0, end = target["match_date"].min(), target["match_date"].max()
    rows = []
    while t0 <= end:
        t1 = t0 + timedelta(days=STEP_DAYS)
        block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
        if len(block):
            model = make_model().fit(m, as_of=t0)
            raw = copy.copy(model)
            raw.total_compression = 1.0
            for r in block.itertuples(index=False):
                lh, la = model.lambdas(r.home, r.away)
                rh, ra = raw.lambdas(r.home, r.away)
                rows.append({"league": league, "season": r.season, "match_date": r.match_date, "home": r.home, "away": r.away,
                             "ft_home": r.ft_home, "ft_away": r.ft_away, "lam_h": lh, "lam_a": la, "raw_h": rh, "raw_a": ra,
                             "rho": model.rho, "ref_log_total": model.ref_log_total, "known": model.known(r.home) and model.known(r.away)})
        t0 = t1
        print(league, t0, flush=True)
    pd.DataFrame(rows).to_pickle(f"data/processed/lambdas_{league}.pkl")
    print("saved", league, len(rows))


if __name__ == "__main__":
    main(sys.argv[1])
