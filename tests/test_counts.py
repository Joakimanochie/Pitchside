import datetime as dt
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pitchside.db.markets import seed_markets
from pitchside.db.predictions import create_run, ensure_model_version, write_predictions
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.markets.base import price
from pitchside.markets.counts import CARDS, MARKETS, STATS, stat_value
from pitchside.markets.registry import MARKETS as ALL_MARKETS
from pitchside.models.counts import CountModel
from pitchside.pipeline.weekly import (
    COUNT_MODEL_VERSION,
    load_count_history,
    predict_counts,
)
from pitchside.settle.settle import settle_all

# ---- markets ---------------------------------------------------------------------------------------------------


def test_every_statistic_has_its_markets_in_the_right_family():
    ids = set(MARKETS)
    for stat, cfg in STATS.items():
        for suffix in ("ou_total", "ou_home", "ou_away", "x12", "ah"):
            assert f"{stat}_{suffix}" in ids
            assert MARKETS[f"{stat}_{suffix}"].family == cfg["family"] and MARKETS[f"{stat}_{suffix}"].stat == stat
    assert {m.family for m in MARKETS.values()} == {"F", "G", "H"}
    assert set(MARKETS) <= set(ALL_MARKETS) and not (set(MARKETS) & {"ou_total", "1x2"})


def test_count_markets_reuse_the_goal_rules_on_counts():
    m = MARKETS["corners_ou_total"]
    h, a = np.array([6, 4, 5]), np.array([5, 4, 4])
    assert m.codes("over", 9.5, h, a).tolist() == [4, 0, 0] and m.codes("under", 9.5, h, a).tolist() == [0, 4, 4]
    x12 = MARKETS["cards_x12"]
    assert x12.codes("draw", None, np.array([2, 3]), np.array([2, 1])).tolist() == [4, 0]
    ah = MARKETS["corners_ah"]   # home gives 1.5 corners
    assert ah.codes("home", -1.5, np.array([7]), np.array([5]))[0] == 4 and ah.codes("home", -1.5, np.array([6]), np.array([5]))[0] == 0
    assert MARKETS["corners_range"].codes("9-11", None, np.array([6]), np.array([4]))[0] == 4


def test_prices_sum_to_one_per_market_and_lines_are_half_lines_so_nothing_is_returned():
    model = CountModel(max_count=30)
    model.mu, model.dispersion = np.log(5.0), 0.1
    p = model.count_matrix("A", "B")
    for market in MARKETS.values():
        if market.stat != "corners":
            continue
        for line in market.lines if market.has_line else (None,):
            rows = price(market, line, p)
            if market.exclusive:
                assert sum(r["probability"] for r in rows) == pytest.approx(1.0, abs=1e-6), market.id
            assert all(r["p_push"] < 1e-9 for r in rows), market.id


def test_stat_value_reads_the_right_columns_and_adds_cards():
    row = {"corners": 7.0, "yellow_cards": 2.0, "red_cards": 1.0, "shots": 14.0, "shots_on_target": 5.0}
    assert stat_value("corners", row) == 7 and stat_value("shots", row) == 14 and stat_value("sot", row) == 5
    assert stat_value(CARDS, row) == 3
    assert stat_value("corners", None) is None and stat_value(CARDS, {"yellow_cards": 2.0, "red_cards": None}) is None


# ---- the model -------------------------------------------------------------------------------------------------

def simulate_counts(n_teams=8, seasons=3, seed=0, mean=5.0, dispersion=0.15):
    rng = np.random.default_rng(seed)
    att, dfn = rng.normal(0, 0.25, n_teams), rng.normal(0, 0.2, n_teams)
    rows, day = [], dt.date(2018, 8, 1)
    for s in range(seasons):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                lam_h, lam_a = mean * np.exp(0.15 + att[i] - dfn[j]), mean * np.exp(att[j] - dfn[i])
                r = 1 / dispersion
                rows.append((day + dt.timedelta(days=int(rng.integers(0, 280)) + 365 * s), f"T{i}", f"T{j}",
                             rng.negative_binomial(r, r / (r + lam_h)), rng.negative_binomial(r, r / (r + lam_a))))
    return pd.DataFrame(rows, columns=["match_date", "home", "away", "count_home", "count_away"]).sort_values("match_date").reset_index(drop=True), att


