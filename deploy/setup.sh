#!/usr/bin/env bash
# Einrichtung des SpotiStats-Stacks: .env mit Zufallspasswörtern, Ordner, Rechte.
# Startet nichts. Mehrfaches Ausführen ist gefahrlos (vorhandene .env bleibt unverändert).
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v podman >/dev/null 2>&1; then
  echo "WARNUNG: podman wurde nicht gefunden." >&2
fi
if ! podman compose version >/dev/null 2>&1 && ! command -v podman-compose >/dev/null 2>&1; then
  echo "WARNUNG: weder 'podman compose' noch 'podman-compose' gefunden." >&2
fi

random_password() { head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

if [ -f .env ]; then
  echo ".env existiert bereits und bleibt unverändert."
else
  cp .env.example .env
  for key in SPOTISTATS_DB_PASSWORD GRAFANA_DB_PASSWORD GRAFANA_ADMIN_PASSWORD; do
    sed -i "s|^${key}=.*|${key}=$(random_password)|" .env
  done
  chmod 600 .env
  echo ".env mit zufälligen Passwörtern erstellt."
fi

mkdir -p collector-data import backups
chmod +x setup.sh backup.sh initdb/04_grafana_user.sh

cat <<'MSG'

Noch von Hand in .env eintragen:
  SPOTIPY_CLIENT_ID und SPOTIPY_CLIENT_SECRET   (aus dem Spotify Developer Dashboard)
  GRAFANA_BIND                                  (optional: LAN-IP der shitbox für Zugriff im Heimnetz)

Danach:
  podman compose build
  podman compose up -d db grafana
Das Grafana-Admin-Passwort steht in .env (GRAFANA_ADMIN_PASSWORD), der Benutzer heißt admin.
MSG
