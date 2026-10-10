#!/bin/bash
# Legt den Nur-Lese-Benutzer grafana_ro an, wenn GRAFANA_DB_PASSWORD gesetzt ist.
# Läuft nur beim allerersten Start (leeres Datenbank-Volume). Bewusst ohne "exit" und
# "set -e": Das Init-Skript wird vom Entrypoint teilweise "gesourct".
if [ -n "${GRAFANA_DB_PASSWORD:-}" ]; then
  psql -v ON_ERROR_STOP=1 -v pw="$GRAFANA_DB_PASSWORD" \
       --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
CREATE ROLE grafana_ro LOGIN PASSWORD :'pw';
GRANT CONNECT ON DATABASE spotistats TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
REVOKE ALL ON raw_documents FROM grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
EOSQL
else
  echo "04_grafana_user.sh: GRAFANA_DB_PASSWORD nicht gesetzt - Benutzer grafana_ro wird nicht angelegt."
fi
