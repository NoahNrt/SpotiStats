-- =====================================================================
-- SpotiStats – Auswertungs-Views (Grundlage für Web-Anwendung und Grafana)
-- Anzeigezeit in Europe/Berlin, gespeichert wird UTC.
-- Die Datei darf jederzeit erneut ausgeführt werden (DROP + CREATE).
-- =====================================================================

BEGIN;

DROP VIEW IF EXISTS
    v_playlist_overview, v_library_current, v_top_items_snapshots, v_daily_listening,
    v_genre_listening, v_top_tracks, v_top_artists, v_monthly_listening,
    v_play_details, v_plays_combined;

-- ---------------------------------------------------------------------
-- Alle Wiedergaben aus Export und API in einer Sicht.
-- API-Wiedergaben zählen nur NACH der letzten Wiedergabe des Exports, damit
-- Zeiträume, die der Export schon abdeckt, nicht doppelt vorkommen.
-- Für API-Wiedergaben ist ms_played die volle Titellänge (Annäherung), und sie
-- gelten als Stream (Annahme: die API listet nur tatsächlich gehörte Titel).
-- ---------------------------------------------------------------------
CREATE VIEW v_plays_combined AS
SELECT  'export'::text            AS source,
        p.play_id                 AS source_play_id,
        p.user_id,
        p.played_at,
        p.ms_played,
        p.is_counted_stream,
        p.content_type::text      AS content_type,
        p.track_id,
        p.episode_id,
        p.chapter_id,
        p.platform,
        p.conn_country,
        p.reason_start,
        p.reason_end,
        p.shuffle,
        p.skipped,
        p.offline,
        p.incognito_mode
FROM    plays p
UNION ALL
SELECT  'api'::text,
        a.api_play_id,
        a.user_id,
        a.played_at,
        t.duration_ms,
        true,
        'track'::text,
        a.track_id,
        NULL::bigint,
        NULL::bigint,
        NULL::text,
        NULL::text,
        NULL::text,
        NULL::text,
        NULL::boolean,
        NULL::boolean,
        NULL::boolean,
        NULL::boolean
FROM    api_plays a
JOIN    tracks t ON t.track_id = a.track_id
WHERE   a.played_at > COALESCE(
            (SELECT max(p2.played_at) FROM plays p2 WHERE p2.user_id = a.user_id),
            '-infinity'::timestamptz);

CREATE VIEW v_play_details AS
SELECT  p.source,
        p.source_play_id,
        p.user_id,
        p.played_at,
        (p.played_at AT TIME ZONE 'Europe/Berlin')            AS played_at_local,
        p.ms_played,
        p.is_counted_stream,
        p.content_type,
        COALESCE(t.title, e.title, c.chapter_title)           AS item_title,
        COALESCE(ar.name, s.name, c.audiobook_title)          AS creator_name,
        al.title                                              AS album_title,
        p.platform,
        p.conn_country,
        p.reason_start,
        p.reason_end,
        p.shuffle,
        p.skipped,
        p.offline,
        p.incognito_mode
FROM    v_plays_combined p
LEFT JOIN tracks             t  ON t.track_id    = p.track_id
LEFT JOIN artists            ar ON ar.artist_id  = t.artist_id
LEFT JOIN albums             al ON al.album_id   = t.album_id
LEFT JOIN episodes           e  ON e.episode_id  = p.episode_id
LEFT JOIN shows              s  ON s.show_id     = e.show_id
LEFT JOIN audiobook_chapters c  ON c.chapter_id  = p.chapter_id;

CREATE VIEW v_daily_listening AS
SELECT  user_id,
        (played_at AT TIME ZONE 'Europe/Berlin')::date                AS day,
        count(*) FILTER (WHERE is_counted_stream)                     AS streams,
        round(sum(ms_played) / 3600000.0, 2)                          AS hours_played
FROM    v_plays_combined
GROUP BY user_id, (played_at AT TIME ZONE 'Europe/Berlin')::date;

