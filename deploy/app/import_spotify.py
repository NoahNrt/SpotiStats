#!/usr/bin/env python3
"""
SpotiStats – Importskript für Spotify-Exporte (PostgreSQL)

Unterkommandos
  streaming  Extended Streaming History (Streaming_History_Audio_*.json) in die
             Tabellen plays / tracks / artists / albums / episodes ... importieren.
  raw        Beliebige JSON-Dateien (z. B. Account Data) unverändert als JSONB in
             raw_documents ablegen.

Verbindung
  Umgebungsvariable SPOTISTATS_DSN, z. B.
  postgresql://spotistats:PASSWORT@192.168.178.10:5432/spotistats

Beispiele
  python import_spotify.py streaming "~/Downloads/Spotify Extended Streaming History" --user noah --dry-run
  python import_spotify.py streaming "~/Downloads/Spotify Extended Streaming History" --user noah
  python import_spotify.py raw "~/Downloads/Spotify Account Data" --user noah --package account_data

Der Import ist idempotent: Mehrfaches Einlesen derselben oder überlappender
Dateien erzeugt keine Dubletten (UNIQUE-Constraint auf plays).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CHUNK_SIZE = 5000

# Dateien der Account Data, die standardmäßig als Rohdaten übernommen werden.
# Bewusst NICHT enthalten (Datenminimierung): Identity, Identifiers, Payments,
# MessageData, UserAttributes, Inferences, DuoNewFamily, AgentGateway, Marquee.
DEFAULT_RAW_INCLUDE = [
    "YourLibrary.json",
    "Playlist*.json",
    "Follow.json",
    "SearchQueries.json",
    "Wrapped*.json",
    "YourSoundCapsule.json",
]


# ---------------------------------------------------------------------------
# Parsen und Bereinigen der Exportzeilen (ohne Datenbank, gut testbar)
# ---------------------------------------------------------------------------
def clean(value):
    """Leere Strings zu None, Text trimmen."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def as_bool(value):
    return value if isinstance(value, bool) else None


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def parse_ts(value):
    """ISO-8601 ('2021-12-04T19:44:49Z') oder '2021-12-04 19:44:49' -> UTC-datetime."""
    value = clean(value)
    if value is None:
        return None
    text = str(value).replace("Z", "+00:00")
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_row(raw: dict):
    """Gibt (eintrag, None) zurück oder (None, grund), wenn die Zeile unbrauchbar ist."""
    played_at = parse_ts(raw.get("ts"))
    if played_at is None:
        return None, "kein_zeitstempel"

    ms_played = as_int(raw.get("ms_played"))
    if ms_played is None or ms_played < 0:
        return None, "ms_played_ungueltig"

    track_uri = clean(raw.get("spotify_track_uri"))
    episode_uri = clean(raw.get("spotify_episode_uri"))
    chapter_uri = clean(raw.get("audiobook_chapter_uri"))

    if track_uri:
        content_type = "track"
    elif episode_uri:
        content_type = "episode"
    elif chapter_uri:
        content_type = "audiobook_chapter"
    else:
        return None, "kein_inhalt"   # Zeilen ohne URI (kommen im Export vereinzelt vor)

    entry = {
        "played_at": played_at,
        "ms_played": ms_played,
        "content_type": content_type,
        "platform": clean(raw.get("platform")),
        "conn_country": clean(raw.get("conn_country")),
        "reason_start": clean(raw.get("reason_start")),
        "reason_end": clean(raw.get("reason_end")),
        "shuffle": as_bool(raw.get("shuffle")),
        "skipped": as_bool(raw.get("skipped")),
        "offline": as_bool(raw.get("offline")),
        "offline_timestamp": as_int(raw.get("offline_timestamp")),
        "incognito_mode": as_bool(raw.get("incognito_mode")),
        # Katalogdaten
        "track_uri": track_uri,
        "track_title": clean(raw.get("master_metadata_track_name")),
        "artist": clean(raw.get("master_metadata_album_artist_name")),
        "album": clean(raw.get("master_metadata_album_album_name")),
        "episode_uri": episode_uri,
        "episode_title": clean(raw.get("episode_name")),
        "show": clean(raw.get("episode_show_name")),
        "chapter_uri": chapter_uri,
        "chapter_title": clean(raw.get("audiobook_chapter_title")),
        "audiobook_title": clean(raw.get("audiobook_title")),
        "audiobook_uri": clean(raw.get("audiobook_uri")),
    }
    return entry, None


