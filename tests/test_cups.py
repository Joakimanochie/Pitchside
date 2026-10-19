import datetime as dt

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import check_grad

from pitchside.db.cup_teams import CupTeams
from pitchside.db.teams import load_aliases, seed_leagues
from pitchside.ingest.cup_names import match_known
from pitchside.ingest.espn_cups import parse_result, season_of
from pitchside.ingest.openfootball import parse
from pitchside.models.pyramid import PyramidDixonColes
from pitchside.models.pyramid import neg_log_likelihood_pyramid as pyramid_nll

SAMPLE = """= UEFA Champions League 2023/24

▪ Group, Matchday 1
  Tue Sep 19 2023
    18:45  AC Milan (ITA)          v Newcastle United FC (ENG)  0-0
           BSC Young Boys (SUI)    v RB Leipzig (GER)         1-3 (1-1)
  Wed Sep 20
    21:00  Sevilla FC (ESP)        v Racing Club de Lens (FRA)  1-1
           Arsenal FC (ENG)        v FC Porto (POR)           2-1 (1-0)

▪ Finals, Round of 16
  Tue Mar 12 2024
    21:00  Arsenal FC (ENG)        v FC Porto (POR)           4-2 pen. 1-0 a.e.t. (1-0, 1-0)
  Wed Apr 17 2024
    21:00  Manchester City FC (ENG) v Real Madrid CF (ESP)     3-4 pen. 1-1 a.e.t. (1-1, 0-1)
    21:00  Not Played (ENG)         v Nobody (ESP)
"""


# ---- openfootball -------------------------------------------------------------------------------------------------

def test_results_halftime_and_the_90_minute_score_of_extra_time_matches():
    ms = parse(SAMPLE, 2023)
    by = {(m.home, m.day): m for m in ms}
    assert by[("AC Milan", dt.date(2023, 9, 19))].ft == (0, 0) and by[("AC Milan", dt.date(2023, 9, 19))].ht is None
    young_boys = by[("BSC Young Boys", dt.date(2023, 9, 19))]
    assert young_boys.ft == (1, 3) and young_boys.ht == (1, 1) and young_boys.home_country == "SUI" and young_boys.away == "RB Leipzig"
    assert by[("Sevilla FC", dt.date(2023, 9, 20))].day == dt.date(2023, 9, 20)       # a date without a year takes the season's
    city = by[("Manchester City FC", dt.date(2024, 4, 17))]
    assert city.extra_time and city.ft == (1, 1) and city.ht == (0, 1)                # level after 90 minutes; the penalties and extra time are not the score of record
    arsenal = by[("Arsenal FC", dt.date(2024, 3, 12))]
    assert arsenal.extra_time and arsenal.ft == (1, 0) and arsenal.ht == (1, 0)
    assert len(ms) == 6                                                                # the unplayed line is not a match


# ---- names --------------------------------------------------------------------------------------------------------

KNOWN = ["Arsenal", "Internazionale", "Bayern Munich", "Paris Saint-Germain", "Manchester City", "Manchester United", "Atlético Madrid", "Borussia Dortmund"]


@pytest.mark.parametrize("spelling,expected", [
    ("Arsenal FC", "Arsenal"), ("FC Internazionale Milano", "Internazionale"), ("Inter", "Internazionale"), ("FC Bayern München", "Bayern Munich"),
    ("Paris Saint-Germain FC", "Paris Saint-Germain"), ("Manchester City FC", "Manchester City"), ("Manchester United", "Manchester United"),
    ("Club Atlético de Madrid", "Atlético Madrid"), ("Borussia Dortmund", "Borussia Dortmund"), ("Chelsea FC", None), ("Celtic FC", None)])
def test_cup_spellings_find_the_database_club_or_none(spelling, expected):
    assert match_known(spelling, KNOWN) == expected


def test_new_clubs_are_created_once_and_known_clubs_reused(conn):
    seed_leagues(conn)
    load_aliases(conn)
    conn.commit()
    teams = CupTeams(conn)
    arsenal = teams.resolve("openfootball", "Arsenal FC", "ENG")
    assert arsenal == conn.execute("SELECT id FROM teams WHERE canonical_name = 'Arsenal'").fetchone()[0]
    a = teams.resolve("openfootball", "Sport Lisboa e Benfica", "POR")
    b = teams.resolve("openfootball", "SL Benfica", "POR")
    c = teams.resolve("espn", "Benfica")                    # ESPN names carry no country
    assert a == b == c and teams.created == ["Benfica"]
    f = teams.resolve("openfootball", "Feyenoord Rotterdam", "NED")
    assert teams.resolve("openfootball", "Feyenoord", "NED") == f
    assert teams.resolve("openfootball", "AS Monaco FC", "MCO") == conn.execute("SELECT id FROM teams WHERE canonical_name = 'AS Monaco'").fetchone()[0]


# ---- ESPN results ---------------------------------------------------------------------------------------------------

def event(kind, team, display, period):
    return {"type": {"type": kind}, "team": {"displayName": team}, "clock": {"displayValue": display}, "period": {"number": period}, "participants": [{"athlete": {"displayName": "P"}}]}


