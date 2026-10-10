#!/usr/bin/env bash
# SpotiStats – Datenbank-Backup (pg_dump im Container, Format "custom")
# Aufruf:  ./backup.sh [Zielordner]      Standard: ./backups
# Wiederherstellen:
#   podman exec -i spotistats-db pg_restore -U spotistats -d spotistats --clean --if-exists < backups/DATEI.dump
set -euo pipefail

OUT_DIR="${1:-./backups}"
KEEP_DAYS=14
STAMP="$(date +%Y-%m-%d_%H%M)"

mkdir -p "$OUT_DIR"
podman exec spotistats-db pg_dump -U spotistats -d spotistats --format=custom > "$OUT_DIR/spotistats_${STAMP}.dump"
find "$OUT_DIR" -name 'spotistats_*.dump' -mtime +"$KEEP_DAYS" -delete
echo "Backup erstellt: $OUT_DIR/spotistats_${STAMP}.dump"
