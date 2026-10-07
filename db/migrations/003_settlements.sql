-- 003_settlements: real match records and the settlement of each prediction against them.

-- The real MatchRecord for a finished match, built from the warehouse.
CREATE TABLE match_outcomes (
    match_id    bigint PRIMARY KEY REFERENCES matches(id),
    record      jsonb NOT NULL,                  -- goals with minutes, corners, cards, shots, ...
    coverage    jsonb NOT NULL DEFAULT '{}',     -- which record fields were actually available
    built_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE settlements (
    prediction_id  bigint PRIMARY KEY REFERENCES predictions(id),
    result         text NOT NULL
                   CHECK (result IN ('won', 'lost', 'push', 'half_won', 'half_lost', 'void', 'not_scorable')),
    outcome_value  numeric(4,3),                 -- 1, 0, 0.5 (push/void excluded), 0.75 ... share that "happened"
    observed       jsonb NOT NULL DEFAULT '{}',  -- e.g. {"total_goals": 3}
    log_loss       numeric(8,6),
    brier          numeric(8,6),
    settled_at     timestamptz NOT NULL DEFAULT now(),
    CHECK ((result IN ('push', 'void', 'not_scorable')) = (outcome_value IS NULL)),
    CHECK (log_loss IS NULL OR log_loss >= 0)
);

-- Settled predictions with their context; the base for every track-record view.
CREATE VIEW v_settled AS
SELECT s.prediction_id, s.result, s.outcome_value, s.log_loss, s.brier,
       p.run_id, p.match_id, p.market_id, p.line, p.selection, p.probability, p.is_pick, p.confidence_tier,
       r.model_version_id, r.run_type, m.league_id, m.season, m.match_date, mk.family
FROM settlements s
JOIN predictions p ON p.id = s.prediction_id
JOIN prediction_runs r ON r.id = p.run_id
JOIN matches m ON m.id = p.match_id
JOIN markets mk ON mk.id = p.market_id;

-- Row-level security. The job connects as the service role (bypasses RLS); the app reads only.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['leagues', 'teams', 'team_aliases', 'matches', 'team_match_stats', 'match_events',
                             'elo_ratings', 'ingest_log', 'markets', 'market_aliases', 'model_versions',
                             'prediction_runs', 'predictions', 'match_outcomes', 'settlements']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        IF t <> 'ingest_log' AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('CREATE POLICY %I ON %I FOR SELECT TO anon, authenticated USING (true)',
                           t || '_read', t);
        END IF;
    END LOOP;
END $$;
