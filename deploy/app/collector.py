#!/usr/bin/env python3
"""
SpotiStats – Collector

Ruft Daten über die Spotify-API (Spotipy) ab und speichert sie in PostgreSQL.

Unterkommandos
  auth     einmalige Anmeldung (Browser nötig), erzeugt die Token-Datei
  run      Jobs einmal ausführen (alle oder --only recent,top,...)
  loop     Dauerbetrieb mit festen Intervallen (für den Container)
  status   letzte Läufe je Job anzeigen

Jobs
  profile    Konto prüfen, Spotify-Benutzer-ID speichern
  recent     zuletzt gespielte Titel            -> api_plays
  top        Top-Titel/-Künstler (3 Zeiträume)  -> top_items
  library    gespeicherte Titel, Alben, Shows, Folgen, Hörbücher, gefolgte Künstler -> library_items
  playlists  Playlists und ihre Inhalte         -> playlists, playlist_items
  enrich     Details für Titel/Künstler aus dem Export nachholen (IDs, Dauer, Genres)

Umgebungsvariablen
  SPOTISTATS_DSN        z. B. postgresql://spotistats:PASSWORT@db:5432/spotistats
  SPOTISTATS_USER       Anzeigename des Benutzers in der Datenbank (Standard: noah)
  SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI (alternativ SPOTIFY_CLIENT_ID/_SECRET/_REDIRECT_URI)
  SPOTIPY_CACHE_PATH    Token-Datei (Standard: .spotify_token)
  RECENT_INTERVAL_MIN (30), ENRICH_INTERVAL_MIN (60), DAILY_INTERVAL_H (24),
  ENRICH_LIMIT (300 API-Abfragen je Enrich-Lauf), API_DELAY_S (0.3)

Hinweis zur API (Development Mode, Stand 2026): keine Batch-Abfragen, keine
Popularität/Follower, Playlist-Inhalte nur für eigene oder gemeinsam bearbeitete
Playlists. Der Collector verwendet deshalb nur Einzelabfragen und behandelt
fehlende Felder als "nicht vorhanden".
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

try:
    from spotipy.exceptions import SpotifyException
except ImportError:  # nur für Tests ohne installiertes Spotipy
    class SpotifyException(Exception):
        def __init__(self, http_status=None, code=None, msg="", reason=None, headers=None):
            super().__init__(msg)
            self.http_status = http_status
            self.msg = msg
            self.headers = headers or {}

SCOPE = ("user-read-recently-played user-top-read user-library-read user-follow-read "
         "playlist-read-private playlist-read-collaborative")

log = logging.getLogger("collector")


class RateLimited(Exception):
    """Spotify verlangt eine längere Pause; der Job wird abgebrochen und später wiederholt."""


class AuthMissing(Exception):
    """Token-Datei fehlt oder passt nicht zu den benötigten Rechten."""


# ---------------------------------------------------------------------------
# Hilfsfunktionen (ohne Datenbank, gut testbar)
# ---------------------------------------------------------------------------
def parse_iso(value):
    """ISO-8601 mit 'Z' -> UTC-datetime; None bei leeren/ungültigen Werten."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_release_date(value):
    """Spotify liefert '2020', '2020-05' oder '2020-05-17' -> date oder None."""
    if not value:
        return None
    parts = str(value).split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# API-Zugriff mit Drosselung, Wiederholung und Rate-Limit-Behandlung
