import datetime as dt
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from pitchside.db.markets import seed_markets
from pitchside.db.predictions import create_run, ensure_model_version, write_predictions
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.espn_log import (
    _minute,
    parse_log,
    store_log,
    verified,
)
from pitchside.markets.cardtiming import MARKETS as TIMING
from pitchside.markets.cardtiming import settle_card_timing
from pitchside.markets.players import MARKETS as PLAYER
from pitchside.markets.registry import MARKETS
from pitchside.models.cardtiming import (
    CardProfile,
    half_grid,
    price_card_timing,
    total_distribution,
)
from pitchside.models.players import LogRates, apply_lineup_log, card_rate, log_rates
from pitchside.settle.settle import settle_all


def matrix(lam_h=1.5, lam_a=1.9, n=13):
    k = np.arange(n)
    p = np.outer(poisson.pmf(k, lam_h), poisson.pmf(k, lam_a))
    return p / p.sum()


def profile(share=0.4):
    g = np.cumsum(np.concatenate([[0.0], np.full(45, share / 45), np.full(55, (1 - share) / 55)]))
    return CardProfile(first_half_share=share, by_minute=g / g[-1], n_cards=5000)


# ---- settlement --------------------------------------------------------------------------------------------------

CARDS = [["away", 1, 23], ["home", 1, 40], ["home", 2, 55], ["away", 2, 88]]


def test_cards_by_half_and_half_with_most():
    assert settle_card_timing(TIMING["cards_h1_ou"], 1.5, "over", CARDS)["outcome_value"] == 1.0       # two in the first half
    assert settle_card_timing(TIMING["cards_h1_ou"], 2.5, "over", CARDS)["outcome_value"] == 0.0
    assert settle_card_timing(TIMING["cards_h2_ou"], 1.5, "under", CARDS)["outcome_value"] == 0.0
    assert settle_card_timing(TIMING["cards_half_most"], None, "equal", CARDS)["outcome_value"] == 1.0
    assert settle_card_timing(TIMING["cards_half_most"], None, "1st", CARDS + [["home", 2, 90]])["outcome_value"] == 0.0


def test_first_card_team_and_card_by_a_minute():
    assert settle_card_timing(TIMING["first_card_team"], None, "away", CARDS)["outcome_value"] == 1.0
    assert settle_card_timing(TIMING["first_card_team"], None, "none", [])["outcome_value"] == 1.0
    assert settle_card_timing(TIMING["first_card_by"], 30, "yes", CARDS)["outcome_value"] == 1.0     # a card at 23'
    assert settle_card_timing(TIMING["first_card_by"], 15, "yes", CARDS)["outcome_value"] == 0.0
    assert settle_card_timing(TIMING["first_card_by"], 15, "no", [])["outcome_value"] == 1.0


# ---- pricing -----------------------------------------------------------------------------------------------------

def test_card_timing_prices_are_coherent():
    rows = price_card_timing(matrix(), profile(), TIMING)
    by = {(r["market_id"], r["line"], r["selection"]): r["probability"] for r in rows}
    assert by[("cards_half_most", None, "1st")] + by[("cards_half_most", None, "2nd")] + by[("cards_half_most", None, "equal")] == pytest.approx(1)
    assert sum(by[("first_card_team", None, s)] for s in ("home", "away", "none")) == pytest.approx(1)
    assert by[("first_card_team", None, "none")] == pytest.approx(matrix()[0, 0])
    assert by[("first_card_team", None, "away")] > by[("first_card_team", None, "home")]        # the away side is expected to get more
    assert by[("cards_h1_ou", 0.5, "over")] > by[("cards_h1_ou", 1.5, "over")] > by[("cards_h1_ou", 2.5, "over")]
    assert by[("cards_h2_ou", 1.5, "over")] > by[("cards_h1_ou", 1.5, "over")]                  # more cards after the break (60% of them)
    assert by[("first_card_by", 15, "yes")] < by[("first_card_by", 30, "yes")] < by[("first_card_by", 45, "yes")] < 1 - matrix()[0, 0]
    for r in rows:
        assert 0 <= r["probability"] <= 1 and r["market_id"] in MARKETS


def test_half_grid_splits_the_same_total():
    m = matrix()
    grid = half_grid(m, 0.4)
    assert grid.sum() == pytest.approx(1)
    a, b = np.indices(grid.shape)
    assert np.bincount((a + b).ravel(), weights=grid.ravel())[: len(total_distribution(m))] == pytest.approx(total_distribution(m))
    assert (grid * a).sum() / (grid * (a + b)).sum() == pytest.approx(0.4)