def test_fit_recovers_the_spread_and_orders_teams():
    df, att = simulate_counts(seasons=6)
    model = CountModel(max_count=40).fit(df, as_of=dt.date(2025, 1, 1))
    assert model.dispersion == pytest.approx(0.15, abs=0.06)
    strongest, weakest = int(np.argmax(att)), int(np.argmin(att))
    assert model.attack[f"T{strongest}"] > model.attack[f"T{weakest}"]
    m, n = model.means("T0", "T1")
    assert 2.5 < m < 9 and 2.5 < n < 9


def test_matrix_is_a_probability_distribution_and_unknown_clubs_get_the_average():
    df, _ = simulate_counts()
    model = CountModel(max_count=30).fit(df, as_of=dt.date(2021, 1, 1))
    p = model.count_matrix("T0", "T1")
    assert p.shape == (31, 31) and p.sum() == pytest.approx(1.0)
    assert model.means("Nobody", "T1")[0] == pytest.approx(float(np.exp(model.mu + model.home_adv - model.defence["T1"])))
    assert not model.known("Nobody")


def test_no_leakage_and_missing_counts_are_ignored():
    df, _ = simulate_counts(seasons=3)
    cutoff = dt.date(2020, 3, 1)
    base = CountModel().fit(df, as_of=cutoff).count_matrix("T0", "T1")
    future = df.copy()
    future.loc[future["match_date"] >= cutoff, ["count_home", "count_away"]] = [40, 0]
    np.testing.assert_array_equal(base, CountModel().fit(future, as_of=cutoff).count_matrix("T0", "T1"))
    holes = df.copy()
    holes.loc[holes.index[:10], "count_home"] = np.nan                                 # ten early matches without a count
    assert CountModel().fit(holes, as_of=cutoff).n_matches == CountModel().fit(df, as_of=cutoff).n_matches - 10


def test_needs_enough_matches():
    df, _ = simulate_counts(n_teams=3, seasons=1)
    with pytest.raises(ValueError, match="at least 50"):
        CountModel().fit(df, as_of=dt.date(2030, 1, 1))


# ---- settling and the weekly step --------------------------------------------------------------------------------

@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    seed_markets(conn)
    ensure_model_version(conn, "test-0", "test", {})
    conn.commit()
    return conn


def match_with_stats(conn, home_stats, away_stats, ft=(2, 1)):
    mid = conn.execute(
        "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, ft_home, ft_away) "
        "VALUES ('EPL', 2026, %s, %s, (SELECT id FROM teams WHERE canonical_name = 'Arsenal'), (SELECT id FROM teams WHERE canonical_name = 'Leeds United'), "
        "'finished', %s, %s) RETURNING id", (dt.date(2099, 10, 10), datetime(2099, 10, 10, 14, tzinfo=UTC), ft[0], ft[1])).fetchone()[0]   # kickoff after the prediction, as in real life
    for is_home, st in ((True, home_stats), (False, away_stats)):
        if st is None:
            continue
        conn.execute("INSERT INTO team_match_stats (match_id, team_id, is_home, corners, yellow_cards, red_cards, shots, shots_on_target, source) "
                     "VALUES (%s, (SELECT id FROM teams WHERE canonical_name = %s), %s, %s, %s, %s, %s, %s, 'test')",
                     (mid, "Arsenal" if is_home else "Leeds United", is_home, st["corners"], st["yellow"], st["red"], st["shots"], st["sot"]))
    return mid


def predict(conn, mid, rows):
    run_id = create_run(conn, "weekly", "test-0", "f0", datetime.now(UTC) - timedelta(days=3))
    write_predictions(conn, run_id, mid, rows, ALL_MARKETS, {})


def pr(market_id, selection, p, line=None):
    return {"market_id": market_id, "line": line, "selection": selection, "probability": p, "p_win": p, "p_lose": 1 - p, "p_push": 0.0}


def result(conn, market_id, selection, line=None):
    return conn.execute("SELECT s.result, s.outcome_value, s.observed FROM settlements s JOIN predictions p ON p.id = s.prediction_id "
                        "WHERE p.market_id = %s AND p.selection = %s AND p.line IS NOT DISTINCT FROM %s", (market_id, selection, line)).fetchone()