# ---------------------------------------------------------------------------
class Api:
    def __init__(self, sp, delay=0.3, max_wait=300):
        self.sp = sp
        self.delay = delay
        self.max_wait = max_wait

    def call(self, name, *args, **kwargs):
        """Ruft eine Methode des Spotipy-Clients auf. Gibt None zurück, wenn der Eintrag nicht (mehr) existiert."""
        for attempt in range(4):
            if self.delay:
                time.sleep(self.delay)
            try:
                return getattr(self.sp, name)(*args, **kwargs)
            except SpotifyException as exc:
                status = getattr(exc, "http_status", None)
                if status == 429:
                    headers = getattr(exc, "headers", None) or {}
                    wait = int(headers.get("Retry-After", headers.get("retry-after", 5))) + 1
                    if wait > self.max_wait:
                        raise RateLimited(f"Retry-After {wait} s") from exc
                    log.warning("429 von Spotify, warte %s s", wait)
                    time.sleep(wait)
                    continue
                if status in (500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                if status == 404:
                    return None
                raise
        raise RateLimited("zu viele Wiederholungen")


def pages(api, method, *args, page_size=50, **kwargs):
    """Liest eine offset-basierte Liste vollständig (Generator über die Einträge)."""
    offset = 0
    while True:
        page = api.call(method, *args, limit=page_size, offset=offset, **kwargs)
        if not page:
            return
        items = page.get("items") or []
        yield from items
        if not page.get("next") or not items:
            return
        offset += page_size


# ---------------------------------------------------------------------------
# Katalog-Schreibzugriffe
# ---------------------------------------------------------------------------
class Store:
    """Legt Künstler, Alben, Titel ... an oder ergänzt sie, ohne Zeilen aus dem Export zu verdoppeln."""

    def __init__(self, cur):
        self.cur = cur
        self.tracks_done = {}     # uri -> track_id (pro Lauf)
        self.artists_done = {}    # spotify_artist_id -> artist_id

    # -- Künstler ----------------------------------------------------------
    def resolve_artist(self, sid, name, hint_id=None):
        if not sid:
            return None
        if sid in self.artists_done:
            return self.artists_done[sid]
        cur = self.cur
        row = cur.execute("SELECT artist_id FROM artists WHERE spotify_artist_id = %s", (sid,)).fetchone()
        aid = row[0] if row else None
        if aid is None and hint_id is not None:
            row = cur.execute(
                "UPDATE artists SET spotify_artist_id = %s "
                "WHERE artist_id = %s AND spotify_artist_id IS NULL AND name = %s RETURNING artist_id",
                (sid, hint_id, name)).fetchone()
            aid = row[0] if row else None
        if aid is None and name:
            row = cur.execute(
                "UPDATE artists SET spotify_artist_id = %s WHERE artist_id = ("
                "  SELECT artist_id FROM artists WHERE name = %s AND spotify_artist_id IS NULL "
                "  ORDER BY artist_id LIMIT 1) RETURNING artist_id",
                (sid, name)).fetchone()
            aid = row[0] if row else None
        if aid is None:
            aid = cur.execute(
                "INSERT INTO artists (name, spotify_artist_id) VALUES (%s, %s) "
                "ON CONFLICT (spotify_artist_id) DO UPDATE SET name = artists.name RETURNING artist_id",
                (name or sid, sid)).fetchone()[0]
        self.artists_done[sid] = aid
        return aid

    def ingest_artist(self, obj, hint_id=None):
        """Künstlerobjekt der API (mit oder ohne Genres) speichern."""
        aid = self.resolve_artist(obj.get("id"), obj.get("name"), hint_id)
        if aid is not None and "genres" in obj:
            self.set_genres(aid, obj.get("genres") or [])
        return aid

    def set_genres(self, artist_id, genres):
        cur = self.cur
        for genre in genres:
            gid = cur.execute(
                "INSERT INTO genres (name) VALUES (%s) "
                "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING genre_id",
                (genre,)).fetchone()[0]
            cur.execute("INSERT INTO artist_genres (artist_id, genre_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (artist_id, gid))
        cur.execute("UPDATE artists SET genres_synced_at = now() WHERE artist_id = %s", (artist_id,))

    # -- Alben -------------------------------------------------------------
    def resolve_album(self, album, primary_artist_id, hint_id=None):
        asid = album.get("id")
        title = album.get("name")
        if not asid or not title:
            return None
        cur = self.cur
        release = parse_release_date(album.get("release_date"))
        row = cur.execute("SELECT album_id FROM albums WHERE spotify_album_id = %s", (asid,)).fetchone()
        if row:
            return row[0]
        row = None
        if hint_id is not None:
            row = cur.execute(
                "UPDATE albums SET spotify_album_id = %s, release_date = COALESCE(release_date, %s) "
                "WHERE album_id = %s AND spotify_album_id IS NULL AND title = %s RETURNING album_id",
                (asid, release, hint_id, title)).fetchone()
        if row is None:
            row = cur.execute(
                "UPDATE albums SET spotify_album_id = %s, release_date = COALESCE(release_date, %s) "
                "WHERE album_id = ("
                "  SELECT album_id FROM albums WHERE title = %s AND artist_id IS NOT DISTINCT FROM %s "
                "  AND spotify_album_id IS NULL ORDER BY album_id LIMIT 1) RETURNING album_id",
                (asid, release, title, primary_artist_id)).fetchone()
        if row is None:
            row = cur.execute(
                "INSERT INTO albums (title, artist_id, spotify_album_id, release_date) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (spotify_album_id) DO UPDATE SET title = albums.title RETURNING album_id",
                (title, primary_artist_id, asid, release)).fetchone()
        return row[0]

    def ingest_album(self, album):
        """Album-Objekt der API (z. B. gespeicherte Alben)."""
        artist_ids = [self.ingest_artist(a) for a in (album.get("artists") or [])]
        artist_ids = [a for a in artist_ids if a is not None]
        return self.resolve_album(album, artist_ids[0] if artist_ids else None)

    # -- Titel -------------------------------------------------------------
    def ingest_track(self, track):
        """Titel-Objekt der API speichern. Gibt track_id zurück oder None (z. B. lokale Dateien)."""
        uri = track.get("uri")
        if not uri or not track.get("id") or track.get("is_local"):
            return None
        if uri in self.tracks_done:
            return self.tracks_done[uri]
        cur = self.cur
        existing = cur.execute(
            "SELECT track_id, artist_id, album_id FROM tracks WHERE spotify_track_uri = %s", (uri,)).fetchone()
        hint_artist = existing[1] if existing else None
        hint_album = existing[2] if existing else None

        artist_ids = []
        for index, artist in enumerate(track.get("artists") or []):
            aid = self.ingest_artist(artist, hint_artist if index == 0 else None)
            if aid is not None and aid not in artist_ids:
                artist_ids.append(aid)
        primary = artist_ids[0] if artist_ids else None

        album = track.get("album") or {}
        album_id = self.resolve_album(album, primary, hint_album) if album else None
        duration = track.get("duration_ms") if isinstance(track.get("duration_ms"), int) else None

        track_id = cur.execute(
            "INSERT INTO tracks (spotify_track_uri, title, artist_id, album_id, duration_ms, enriched_at) "
            "VALUES (%s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (spotify_track_uri) DO UPDATE SET "
            "  title = EXCLUDED.title, "
            "  artist_id = COALESCE(EXCLUDED.artist_id, tracks.artist_id), "
            "  album_id = COALESCE(EXCLUDED.album_id, tracks.album_id), "
            "  duration_ms = COALESCE(EXCLUDED.duration_ms, tracks.duration_ms), "
            "  enriched_at = now() "
            "RETURNING track_id",
            (uri, track.get("name") or uri, primary, album_id, duration)).fetchone()[0]
        for pos, aid in enumerate(artist_ids):
            cur.execute(
                "INSERT INTO track_artists (track_id, artist_id, pos) VALUES (%s, %s, %s) "
                "ON CONFLICT (track_id, artist_id) DO UPDATE SET pos = EXCLUDED.pos",
                (track_id, aid, pos))
        self.tracks_done[uri] = track_id
        return track_id

    # -- Podcasts ----------------------------------------------------------
    def resolve_show(self, show):
        sid = (show or {}).get("id")
        name = (show or {}).get("name")
        if not sid:
            return None
        cur = self.cur
        row = cur.execute("SELECT show_id FROM shows WHERE spotify_show_id = %s", (sid,)).fetchone()
        if row is None and name:
            row = cur.execute(
                "UPDATE shows SET spotify_show_id = %s WHERE show_id = ("
                "  SELECT show_id FROM shows WHERE name = %s AND spotify_show_id IS NULL "
                "  ORDER BY show_id LIMIT 1) RETURNING show_id",
                (sid, name)).fetchone()
        if row is None:
            row = cur.execute(
                "INSERT INTO shows (name, spotify_show_id) VALUES (%s, %s) "
                "ON CONFLICT (spotify_show_id) DO UPDATE SET name = shows.name RETURNING show_id",
                (name or sid, sid)).fetchone()
        return row[0]

    def ingest_episode(self, episode):
        uri = episode.get("uri")
        if not uri or not episode.get("id"):
            return None
        show_id = self.resolve_show(episode.get("show"))
        return self.cur.execute(
            "INSERT INTO episodes (spotify_episode_uri, title, show_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (spotify_episode_uri) DO UPDATE SET "
            "  title = EXCLUDED.title, show_id = COALESCE(EXCLUDED.show_id, episodes.show_id) "
            "RETURNING episode_id",
            (uri, episode.get("name") or uri, show_id)).fetchone()[0]

    # -- Bibliothek --------------------------------------------------------
    def library_upsert(self, user_id, item_type, spotify_id, name, added_at, started, **links):
        self.cur.execute(
            "INSERT INTO library_items (user_id, item_type, spotify_id, name, added_at, first_seen_at, last_seen_at, "
            "                           track_id, album_id, artist_id, show_id, episode_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, item_type, spotify_id) DO UPDATE SET "
            "  name = EXCLUDED.name, "
            "  added_at = COALESCE(EXCLUDED.added_at, library_items.added_at), "
            "  last_seen_at = EXCLUDED.last_seen_at, "
            "  removed_at = NULL, "
            "  track_id = COALESCE(EXCLUDED.track_id, library_items.track_id), "
            "  album_id = COALESCE(EXCLUDED.album_id, library_items.album_id), "
            "  artist_id = COALESCE(EXCLUDED.artist_id, library_items.artist_id), "
            "  show_id = COALESCE(EXCLUDED.show_id, library_items.show_id), "
            "  episode_id = COALESCE(EXCLUDED.episode_id, library_items.episode_id)",
            (user_id, item_type, spotify_id, name, added_at, started, started,
             links.get("track_id"), links.get("album_id"), links.get("artist_id"),
             links.get("show_id"), links.get("episode_id")))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
@dataclass
class Ctx:
    conn: object
    api: Api
    user_id: int
    spotify_user_id: str | None = None
    enrich_limit: int = 300
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    store: Store | None = None

    @property
    def cur(self):
        return self.store.cur


def job_profile(ctx):
    me = ctx.api.call("current_user") or {}
    sid = me.get("id")
    if not sid:
        raise RuntimeError("Die API hat keine Benutzer-ID geliefert.")
    row = ctx.cur.execute("SELECT spotify_user_id FROM users WHERE user_id = %s", (ctx.user_id,)).fetchone()
    if row and row[0] and row[0] != sid:
        raise RuntimeError(f"Das Token gehört zu {sid}, in der Datenbank steht {row[0]}. Abbruch, um Daten nicht zu mischen.")
    ctx.cur.execute("UPDATE users SET spotify_user_id = %s WHERE user_id = %s", (sid, ctx.user_id))
    ctx.spotify_user_id = sid
    return 1, 1, f"Konto {sid}"


def job_recent(ctx):
    page = ctx.api.call("current_user_recently_played", limit=50) or {}
    items = page.get("items") or []
    written = 0
    for item in items:
        played_at = parse_iso(item.get("played_at"))
        track_id = ctx.store.ingest_track(item.get("track") or {})
        if track_id is None or played_at is None:
            continue
        context = item.get("context") or {}
        ctx.cur.execute(
            "INSERT INTO api_plays (user_id, played_at, track_id, context_type, context_uri) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (ctx.user_id, played_at, track_id, context.get("type"), context.get("uri")))
        written += ctx.cur.rowcount
    return len(items), written, ""


def job_top(ctx):
    fetched = written = 0
    day = ctx.started.date()
    for item_type, method in (("track", "current_user_top_tracks"), ("artist", "current_user_top_artists")):
        for time_range in ("short_term", "medium_term", "long_term"):
            page = ctx.api.call(method, limit=50, offset=0, time_range=time_range) or {}
            items = page.get("items") or []
            ctx.cur.execute(
                "DELETE FROM top_items WHERE user_id = %s AND collected_on = %s AND item_type = %s AND time_range = %s",
                (ctx.user_id, day, item_type, time_range))
            for rank, obj in enumerate(items, start=1):
                fetched += 1
                if item_type == "track":
                    track_id, artist_id = ctx.store.ingest_track(obj), None
                    if track_id is None:
                        continue
                else:
                    track_id, artist_id = None, ctx.store.ingest_artist(obj)
                    if artist_id is None:
                        continue
                ctx.cur.execute(
                    "INSERT INTO top_items (user_id, collected_on, item_type, time_range, rank_no, track_id, artist_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (ctx.user_id, day, item_type, time_range, rank, track_id, artist_id))
                written += 1
    return fetched, written, ""


# (Typ, Spotipy-Methode, feste Argumente, Schlüssel im Eintrag)
LIBRARY_SOURCES = [
    ("track", "current_user_saved_tracks", (), "track"),
    ("album", "current_user_saved_albums", (), "album"),
    ("show", "current_user_saved_shows", (), "show"),
    ("episode", "_get", ("me/episodes",), "episode"),
    ("audiobook", "_get", ("me/audiobooks",), "audiobook"),
]


def _mark_removed(ctx, item_type):
    ctx.cur.execute(
        "UPDATE library_items SET removed_at = %s "
        "WHERE user_id = %s AND item_type = %s AND last_seen_at < %s AND removed_at IS NULL",
        (ctx.started, ctx.user_id, item_type, ctx.started))


def job_library(ctx):
    fetched = written = 0
    notes = []
    store, started = ctx.store, ctx.started

    for item_type, method, args, key in LIBRARY_SOURCES:
        try:
            for entry in pages(ctx.api, method, *args):
                fetched += 1
                obj = entry.get(key) or entry
                sid = obj.get("id")
                if not sid:
                    continue
                links = {}
                if item_type == "track":
                    links["track_id"] = store.ingest_track(obj)
                    if links["track_id"] is None:
                        continue
                elif item_type == "album":
                    links["album_id"] = store.ingest_album(obj)
                elif item_type == "show":
                    links["show_id"] = store.resolve_show(obj)
                elif item_type == "episode":
                    links["episode_id"] = store.ingest_episode(obj)
                store.library_upsert(ctx.user_id, item_type, sid, obj.get("name"),
                                     parse_iso(entry.get("added_at")), started, **links)
                written += 1
        except SpotifyException as exc:
            if getattr(exc, "http_status", None) in (400, 403):
                notes.append(f"{item_type}: nicht verfügbar ({exc.http_status})")
                continue
            raise
        _mark_removed(ctx, item_type)

    # gefolgte Künstler (Cursor statt Offset)
    after = None
    while True:
        result = ctx.api.call("current_user_followed_artists", limit=50, after=after) or {}
        block = result.get("artists") or {}
        items = block.get("items") or []
        for artist in items:
            fetched += 1
            artist_id = store.ingest_artist(artist)
            if artist_id is None:
                continue
            store.library_upsert(ctx.user_id, "artist", artist["id"], artist.get("name"), None, started,
                                 artist_id=artist_id)
            written += 1
        after = (block.get("cursors") or {}).get("after")
        if not after or not items:
            break
    _mark_removed(ctx, "artist")
    return fetched, written, "; ".join(notes)


def _playlist_items(ctx, spotify_playlist_id):
    """Inhalte über GET /playlists/{id}/items holen (seit Februar 2026 der einzige Endpunkt)."""
    return list(pages(ctx.api, "_get", f"playlists/{spotify_playlist_id}/items", additional_types="track,episode"))


def _sync_playlist_items(ctx, local_id, spotify_playlist_id, snapshot_id, expected_total):
    entries = _playlist_items(ctx, spotify_playlist_id)
    if not entries and expected_total:
        log.warning("Playlist %s: API lieferte keine Einträge, obwohl %s erwartet wurden - nichts geändert",
                    spotify_playlist_id, expected_total)
        return 0
    cur, store = ctx.cur, ctx.store
    stored = 0
    with ctx.conn.transaction():
        cur.execute("DELETE FROM playlist_items WHERE playlist_id = %s", (local_id,))
        for pos, entry in enumerate(entries):
            obj = entry.get("item") or entry.get("track")
            if not obj or entry.get("is_local"):
                continue
            kind = obj.get("type")
            track_id = episode_id = None
            if kind == "track":
                track_id = store.ingest_track(obj)
            elif kind == "episode":
                episode_id = store.ingest_episode(obj)
            if track_id is None and episode_id is None:
                continue
            added_by = (entry.get("added_by") or {}).get("id")
            cur.execute(
                "INSERT INTO playlist_items (playlist_id, pos, content_type, track_id, episode_id, added_at, added_by_spotify_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (local_id, pos, "track" if track_id is not None else "episode", track_id, episode_id,
                 parse_iso(entry.get("added_at")), added_by))
            stored += 1
        cur.execute("UPDATE playlists SET snapshot_id = %s, items_synced_at = now() WHERE playlist_id = %s",
                    (snapshot_id, local_id))
    return stored


def job_playlists(ctx):
    fetched = synced = no_access = 0
    cur = ctx.cur
    for playlist in pages(ctx.api, "current_user_playlists"):
        spotify_playlist_id = playlist.get("id")
        if not spotify_playlist_id:
            continue
        fetched += 1
        owner = playlist.get("owner") or {}
        meta = playlist.get("items") if isinstance(playlist.get("items"), dict) else playlist.get("tracks")
        total = (meta or {}).get("total")
        row = cur.execute(
            "INSERT INTO playlists (user_id, spotify_playlist_id, name, description, owner_spotify_id, owner_name, "
            "                       is_public, is_collaborative, total_items, first_seen_at, last_seen_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, spotify_playlist_id) DO UPDATE SET "
            "  name = EXCLUDED.name, description = EXCLUDED.description, "
            "  owner_spotify_id = EXCLUDED.owner_spotify_id, owner_name = EXCLUDED.owner_name, "
            "  is_public = EXCLUDED.is_public, is_collaborative = EXCLUDED.is_collaborative, "
            "  total_items = EXCLUDED.total_items, last_seen_at = EXCLUDED.last_seen_at, removed_at = NULL "
            "RETURNING playlist_id, snapshot_id, items_synced_at",
            (ctx.user_id, spotify_playlist_id, playlist.get("name") or spotify_playlist_id, playlist.get("description"),
             owner.get("id"), owner.get("display_name"), playlist.get("public"), playlist.get("collaborative"),
             total, ctx.started, ctx.started)).fetchone()
        local_id, old_snapshot, synced_at = row
        readable = owner.get("id") == ctx.spotify_user_id or bool(playlist.get("collaborative"))
        if not readable:
            no_access += 1
            continue
        snapshot = playlist.get("snapshot_id")
        if synced_at is None or snapshot != old_snapshot:
            try:
                _sync_playlist_items(ctx, local_id, spotify_playlist_id, snapshot, total)
                synced += 1
            except SpotifyException as exc:
                if getattr(exc, "http_status", None) == 403:
                    no_access += 1
                    continue
                raise
    cur.execute("UPDATE playlists SET removed_at = %s WHERE user_id = %s AND last_seen_at < %s AND removed_at IS NULL",
                (ctx.started, ctx.user_id, ctx.started))
    msg = f"{no_access} Playlists ohne Zugriff auf die Inhalte" if no_access else ""
    return fetched, synced, msg


def job_enrich(ctx):
    """Details für Titel und Künstler aus dem Export nachholen, meistgehörte zuerst."""
    cur, store, api = ctx.cur, ctx.store, ctx.api
    budget = max(ctx.enrich_limit, 0)
    done_artists = done_tracks = 0

    artist_rows = cur.execute(
        "SELECT a.artist_id, a.spotify_artist_id FROM artists a "
        "LEFT JOIN (SELECT t.artist_id, count(*) AS n FROM plays p JOIN tracks t ON t.track_id = p.track_id "
        "           GROUP BY t.artist_id) ac ON ac.artist_id = a.artist_id "
        "WHERE a.spotify_artist_id IS NOT NULL AND a.genres_synced_at IS NULL "
        "ORDER BY COALESCE(ac.n, 0) DESC, a.artist_id LIMIT %s",
        (budget // 2,)).fetchall()
    for artist_id, spotify_artist_id in artist_rows:
        obj = api.call("artist", spotify_artist_id)
        if obj:
            store.ingest_artist(obj)
        else:
            cur.execute("UPDATE artists SET genres_synced_at = now() WHERE artist_id = %s", (artist_id,))
        done_artists += 1
        if done_artists % 25 == 0:
            ctx.conn.commit()

    remaining = budget - done_artists
    track_rows = cur.execute(
        "SELECT t.track_id, t.spotify_track_uri FROM tracks t "
        "LEFT JOIN (SELECT track_id, count(*) AS n FROM plays WHERE track_id IS NOT NULL GROUP BY track_id) pc "
        "  ON pc.track_id = t.track_id "
        "WHERE t.enriched_at IS NULL AND starts_with(t.spotify_track_uri, 'spotify:track:') "
        "ORDER BY COALESCE(pc.n, 0) DESC, t.track_id LIMIT %s",
        (max(remaining, 0),)).fetchall()
    for track_id, uri in track_rows:
        obj = api.call("track", uri)
        if (store.ingest_track(obj) if obj else None) is None:
            # nicht mehr abrufbar: nicht bei jedem Lauf erneut versuchen
            cur.execute("UPDATE tracks SET enriched_at = now() WHERE track_id = %s", (track_id,))
        done_tracks += 1
        if done_tracks % 25 == 0:
            ctx.conn.commit()

    left_tracks = cur.execute(
        "SELECT count(*) FROM tracks WHERE enriched_at IS NULL AND starts_with(spotify_track_uri, 'spotify:track:')"
    ).fetchone()[0]
    return done_artists + done_tracks, done_artists + done_tracks, \
        f"{done_tracks} Titel, {done_artists} Künstler; noch offen: {left_tracks} Titel"


JOBS = {
    "profile": job_profile,
    "recent": job_recent,
    "top": job_top,
    "library": job_library,
    "playlists": job_playlists,
    "enrich": job_enrich,
}
ORDER = ["profile", "recent", "top", "library", "playlists", "enrich"]


def intervals():
    daily = float(os.environ.get("DAILY_INTERVAL_H", "24")) * 3600
    return {
        "profile": daily,
        "recent": float(os.environ.get("RECENT_INTERVAL_MIN", "30")) * 60,
        "top": daily,
        "library": daily,
        "playlists": daily,
        "enrich": float(os.environ.get("ENRICH_INTERVAL_MIN", "60")) * 60,
    }


# ---------------------------------------------------------------------------
# Ablauf: Verbindung, Jobs, Protokoll
# ---------------------------------------------------------------------------
def ensure_user(cur, display_name):
    cur.execute("INSERT INTO users (display_name) VALUES (%s) ON CONFLICT (display_name) DO NOTHING", (display_name,))
    return cur.execute("SELECT user_id FROM users WHERE display_name = %s", (display_name,)).fetchone()[0]


def is_due(cur, user_id, job, interval_s, retry_after_error_s=900):
    """Fällig, wenn der letzte erfolgreiche Lauf länger als das Intervall zurückliegt.
    Nach einem Fehler wird frühestens nach 15 Minuten wiederholt (kein Dauerfeuer auf die API)."""
    row = cur.execute(
        "SELECT max(started_at) FILTER (WHERE status = 'ok'), max(started_at) FILTER (WHERE status = 'error') "
        "FROM collector_runs WHERE user_id = %s AND job = %s",
        (user_id, job)).fetchone()
    last_ok, last_error = (row or (None, None))
    now = datetime.now(timezone.utc)
    if last_error is not None and (now - last_error).total_seconds() < retry_after_error_s:
        return False
    return last_ok is None or (now - last_ok).total_seconds() >= interval_s


def run_job(ctx, name):
    """Führt einen Job aus und protokolliert ihn. Gibt 'ok', 'error' oder 'ratelimited' zurück."""
    conn = ctx.conn
    ctx.started = datetime.now(timezone.utc)
    ctx.store = Store(conn.cursor())
    cur = ctx.cur
    run_id = cur.execute("INSERT INTO collector_runs (user_id, job) VALUES (%s, %s) RETURNING run_id",
                         (ctx.user_id, name)).fetchone()[0]
    conn.commit()
    status, message, fetched, written = "ok", "", None, None
    result = "ok"
    try:
        fetched, written, message = JOBS[name](ctx)
        conn.commit()
    except RateLimited as exc:
        conn.rollback()
        status, message, result = "error", f"Rate-Limit: {exc}", "ratelimited"
        log.warning("%s: %s", name, message)
    except Exception as exc:  # noqa: BLE001 - jeder Fehler wird protokolliert, der Dienst läuft weiter
        conn.rollback()
        status, message, result = "error", f"{type(exc).__name__}: {exc}", "error"
        log.exception("%s fehlgeschlagen", name)
    cur = conn.cursor()
    cur.execute(
        "UPDATE collector_runs SET finished_at = now(), status = %s, items_fetched = %s, items_written = %s, "
        "message = %s WHERE run_id = %s",
        (status, fetched, written, (message or "")[:500], run_id))
    conn.commit()
    if status == "ok":
        log.info("%s: %s gelesen, %s geschrieben %s", name, fetched, written, message)
    return result


def apply_env_aliases():
    """Akzeptiert auch SPOTIFY_CLIENT_ID/_SECRET/_REDIRECT_URI (wie in main.py) statt SPOTIPY_*."""
    for suffix in ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI"):
        if not os.environ.get(f"SPOTIPY_{suffix}") and os.environ.get(f"SPOTIFY_{suffix}"):
            os.environ[f"SPOTIPY_{suffix}"] = os.environ[f"SPOTIFY_{suffix}"]


def make_client(interactive=False):
    apply_env_aliases()
    import spotipy
    from spotipy.cache_handler import CacheFileHandler
    from spotipy.oauth2 import SpotifyOAuth

    cache = CacheFileHandler(cache_path=os.environ.get("SPOTIPY_CACHE_PATH", ".spotify_token"))
    auth = SpotifyOAuth(scope=SCOPE, cache_handler=cache, open_browser=interactive)
    if not interactive and auth.validate_token(cache.get_cached_token()) is None:
        raise AuthMissing("Token fehlt oder hat nicht die nötigen Rechte. "
                          "Auf einem Rechner mit Browser 'python collector.py auth' ausführen und die Token-Datei kopieren.")
    return spotipy.Spotify(auth_manager=auth, requests_timeout=20, retries=1, status_retries=0)


def connect():
    import psycopg
    dsn = os.environ.get("SPOTISTATS_DSN")
    if not dsn:
        sys.exit("Umgebungsvariable SPOTISTATS_DSN ist nicht gesetzt.")
    return psycopg.connect(dsn)


def run_once(only=None, force=False):
    """Ein Durchlauf: fällige (oder gewählte) Jobs ausführen."""
    user_name = os.environ.get("SPOTISTATS_USER", "noah")
    enrich_limit = int(os.environ.get("ENRICH_LIMIT", "300"))
    delay = float(os.environ.get("API_DELAY_S", "0.3"))
    sp = make_client()
    with connect() as conn:
        cur = conn.cursor()
        user_id = ensure_user(cur, user_name)
        conn.commit()
        row = cur.execute("SELECT spotify_user_id FROM users WHERE user_id = %s", (user_id,)).fetchone()
        ctx = Ctx(conn=conn, api=Api(sp, delay=delay), user_id=user_id,
                  spotify_user_id=row[0], enrich_limit=enrich_limit)
        wanted = [j for j in ORDER if (only is None or j in only)]
        limits = intervals()
        if "playlists" in wanted and "profile" not in wanted and ctx.spotify_user_id is None:
            run_job(ctx, "profile")
        for job in wanted:
            if not force and not is_due(cur, user_id, job, limits[job]):
                continue
            if run_job(ctx, job) == "ratelimited":
                log.warning("Rate-Limit erreicht, restliche Jobs warten bis zum nächsten Durchlauf")
                return "ratelimited"
    return "ok"


# ---------------------------------------------------------------------------
# Kommandozeile
# ---------------------------------------------------------------------------
def cmd_auth(args):
    sp = make_client(interactive=True)
    me = sp.current_user()
    print(f"Angemeldet als {me.get('id')} ({me.get('display_name')}). Token-Datei: "
          f"{os.environ.get('SPOTIPY_CACHE_PATH', '.spotify_token')}")


def cmd_run(args):
    only = set(args.only.split(",")) if args.only else None
    if only and not only <= set(JOBS):
        sys.exit(f"Unbekannte Jobs: {', '.join(sorted(only - set(JOBS)))}. Möglich: {', '.join(ORDER)}")
    run_once(only=only, force=True)


def cmd_loop(args):
    log.info("Collector gestartet")
    while True:
        pause = 60
        try:
            if run_once() == "ratelimited":
                pause = 900
        except AuthMissing as exc:
            log.error("%s", exc)
            pause = 600
        except Exception:  # noqa: BLE001 - z. B. Datenbank noch nicht erreichbar
            log.exception("Durchlauf fehlgeschlagen, neuer Versuch in 60 s")
        time.sleep(pause)


def cmd_status(args):
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (job) job, status, started_at, items_fetched, items_written, message "
            "FROM collector_runs ORDER BY job, started_at DESC").fetchall()
    for job, status, started, fetched, written, message in rows:
        print(f"{job:10} {status:8} {started:%Y-%m-%d %H:%M} gelesen={fetched} geschrieben={written} {message or ''}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="SpotiStats – Collector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth", help="einmalige Anmeldung bei Spotify").set_defaults(func=cmd_auth)
    r = sub.add_parser("run", help="Jobs einmal ausführen")
    r.add_argument("--only", help="kommagetrennt, z. B. recent,top")
    r.set_defaults(func=cmd_run)
    sub.add_parser("loop", help="Dauerbetrieb").set_defaults(func=cmd_loop)
    sub.add_parser("status", help="letzte Läufe anzeigen").set_defaults(func=cmd_status)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