def summary(score_home, score_away, goals):
    stat = lambda **kw: [{"name": k, "displayValue": str(v)} for k, v in kw.items()]
    return {"header": {"competitions": [{"competitors": [{"homeAway": "home", "score": score_home, "team": {"displayName": "Arsenal"}},
                                                         {"homeAway": "away", "score": score_away, "team": {"displayName": "Porto"}}]}]},
            "keyEvents": [event(*g) for g in goals],
            "boxscore": {"teams": [{"team": {"displayName": "Arsenal"}, "statistics": stat(wonCorners=6, yellowCards=1, redCards=0, totalShots=14, shotsOnTarget=5, foulsCommitted=9)},
                                   {"team": {"displayName": "Porto"}, "statistics": stat(wonCorners=3, yellowCards=2, redCards=0, totalShots=7, shotsOnTarget=2, foulsCommitted=12)}]}}


def test_a_normal_match_is_stored_only_when_the_goals_equal_espns_score():
    goals = [("goal", "Arsenal", "12'", 1), ("goal", "Porto", "50'", 2), ("goal", "Arsenal", "88'", 2)]
    r = parse_result(summary("2", "1", goals), beyond_90=False)
    assert r["ft"] == (2, 1) and r["ht"] == (1, 0) and r["stats"]["home"]["corners"] == 6 and r["stats"]["away"]["yellow_cards"] == 2
    assert parse_result(summary("3", "1", goals), beyond_90=False) is None


def test_extra_time_goals_and_the_shootout_are_not_part_of_the_90_minute_score():
    goals = [("goal", "Arsenal", "30'", 1), ("goal", "Porto", "70'", 2), ("goal", "Arsenal", "105'", 3), ("penalty---scored", "Porto", "120'", 5)]
    r = parse_result(summary("2", "2", goals), beyond_90=True)
    assert r["ft"] == (1, 1) and r["ht"] == (1, 0)


def test_season_is_named_by_the_year_it_started():
    assert season_of(dt.date(2026, 10, 20)) == 2026 and season_of(dt.date(2027, 3, 1)) == 2026 and season_of(dt.date(2026, 7, 15)) == 2026


# ---- the cross-league model -------------------------------------------------------------------------------------------

def test_gradient_with_more_competitions_than_groups():
    rng = np.random.default_rng(3)
    n, comps, groups, m = 8, 3, 2, 120
    hi, ai = rng.integers(0, n, m), rng.integers(0, n, m)
    ai = np.where(ai == hi, (ai + 1) % n, ai)
    li = rng.integers(0, comps, m)
    hg, ag, w = rng.poisson(1.4, m).astype(float), rng.poisson(1.1, m).astype(float), rng.uniform(0.3, 1, m)
    team_league = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    theta = rng.normal(0, 0.1, 2 + comps + 2 * n + 2 * (groups - 1))
    theta[1] = 0.05
    args = (hi, ai, li, hg, ag, w, n, comps, team_league, 2.0, groups)
    assert check_grad(lambda t: pyramid_nll(t, *args)[0], lambda t: pyramid_nll(t, *args)[1], theta) < 1e-4


def cup_frame():
    rng = np.random.default_rng(1)
    rows = []
    day = dt.date(2025, 1, 1)
    strong, mid, weak = ["S1", "S2", "S3"], ["M1", "M2", "M3"], ["W1", "W2", "W3"]
    lam = {"S": 1.9, "M": 1.3, "W": 0.8}
    for k in range(240):
        league, pool = ("EPL", strong + mid) if k % 3 == 0 else ("LALIGA", mid + weak) if k % 3 == 1 else ("CL", strong + weak)
        h, a = rng.choice(pool, 2, replace=False)
        rows.append((league, 2025, day + dt.timedelta(days=k // 2), h, a, int(rng.poisson(lam[h[0]])), int(rng.poisson(lam[a[0]] * 0.8))))
    return pd.DataFrame(rows, columns=["league", "season", "match_date", "home", "away", "ft_home", "ft_away"])


def test_a_club_never_seen_is_rated_as_an_average_member_of_the_other_group():
    df = cup_frame()
    group = {"S1": "EPL", "S2": "EPL", "M1": "EPL", "M2": "LALIGA", "M3": "LALIGA", "W1": "LALIGA"}      # S3, W2, W3 have no domestic group: they join OTHER
    model = PyramidDixonColes(half_life_days=730, ridge=2.0, target_league="CL", team_group=group, ref_group="EPL").fit(df, as_of=dt.date(2026, 1, 1))
    assert "OTHER" in model.league_mean_attack
    assert model.default_attack == pytest.approx(model.league_mean_attack["OTHER"]) and model.default_defence == pytest.approx(model.league_mean_defence["OTHER"])
    unseen = model.lambdas("Brand New FC", "Another New FC")
    assert 0.3 < unseen[0] < 4 and 0.3 < unseen[1] < 4
    assert model.score_matrix("Brand New FC", "S1").sum() == pytest.approx(1)
    assert model.lambdas("S1", "W1")[0] > model.lambdas("W1", "S1")[0]


def test_matches_after_the_date_are_never_used():
    df = cup_frame()
    cut = dt.date(2025, 3, 1)
    group = {t: "EPL" for t in ["S1", "S2", "S3", "M1", "M2", "M3", "W1", "W2", "W3"]}
    make = lambda: PyramidDixonColes(half_life_days=730, ridge=2.0, target_league="CL", team_group=group, ref_group="EPL")
    early = make().fit(df, as_of=cut)
    changed = df.copy()
    changed.loc[changed["match_date"] >= cut, "ft_home"] += 5
    again = make().fit(changed, as_of=cut)
    assert early.lambdas("S1", "W1") == pytest.approx(again.lambdas("S1", "W1"))