def find_files(path: str, pattern: str):
    p = Path(path).expanduser()
    if p.is_file():
        return [p]
    if not p.is_dir():
        sys.exit(f"Pfad nicht gefunden: {p}")
    return sorted(p.rglob(pattern))


def load_json_list(file: Path):
    with file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        sys.exit(f"{file.name}: erwartet wurde eine JSON-Liste, gefunden: {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Katalog-Cache: legt Künstler, Alben, Titel ... an und merkt sich die IDs
# ---------------------------------------------------------------------------
class Catalog:
    """Legt Katalogzeilen an und merkt sich ihre IDs.

    Künstler, Alben und Sendungen können nach dem API-Abgleich eine Spotify-ID haben;
    gleichnamige Zeilen sind nur ohne ID eindeutig. Beim Import wird deshalb zuerst
    eine vorhandene Zeile gesucht (bevorzugt eine mit Spotify-ID) und nur sonst neu angelegt.
    """

    def __init__(self, cur):
        self.cur = cur
        q = cur.execute
        self.artists = {n: i for n, i in q(
            "SELECT DISTINCT ON (name) name, artist_id FROM artists "
            "ORDER BY name, (spotify_artist_id IS NULL), artist_id").fetchall()}
        self.albums = {(t, a): i for t, a, i in q(
            "SELECT DISTINCT ON (title, artist_id) title, artist_id, album_id FROM albums "
            "ORDER BY title, artist_id, (spotify_album_id IS NULL), album_id").fetchall()}
        self.tracks = {u: i for i, u in q("SELECT track_id, spotify_track_uri FROM tracks").fetchall()}
        self.shows = {n: i for n, i in q(
            "SELECT DISTINCT ON (name) name, show_id FROM shows "
            "ORDER BY name, (spotify_show_id IS NULL), show_id").fetchall()}
        self.episodes = {u: i for i, u in q("SELECT episode_id, spotify_episode_uri FROM episodes").fetchall()}
        self.chapters = {u: i for i, u in q("SELECT chapter_id, spotify_chapter_uri FROM audiobook_chapters").fetchall()}

    def _get_or_create(self, cache, key, select_sql, select_params, insert_sql, insert_params):
        if key in cache:
            return cache[key]
        row = self.cur.execute(select_sql, select_params).fetchone()
        if row is None:
            self.cur.execute(insert_sql + " ON CONFLICT DO NOTHING", insert_params)
            row = self.cur.execute(select_sql, select_params).fetchone()
        cache[key] = row[0]
        return cache[key]

    def artist(self, name):
        if name is None:
            return None
        return self._get_or_create(
            self.artists, name,
            "SELECT artist_id FROM artists WHERE name = %s ORDER BY (spotify_artist_id IS NULL), artist_id LIMIT 1",
            (name,),
            "INSERT INTO artists (name) VALUES (%s)", (name,))

    def album(self, title, artist_id):
        if title is None:
            return None
        return self._get_or_create(
            self.albums, (title, artist_id),
            "SELECT album_id FROM albums WHERE title = %s AND artist_id IS NOT DISTINCT FROM %s "
            "ORDER BY (spotify_album_id IS NULL), album_id LIMIT 1",
            (title, artist_id),
            "INSERT INTO albums (title, artist_id) VALUES (%s, %s)", (title, artist_id))

    def track(self, uri, title, artist_id, album_id):
        return self._get_or_create(
            self.tracks, uri,
            "SELECT track_id FROM tracks WHERE spotify_track_uri = %s", (uri,),
            "INSERT INTO tracks (spotify_track_uri, title, artist_id, album_id) VALUES (%s, %s, %s, %s)",
            (uri, title or uri, artist_id, album_id))

    def show(self, name):
        if name is None:
            return None
        return self._get_or_create(
            self.shows, name,
            "SELECT show_id FROM shows WHERE name = %s ORDER BY (spotify_show_id IS NULL), show_id LIMIT 1",
            (name,),
            "INSERT INTO shows (name) VALUES (%s)", (name,))

    def episode(self, uri, title, show_id):
        return self._get_or_create(
            self.episodes, uri,
            "SELECT episode_id FROM episodes WHERE spotify_episode_uri = %s", (uri,),
            "INSERT INTO episodes (spotify_episode_uri, title, show_id) VALUES (%s, %s, %s)",
            (uri, title or uri, show_id))

    def chapter(self, uri, title, audiobook_title, audiobook_uri):
        return self._get_or_create(
            self.chapters, uri,
            "SELECT chapter_id FROM audiobook_chapters WHERE spotify_chapter_uri = %s", (uri,),
            "INSERT INTO audiobook_chapters (spotify_chapter_uri, chapter_title, audiobook_title, spotify_audiobook_uri) "
            "VALUES (%s, %s, %s, %s)",
            (uri, title or uri, audiobook_title, audiobook_uri))


INSERT_PLAY = """
INSERT INTO plays (user_id, played_at, ms_played, content_type, track_id, episode_id, chapter_id,
                   platform, conn_country, reason_start, reason_end, shuffle, skipped, offline,
                   offline_timestamp, incognito_mode, batch_id)
VALUES (%s, %s, %s, %s::content_type, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
"""


# ---------------------------------------------------------------------------
# Unterkommando: streaming
# ---------------------------------------------------------------------------
def cmd_streaming(args):
    files = find_files(args.path, args.pattern)
    if not files:
        sys.exit(f"Keine Dateien gefunden (Muster: {args.pattern}) in {args.path}")

    if args.dry_run:
        return dry_run_streaming(files)

    import psycopg  # erst hier importieren, damit --dry-run ohne Treiber funktioniert

    dsn = os.environ.get("SPOTISTATS_DSN")
    if not dsn:
        sys.exit("Umgebungsvariable SPOTISTATS_DSN ist nicht gesetzt.")

    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        user_id = ensure_user(cur, args.user)
        plays_before = cur.execute("SELECT count(*) FROM plays WHERE user_id = %s", (user_id,)).fetchone()[0]
        batch_id = cur.execute(
            "INSERT INTO import_batches (user_id, source_package, source_files) VALUES (%s, %s, %s) RETURNING batch_id",
            (user_id, "extended_streaming_history", [f.name for f in files])).fetchone()[0]
        conn.commit()

        catalog = Catalog(cur)
        rows_read = 0
        invalid = Counter()

        for file in files:
            data = load_json_list(file)
            chunk = []
            for raw in data:
                rows_read += 1
                entry, reason = parse_row(raw)
                if entry is None:
                    invalid[reason] += 1
                    continue
                chunk.append(play_params(catalog, user_id, batch_id, entry))
                if len(chunk) >= CHUNK_SIZE:
                    cur.executemany(INSERT_PLAY, chunk)
                    chunk = []
            if chunk:
                cur.executemany(INSERT_PLAY, chunk)
            conn.commit()
            print(f"  {file.name}: {len(data)} Zeilen verarbeitet")

        plays_after = cur.execute("SELECT count(*) FROM plays WHERE user_id = %s", (user_id,)).fetchone()[0]
        inserted = plays_after - plays_before
        rows_invalid = sum(invalid.values())
        duplicates = rows_read - rows_invalid - inserted
        cur.execute(
            "UPDATE import_batches SET finished_at = now(), rows_read = %s, rows_inserted = %s, "
            "rows_duplicate = %s, rows_invalid = %s WHERE batch_id = %s",
            (rows_read, inserted, duplicates, rows_invalid, batch_id))
        conn.commit()

    print(f"\nFertig. Gelesen: {rows_read}, neu: {inserted}, Dubletten: {duplicates}, ungültig: {rows_invalid}")
    for reason, n in invalid.items():
        print(f"  ungültig ({reason}): {n}")


def play_params(catalog, user_id, batch_id, e):
    track_id = episode_id = chapter_id = None
    if e["content_type"] == "track":
        artist_id = catalog.artist(e["artist"])
        album_id = catalog.album(e["album"], artist_id)
        track_id = catalog.track(e["track_uri"], e["track_title"], artist_id, album_id)
    elif e["content_type"] == "episode":
        show_id = catalog.show(e["show"])
        episode_id = catalog.episode(e["episode_uri"], e["episode_title"], show_id)
    else:
        chapter_id = catalog.chapter(e["chapter_uri"], e["chapter_title"], e["audiobook_title"], e["audiobook_uri"])
    return (user_id, e["played_at"], e["ms_played"], e["content_type"], track_id, episode_id, chapter_id,
            e["platform"], e["conn_country"], e["reason_start"], e["reason_end"], e["shuffle"],
            e["skipped"], e["offline"], e["offline_timestamp"], e["incognito_mode"], batch_id)


def dry_run_streaming(files):
    """Nur parsen und zählen, ohne Datenbank."""
    total = 0
    types = Counter()
    invalid = Counter()
    tracks, artists = set(), set()
    first = last = None
    keys = set()
    duplicates_in_files = 0
    for file in files:
        data = load_json_list(file)
        print(f"  {file.name}: {len(data)} Zeilen")
        for raw in data:
            total += 1
            entry, reason = parse_row(raw)
            if entry is None:
                invalid[reason] += 1
                continue
            types[entry["content_type"]] += 1
            if entry["track_uri"]:
                tracks.add(entry["track_uri"])
            if entry["artist"]:
                artists.add(entry["artist"])
            ts = entry["played_at"]
            first = ts if first is None or ts < first else first
            last = ts if last is None or ts > last else last
            key = (ts, entry["track_uri"], entry["episode_uri"], entry["chapter_uri"])
            if key in keys:
                duplicates_in_files += 1
            keys.add(key)
    print(f"\nTrockenlauf (es wurde nichts in die Datenbank geschrieben)")
    print(f"  Zeilen gelesen:        {total}")
    print(f"  gültig:                {sum(types.values())}  {dict(types)}")
    print(f"  ungültig:              {sum(invalid.values())}  {dict(invalid)}")
    print(f"  Dubletten in Dateien:  {duplicates_in_files}")
    print(f"  verschiedene Titel:    {len(tracks)}")
    print(f"  verschiedene Künstler: {len(artists)}")
    if first:
        print(f"  Zeitraum (UTC):        {first:%Y-%m-%d} bis {last:%Y-%m-%d}")


def ensure_user(cur, display_name):
    cur.execute("INSERT INTO users (display_name) VALUES (%s) ON CONFLICT (display_name) DO NOTHING", (display_name,))
    return cur.execute("SELECT user_id FROM users WHERE display_name = %s", (display_name,)).fetchone()[0]


# ---------------------------------------------------------------------------
# Unterkommando: raw
# ---------------------------------------------------------------------------
def cmd_raw(args):
    base = Path(args.path).expanduser()
    if not base.is_dir():
        sys.exit(f"Ordner nicht gefunden: {base}")
    files = sorted(f for f in base.rglob("*.json")
                   if any(fnmatch.fnmatch(f.name, pat) for pat in args.include))
    if not files:
        sys.exit("Keine passenden JSON-Dateien gefunden.")

    if args.dry_run:
        for f in files:
            print(f"  würde importieren: {f.name} ({f.stat().st_size} Bytes)")
        return

    import psycopg
    from psycopg.types.json import Jsonb

    dsn = os.environ.get("SPOTISTATS_DSN")
    if not dsn:
        sys.exit("Umgebungsvariable SPOTISTATS_DSN ist nicht gesetzt.")

    new = skipped = 0
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        user_id = ensure_user(cur, args.user)
        for f in files:
            content = f.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            payload = json.loads(content.decode("utf-8"))
            cur.execute(
                "INSERT INTO raw_documents (user_id, source_package, file_name, sha256, payload) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (user_id, args.package, f.name, digest, Jsonb(payload)))
            if cur.rowcount == 1:
                new += 1
                print(f"  importiert: {f.name}")
            else:
                skipped += 1
                print(f"  schon vorhanden: {f.name}")
        conn.commit()
    print(f"\nFertig. Neu: {new}, übersprungen: {skipped}")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="SpotiStats – Import der Spotify-Exporte")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("streaming", help="Extended Streaming History importieren")
    s.add_argument("path", help="Ordner oder einzelne JSON-Datei")
    s.add_argument("--user", required=True, help="Anzeigename des Benutzers (wird angelegt, falls neu)")
    s.add_argument("--pattern", default="Streaming_History_Audio_*.json",
                   help="Dateimuster (Standard: nur Audio; für Video 'Streaming_History_*.json')")
    s.add_argument("--dry-run", action="store_true", help="nur prüfen, nichts schreiben")
    s.set_defaults(func=cmd_streaming)

    r = sub.add_parser("raw", help="JSON-Dateien unverändert als JSONB ablegen")
    r.add_argument("path", help="Ordner mit den JSON-Dateien")
    r.add_argument("--user", required=True)
    r.add_argument("--package", required=True, help="z. B. account_data oder technical_log")
    r.add_argument("--include", nargs="+", default=DEFAULT_RAW_INCLUDE,
                   help="Dateinamen-Muster, die importiert werden")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_raw)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
