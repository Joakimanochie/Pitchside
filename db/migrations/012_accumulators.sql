-- 012_accumulators: the daily "odds" slips (2, 3, 5, 10, 20, 30 odds), stored before kickoff and never edited, like the predictions they are made from.
-- A slip is a list of legs; each leg points at one stored prediction, so how a slip turned out is read from the settlements of its legs.

CREATE TABLE accumulators (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    slip_date       date        NOT NULL,                 -- the UK date the matches are played on
    target_odds     numeric(6,2) NOT NULL,                -- 2, 3, 5, 10, 20 or 30
    fair_odds       numeric(10,3) NOT NULL,               -- the product of the legs' fair odds (1 / probability); bookmakers pay less
    win_probability numeric(9,7) NOT NULL,                -- the model's chance that every leg wins
    rules           text        NOT NULL,                 -- the version of the selection rules that built it
    UNIQUE (slip_date, target_odds)
);

CREATE TABLE accumulator_legs (
    accumulator_id uuid   NOT NULL REFERENCES accumulators(id),
    position       smallint NOT NULL,
    prediction_id  bigint NOT NULL REFERENCES predictions(id),
    match_id       bigint NOT NULL REFERENCES matches(id),
    PRIMARY KEY (accumulator_id, position),
    UNIQUE (accumulator_id, match_id)                     -- one leg per match
);
CREATE INDEX accumulator_legs_prediction_idx ON accumulator_legs(prediction_id);

CREATE TRIGGER accumulators_no_update_delete BEFORE UPDATE OR DELETE ON accumulators
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER accumulator_legs_no_update_delete BEFORE UPDATE OR DELETE ON accumulator_legs
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE TRIGGER accumulators_no_truncate BEFORE TRUNCATE ON accumulators
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER accumulator_legs_no_truncate BEFORE TRUNCATE ON accumulator_legs
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

ALTER TABLE accumulators ENABLE ROW LEVEL SECURITY;      -- no policy: read only through the pipeline's exports
ALTER TABLE accumulator_legs ENABLE ROW LEVEL SECURITY;
