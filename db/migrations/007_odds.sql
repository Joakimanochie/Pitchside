-- 007_odds: bookmaker odds seen before kickoff, stored as dated snapshots so a price can be compared with the prediction made at the time.
-- Append-only, like predictions. Not readable by the anonymous role: odds data is licensed to us, not published.

CREATE TABLE odds_snapshots (
    id          bigserial PRIMARY KEY,
    match_id    bigint        NOT NULL REFERENCES matches(id),
    source      text          NOT NULL,                 -- where it came from, e.g. 'footballdata_fixtures'
    bookmaker   text          NOT NULL,                 -- 'avg' market average, 'max' best price, 'b365' Bet365
    market_id   text          NOT NULL,                 -- our market id: 1x2, ou_total, asian_handicap
    line        numeric(4, 2),                          -- null for markets without a line; the home handicap for asian_handicap
    selection   text          NOT NULL,                 -- our selection code: home, draw, away, over, under
    odds        numeric(8, 3) NOT NULL CHECK (odds > 1),
    fetched_at  timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX odds_snapshots_match_idx ON odds_snapshots(match_id, market_id, fetched_at DESC);

CREATE TRIGGER odds_snapshots_no_update_delete BEFORE UPDATE OR DELETE ON odds_snapshots
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER odds_snapshots_no_truncate BEFORE TRUNCATE ON odds_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

ALTER TABLE odds_snapshots ENABLE ROW LEVEL SECURITY;   -- no policy: only the owning role reads or writes

-- The latest price for every (match, bookmaker, market, line, selection).
CREATE VIEW v_latest_odds WITH (security_invoker = true) AS
SELECT DISTINCT ON (match_id, bookmaker, market_id, line, selection)
       match_id, source, bookmaker, market_id, line, selection, odds, fetched_at
FROM odds_snapshots
ORDER BY match_id, bookmaker, market_id, line, selection, fetched_at DESC, id DESC;
