#!/usr/bin/env bash
# End-to-end smoke test of the running platform.
# Every check exercises what the service is for, not only that its port is open.
#
#   SKIP_OSRM=1        skip the routing check
#   SMOKE_ROUTE=...    lon,lat;lon,lat pair for the routing check (default: hub to Sagrada Familia)
set -uo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

COMPOSE="docker compose"
ROUTE="${SMOKE_ROUTE:-2.1370,41.3405;2.1744,41.4036}"
pass=0; fail=0

check() {  # check <name> <command...>
  local name="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    printf '  \033[32mPASS\033[0m  %-18s %s\n' "$name" "$(echo "$out" | tail -1 | cut -c1-90)"
    pass=$((pass + 1))
  else
    printf '  \033[31mFAIL\033[0m  %-18s %s\n' "$name" "$(echo "$out" | tail -1 | cut -c1-90)"
    fail=$((fail + 1))
  fi
}

redpanda() {
  $COMPOSE exec -T redpanda rpk cluster health | grep -Eq 'Healthy:.+true' || { echo "cluster not healthy"; return 1; }
  local topics; topics=$($COMPOSE exec -T redpanda rpk topic list | awk 'NR>1 {print $1}' | sort | tr '\n' ' ')
  [[ "$topics" == *"gps.pings"* && "$topics" == *"vehicle.telemetry"* ]] || { echo "topics missing: $topics"; return 1; }
  # Round trip through a throwaway topic, so no probe message ever lands in a real topic.
  local probe="smoke-$(date +%s)"
  $COMPOSE exec -T redpanda rpk topic create _smoke >/dev/null 2>&1 || true
  echo "$probe" | $COMPOSE exec -T redpanda rpk topic produce _smoke >/dev/null
  local got; got=$($COMPOSE exec -T redpanda rpk topic consume _smoke -o -1 -n 1 -f '%v')
  $COMPOSE exec -T redpanda rpk topic delete _smoke >/dev/null 2>&1 || true
  [[ "$got" == *"$probe"* ]] || { echo "round trip failed"; return 1; }
  echo "healthy, topics: $topics, produce/consume round trip ok"
}

console() { curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8080/; }