def test_profile_is_read_from_past_cards():
    rng = np.random.default_rng(0)
    minutes = np.concatenate([rng.integers(1, 46, 400), rng.integers(46, 91, 600)])
    periods = np.where(minutes <= 45, 1, 2)
    p = CardProfile.fit(periods, minutes)
    assert p.first_half_share == pytest.approx(0.4) and p.by_minute[45] == pytest.approx(0.4, abs=0.01) and p.by_minute[-1] == pytest.approx(1)
    with pytest.raises(ValueError):
        CardProfile.fit(periods[:100], minutes[:100])


# ---- the ESPN log --------------------------------------------------------------------------------------------------

def payload(cards=((1, "yellow-card", "Millwall", "A"), (2, "yellow-card", "Portsmouth", "C"))):
    ros = lambda side, names: {"homeAway": side, "roster": [{"starter": i < 11, "athlete": {"displayName": n}, "stats": [
        {"name": "foulsCommitted", "value": 2.0 if n == "A" else 0.0}, {"name": "foulsSuffered", "value": 1.0},
        {"name": "yellowCards", "value": 1.0 if n in ("A", "C") else 0.0}, {"name": "redCards", "value": 0.0}, {"name": "appearances", "value": 1.0}]} for i, n in enumerate(names)]}
    return {"header": {"competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": "Millwall"}}, {"homeAway": "away", "team": {"displayName": "Portsmouth"}}]}]},
            "keyEvents": [{"type": {"type": t}, "team": {"displayName": team}, "clock": {"displayValue": "36'" if period == 1 else "70'"}, "period": {"number": period},
                           "participants": [{"athlete": {"displayName": who}}]} for period, t, team, who in cards],
            "rosters": [ros("home", ["A", *[f"H{i}" for i in range(10)], "Sub"]), ros("away", ["C", *[f"P{i}" for i in range(10)], "Sub2"])]}


def test_log_is_parsed_and_only_trusted_when_the_cards_add_up():
    parsed = parse_log(payload())
    assert [(c["side"], c["period"], c["minute"], c["card"]) for c in parsed["cards"]] == [("home", 1, 36, "yellow"), ("away", 2, 70, "yellow")]
    a = next(p for p in parsed["players"] if p["player"] == "A")
    assert a["fouls_committed"] == 2 and a["yellow"] == 1 and a["starter"] and a["played"]
    assert verified(parsed, {"home": 1, "away": 1})
    assert not verified(parsed, {"home": 2, "away": 1}) and not verified(parsed, {"home": 1, "away": None})
    assert parse_log({}) is None and _minute("45'+3'") == 45


def test_a_card_that_cannot_be_placed_discards_the_log():
    assert parse_log(payload(cards=((1, "yellow-card", "Somebody Else", "A"),))) is None


# ---- player rates and settlement end to end -------------------------------------------------------------------------

def test_player_card_rate_follows_his_record_and_the_clubs_expected_cards():
    log = pd.DataFrame({"match_id": [1, 1, 2, 2, 3, 3], "player": ["A", "B"] * 3, "cards": [1, 0, 1, 0, 0, 1], "fouls": [2, 0, 1, 0, 1, 1], "fouled": [0, 1, 0, 1, 0, 0]})
    rates = log_rates(log, [3, 2, 1], half_life_matches=10.0)
    base = card_rate(rates, club_expected_cards=rates.team_cards / rates.weight)
    assert base["A"] > base["B"] > 0
    assert card_rate(rates, club_expected_cards=2 * rates.team_cards / rates.weight)["A"] == pytest.approx(2 * base["A"])
    out = apply_lineup_log(rates, starters={"B"}, bench=set()).players
    assert out.loc["A"].sum() == 0 and out.loc["B", "cards"] >= rates.players.loc["B", "cards"]


@pytest.fixture()
def db(conn):
    seed_leagues(conn)
    load_aliases(conn)
    seed_markets(conn)
    ensure_model_version(conn, "cardtime-test", "test", {})
    conn.commit()
    return conn


