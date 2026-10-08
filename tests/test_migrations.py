import psycopg
import pytest

from pitchside.db.migrate import apply_migrations


def seed(conn):
    """Minimal rows: one league, two teams, one finished match, one market, one model, one run."""
    conn.execute("INSERT INTO leagues (id, name, country) VALUES ('EPL', 'Premier League', 'England')")
    conn.execute("INSERT INTO teams (canonical_name) VALUES ('Arsenal'), ('Leeds United')")
    conn.execute(
        "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away) "
        "VALUES ('EPL', 2026, '2026-10-10', (SELECT id FROM teams WHERE canonical_name = 'Arsenal'), "
        "(SELECT id FROM teams WHERE canonical_name = 'Leeds United'), 'finished', 2, 0)"
    )
    conn.execute("INSERT INTO markets (id, family, name) VALUES ('1x2', 'A', 'Match result')")
    conn.execute("INSERT INTO model_versions (id) VALUES ('test-0')")
    run_id = conn.execute(
        "INSERT INTO prediction_runs (run_type, model_version_id, feature_version, data_cutoff) "
        "VALUES ('weekly', 'test-0', 'f0', now()) RETURNING id"
    ).fetchone()[0]
    return run_id


def add_prediction(conn, run_id, selection="home", p=0.6, line=None):
    return conn.execute(
        "INSERT INTO predictions (run_id, match_id, market_id, line, selection, probability) "
        "VALUES (%s, (SELECT id FROM matches LIMIT 1), '1x2', %s, %s, %s) RETURNING id",
        (run_id, line, selection, p),
    ).fetchone()[0]


def test_migrations_apply_once(conn):
    assert apply_migrations(conn) == []  # second call applies nothing
    names = [r[0] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names == ["001_warehouse.sql", "002_predictions.sql", "003_settlements.sql", "004_security_hardening.sql",
                     "005_track_record_views.sql",
                     "006_prediction_context.sql"]


def test_predictions_are_append_only(conn):
    run_id = seed(conn)
    pid = add_prediction(conn, run_id)
    conn.commit()
    for sql in ("UPDATE predictions SET probability = 0.9", "DELETE FROM predictions", "TRUNCATE predictions, settlements"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql)
        conn.rollback()
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("UPDATE prediction_runs SET notes = 'edited'")
    conn.rollback()
    assert float(conn.execute("SELECT probability FROM predictions WHERE id = %s", (pid,)).fetchone()[0]) == pytest.approx(0.6)


def test_probability_must_be_between_0_and_1(conn):
    run_id = seed(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_prediction(conn, run_id, p=1.2)


def test_duplicate_prediction_rejected_including_null_line(conn):
    run_id = seed(conn)
    add_prediction(conn, run_id, "home")
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_prediction(conn, run_id, "home")
    conn.rollback()


def test_same_prediction_allowed_in_a_different_run(conn):
    run_id = seed(conn)
    add_prediction(conn, run_id, "home")
    run2 = conn.execute(
        "INSERT INTO prediction_runs (run_type, model_version_id, feature_version, data_cutoff) "
        "VALUES ('pre_kickoff', 'test-0', 'f0', now()) RETURNING id"
    ).fetchone()[0]
    add_prediction(conn, run2, "home", 0.65)


def test_finished_match_needs_a_score_and_vice_versa(conn):
    seed(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status) "
            "VALUES ('EPL', 2026, '2026-11-01', 2, 1, 'finished')"
        )
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, ft_home, ft_away) "
            "VALUES ('EPL', 2026, '2026-11-01', 2, 1, 'scheduled', 1, 0)"
        )
    conn.rollback()


def test_team_cannot_play_itself(conn):
    seed(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id) "
            "VALUES ('EPL', 2026, '2026-11-01', 1, 1)"
        )
    conn.rollback()


def test_alias_maps_to_one_team_per_source(conn):
    seed(conn)
    conn.execute("INSERT INTO team_aliases (source, alias, team_id) VALUES ('footballdata', 'Leeds', 2)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO team_aliases (source, alias, team_id) VALUES ('footballdata', 'Leeds', 1)")
    conn.rollback()


def test_settlement_rules_and_view(conn):
    run_id = seed(conn)
    pid = add_prediction(conn, run_id)
    # a push must have no outcome value; a win must
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO settlements (prediction_id, result, outcome_value) VALUES (%s, 'push', 1)", (pid,))
    conn.rollback()
    run_id = seed(conn)  # the rollback above discarded the first seed
    pid = add_prediction(conn, run_id)
    conn.execute(
        "INSERT INTO settlements (prediction_id, result, outcome_value, log_loss, brier) "
        "VALUES (%s, 'won', 1, 0.5108, 0.16)",
        (pid,),
    )
    row = conn.execute("SELECT league_id, family, result FROM v_settled").fetchone()
    assert row == ("EPL", "A", "won")


def test_every_public_table_has_row_level_security(conn):
    unprotected = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity")]
    assert unprotected == []


def test_settled_view_respects_caller_rights(conn):
    opts = conn.execute("SELECT reloptions FROM pg_class WHERE relname = 'v_settled'").fetchone()[0]
    assert "security_invoker=true" in opts
