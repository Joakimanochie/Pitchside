-- 010_espn_match_log: every card with its minute and player, and every player's fouls and cards per match (ESPN match summary).
-- Feeds the card timing markets (first card, cards by half), player-to-be-carded and player fouls markets, and settles them.
-- A match is flagged matches.source_ids.espn_log = true only when the cards add up to the real card counts (football-data), else false.

CREATE TABLE card_events (
    id          bigserial PRIMARY KEY,
    match_id    bigint   NOT NULL REFERENCES matches(id),
    team_id     bigint   NOT NULL REFERENCES teams(id),
    player_name text,
    card        text     NOT NULL,        -- yellow or red (a second yellow is a yellow followed by a red)
    period      smallint NOT NULL,        -- 1 or 2
    minute      smallint NOT NULL         -- the minute it was shown; stoppage time keeps the minute it was added to (45, 90)
);
CREATE INDEX card_events_match_idx ON card_events(match_id);

CREATE TABLE player_match_log (
    match_id        bigint   NOT NULL REFERENCES matches(id),
    team_id         bigint   NOT NULL REFERENCES teams(id),
    player_name     text     NOT NULL,
    starter         boolean  NOT NULL,
    played          boolean  NOT NULL,    -- started, or came on
    fouls_committed smallint NOT NULL DEFAULT 0,
    fouls_suffered  smallint NOT NULL DEFAULT 0,
    yellow          smallint NOT NULL DEFAULT 0,
    red             smallint NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, team_id, player_name)
);
CREATE INDEX player_match_log_player_idx ON player_match_log(player_name, match_id);

ALTER TABLE card_events ENABLE ROW LEVEL SECURITY;       -- no policy: read only through the pipeline's exports
ALTER TABLE player_match_log ENABLE ROW LEVEL SECURITY;
