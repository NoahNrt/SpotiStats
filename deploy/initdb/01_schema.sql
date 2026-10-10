-- =====================================================================
-- SpotiStats – Kernschema
-- Ziel-DBMS: PostgreSQL 16 (benötigt >= 15 wegen NULLS NOT DISTINCT)
-- Reihenfolge beim ersten Containerstart: 01_schema.sql, 02_api_collector.sql,
-- 03_views.sql, 04_grafana_user.sh. Zeitstempel sind durchgehend UTC (timestamptz).
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Benutzer (zunächst nur einer, Schema ist aber mehrbenutzerfähig)
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    display_name     text        NOT NULL UNIQUE,
    spotify_user_id  text        UNIQUE,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Katalog: Künstler, Genres, Alben, Titel
-- Der Export enthält nur Namen. Die Spotify-IDs kommen später über die API und
-- werden an die vorhandenen Zeilen "angeheftet". Gleichnamige Künstler/Alben
-- sind deshalb nur ohne Spotify-ID eindeutig (partieller Unique-Index);
-- mit ID gilt die ID als Schlüssel.
-- ---------------------------------------------------------------------
CREATE TABLE artists (
    artist_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name               text        NOT NULL,
    spotify_artist_id  text        UNIQUE,
    genres_synced_at   timestamptz
);
CREATE UNIQUE INDEX artists_name_unlinked_uq ON artists (name) WHERE spotify_artist_id IS NULL;
CREATE INDEX artists_name_idx ON artists (name);

CREATE TABLE genres (
    genre_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name      text NOT NULL UNIQUE
);

CREATE TABLE artist_genres (
    artist_id  bigint NOT NULL REFERENCES artists (artist_id) ON DELETE CASCADE,
    genre_id   bigint NOT NULL REFERENCES genres  (genre_id)  ON DELETE CASCADE,
    PRIMARY KEY (artist_id, genre_id)
);

CREATE TABLE albums (
    album_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title             text   NOT NULL,
    artist_id         bigint REFERENCES artists (artist_id),
    spotify_album_id  text   UNIQUE,
    release_date      date
);
CREATE UNIQUE INDEX albums_title_unlinked_uq ON albums (title, artist_id) NULLS NOT DISTINCT
    WHERE spotify_album_id IS NULL;

CREATE TABLE tracks (
    track_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    spotify_track_uri  text    NOT NULL UNIQUE,   -- auch 'spotify:local:...' bei lokalen Dateien
    title              text    NOT NULL,
    artist_id          bigint  REFERENCES artists (artist_id),   -- Hauptkünstler
    album_id           bigint  REFERENCES albums  (album_id),
    duration_ms        integer CHECK (duration_ms > 0),          -- erst nach API-Abgleich
    enriched_at        timestamptz                               -- gesetzt, sobald die API-Details geholt wurden
);

-- ---------------------------------------------------------------------
-- Katalog: Podcasts und Hörbücher
-- ---------------------------------------------------------------------
CREATE TABLE shows (
    show_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text NOT NULL,
    spotify_show_id  text UNIQUE
);
CREATE UNIQUE INDEX shows_name_unlinked_uq ON shows (name) WHERE spotify_show_id IS NULL;

CREATE TABLE episodes (
    episode_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    spotify_episode_uri  text   NOT NULL UNIQUE,
    title                text   NOT NULL,
    show_id              bigint REFERENCES shows (show_id)
);

CREATE TABLE audiobook_chapters (
    chapter_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    spotify_chapter_uri   text NOT NULL UNIQUE,
    chapter_title         text NOT NULL,
    audiobook_title       text,
    spotify_audiobook_uri text
);

