#!/usr/bin/env bash
# Apply the pending SQL migrations in infra/postgres/migrations, in order, and record each one in
# ops.schema_migrations. Runs on every `docker compose up` (service db-migrate), so a new
# migration reaches an existing volume too. Safe to re-run.
#
# Rules for migration files:
#   - named NNN_description.sql, applied in NNN order, each in a single transaction;
#   - never edited once applied: the checksum is recorded and a changed file stops the run.
#     Fix a mistake with a new migration;
#   - one number per migration: a file whose number is recorded under another name stops the run.
# Two runs at the same time (make migrate during docker compose up) take turns on an advisory
# lock, so the second one finds everything applied instead of failing.
set -euo pipefail

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"
PSQL=(psql -X -q -v ON_ERROR_STOP=1)
export PGOPTIONS="-c client_min_messages=warning"

# The first start of a fresh volume runs the init scripts on a server that only listens on its
# Unix socket; wait until the database accepts TCP connections and the init scripts are done.
for attempt in $(seq 1 60); do
  if "${PSQL[@]}" -tAc "SELECT 1 FROM pg_namespace WHERE nspname = 'ops'" 2>/dev/null | grep -q 1; then
    break
  fi
  [[ $attempt -eq 60 ]] && { echo "database not ready after 120 s" >&2; exit 1; }
  sleep 2
done

# Hold a session-level advisory lock for the whole run. The locking session is a background psql
# that lives as long as this script: when the script exits, its input closes and the lock goes.
coproc LOCK_SESSION { "${PSQL[@]}" -tA; }
echo "SELECT pg_advisory_lock(hashtext('llobregat.migrate')); SELECT 'locked';" >&"${LOCK_SESSION[1]}"
locked=false
while read -r line <&"${LOCK_SESSION[0]}"; do
  [[ "$line" == locked ]] && { locked=true; break; }
done
$locked || { echo "could not take the migration lock" >&2; exit 1; }

# The ledger is created in its first shape here; later migrations evolve it (007 adds source and
# ingested_at), so the comment is only written when the table is created.
"${PSQL[@]}" <<'SQL'
DO $$
BEGIN
    IF to_regclass('ops.schema_migrations') IS NULL THEN
        CREATE TABLE ops.schema_migrations (
            version      integer PRIMARY KEY,
            name         text NOT NULL,
            checksum     text NOT NULL,
            applied_at   timestamptz NOT NULL DEFAULT now(),
            applied_by   text NOT NULL DEFAULT current_user,
            duration_ms  integer
        );
        COMMENT ON TABLE ops.schema_migrations IS '{"owner": "platform", "schema_version": 1}';
    END IF;
END
$$;
SQL

applied=0; skipped=0
shopt -s nullglob
for file in "$MIGRATIONS_DIR"/[0-9][0-9][0-9]_*.sql; do
  name=$(basename "$file" .sql)
  [[ "$name" =~ ^[0-9]{3}_[a-z0-9_]+$ ]] || { echo "bad migration name: $name" >&2; exit 1; }
  version=$((10#${name:0:3}))
  checksum=$(sha256sum "$file" | cut -d' ' -f1)
  recorded=$("${PSQL[@]}" -tA -F ' ' -c "SELECT name, checksum FROM ops.schema_migrations WHERE version = $version")

  if [[ -n "$recorded" ]]; then
    read -r recorded_name recorded_checksum <<<"$recorded"
    if [[ "$recorded_name" != "$name" ]]; then
      echo "migration number ${name:0:3} is recorded as $recorded_name, not $name; two files share a number" \
           "or an applied file was renamed" >&2
      exit 1
    fi
    if [[ "$recorded_checksum" != "$checksum" ]]; then
      echo "migration $name was changed after it was applied; add a new migration instead" >&2
      exit 1
    fi
    skipped=$((skipped + 1))
    continue
  fi

  echo "applying $name"
  "${PSQL[@]}" --single-transaction -o /dev/null -f "$file" -c "
    INSERT INTO ops.schema_migrations (version, name, checksum, duration_ms)
    VALUES ($version, '$name', '$checksum',
            (extract(epoch FROM clock_timestamp() - now()) * 1000)::integer)"
  applied=$((applied + 1))
done

echo "migrations: $applied applied, $skipped already in place"
"${PSQL[@]}" -c "SELECT version, name, applied_at FROM ops.schema_migrations ORDER BY version"