CREATE VIEW v_monthly_listening AS
SELECT  user_id,
        date_trunc('month', played_at AT TIME ZONE 'Europe/Berlin')::date AS month,
        count(*) FILTER (WHERE is_counted_stream)                         AS streams,
        round(sum(ms_played) / 3600000.0, 2)                              AS hours_played
FROM    v_plays_combined
GROUP BY user_id, date_trunc('month', played_at AT TIME ZONE 'Europe/Berlin')::date;

-- Zählt beim Hauptkünstler des Titels
CREATE VIEW v_top_artists AS
SELECT  p.user_id,
        ar.artist_id,
        ar.name                                          AS artist_name,
        count(*) FILTER (WHERE p.is_counted_stream)      AS streams,
        round(sum(p.ms_played) / 3600000.0, 2)           AS hours_played
FROM    v_plays_combined p
JOIN    tracks  t  ON t.track_id   = p.track_id
JOIN    artists ar ON ar.artist_id = t.artist_id
GROUP BY p.user_id, ar.artist_id, ar.name;

CREATE VIEW v_top_tracks AS
SELECT  p.user_id,
        t.track_id,
        t.title                                          AS track_title,
        ar.name                                          AS artist_name,
        count(*) FILTER (WHERE p.is_counted_stream)      AS streams,
        round(sum(p.ms_played) / 3600000.0, 2)           AS hours_played
FROM    v_plays_combined p
JOIN    tracks  t  ON t.track_id   = p.track_id
LEFT JOIN artists ar ON ar.artist_id = t.artist_id
GROUP BY p.user_id, t.track_id, t.title, ar.name;

-- Ein Künstler mit mehreren Genres zählt bei jedem davon; die Summe über alle
-- Genres ist deshalb größer als die Gesamtzahl der Wiedergaben.
CREATE VIEW v_genre_listening AS
SELECT  p.user_id,
        g.name                                           AS genre,
        count(*) FILTER (WHERE p.is_counted_stream)      AS streams,
        round(sum(p.ms_played) / 3600000.0, 2)           AS hours_played
FROM    v_plays_combined p
JOIN    tracks         t  ON t.track_id   = p.track_id
JOIN    artist_genres  ag ON ag.artist_id = t.artist_id
JOIN    genres         g  ON g.genre_id   = ag.genre_id
GROUP BY p.user_id, g.name;

-- Top-Listen der API als Momentaufnahmen mit Namen
CREATE VIEW v_top_items_snapshots AS
SELECT  ti.user_id,
        ti.collected_on,
        ti.item_type,
        ti.time_range,
        ti.rank_no,
        COALESCE(t.title, a.name)                        AS name,
        CASE WHEN ti.item_type = 'track' THEN ar.name END AS artist_name
FROM    top_items ti
LEFT JOIN tracks  t  ON t.track_id   = ti.track_id
LEFT JOIN artists ar ON ar.artist_id = t.artist_id
LEFT JOIN artists a  ON a.artist_id  = ti.artist_id;

-- Aktuelle Bibliothek (entfernte Einträge ausgeblendet)
CREATE VIEW v_library_current AS
SELECT  user_id, item_type, name, added_at, first_seen_at,
        track_id, album_id, artist_id, show_id, episode_id
FROM    library_items
WHERE   removed_at IS NULL;

CREATE VIEW v_playlist_overview AS
SELECT  p.user_id,
        p.playlist_id,
        p.name,
        p.owner_name,
        p.is_public,
        p.is_collaborative,
        p.total_items,
        p.items_synced_at,
        count(pi.pos)                                    AS items_stored
FROM    playlists p
LEFT JOIN playlist_items pi ON pi.playlist_id = p.playlist_id
WHERE   p.removed_at IS NULL
GROUP BY p.user_id, p.playlist_id, p.name, p.owner_name, p.is_public,
         p.is_collaborative, p.total_items, p.items_synced_at;

COMMIT;
