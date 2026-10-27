"""Step 3 of docs/model-improvement-research.md: what would knowing the starting lineup be worth? (an upper bound, attack side only)

Real lineups of finished matches are known only in hindsight, so this measures the best a lineup signal could do, not what a pre-match injury feed would deliver.
For each team and match (2023/24 onward, the seasons with both ESPN lineups and Understat shots):
  * a player's value is his share of the team's chances: (xG he shot + xG of the shots he assisted) over the team's previous 45 matches, divided by the team's xG in them;
  * the XI's value is the sum of those shares over the players who started the match; its baseline is the average XI value over the team's previous 10 matches;
  * x = XI value minus baseline. Negative means a weaker attacking XI than usual (key attackers rested or injured).
A Poisson regression of goals with the model's expected goals as the offset, log lambda = log model + gamma * x (own team), is fitted on 2024/25 and scored on 2025/26 onwards.
Defenders and goalkeepers carry no chance share here, so the defensive side of a lineup is not measured.

    uv run python scripts/improve_lineups.py
"""
import os
from collections import defaultdict, deque

import numpy as np
import pandas as pd
import psycopg
from improve_rest import fit_poisson
from improve_totals import LEAGUES, actuals, ll, price

from pitchside.db.migrate import _load_env
from pitchside.ingest.lineups import _same_player, norm

WINDOW, BASE_N, MIN_BASE = 45, 10, 5
TUNE_SEASON, TEST_SEASONS = (2024, 2024), (2025, 2026)


def load(conn):
    matches = conn.execute(
        "SELECT m.id, m.league_id, m.season, m.match_date, th.canonical_name, ta.canonical_name, m.home_team_id, m.away_team_id FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE m.status = 'finished' AND m.league_id = ANY(%s) AND m.season >= 2023 ORDER BY m.match_date, m.id", (LEAGUES,)).fetchall()
    ids = [m[0] for m in matches]
    shots = conn.execute("SELECT match_id, team_id, player_name, assist_name, xg FROM shot_events WHERE match_id = ANY(%s) AND result <> 'Own Goal'", (ids,)).fetchall()
    starters = conn.execute("SELECT match_id, team_id, player_name FROM player_match_log WHERE match_id = ANY(%s) AND starter", (ids,)).fetchall()
    return matches, shots, starters


def main() -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        matches, shots, starters = load(conn)
    value = defaultdict(lambda: defaultdict(float))   # (match, team) -> understat name -> xG shot + xG assisted
    team_xg = defaultdict(float)
    roster = defaultdict(set)
    for mid, tid, player, assist, xg in shots:
        xg = float(xg or 0.0)
        team_xg[(mid, tid)] += xg
        roster[tid].add(player)
        value[(mid, tid)][player] += xg
        if assist:
            value[(mid, tid)][assist] += xg
            roster[tid].add(assist)
    start = defaultdict(set)
    cache: dict = {}
    for mid, tid, name in starters:
        key = (tid, name)
        if key not in cache:
            cache[key] = next((r for r in sorted(roster[tid]) if _same_player(norm(r), norm(name))), None)
        if cache[key]:
            start[(mid, tid)].add(cache[key])
    print(f"starters mapped to a player with Understat chances: {sum(len(v) for v in start.values()) / max(1, len(starters)):.1%} of {len(starters):,} ESPN starters "
          "(the rest are mostly goalkeepers and defenders with no shots)")

    history: dict = defaultdict(lambda: deque(maxlen=WINDOW))
    base_hist: dict = defaultdict(lambda: deque(maxlen=BASE_N))
    rows = []
    for mid, lg, season, date, home, away, hid, aid in matches:
        x = {}
        for tid in (hid, aid):
            h = history[tid]
            tot = sum(t for _, t in h)
            if (mid, tid) in start and len(base_hist[tid]) >= MIN_BASE and tot > 0:
                share = defaultdict(float)
                for v, _ in h:
                    for p, val in v.items():
                        share[p] += val
                xi = sum(share[p] / tot for p in start[(mid, tid)])
                x[tid] = (xi, xi - float(np.mean(base_hist[tid])))
                base_hist[tid].append(xi)
            elif (mid, tid) in start and tot > 0:
                share = defaultdict(float)
                for v, _ in h:
                    for p, val in v.items():
                        share[p] += val
                base_hist[tid].append(sum(share[p] / tot for p in start[(mid, tid)]))
        if hid in x and aid in x:
            rows.append({"league": lg, "match_date": date, "home": home, "away": away, "x_home": x[hid][1], "x_away": x[aid][1]})
        for tid in (hid, aid):
            history[tid].append((dict(value[(mid, tid)]), team_xg[(mid, tid)]))
    feat = pd.DataFrame(rows)
    feat["match_date"] = pd.to_datetime(feat["match_date"]).dt.date
    print(f"matches with a usable lineup signal for both teams: {len(feat):,}; spread of x (standard deviation): home {feat.x_home.std():.3f}, away {feat.x_away.std():.3f}")

    cache_df = pd.concat([pd.read_pickle(f"data/processed/lambdas_{lg}.pkl") for lg in LEAGUES], ignore_index=True)
    cache_df["match_date"] = pd.to_datetime(cache_df["match_date"]).dt.date
    df = cache_df.merge(feat, on=["league", "match_date", "home", "away"], how="inner").sort_values("match_date").reset_index(drop=True)
    tune = df[df.season.between(*TUNE_SEASON)].reset_index(drop=True)
    test = df[df.season.between(*TEST_SEASONS)].reset_index(drop=True)
    print(f"tune {len(tune):,} matches (2024/25), test {len(test):,} (2025/26 onward)")

    X = np.r_[tune.x_home, tune.x_away][:, None]
    y = np.r_[tune.ft_home, tune.ft_away].astype(float)
    off = np.log(np.r_[tune.lam_h, tune.lam_a])
    beta, se = fit_poisson(X, y, off)
    print(f"\ngamma (effect of the XI's attacking value, minus its usual, on log expected goals): {beta[0]:+.3f}  (z {beta[0] / se[0]:+.1f})")
    print(f"  so a lineup that is one standard deviation weaker than usual changes the team's expected goals by about {100 * (np.exp(beta[0] * -feat.x_home.std()) - 1):+.1f}%")

    for name, part in (("2025/26 onward, fitted on itself", test), ("all matches pooled", df)):
        b2, s2 = fit_poisson(np.r_[part.x_home, part.x_away][:, None], np.r_[part.ft_home, part.ft_away].astype(float), np.log(np.r_[part.lam_h, part.lam_a]))
        print(f"  gamma, {name}: {b2[0]:+.3f}  (z {b2[0] / s2[0]:+.1f})")

    y_s = actuals(test)
    base = price(test, test.lam_h.to_numpy(), test.lam_a.to_numpy())
    adj = price(test, (test.lam_h * np.exp(beta[0] * test.x_home)).to_numpy(), (test.lam_a * np.exp(beta[0] * test.x_away)).to_numpy())
    keys = list(y_s)
    out = pd.DataFrame({"baseline": {k: ll(base[k], y_s[k]) for k in keys}, "with actual lineup": {k: ll(adj[k], y_s[k]) for k in keys}})
    out["difference"] = out["with actual lineup"] - out["baseline"]
    out.to_csv("data/processed/improve_lineups.csv")
    print("\ntest seasons: log loss (negative difference = better)")
    print(out.round(5).to_string())


if __name__ == "__main__":
    main()
