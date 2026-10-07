-- 002_predictions: market catalogue, model versions, runs, and the append-only predictions table.

CREATE TABLE markets (
    id           text PRIMARY KEY,               -- canonical id, e.g. 'ou_total', '1x2', 'btts'
    family       char(1) NOT NULL CHECK (family IN ('A','B','C','D','E','F','G','H','I')),
    name         text NOT NULL,
    has_line     boolean NOT NULL DEFAULT false, -- true for over/under, handicap, etc.
    scorable     boolean NOT NULL DEFAULT true   -- false when our sources cannot settle it
);

-- Each site's display name -> canonical market (SportyBet first).
CREATE TABLE market_aliases (
    source        text NOT NULL,
    display_name  text NOT NULL,
    market_id     text NOT NULL REFERENCES markets(id),
    PRIMARY KEY (source, display_name)
);

CREATE TABLE model_versions (
    id           text PRIMARY KEY,               -- e.g. 'goals-dc-0.1.0'
    description  text,
    params       jsonb NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE prediction_runs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at        timestamptz NOT NULL DEFAULT now(),
    run_type          text NOT NULL CHECK (run_type IN ('weekly', 'pre_kickoff', 'backtest')),
    model_version_id  text NOT NULL REFERENCES model_versions(id),
    feature_version   text NOT NULL,
    data_cutoff       timestamptz NOT NULL,      -- only data before this instant was used
    n_sims            integer,
    notes             text
);

-- One row per match x market x line x selection x run. Frozen once written.
CREATE TABLE predictions (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id           uuid NOT NULL REFERENCES prediction_runs(id),
    match_id         bigint NOT NULL REFERENCES matches(id),
    market_id        text NOT NULL REFERENCES markets(id),
    line             numeric(6,2),               -- NULL for markets without a line
    selection        text NOT NULL,              -- 'home', 'draw', 'over', 'yes', '2-1', player name, ...
    probability      numeric(7,6) NOT NULL CHECK (probability >= 0 AND probability <= 1),
    is_pick          boolean NOT NULL DEFAULT false,
    confidence_tier  text CHECK (confidence_tier IN ('high', 'medium', 'low')),
    why              jsonb NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX predictions_unique_idx
    ON predictions (run_id, match_id, market_id, COALESCE(line, -9999), selection);
CREATE INDEX predictions_match_idx ON predictions(match_id, market_id);
CREATE INDEX predictions_run_idx ON predictions(run_id);

-- Append-only: no updates, no deletes, no truncate.
CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only (% not allowed)', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER predictions_no_update_delete BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER predictions_no_truncate BEFORE TRUNCATE ON predictions
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER runs_no_update_delete BEFORE UPDATE OR DELETE ON prediction_runs
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
