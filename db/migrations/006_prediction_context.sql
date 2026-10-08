-- 006_prediction_context: the explanation of a prediction run is stored once per match instead of on every row.
-- A match now has about 945 prediction rows, so repeating the context on each of them would waste storage.

CREATE TABLE prediction_context (
    run_id    uuid   NOT NULL REFERENCES prediction_runs(id),
    match_id  bigint NOT NULL REFERENCES matches(id),
    context   jsonb  NOT NULL,          -- expected goals, history used, simulation size, which families were priced
    PRIMARY KEY (run_id, match_id)
);
CREATE INDEX prediction_context_match_idx ON prediction_context(match_id);

-- Append-only, like the predictions it explains.
CREATE TRIGGER prediction_context_no_update_delete BEFORE UPDATE OR DELETE ON prediction_context
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER prediction_context_no_truncate BEFORE TRUNCATE ON prediction_context
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

ALTER TABLE prediction_context ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE POLICY prediction_context_read ON prediction_context FOR SELECT TO anon, authenticated USING (true);
    END IF;
END $$;
