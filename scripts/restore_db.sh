#!/usr/bin/env bash
# Restore a database backup into the docker compose database. DESTRUCTIVE.
#
# Usage (run from the directory that contains compose.yaml):
#   scripts/restore_db.sh <backup-file>
#
# Supported backups:
#   *.sql   plain SQL dump, e.g. from the bot's /backup command (db_backup_*.sql)
#   *.dump  custom-format dump, e.g. the pre-deploy backups (backup_before_deploy_*.dump)
#
# What it does:
#   1. asks you to type the database name to confirm;
#   2. stops the bot;
#   3. drops the `app` and `budget` schemas and the Alembic version table and loads the backup.
#      For *.sql this happens in a single transaction: if anything fails, nothing changes.
#      For *.dump the drop runs first, then pg_restore in one transaction.
#   4. starts the bot again. On startup it applies any migrations the backup is missing,
#      or stamps a pre-Alembic backup as the baseline.
#
# If any step fails, the script stops and leaves the bot stopped so you can inspect it.
set -euo pipefail

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

BACKUP_FILE="${1:-}"
if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
    usage
    echo "Error: backup file not found: '${BACKUP_FILE}'" >&2
    exit 1
fi
if [[ ! -f compose.yaml ]]; then
    echo "Error: run this from the directory that contains compose.yaml." >&2
    exit 1
fi

case "$BACKUP_FILE" in
    *.sql) FORMAT="sql" ;;
    *.dump) FORMAT="dump" ;;
    *) echo "Error: expected a .sql or .dump file." >&2; exit 1 ;;
esac

DROP_SQL='DROP SCHEMA IF EXISTS app CASCADE; DROP SCHEMA IF EXISTS budget CASCADE; DROP TABLE IF EXISTS public.alembic_version;'

# Runs psql inside the database container, as the database's own user.
db_psql() {
    docker compose exec -T pgdatabase sh -c \
        'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' psql "$@"
}

# `docker compose exec -T` reads stdin; give it /dev/null wherever it shouldn't consume input.
DB_NAME="$(docker compose exec -T pgdatabase sh -c 'printf %s "$POSTGRES_DB"' </dev/null)"

echo "This will DELETE all data in schemas 'app' and 'budget' of database '${DB_NAME}'"
echo "and replace it with: ${BACKUP_FILE}"
read -r -p "Type the database name to continue: " CONFIRM
if [[ "$CONFIRM" != "$DB_NAME" ]]; then
    echo "Aborted."
    exit 1
fi

echo "Stopping the bot..."
docker compose stop budget_bot </dev/null

echo "Restoring ${BACKUP_FILE}..."
if [[ "$FORMAT" == "sql" ]]; then
    # Ownership lines are dropped so the restore works under a different DB user;
    # objects end up owned by the database's own user.
    { echo "$DROP_SQL"; sed -E '/^ALTER .* OWNER TO /d' "$BACKUP_FILE"; } \
        | db_psql --single-transaction -f -
else
    db_psql -c "$DROP_SQL" </dev/null
    docker compose exec -T pgdatabase sh -c \
        'pg_restore --single-transaction --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        < "$BACKUP_FILE"
fi

echo "Starting the bot..."
docker compose start budget_bot </dev/null
echo "Done. Check the bot logs: docker compose logs -f budget_bot"
