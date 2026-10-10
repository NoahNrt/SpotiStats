#!/usr/bin/env python3
"""
Offline-Test für collector.py ohne Spotify und ohne Datenbank.

Prüft mit einer Spotify-Attrappe (Antworten im Format der Web-API nach den
Änderungen von 2026) und einer Datenbank-Attrappe, dass
  * jede SQL-Anweisung genau so viele Parameter bekommt, wie sie Platzhalter hat,
  * alle Jobs ohne Ausnahme durchlaufen,
  * die Hilfsfunktionen Datum und Zeit richtig lesen.
Es prüft NICHT, ob das SQL von PostgreSQL akzeptiert wird.

Aufruf:  python test_collector.py
"""
import collections
import re
from contextlib import contextmanager
from datetime import date, datetime, timezone

import collector
from collector import (Api, Ctx, Store, job_enrich, job_library, job_playlists, job_profile, job_recent,
                       job_top, parse_iso, parse_release_date)


# ---------------------------------------------------------------------------
# Attrappen
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, log):
        self.log = log
        self.rowcount = 1
        self._rows = []
        self._seen = collections.Counter()

    def execute(self, sql, params=None):
        params = tuple(params or ())
        placeholders = len(re.findall(r"%s", sql))
        assert placeholders == len(params), f"Platzhalter {placeholders} != Parameter {len(params)}:\n{sql}\n{params}"
        assert "%" not in re.sub(r"%s", "", sql), f"Unmaskiertes % im SQL:\n{sql}"
        self.log.append(sql.split()[0].upper())
        self._seen[sql] += 1
        first = self._seen[sql] == 1
        head = sql.lstrip().upper()
        if "FROM ARTISTS A " in head and "GENRES_SYNCED_AT IS NULL" in head:
            self._rows = [(2, "artistid1"), (3, "artistid2")]
        elif "FROM TRACKS T " in head and "ENRICHED_AT IS NULL" in head:
            self._rows = [(1, "spotify:track:t1"), (5, "spotify:track:gone")]
        elif head.startswith("SELECT TRACK_ID, ARTIST_ID, ALBUM_ID"):
            self._rows = [] if first else [(11, 12, 13)]
        elif head.startswith("SELECT SPOTIFY_USER_ID"):
            self._rows = [(None,)]
        elif head.startswith("SELECT COUNT"):
            self._rows = [(42,)]
        elif head.startswith("SELECT") and first:
            self._rows = []            # beim ersten Mal "nicht gefunden" -> Anlegen-Pfad
        elif "RETURNING PLAYLIST_ID" in head:
            self._rows = [(9, None, None)]
        elif "RETURNING" in head or head.startswith("SELECT"):
            self._rows = [(11,)]
        else:
            self._rows = []
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self):
        self.log = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    @contextmanager
    def transaction(self):
        yield


def track(n, artist="a1", with_album=True):
    obj = {"id": f"t{n}", "uri": f"spotify:track:t{n}", "name": f"Titel {n}", "duration_ms": 200000 + n,
           "type": "track", "artists": [{"id": artist, "name": "Künstler"}, {"id": "a2", "name": "Gast"}]}
    if with_album:
        obj["album"] = {"id": "al1", "name": "Album", "release_date": "2020-05"}
    return obj


