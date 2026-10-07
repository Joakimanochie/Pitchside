-- 001_warehouse: leagues, teams, aliases, matches, team stats, events, Elo, ingest log.
-- Target: Supabase Postgres (also runs on plain Postgres 14+).

CREATE TABLE leagues (
    id            text PRIMARY KEY,              -- 'EPL', 'LALIGA', 'BUNDESLIGA', 'SERIEA', 'LIGUE1'
    name          text NOT NULL,
    country       text NOT NULL,
    tier          smallint NOT NULL DEFAULT 1,
    fd_code       text,                          -- football-data.co.uk division code, e.g. 'E0'
    understat     text,                          -- soccerdata league key, e.g. 'ENG-Premier League'
    espn_code     text,                          -- ESPN slug, e.g. 'eng.1'
    active        boolean NOT NULL DEFAULT true
);

CREATE TABLE teams (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_name  text NOT NULL UNIQUE,
    country         text
);

-- Each source spells clubs differently; every spelling maps to exactly one team.
CREATE TABLE team_aliases (
    source    text NOT NULL,                     -- 'footballdata', 'understat', 'whoscored', 'espn', 'manual'
    alias     text NOT NULL,
    team_id   bigint NOT NULL REFERENCES teams(id),
    PRIMARY KEY (source, alias)
);
CREATE INDEX team_aliases_team_idx ON team_aliases(team_id);

CREATE TABLE matches (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    league_id      text NOT NULL REFERENCES leagues(id),
    season         smallint NOT NULL,            -- start year: 2025 = 2025/26
    match_date     date NOT NULL,
    kickoff        timestamptz,
    matchweek      smallint,
    home_team_id   bigint NOT NULL REFERENCES teams(id),
    away_team_id   bigint NOT NULL REFERENCES teams(id),
    status         text NOT NULL DEFAULT 'scheduled'
                   CHECK (status IN ('scheduled', 'live', 'finished', 'postponed', 'cancelled')),
    ft_home        smallint,
    ft_away        smallint,
    ht_home        smallint,
    ht_away        smallint,
    referee        text,
    source_ids     jsonb NOT NULL DEFAULT '{}',  -- {"espn": "...", "understat": "...", "whoscored": "..."}
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (home_team_id <> away_team_id),
    CHECK ((status = 'finished') = (ft_home IS NOT NULL AND ft_away IS NOT NULL)),
    UNIQUE (league_id, season, home_team_id, away_team_id, match_date)
);
CREATE INDEX matches_league_season_idx ON matches(league_id, season, match_date);
CREATE INDEX matches_date_idx ON matches(match_date);
CREATE INDEX matches_home_idx ON matches(home_team_id, match_date);
CREATE INDEX matches_away_idx ON matches(away_team_id, match_date);

-- One row per team per match. NULL means the source did not provide it (never 0 by default).
CREATE TABLE team_match_stats (
    match_id          bigint NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    team_id           bigint NOT NULL REFERENCES teams(id),
    is_home           boolean NOT NULL,
    shots             smallint,
    shots_on_target   smallint,
    corners           smallint,
    fouls             smallint,
    yellow_cards      smallint,
    red_cards         smallint,
    offsides          smallint,
    tackles           smallint,
    possession        numeric(5,2),
    xg                numeric(6,3),
    source            text NOT NULL,
    PRIMARY KEY (match_id, team_id)
);

-- Goals, cards, corners, subs with minute. Filled from Understat / WhoScored.
CREATE TABLE match_events (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id       bigint NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    team_id        bigint REFERENCES teams(id),
    event_type     text NOT NULL
                   CHECK (event_type IN ('goal', 'own_goal', 'penalty_goal', 'yellow_card', 'red_card',
                                         'corner', 'substitution', 'shot', 'offside', 'foul', 'tackle')),
    period         smallint,                     -- 1 = first half, 2 = second half
    minute         smallint,
    added_minute   smallint,
    player_name    text,
    details        jsonb NOT NULL DEFAULT '{}',
    source         text NOT NULL
);
CREATE INDEX match_events_match_idx ON match_events(match_id, event_type, minute);

CREATE TABLE elo_ratings (
    team_id   bigint NOT NULL REFERENCES teams(id),
    as_of     date NOT NULL,                     -- rating before matches on this date
    elo       numeric(7,2) NOT NULL,
    source    text NOT NULL,                     -- 'computed' or 'clubelo'
    PRIMARY KEY (team_id, as_of, source)
);

-- What each ingest step loaded and when; drives "only fetch what is new".
CREATE TABLE ingest_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        text NOT NULL,
    league_id     text REFERENCES leagues(id),
    season        smallint,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    rows_written  integer,
    status        text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed')),
    error         text
);

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER matches_touch BEFORE UPDATE ON matches
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
