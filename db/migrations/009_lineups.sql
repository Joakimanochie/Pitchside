-- 009_lineups: announced starting elevens and benches (ESPN), fetched shortly before kickoff.
-- Several snapshots per match and club are allowed (a lineup can be corrected); the newest one is used.

CREATE TABLE lineups (
    id         bigserial PRIMARY KEY,
    match_id   bigint      NOT NULL REFERENCES matches(id),
    team_id    bigint      NOT NULL REFERENCES teams(id),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    formation  text,
    starters   jsonb       NOT NULL,   -- list of player names
    bench      jsonb       NOT NULL,
    source     text        NOT NULL DEFAULT 'espn'
);
CREATE INDEX lineups_match_idx ON lineups(match_id, team_id, fetched_at);

ALTER TABLE lineups ENABLE ROW LEVEL SECURITY;   -- no policy: read only through the pipeline's exports
