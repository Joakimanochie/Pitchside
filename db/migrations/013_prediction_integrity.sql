-- Close the duplicate-run gap in 011. A match/model/run-type can have many
-- selections in one run, but must not be split across separate official runs.
-- The advisory lock makes the check safe when two pipeline workers race.
-- pitchside.unsafe_writes remains available only for isolated test fixtures.
CREATE OR REPLACE FUNCTION guard_prediction_insert() RETURNS trigger AS $$
DECLARE
    r_type    text;
    r_version text;
    kick      timestamptz;
BEGIN
    IF current_setting('pitchside.unsafe_writes', true) = 'on' THEN
        RETURN NEW;
    END IF;
    SELECT run_type, model_version_id INTO r_type, r_version
      FROM prediction_runs WHERE id = NEW.run_id;
    IF r_type = 'backtest' THEN
        RETURN NEW;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.match_id::text || ':' || r_type || ':' || r_version, 0));

    SELECT kickoff INTO kick FROM matches WHERE id = NEW.match_id;
    IF kick IS NOT NULL AND clock_timestamp() >= kick THEN
        RAISE EXCEPTION 'official predictions must be stored before kickoff (match %, kickoff %)', NEW.match_id, kick;
    END IF;
    IF EXISTS (
        SELECT 1 FROM predictions p
        JOIN prediction_runs r ON r.id = p.run_id
        WHERE p.match_id = NEW.match_id
          AND p.run_id <> NEW.run_id
          AND r.model_version_id = r_version
          AND r.run_type = r_type
    ) THEN
        RAISE EXCEPTION 'match % already has an official % run from model version %', NEW.match_id, r_type, r_version;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE prediction_runs ADD COLUMN confidence_rules_hash text;