def test_count_markets_settle_from_team_statistics_not_goals(db):
    mid = match_with_stats(db, {"corners": 7, "yellow": 2, "red": 0, "shots": 15, "sot": 6}, {"corners": 4, "yellow": 3, "red": 1, "shots": 9, "sot": 2}, ft=(2, 1))
    predict(db, mid, [pr("corners_ou_total", "over", 0.5, 10.5), pr("corners_x12", "home", 0.5), pr("cards_ou_total", "over", 0.5, 5.5),
                      pr("cards_ou_away", "over", 0.5, 3.5), pr("shots_ou_total", "under", 0.5, 24.5), pr("sot_ou_home", "over", 0.5, 5.5)])
    settle_all(db)
    assert result(db, "corners_ou_total", "over", 10.5)[:2] == ("won", 1.0)       # 7 + 4 = 11 corners
    assert result(db, "corners_x12", "home")[:2] == ("won", 1.0)
    assert result(db, "cards_ou_total", "over", 5.5)[:2] == ("won", 1.0)           # 2 cards + (3 yellow + 1 red = 4) = 6
    assert result(db, "cards_ou_away", "over", 3.5)[:2] == ("won", 1.0)            # 3 yellow + 1 red = 4 cards
    assert result(db, "shots_ou_total", "under", 24.5)[:2] == ("won", 1.0)         # 24 shots
    assert result(db, "sot_ou_home", "over", 5.5)[:2] == ("won", 1.0)


def test_missing_team_statistics_are_not_scorable_never_guessed(db):
    mid = match_with_stats(db, {"corners": 7, "yellow": 2, "red": 0, "shots": 15, "sot": 6}, None)
    predict(db, mid, [pr("corners_ou_total", "over", 0.5, 8.5), pr("1x2", "home", 0.6)])
    settle_all(db)
    res, val, observed = result(db, "corners_ou_total", "over", 8.5)
    assert (res, val) == ("not_scorable", None) and observed["reason"] == "team_stats_missing"
    assert result(db, "1x2", "home")[0] == "won"


@pytest.fixture()
def world(db):
    """A club pair with enough history of stats to fit the count models, plus one upcoming fixture."""
    rng = np.random.default_rng(0)
    day = dt.date(2025, 1, 1)
    teams = ["Arsenal", "Leeds United", "Chelsea", "Fulham", "Everton", "Brentford"]
    ids = {t: db.execute("SELECT id FROM teams WHERE canonical_name = %s", (t,)).fetchone()[0] for t in teams}
    k = 0
    for rep in range(6):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                k += 1
                mid = db.execute("INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away) "
                                 "VALUES ('EPL', 2025, %s, %s, %s, 'finished', 1, 1) ON CONFLICT DO NOTHING RETURNING id", (day + dt.timedelta(days=k), ids[h], ids[a])).fetchone()
                if mid is None:
                    continue
                for is_home, t in ((True, h), (False, a)):
                    db.execute("INSERT INTO team_match_stats (match_id, team_id, is_home, corners, yellow_cards, red_cards, shots, shots_on_target, source) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'test')", (mid[0], ids[t], is_home, int(rng.poisson(5)), int(rng.poisson(2)), 0, int(rng.poisson(12)), int(rng.poisson(4))))
    kickoff = datetime.now(UTC) + timedelta(days=2)
    db.execute("INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status) VALUES ('EPL', 2026, %s, %s, %s, %s, 'scheduled')",
               (kickoff.date(), kickoff, ids["Arsenal"], ids["Leeds United"]))
    db.commit()
    return db


def test_history_has_both_teams_counts_and_cards_add_yellow_and_red(world):
    h = load_count_history(world, "EPL")
    assert len(h) > 100 and h[["corners_h", "corners_a", "cards_h", "shots_h", "sot_a"]].notna().all().all()


def test_weekly_counts_step_stores_only_count_markets_under_its_own_version_once(world, monkeypatch):
    monkeypatch.setattr("pitchside.pipeline.weekly.MIN_HISTORY_MATCHES", 50)
    today = datetime.now(UTC).date()
    out = predict_counts(world, "EPL", today, days=5)
    assert out["matches"] == 1 and out["predictions"] == 212        # every line of every count market
    versions = {r[0] for r in world.execute("SELECT DISTINCT r.model_version_id FROM predictions p JOIN prediction_runs r ON r.id = p.run_id")}
    assert versions == {COUNT_MODEL_VERSION}
    families = {r[0] for r in world.execute("SELECT DISTINCT mk.family FROM predictions p JOIN markets mk ON mk.id = p.market_id")}
    assert families == {"F", "G", "H"}
    assert predict_counts(world, "EPL", today, days=5)["matches"] == 0          # one official run per match per version
    ctx = world.execute("SELECT context FROM prediction_context").fetchone()[0]
    assert ctx["corners"]["mean_home"] > 0
