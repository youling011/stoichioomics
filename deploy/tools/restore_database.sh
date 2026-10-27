#!/bin/sh
set -eu
if [ "${STOICH_RESTORE_EMPTY_DATABASE:-}" != "1" ]; then
    echo 'Set STOICH_RESTORE_EMPTY_DATABASE=1 explicitly for a NEW EMPTY database.' >&2
    exit 2
fi
archive=${1:?Pass the verified /releases/path-to-custom-format-dump}
case "$archive" in /releases/*) ;; *) echo 'Archive must be under the read-only /releases mount.' >&2; exit 2;; esac
if [ ! -f "$archive" ]; then echo 'Verified database archive is missing.' >&2; exit 2; fi
export PGUSER="$POSTGRES_USER" PGDATABASE="$POSTGRES_DB" PGPASSWORD="$POSTGRES_PASSWORD"
count=$(psql -X -A -t -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f');")
if [ "$count" != "0" ]; then echo 'Restore refused: target database already contains user objects.' >&2; exit 2; fi
exec pg_restore --exit-on-error --single-transaction --no-owner --no-privileges --dbname "$PGDATABASE" "$archive"