-- ---------------------------------------------------------------------
-- Import-Protokoll: jeder Importlauf wird nachvollziehbar festgehalten
-- ---------------------------------------------------------------------
CREATE TABLE import_batches (
    batch_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         integer NOT NULL REFERENCES users (user_id),
    source_package  text    NOT NULL,                 -- z. B. 'extended_streaming_history'
    source_files    text[]  NOT NULL DEFAULT '{}',
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    rows_read       integer,
    rows_inserted   integer,
    rows_duplicate  integer,
    rows_invalid    integer
);

-- ---------------------------------------------------------------------
-- Wiedergaben aus dem Export (Faktentabelle). ts im Export = Ende der Wiedergabe.
-- Es wird bewusst keine IP-Adresse und kein User-Agent gespeichert
-- (Datenminimierung); der Benutzername steht in users.
-- Wiedergaben aus der API liegen getrennt in api_plays (siehe 02_api_collector.sql).
-- ---------------------------------------------------------------------
CREATE TYPE content_type AS ENUM ('track', 'episode', 'audiobook_chapter');

CREATE TABLE plays (
    play_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id            integer      NOT NULL REFERENCES users (user_id),
    played_at          timestamptz  NOT NULL,
    ms_played          integer      NOT NULL CHECK (ms_played >= 0),
    content_type       content_type NOT NULL,
    track_id           bigint REFERENCES tracks (track_id),
    episode_id         bigint REFERENCES episodes (episode_id),
    chapter_id         bigint REFERENCES audiobook_chapters (chapter_id),
    platform           text,
    conn_country       text,
    reason_start       text,
    reason_end         text,
    shuffle            boolean,
    skipped            boolean,
    offline            boolean,
    offline_timestamp  bigint,    -- Rohwert aus dem Export, Einheit nicht dokumentiert
    incognito_mode     boolean,
    -- Spotify zählt einen Stream ab 30 Sekunden Wiedergabe
    is_counted_stream  boolean GENERATED ALWAYS AS (ms_played >= 30000) STORED,
    batch_id           bigint REFERENCES import_batches (batch_id),

    CONSTRAINT plays_exactly_one_content CHECK (
        (content_type = 'track'             AND track_id   IS NOT NULL AND episode_id IS NULL     AND chapter_id IS NULL) OR
        (content_type = 'episode'           AND episode_id IS NOT NULL AND track_id   IS NULL     AND chapter_id IS NULL) OR
        (content_type = 'audiobook_chapter' AND chapter_id IS NOT NULL AND track_id   IS NULL     AND episode_id IS NULL)
    ),
    -- verhindert Dubletten bei überlappenden Exporten (Reimport ist gefahrlos)
    CONSTRAINT plays_no_duplicates
        UNIQUE NULLS NOT DISTINCT (user_id, played_at, track_id, episode_id, chapter_id)
);

CREATE INDEX plays_track_idx    ON plays (track_id)   WHERE track_id   IS NOT NULL;
CREATE INDEX plays_episode_idx  ON plays (episode_id) WHERE episode_id IS NOT NULL;
CREATE INDEX tracks_artist_idx  ON tracks (artist_id);
CREATE INDEX tracks_album_idx   ON tracks (album_id);
CREATE INDEX albums_artist_idx  ON albums (artist_id);
CREATE INDEX artist_genres_genre_idx ON artist_genres (genre_id);

-- ---------------------------------------------------------------------
-- Rohdaten: weitere Exportdateien (Account Data, Technical Log) unverändert
-- als JSONB. So geht nichts verloren, ohne dass dafür sofort Tabellen
-- modelliert werden müssen.
-- ---------------------------------------------------------------------
CREATE TABLE raw_documents (
    raw_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         integer NOT NULL REFERENCES users (user_id),
    source_package  text    NOT NULL,      -- z. B. 'account_data', 'technical_log'
    file_name       text    NOT NULL,
    sha256          char(64) NOT NULL,
    imported_at     timestamptz NOT NULL DEFAULT now(),
    payload         jsonb   NOT NULL,
    UNIQUE (user_id, source_package, file_name, sha256)
);

COMMIT;