def test_card_markets_are_settled_from_the_verified_log_and_wait_when_there_is_none(db):
    tid = lambda n: db.execute("SELECT id FROM teams WHERE canonical_name = %s", (n,)).fetchone()[0]
    kickoff = datetime.now(UTC) + timedelta(days=1)
    mids = []
    for flag in ("true", "false"):
        mids.append(db.execute(
            "INSERT INTO matches (league_id, season, match_date, kickoff, home_team_id, away_team_id, status, source_ids) VALUES ('CHAMP', 2026, %s, %s, %s, %s, 'scheduled', %s) RETURNING id",
            (kickoff.date() + timedelta(days=len(mids)), kickoff, tid("Millwall"), tid("Portsmouth"), f'{{"espn": "1", "espn_log": {flag}}}')).fetchone()[0])
    run = create_run(db, "weekly", "cardtime-test", "f", datetime.now(UTC) - timedelta(days=2))
    rows = [{"market_id": mid, "line": line, "selection": sel, "probability": 0.5, "p_win": 0.5, "p_lose": 0.5, "p_push": 0.0}
            for mid, line, sel in (("cards_h1_ou", 0.5, "over"), ("first_card_team", None, "home"), ("player_carded", None, "A"), ("player_fouls", 1.5, "A"))]
    for m in mids:
        write_predictions(db, run, m, rows, MARKETS, {})
    db.commit()
    for m in mids:      # the match finishes: 1-0, cards as in the payload; only the first has a verified log
        db.execute("UPDATE matches SET status = 'finished', ft_home = 1, ft_away = 0, ht_home = 1, ht_away = 0 WHERE id = %s", (m,))
        for home, y in ((True, 1), (False, 1)):
            db.execute("INSERT INTO team_match_stats (match_id, team_id, is_home, yellow_cards, red_cards, source) VALUES (%s,%s,%s,%s,0,'t')", (m, tid("Millwall" if home else "Portsmouth"), home, y))
    parsed = parse_log(payload())
    store_log(db, mids[0], tid("Millwall"), tid("Portsmouth"), parsed, True)
    store_log(db, mids[1], tid("Millwall"), tid("Portsmouth"), parsed, False)
    db.commit()
    settle_all(db)
    got = {(m, mk, sel): (res, val) for m, mk, sel, res, val in db.execute(
        "SELECT p.match_id, p.market_id, p.selection, s.result, s.outcome_value FROM predictions p JOIN settlements s ON s.prediction_id = p.id")}
    assert got[(mids[0], "cards_h1_ou", "over")] == ("won", 1.0)             # the home card at 36'
    assert got[(mids[0], "first_card_team", "home")] == ("won", 1.0)
    assert got[(mids[0], "player_carded", "A")] == ("won", 1.0)
    assert got[(mids[0], "player_fouls", "A")] == ("won", 1.0)               # two fouls beat 1.5
    assert got[(mids[1], "cards_h1_ou", "over")][0] == "not_scorable" and got[(mids[1], "player_carded", "A")][0] == "not_scorable"


def test_every_new_market_is_registered_with_a_family():
    assert {"cards_h1_ou", "cards_h2_ou", "cards_half_most", "first_card_team", "first_card_by", "player_carded", "player_fouls", "player_fouled"} <= set(MARKETS)
    assert all(MARKETS[m].family == "G" for m in TIMING) and all(MARKETS[m].family == "I" for m in PLAYER)
    assert isinstance(LogRates, type) and dt.date(2026, 1, 1)


def test_a_player_logged_for_both_clubs_is_priced_once_for_the_club_he_played_for_last(db):
    from pitchside.pipeline.weekly import match_player_rows

    tid = lambda n: db.execute("SELECT id FROM teams WHERE canonical_name = %s", (n,)).fetchone()[0]
    arsenal, leeds = tid("Arsenal"), tid("Leeds United")

    class Cards:
        def means(self, home, away):
            return 1.5, 1.5

    for k in range(10):
        mid = db.execute("INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away, source_ids) VALUES ('EPL', 2026, %s, %s, %s, 'finished', 1, 0, '{\"espn_log\": true}') RETURNING id",
                         (dt.date(2026, 1, 1) + timedelta(days=7 * k), arsenal, leeds)).fetchone()[0]
        for team, name in ((arsenal, "Mover" if k >= 5 else "Gunner"), (leeds, "Mover" if k < 5 else "Whites")):
            db.execute("INSERT INTO player_match_log (match_id, team_id, player_name, starter, played, yellow, fouls_committed, fouls_suffered) VALUES (%s,%s,%s,true,true,1,2,1)", (mid, team, name))
    db.commit()
    rows = match_player_rows(db, "EPL", 1, arsenal, leeds, dt.date(2026, 6, 1), Cards())
    keys = [(r["market_id"], r["line"], r["selection"]) for r in rows]
    assert len(keys) == len(set(keys)) and any(k[2] == "Mover" for k in keys)