timescaledb() {
  local q="SELECT (SELECT extversion FROM pg_extension WHERE extname='timescaledb')
             || ' · schemas ' || (SELECT count(*) FROM pg_namespace WHERE nspname IN ('bronze','silver','gold','ops'))
             || '/4 · dagster db ' || (SELECT count(*) FROM pg_database WHERE datname='dagster')"
  local r; r=$($COMPOSE exec -T timescaledb psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$q")
  [[ "$r" == *"schemas 4/4"*"dagster db 1" ]] || { echo "unexpected: $r"; return 1; }
  echo "TimescaleDB $r"
}

psql_admin() { $COMPOSE exec -T timescaledb psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA "$@"; }
sha256() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$1" | cut -d' ' -f1; }

migrations() {  # every migration file is recorded in ops.schema_migrations with the same checksum
  local rows; rows=$(psql_admin -F ' ' -c "SELECT name, checksum FROM ops.schema_migrations") \
    || { echo "ops.schema_migrations missing: db-migrate has not run"; return 1; }
  local files=(infra/postgres/migrations/[0-9][0-9][0-9]_*.sql) missing=() f name
  for f in "${files[@]}"; do
    name=$(basename "$f" .sql)
    grep -qx "$name $(sha256 "$f")" <<<"$rows" || missing+=("$name")
  done
  [[ ${#missing[@]} -eq 0 ]] || { echo "not applied or changed: ${missing[*]}"; return 1; }
  local tables; tables=$(psql_admin -c "
    SELECT count(*) || ' bronze tables, ' || count(*) FILTER (WHERE is_hypertable) || ' hypertables, '
           || (SELECT count(*) FROM timescaledb_information.jobs
               WHERE proc_name = 'policy_retention' AND hypertable_schema = 'bronze') || ' retention policies'
    FROM ops.table_metadata WHERE schema_name = 'bronze'")
  echo "${#files[@]}/${#files[@]} applied (latest ${name:0:3}); $tables"
}

metadata() {  # the three mandatory metadata elements on every bronze table (ADR 0001, decision 20)
  local r total bad names events
  r=$(psql_admin -c "
    SELECT count(*),
           count(*) FILTER (WHERE owner IS NULL OR schema_version IS NULL OR NOT has_source OR NOT has_ingested_at),
           coalesce(string_agg(table_name, ' ') FILTER (WHERE owner IS NULL OR schema_version IS NULL
                                                         OR NOT has_source OR NOT has_ingested_at), ''),
           count(*) FILTER (WHERE has_event_time)
    FROM ops.table_metadata WHERE schema_name = 'bronze'") || return 1
  IFS='|' read -r total bad names events <<<"$r"
  [[ "$total" -gt 0 && "$bad" -eq 0 ]] || { echo "missing metadata on: ${names:-every table, none found}"; return 1; }
  echo "$total/$total with source, ingested_at, owner, schema_version; $events event tables with event_time"
}

db_access() {  # grafana_reader, the dashboards' role, reads gold and ops and nothing else
  local reader=($COMPOSE exec -T -e PGPASSWORD="$GRAFANA_DB_PASSWORD" timescaledb
                psql -X -h 127.0.0.1 -U grafana_reader -d "$POSTGRES_DB" -tA)
  "${reader[@]}" -c "SELECT count(*) FROM ops.table_metadata" >/dev/null || { echo "cannot read ops"; return 1; }
  local t
  for t in bronze.orders bronze.gps_pings; do
    ! "${reader[@]}" -c "SELECT 1 FROM $t LIMIT 1" >/dev/null 2>&1 || { echo "can read $t"; return 1; }
  done
  ! "${reader[@]}" -c "DELETE FROM ops.data_sources WHERE false" >/dev/null 2>&1 || { echo "can write to ops"; return 1; }
  local schemas; schemas=$(psql_admin -c "
    SELECT string_agg(n, ' ' ORDER BY n) FROM unnest(array['bronze', 'silver', 'gold', 'ops']) n
    WHERE has_schema_privilege('grafana_reader', n, 'USAGE')")
  [[ "$schemas" == "gold ops" ]] || { echo "grafana_reader can use schemas: $schemas"; return 1; }
  echo "grafana_reader reads gold and ops only; bronze reads and ops writes denied"
}

rustfs() {
  curl -fsS -o /dev/null http://localhost:9000/health || { echo "health endpoint down"; return 1; }
  local buckets; buckets=$($COMPOSE run --rm --no-deps -T --entrypoint aws storage-init \
    --endpoint-url http://rustfs:9000 s3 ls | awk '{print $3}' | sort | tr '\n' ' ')
  [[ "$buckets" == *"archive"* && "$buckets" == *"bronze"* ]] || { echo "buckets missing: $buckets"; return 1; }
  echo "buckets: $buckets"
}

grafana() {
  curl -fsS http://localhost:3000/api/health | grep -q '"database": *"ok"' || { echo "api/health not ok"; return 1; }
  local ds; ds=$(curl -fsS -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" http://localhost:3000/api/datasources/uid/timescaledb/health)
  echo "$ds" | grep -q '"status": *"OK"' || { echo "datasource: $ds"; return 1; }
  curl -fsS -o /dev/null http://localhost:3000/api/dashboards/uid/platform-health || { echo "dashboard missing"; return 1; }
  echo "datasource OK, dashboard provisioned, anonymous viewer access on"
}

dagster() {
  curl -fsS -o /dev/null http://localhost:3001/server_info || { echo "webserver down"; return 1; }
  local q='{"query":"{ workspaceOrError { ... on Workspace { locationEntries { name locationOrLoadError { __typename } } } } }"}'
  local r; r=$(curl -fsS -H 'Content-Type: application/json' -d "$q" http://localhost:3001/graphql)
  echo "$r" | grep -q '"name":"llobregat","locationOrLoadError":{"__typename":"RepositoryLocation"}' \
    || { echo "code location not loaded: $r"; return 1; }
  echo "webserver up, code location 'llobregat' loaded"
}

osrm() {
  local r; r=$(curl -fsS "http://localhost:5000/route/v1/driving/${ROUTE}?overview=false") || return 1
  python3 - "$r" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
assert r["code"] == "Ok", r
route = r["routes"][0]
print(f"real road route: {route['distance'] / 1000:.1f} km, {route['duration'] / 60:.0f} min")
PY
}

echo "Llobregat Express · smoke test"
check redpanda redpanda
check redpanda-console console
check timescaledb timescaledb
check migrations migrations
check metadata metadata
check db-access db_access
check rustfs rustfs
check grafana grafana
check dagster dagster
if [[ "${SKIP_OSRM:-0}" == "1" ]]; then echo "  SKIP  osrm"; else check osrm osrm; fi

echo ""
echo "  $pass passed, $fail failed"
[[ $fail -eq 0 ]]
