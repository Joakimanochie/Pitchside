"""Step 2 of docs/model-improvement-research.md: do rest days and fixture congestion (including European weeks) explain goals the model misses?

For every match in the cached walk-forward expected goals (`scripts/cache_lambdas.py`), each team gets: a short rest before the match (3 days or fewer, 4 days, 5 to 6 days; 7 or more is the reference),
whether the previous match was in the Champions League or Europa League, and whether the next match is a European one within 4 days (rotation). Previous and next matches are
read from every finished match in the database (all six domestic leagues and both European cups; domestic cups are not in the database).
A Poisson regression of goals, with the model's expected goals as the offset, is fitted on the tuning seasons 2019/20 to 2021/22: log lambda = log model + own features + opponent's features.
Then the adjusted expected goals are priced and scored on 2022/23 onwards. Log loss, lower is better.

    uv run python scripts/improve_rest.py
"""
import os

import numpy as np
import pandas as pd
import psycopg
from improve_totals import LEAGUES, TEST, TUNE, actuals, ll, price

from pitchside.db.migrate import _load_env

NAMES = ["rest<=3", "rest4", "rest5-6", "prev euro", "next euro<=4d"]


def team_schedule(conn) -> dict:
    """{team: DataFrame(match_date, euro)} of every finished match of the team, sorted by date."""
    rows = conn.execute(
        "SELECT m.match_date, m.league_id, th.canonical_name, ta.canonical_name FROM matches m JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.status = 'finished' ORDER BY m.match_date").fetchall()
    per: dict = {}
    for d, lg, h, a in rows:
        for t in (h, a):
            per.setdefault(t, []).append((pd.Timestamp(d), lg in ("CL", "EL")))
    return {t: pd.DataFrame(v, columns=["date", "euro"]).drop_duplicates("date").reset_index(drop=True) for t, v in per.items()}


def features(sched: dict, team: str, date) -> list[float]:
    s = sched.get(team)
    if s is None:
        return [0.0] * len(NAMES)
    d = pd.Timestamp(date)
    i = s["date"].searchsorted(d)             # index of the first match on or after d (the match itself)
    rest = (d - s["date"].iloc[i - 1]).days if i > 0 else 99
    prev_euro = bool(s["euro"].iloc[i - 1]) if i > 0 else False
    nxt = i + 1 if i < len(s) and s["date"].iloc[i] == d else i
    next_euro = bool(nxt < len(s) and s["euro"].iloc[nxt] and (s["date"].iloc[nxt] - d).days <= 4)
    return [float(rest <= 3), float(rest == 4), float(rest in (5, 6)), float(prev_euro), float(next_euro)]


def fit_poisson(X, y, offset, ridge=1.0, iters=25):
    """Newton / IRLS for log mu = offset + X beta, with a small ridge. Returns beta and standard errors."""
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        mu = np.exp(offset + X @ beta)
        grad = X.T @ (y - mu) - ridge * beta
        hess = (X * mu[:, None]).T @ X + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    mu = np.exp(offset + X @ beta)
    cov = np.linalg.inv((X * mu[:, None]).T @ X + ridge * np.eye(X.shape[1]))
    return beta, np.sqrt(np.diag(cov))


def main() -> None:
    _load_env()
    df = pd.concat([pd.read_pickle(f"data/processed/lambdas_{lg}.pkl") for lg in LEAGUES], ignore_index=True).sort_values("match_date").reset_index(drop=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        sched = team_schedule(conn)
    fh = np.array([features(sched, r.home, r.match_date) for r in df.itertuples()])
    fa = np.array([features(sched, r.away, r.match_date) for r in df.itertuples()])
    print("share of team-matches with each feature:", dict(zip(NAMES, np.round(np.r_[fh, fa].mean(0), 3), strict=True)))
    tune_m = df.season.between(*TUNE).to_numpy()
    test_m = df.season.between(*TEST).to_numpy()

    def design(own, opp):
        return np.hstack([own, opp])

    # stack home and away goals: own features are the scoring team's, opponent features the defending team's
    X = np.vstack([design(fh[tune_m], fa[tune_m]), design(fa[tune_m], fh[tune_m])])
    y = np.r_[df.ft_home[tune_m], df.ft_away[tune_m]].astype(float)
    off = np.log(np.r_[df.lam_h[tune_m], df.lam_a[tune_m]])
    beta, se = fit_poisson(X, y, off)
    print("\ncoefficients on the log of expected goals, tuning seasons (effect on a team's scoring; z = coefficient / standard error):")
    for i, n in enumerate(NAMES):
        print(f"  own {n:15s} {beta[i]:+.3f}  (z {beta[i] / se[i]:+.1f})")
    for i, n in enumerate(NAMES):
        print(f"  opponent {n:10s} {beta[len(NAMES) + i]:+.3f}  (z {beta[len(NAMES) + i] / se[len(NAMES) + i]:+.1f})")

    test = df[test_m].reset_index(drop=True)
    y_s = actuals(test)
    keys = list(y_s)
    base = price(test, test.lam_h.to_numpy(), test.lam_a.to_numpy())
    adj_h = test.lam_h.to_numpy() * np.exp(design(fh[test_m], fa[test_m]) @ beta)
    adj_a = test.lam_a.to_numpy() * np.exp(design(fa[test_m], fh[test_m]) @ beta)
    adj = price(test, adj_h, adj_a)
    out = pd.DataFrame({"baseline": {k: ll(base[k], y_s[k]) for k in keys}, "with rest and congestion": {k: ll(adj[k], y_s[k]) for k in keys}})
    out["difference"] = out["with rest and congestion"] - out["baseline"]
    out.to_csv("data/processed/improve_rest.csv")
    print("\ntest seasons 2022/23 onwards: log loss (negative difference = better)")
    print(out.round(5).to_string())


if __name__ == "__main__":
    main()
