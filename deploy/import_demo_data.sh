#!/usr/bin/env bash
# Replace the server's demo data (portfolio, trades, alerts, chats, reviews, research notes)
# with a dump made on your PC by deploy/export_demo_data.ps1.
#
#   cd ~/finance_agent && bash deploy/import_demo_data.sh [finsight_demo.dump]
#
# Safe to re-run. Before touching anything it saves the server's current data to
# backups/server_<timestamp>.dump, so you can roll back with:
#   bash deploy/import_demo_data.sh backups/server_<timestamp>.dump
set -Eeuo pipefail   # -E: the ERR trap also fires inside functions (needed for auto-rollback)

DUMP="${1:-finsight_demo.dump}"
COMPOSE="${COMPOSE:-docker compose -f docker-compose.prod.yml}"
DB_USER="${DB_USER:-finsight}"
DB_NAME="${DB_NAME:-finsight}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mapfile -t TABLES < <(grep -vE '^\s*(#|$)' "$HERE/demo_tables.txt")
TABLE_LIST="$(IFS=,; echo "${TABLES[*]}")"

say()  { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
psql_db() { $COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" "$@"; }

[ -f "$DUMP" ] || fail "Dump file '$DUMP' not found. Upload it first (export_demo_data.ps1 -Upload does this)."

say "Checking the database"
$COMPOSE exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null || fail "Database container is not ready. Run: $COMPOSE up -d"
for t in "${TABLES[@]}"; do
  exists=$(psql_db -tAc "SELECT to_regclass('public.$t') IS NOT NULL")
  [ "$exists" = "t" ] || fail "Table '$t' does not exist yet. Start the backend once so it creates the tables ($COMPOSE up -d), then re-run."
done

mkdir -p backups
BACKUP="backups/server_$(date +%Y%m%d_%H%M%S).dump"
say "Backing up current server data to $BACKUP"
dump_args=(); for t in "${TABLES[@]}"; do dump_args+=(-t "$t"); done
$COMPOSE exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --data-only --format=custom "${dump_args[@]}" > "$BACKUP"

say "Stopping app containers while data is swapped"
$COMPOSE stop backend celery_worker celery_beat >/dev/null
restart() { say "Starting app containers"; $COMPOSE start backend celery_worker celery_beat >/dev/null; }

# Move every id counter past the existing rows so new chats/notes don't collide.
RESEED_SQL=$(cat <<'SQL'
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.relname AS tbl, a.attname AS col, pg_get_serial_sequence(c.relname, a.attname) AS seq
           FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
           WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace
             AND a.attnum > 0 AND NOT a.attisdropped
             AND pg_get_serial_sequence(c.relname, a.attname) IS NOT NULL
  LOOP
    EXECUTE format('SELECT setval(%L, COALESCE((SELECT max(%I) FROM %I), 0) + 1, false)', r.seq, r.col, r.tbl);
  END LOOP;
END $$;
SQL
)

# load_dump FILE: empty the demo tables and load FILE into them
load_dump() {
  psql_db -c "TRUNCATE $TABLE_LIST RESTART IDENTITY CASCADE;" >/dev/null
  $COMPOSE cp "$1" db:/tmp/finsight_import.dump
  $COMPOSE exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --data-only --no-owner --disable-triggers --exit-on-error /tmp/finsight_import.dump
  $COMPOSE exec -T db rm -f /tmp/finsight_import.dump
  # move every id counter past the loaded rows so new chats/notes don't collide
  psql_db -c "$RESEED_SQL" >/dev/null
}

on_error() {
  trap - ERR
  echo "" >&2; echo "Import failed - putting the previous server data back from $BACKUP" >&2
  if load_dump "$BACKUP"; then echo "Previous data restored." >&2
  else echo "Automatic rollback ALSO failed. Restore manually: bash deploy/import_demo_data.sh $BACKUP" >&2; fi
  restart
  exit 1
}
trap on_error ERR

say "Replacing data"
load_dump "$DUMP"


trap - ERR
restart

say "Imported rows"
for t in "${TABLES[@]}"; do printf '  %-18s %s\n' "$t" "$(psql_db -tAc "SELECT count(*) FROM $t")"; done
echo
echo "Done. Refresh the site. Previous server data: $BACKUP"
