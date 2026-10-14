"""Are clubs with little recent history in a league (newly promoted sides) rated too high by the goals model?

For every held-out match (2022/23 onwards, weekly refits, 0.3.0 settings) compare the goals each side actually scored and conceded with what the model expected,
grouped by how many matches the club had played in this league in the previous three years. A club with few matches is shrunk toward the league average; if promoted
sides are really weaker than average, their goals scored come in below and goals conceded above what the model expects.

Usage: uv run python scripts/analyse_promoted.py
"""
import functools
from datetime import timedelta

import numpy as np
import pandas as pd

from pitchside.ingest.footballdata import load_seasons
from pitchside.leagues import LEAGUES
from pitchside.models.dixon_coles import DixonColes
from pitchside.pipeline.weekly import MODEL_PARAMS

TEST = [2022, 2023, 2024, 2025, 2026]
BINS = [(0, 15, "under 15 matches (promoted)"), (15, 40, "15-39"), (40, 80, "40-79"), (80, 10_000, "80 or more")]


def main() -> None:
    cls = functools.partial(DixonColes, level_window_days=MODEL_PARAMS["level_window_days"], level_shrink=MODEL_PARAMS["level_shrink"],
                            total_compression=MODEL_PARAMS["total_compression"])
    rows = []
    for lg in LEAGUES.values():
        m = load_seasons(lg.fd_code, list(range(2015, 2027)))[["season", "match_date", "home", "away", "ft_home", "ft_away"]].sort_values("match_date").reset_index(drop=True)
        dates = m["match_date"].to_numpy()
        teams_of = {t: np.flatnonzero(((m["home"] == t) | (m["away"] == t)).to_numpy()) for t in set(m["home"]) | set(m["away"])}
        target = m[m["season"].isin(TEST)]
        t0, end = target["match_date"].min(), target["match_date"].max()
        while t0 <= end:
            t1 = t0 + timedelta(days=7)
            block = target[(target["match_date"] >= t0) & (target["match_date"] < t1)]
            if len(block):
                model = cls(half_life_days=MODEL_PARAMS["half_life_days"], ridge=MODEL_PARAMS["ridge"]).fit(m, as_of=t0)
                for r in block.itertuples(index=False):
                    lam_h, lam_a = model.lambdas(r.home, r.away)
                    for team, gf, ga, e_for, e_against in ((r.home, r.ft_home, r.ft_away, lam_h, lam_a), (r.away, r.ft_away, r.ft_home, lam_a, lam_h)):
                        idx = teams_of[team]
                        prev = int(((dates[idx] < r.match_date) & (dates[idx] >= r.match_date - timedelta(days=3 * 365))).sum())
                        rows.append({"league": lg.id, "prev": prev, "gf": gf, "ga": ga, "e_for": e_for, "e_against": e_against})
            t0 = t1
        print(f"done {lg.id}", flush=True)
    df = pd.DataFrame(rows)
    out = []
    for lo, hi, label in BINS:
        g = df[(df["prev"] >= lo) & (df["prev"] < hi)]
        se_for = float(np.sqrt(g["e_for"].sum())) / len(g) if len(g) else np.nan   # Poisson standard error of the mean residual
        out.append({"matches_in_last_3_years": label, "team_matches": len(g), "scored": g["gf"].mean(), "expected_scored": g["e_for"].mean(),
                    "conceded": g["ga"].mean(), "expected_conceded": g["e_against"].mean(),
                    "scored_gap": g["gf"].mean() - g["e_for"].mean(), "conceded_gap": g["ga"].mean() - g["e_against"].mean(), "std_error": se_for})
    res = pd.DataFrame(out)
    res.to_csv("data/processed/promoted_analysis.csv", index=False)
    pd.set_option("display.width", 220)
    print(res.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