class FakeSp:
    def current_user(self):
        return {"id": "me123", "display_name": "Noah"}

    def current_user_recently_played(self, limit=50):
        return {"items": [
            {"played_at": "2026-10-07T10:00:00.123Z", "track": track(1), "context": {"type": "playlist", "uri": "spotify:playlist:p"}},
            {"played_at": "2026-10-07T10:05:00.000Z", "track": track(2), "context": None},
            {"played_at": "2026-10-07T10:09:00.000Z", "track": {"id": None, "uri": "spotify:local:x", "is_local": True}},
        ]}

    def current_user_top_tracks(self, limit=50, offset=0, time_range="short_term"):
        return {"items": [track(1), track(2)]}

    def current_user_top_artists(self, limit=50, offset=0, time_range="short_term"):
        return {"items": [{"id": "a1", "name": "Künstler", "genres": ["hip hop", "rap"]},
                          {"id": "a3", "name": "Anderer", "genres": []}]}

    def current_user_saved_tracks(self, limit=50, offset=0):
        return {"items": [{"added_at": "2024-01-02T03:04:05Z", "track": track(3)}], "next": None}

    def current_user_saved_albums(self, limit=50, offset=0):
        return {"items": [{"added_at": "2024-02-02T03:04:05Z",
                           "album": {"id": "al9", "name": "Gespeichert", "release_date": "2019",
                                     "artists": [{"id": "a1", "name": "Künstler"}]}}], "next": None}

    def current_user_saved_shows(self, limit=50, offset=0):
        return {"items": [{"added_at": "2024-03-02T03:04:05Z", "show": {"id": "s1", "name": "Ein Podcast"}}], "next": None}

    def current_user_followed_artists(self, limit=50, after=None):
        return {"artists": {"items": [{"id": "a1", "name": "Künstler", "genres": ["rap"]}], "cursors": {"after": None}}}

    def current_user_playlists(self, limit=50, offset=0):
        return {"items": [
            {"id": "p1", "name": "Meine", "description": "x", "owner": {"id": "me123", "display_name": "Noah"},
             "public": False, "collaborative": False, "snapshot_id": "snap1", "items": {"total": 2}},
            {"id": "p2", "name": "Fremde", "owner": {"id": "other"}, "collaborative": False,
             "snapshot_id": "snap2", "tracks": {"total": 5}},
        ], "next": None}

    def _get(self, path, **kwargs):
        if path == "me/episodes":
            return {"items": [{"added_at": "2024-04-02T03:04:05Z",
                               "episode": {"id": "e1", "uri": "spotify:episode:e1", "name": "Folge",
                                           "show": {"id": "s1", "name": "Ein Podcast"}}}], "next": None}
        if path == "me/audiobooks":
            return {"items": [{"id": "b1", "name": "Hörbuch"}], "next": None}
        if path == "playlists/p1/items":
            return {"items": [
                {"added_at": "2025-01-01T00:00:00Z", "added_by": {"id": "me123"}, "item": track(4)},
                {"added_at": "2025-01-02T00:00:00Z", "added_by": {"id": "me123"},
                 "item": {"type": "episode", "id": "e1", "uri": "spotify:episode:e1", "name": "Folge",
                          "show": {"id": "s1", "name": "Ein Podcast"}}},
                {"is_local": True, "item": {"type": "track", "uri": "spotify:local:x", "id": None}},
                {"item": None},
            ], "next": None}
        raise AssertionError(f"unerwarteter Pfad {path}")

    def track(self, uri):
        return track(1) if uri.endswith("t1") else None

    def artist(self, sid):
        return {"id": sid, "name": "Künstler", "genres": ["pop"]}


def make_ctx():
    conn = FakeConn()
    api = Api(FakeSp(), delay=0)
    ctx = Ctx(conn=conn, api=api, user_id=1, spotify_user_id="me123", enrich_limit=10)
    ctx.store = Store(conn.cursor())
    return ctx, conn


# ---------------------------------------------------------------------------
def test_helpers():
    assert parse_iso("2026-10-07T10:00:00.123Z") == datetime(2026, 10, 7, 10, 0, 0, 123000, tzinfo=timezone.utc)
    assert parse_iso(None) is None and parse_iso("kaputt") is None
    assert parse_release_date("2020") == date(2020, 1, 1)
    assert parse_release_date("2020-05") == date(2020, 5, 1)
    assert parse_release_date("2020-05-17") == date(2020, 5, 17)
    assert parse_release_date("") is None and parse_release_date("x") is None


def test_jobs():
    results = {}
    for name, job in (("profile", job_profile), ("recent", job_recent), ("top", job_top),
                      ("library", job_library), ("playlists", job_playlists), ("enrich", job_enrich)):
        ctx, conn = make_ctx()
        fetched, written, message = job(ctx)
        results[name] = (fetched, written, message, len(conn.log))
        assert isinstance(fetched, int) and isinstance(written, int), name
    assert results["recent"][0] == 3, results["recent"]          # 3 Einträge gelesen
    assert results["playlists"][2].startswith("1 Playlists ohne Zugriff"), results["playlists"]
    for name, value in results.items():
        print(f"  {name:10} gelesen={value[0]} geschrieben={value[1]} SQL-Anweisungen={value[3]} {value[2]}")


def test_rate_limit_and_404():
    class Boom:
        def __init__(self, status, headers=None):
            self.calls = 0
            self.status = status
            self.headers = headers or {}

        def thing(self):
            self.calls += 1
            raise collector.SpotifyException(self.status, -1, "x", headers=self.headers)

    api = Api(Boom(404), delay=0)
    assert api.call("thing") is None                            # 404 -> None
    long_wait = Api(Boom(429, {"Retry-After": "9999"}), delay=0)
    try:
        long_wait.call("thing")
        raise AssertionError("RateLimited erwartet")
    except collector.RateLimited:
        pass


if __name__ == "__main__":
    test_helpers()
    print("Hilfsfunktionen: OK")
    test_rate_limit_and_404()
    print("404 und Rate-Limit: OK")
    print("Jobs:")
    test_jobs()
    print("Alle Tests bestanden (SQL-Syntax gegen PostgreSQL wurde nicht geprüft).")
