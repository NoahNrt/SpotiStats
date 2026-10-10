# SpotiStats – Stack für das Homelab

Datenbank (PostgreSQL 16), Collector (Spotify-API → Datenbank) und Grafana, gestartet mit Podman (rootless).

| Pfad | Inhalt |
|---|---|
| `docker-compose.yml` | Dienste `db`, `grafana`, `collector` und das Einmal-Werkzeug `importer` |
| `Dockerfile`, `requirements.txt` | Image für Collector und Importer |
| `app/` | `collector.py`, `import_spotify.py`, `test_collector.py` |
| `initdb/` | Schema, API-Tabellen, Views, Grafana-Benutzer (laufen beim ersten Start der Datenbank) |
| `grafana/` | Datenquelle, Dashboard-Provisioning und das Start-Dashboard |
| `setup.sh` | erzeugt `.env` mit Zufallspasswörtern und die lokalen Ordner |
| `backup.sh` | Datenbank-Sicherung nach `backups/` |

Nicht im Repo (durch `.gitignore`): `.env`, `collector-data/` (Spotify-Token), `import/` (Exportdaten), `backups/`.

## Befehle

```bash
bash setup.sh                       # einmalig
podman compose build
podman compose up -d db grafana
podman compose run --rm importer streaming /import/streaming --user noah --dry-run
podman compose run --rm importer streaming /import/streaming --user noah
podman compose run --rm importer raw /import/account --user noah --package account_data
podman compose up -d collector
podman exec spotistats-collector python collector.py status
bash backup.sh
```

Spotify-Anmeldung (einmalig, auf einem Rechner mit Browser): siehe Kommentar am Anfang von `app/collector.py`
(`python collector.py auth`), danach die Token-Datei nach `collector-data/.spotify_token` kopieren.

Die Passwörter in `.env` gelten nur beim ersten Start der Datenbank. Spätere Änderungen wirken nicht auf bestehende Datenbankrollen.
