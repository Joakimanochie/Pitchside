-- 008_shot_events: every shot of a finished match with who took it, who set it up and its expected goals (Understat).
-- Feeds the player layer: how much of a club's scoring, shooting and creating each player has done lately, and the real player counts used to settle player markets.

CREATE TABLE shot_events (
    id                bigserial PRIMARY KEY,
    match_id          bigint   NOT NULL REFERENCES matches(id),
    team_id           bigint   NOT NULL REFERENCES teams(id),   -- the side the shot counts for (for an own goal, Understat names the scorer's own team)
    player_name       text,
    assist_name       text,
    minute            smallint,
    xg                real,
    result            text     NOT NULL,                        -- Goal, SavedShot, MissedShots, BlockedShot, ShotOnPost, Own Goal
    situation         text,
    understat_shot_id bigint   NOT NULL,
    UNIQUE (match_id, understat_shot_id)
);
CREATE INDEX shot_events_team_idx ON shot_events(team_id, match_id);
CREATE INDEX shot_events_player_idx ON shot_events(player_name, match_id);

ALTER TABLE shot_events ENABLE ROW LEVEL SECURITY;   -- no policy: read only through the pipeline's exports
