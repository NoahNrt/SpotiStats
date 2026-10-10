-- =====================================================================
-- SpotiStats – Tabellen für den automatischen Abruf über die Spotify-API
-- Stand der API: Development-Mode-Apps nach den Änderungen vom Februar/März 2026
-- (keine Batch-Abfragen, keine Popularität/Follower, Playlist-Inhalte nur für
-- eigene oder gemeinsam bearbeitete Playlists).
-- =====================================================================

BEGIN;

-- Alle Künstler eines Titels (der Export kennt nur den Hauptkünstler)
CREATE TABLE track_artists (
    track_id   bigint   NOT NULL REFERENCES tracks  (track_id)  ON DELETE CASCADE,
    artist_id  bigint   NOT NULL REFERENCES artists (artist_id),
    pos        smallint NOT NULL,          -- 0 = Hauptkünstler
    PRIMARY KEY (track_id, artist_id)
);
CREATE INDEX track_artists_artist_idx ON track_artists (artist_id);

-- ---------------------------------------------------------------------
-- Zuletzt gespielte Titel (API). played_at ist die Zeit laut API, nicht das
-- Ende der Wiedergabe wie im Export. Eine gespielte Dauer liefert die API nicht.
-- ---------------------------------------------------------------------
CREATE TABLE api_plays (
    api_play_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       integer     NOT NULL REFERENCES users  (user_id),
    played_at     timestamptz NOT NULL,
    track_id      bigint      NOT NULL REFERENCES tracks (track_id),
    context_type  text,                    -- z. B. playlist, album, artist
    context_uri   text,
    collected_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, played_at, track_id)
);

-- ---------------------------------------------------------------------
-- Top-Titel und Top-Künstler als tägliche Momentaufnahme
-- ---------------------------------------------------------------------
CREATE TABLE top_items (
    user_id       integer  NOT NULL REFERENCES users (user_id),
    collected_on  date     NOT NULL,
    item_type     text     NOT NULL CHECK (item_type IN ('track', 'artist')),
    time_range    text     NOT NULL CHECK (time_range IN ('short_term', 'medium_term', 'long_term')),
    rank_no       smallint NOT NULL CHECK (rank_no >= 1),
    track_id      bigint REFERENCES tracks  (track_id),
    artist_id     bigint REFERENCES artists (artist_id),
    PRIMARY KEY (user_id, collected_on, item_type, time_range, rank_no),
    CHECK (
        (item_type = 'track'  AND track_id  IS NOT NULL AND artist_id IS NULL) OR
        (item_type = 'artist' AND artist_id IS NOT NULL AND track_id  IS NULL)
    )
);

-- ---------------------------------------------------------------------
-- Bibliothek: gespeicherte Titel, Alben, Shows, Folgen, Hörbücher, gefolgte Künstler.
-- Wird ein Eintrag aus der Bibliothek entfernt, bleibt die Zeile mit removed_at erhalten.
-- ---------------------------------------------------------------------
CREATE TABLE library_items (
    user_id        integer     NOT NULL REFERENCES users (user_id),
    item_type      text        NOT NULL CHECK (item_type IN ('track', 'album', 'artist', 'show', 'episode', 'audiobook')),
    spotify_id     text        NOT NULL,
    name           text,
    added_at       timestamptz,            -- laut API; bei gefolgten Künstlern nicht vorhanden
    first_seen_at  timestamptz NOT NULL,
    last_seen_at   timestamptz NOT NULL,
    removed_at     timestamptz,
    track_id       bigint REFERENCES tracks   (track_id),
    album_id       bigint REFERENCES albums   (album_id),
    artist_id      bigint REFERENCES artists  (artist_id),
    show_id        bigint REFERENCES shows    (show_id),
    episode_id     bigint REFERENCES episodes (episode_id),
    PRIMARY KEY (user_id, item_type, spotify_id)
);
CREATE INDEX library_items_added_idx ON library_items (user_id, added_at);

-- ---------------------------------------------------------------------
-- Playlists des Benutzers und ihre Inhalte (aktueller Stand, ohne Verlauf).
-- Inhalte liefert die API nur für eigene oder gemeinsam bearbeitete Playlists.
-- ---------------------------------------------------------------------
CREATE TABLE playlists (
    playlist_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              integer     NOT NULL REFERENCES users (user_id),
    spotify_playlist_id  text        NOT NULL,
    name                 text        NOT NULL,
    description          text,
    owner_spotify_id     text,
    owner_name           text,
    is_public            boolean,
    is_collaborative     boolean,
    snapshot_id          text,                  -- Änderungsmarke von Spotify beim letzten Inhaltsabruf
    total_items          integer,
    items_synced_at      timestamptz,
    first_seen_at        timestamptz NOT NULL,
    last_seen_at         timestamptz NOT NULL,
    removed_at           timestamptz,
    UNIQUE (user_id, spotify_playlist_id)
);

CREATE TABLE playlist_items (
    playlist_id          bigint   NOT NULL REFERENCES playlists (playlist_id) ON DELETE CASCADE,
    pos                  integer  NOT NULL,     -- Position in der Playlist (0-basiert)
    content_type         text     NOT NULL CHECK (content_type IN ('track', 'episode')),
    track_id             bigint REFERENCES tracks   (track_id),
    episode_id           bigint REFERENCES episodes (episode_id),
    added_at             timestamptz,
    added_by_spotify_id  text,
    PRIMARY KEY (playlist_id, pos),
    CHECK (
        (content_type = 'track'   AND track_id   IS NOT NULL AND episode_id IS NULL) OR
        (content_type = 'episode' AND episode_id IS NOT NULL AND track_id   IS NULL)
    )
);

-- ---------------------------------------------------------------------
-- Protokoll der Collector-Läufe (steuert auch, wann ein Job wieder fällig ist)
-- ---------------------------------------------------------------------
CREATE TABLE collector_runs (
    run_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        integer     NOT NULL REFERENCES users (user_id),
    job            text        NOT NULL,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    status         text        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'error')),
    items_fetched  integer,
    items_written  integer,
    message        text
);
CREATE INDEX collector_runs_job_idx ON collector_runs (user_id, job, started_at DESC);

COMMIT;
