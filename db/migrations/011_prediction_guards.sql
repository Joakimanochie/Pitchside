-- 011_prediction_guards: the honesty rules, enforced by the database and not only by the pipeline code.
--   1. An official (weekly or pre_kickoff) prediction cannot be inserted once the match has kicked off.
--   2. A match gets one official run per model version: a second run of the same version cannot add predictions for the same match and market.
-- Backtest runs are exempt. The pipeline's own checks already do both; this stops a bug or a hand-run script from breaking them.
-- A session can switch the guards off with  SET pitchside.unsafe_writes = 'on'  (the test suite and the --force flag do). It protects against mistakes,
-- not against someone with full access to the database, who could also drop the trigger.

CREATE OR REPLACE FUNCTION guard_prediction_insert() RETURNS trigger AS $$
DECLARE
    r_type    text;
    r_version text;
    kick      timestamptz;
BEGIN
    IF current_setting('pitchside.unsafe_writes', true) = 'on' THEN
        RETURN NEW;
    END IF;
    SELECT run_type, model_version_id INTO r_type, r_version FROM prediction_runs WHERE id = NEW.run_id;
    IF r_type = 'backtest' THEN
        RETURN NEW;
    END IF;
    SELECT kickoff INTO kick FROM matches WHERE id = NEW.match_id;
    IF kick IS NOT NULL AND clock_timestamp() >= kick THEN
        RAISE EXCEPTION 'official predictions must be stored before kickoff (match %, kickoff %)', NEW.match_id, kick;
    END IF;
    IF EXISTS (SELECT 1 FROM predictions p JOIN prediction_runs r ON r.id = p.run_id
               WHERE p.match_id = NEW.match_id AND p.market_id = NEW.market_id AND p.run_id <> NEW.run_id
                 AND r.model_version_id = r_version AND r.run_type = r_type) THEN
        RAISE EXCEPTION 'match % already has an official % prediction from model version % for market %', NEW.match_id, r_type, r_version, NEW.market_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER predictions_guard BEFORE INSERT ON predictions
    FOR EACH ROW EXECUTE FUNCTION guard_prediction_insert();
