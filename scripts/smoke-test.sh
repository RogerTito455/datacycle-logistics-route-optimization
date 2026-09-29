#!/usr/bin/env bash
# End-to-end smoke test of the running platform.
# Every check exercises what the service is for, not only that its port is open.
#
#   SKIP_OSRM=1        skip the routing checks (route and distance matrix)
#   SMOKE_ROUTE=...    lon,lat;lon,lat pair for the routing checks (default: hub to Sagrada Familia)
#   SMOKE_MAX_LAG=...  messages the stream consumer may have left to write (default 1000)
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
  [[ "$topics" == *"gps.pings"* && "$topics" == *"vehicle.telemetry"* && "$topics" == *"delivery.events"* ]] \
    || { echo "topics missing: $topics"; return 1; }
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
               WHERE proc_name = 'policy_compression' AND hypertable_schema = 'bronze') || ' compression policies'
    FROM ops.table_metadata WHERE schema_name = 'bronze'")
  echo "${#files[@]}/${#files[@]} applied (latest ${name:0:3}); $tables"
}

metadata() {  # the three mandatory metadata elements on every bronze and ops table (ADR 0001, decision 20)
  local r total bad names events
  # Views carry owner and schema_version; tables also carry source and ingested_at.
  r=$(psql_admin -c "
    WITH t AS (
      SELECT schema_name || '.' || table_name AS name, has_event_time,
             owner IS NULL OR schema_version IS NULL
             OR (kind = 'table' AND NOT (has_source AND has_ingested_at)) AS missing
      FROM ops.table_metadata WHERE schema_name IN ('bronze', 'ops'))
    SELECT count(*), count(*) FILTER (WHERE missing),
           coalesce(string_agg(name, ' ') FILTER (WHERE missing), ''),
           count(*) FILTER (WHERE has_event_time)
    FROM t") || return 1
  IFS='|' read -r total bad names events <<<"$r"
  [[ "$total" -gt 0 && "$bad" -eq 0 ]] || { echo "missing metadata on: ${names:-every table, none found}"; return 1; }
  echo "$total/$total in bronze and ops have source, ingested_at, owner, version; $events event_time"
}

bronze_raw() {  # bronze accepts every raw record and keeps it until it is archived
  local r checks retention
  r=$(psql_admin -c "
    SELECT (SELECT count(*) FROM pg_constraint WHERE contype = 'c' AND connamespace = 'bronze'::regnamespace),
           (SELECT count(*) FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_retention' AND hypertable_schema = 'bronze')") || return 1
  IFS='|' read -r checks retention <<<"$r"
  [[ "$checks" -eq 0 && "$retention" -eq 0 ]] \
    || { echo "bronze has $checks CHECK constraints and $retention retention policies; both must be 0"; return 1; }
  echo "no CHECK constraints and no retention policies in bronze"
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
  # Dead letters hold raw messages: the dashboards count them, they do not read the bytes.
  "${reader[@]}" -c "SELECT count(*), max(reason) FROM ops.dead_letters" >/dev/null || { echo "cannot count dead letters"; return 1; }
  ! "${reader[@]}" -c "SELECT payload FROM ops.dead_letters LIMIT 1" >/dev/null 2>&1 || { echo "can read dead letter payloads"; return 1; }
  local schemas; schemas=$(psql_admin -c "
    SELECT string_agg(n, ' ' ORDER BY n) FROM unnest(array['bronze', 'silver', 'gold', 'ops']) n
    WHERE has_schema_privilege('grafana_reader', n, 'USAGE')")
  [[ "$schemas" == "gold ops" ]] || { echo "grafana_reader can use schemas: $schemas"; return 1; }
  echo "grafana_reader reads gold and ops only; bronze, dead letter payloads and ops writes denied"
}

consumer() {  # the stream consumer is healthy, measures its lag and keeps up with the topics
  local health
  health=$($COMPOSE exec -T consumer python -c \
    "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health', timeout=4).read().decode())" 2>&1) \
    || { echo "health endpoint not ok: $(echo "$health" | tail -1)"; return 1; }
  local r topics lag age
  r=$(psql_admin -c "
    SELECT count(DISTINCT topic), coalesce(sum(lag), 0), coalesce(round(extract(epoch FROM now() - max(event_time))), -1)
    FROM (SELECT DISTINCT ON (topic, kafka_partition) topic, lag, event_time FROM ops.consumer_lag
          WHERE consumer_group = 'llobregat-consumer' ORDER BY topic, kafka_partition, event_time DESC) latest") || return 1
  IFS='|' read -r topics lag age <<<"$r"
  [[ "$topics" -eq 3 ]] || { echo "lag recorded for $topics of the 3 topics"; return 1; }
  [[ "$age" -ge 0 && "$age" -le 60 ]] || { echo "last lag measurement ${age} s ago"; return 1; }
  [[ "$lag" -le "${SMOKE_MAX_LAG:-1000}" ]] || { echo "lag of ${lag} messages"; return 1; }
  echo "healthy, lag ${lag} messages over 3 topics, measured ${age} s ago"
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

# The optimizer plans on OSRM's distance matrix, so check the table service too: a square matrix
# with zero on the diagonal, positive times elsewhere, and A→B consistent with the route above.
osrm_table() {
  local t r
  t=$(curl -fsS "http://localhost:5000/table/v1/driving/${ROUTE}?annotations=duration,distance") || return 1
  r=$(curl -fsS "http://localhost:5000/route/v1/driving/${ROUTE}?overview=false") || return 1
  python3 - "$t" "$r" <<'PY'
import json, sys
t, r = json.loads(sys.argv[1]), json.loads(sys.argv[2])
assert t["code"] == "Ok", t
n = len(t["sources"])
for name in ("durations", "distances"):
    m = t[name]
    assert len(m) == n and all(len(row) == n for row in m), f"{name} is not {n}x{n}"
    assert all(m[i][i] == 0 for i in range(n)), f"{name} diagonal is not zero"
    assert all(m[i][j] and m[i][j] > 0 for i in range(n) for j in range(n) if i != j), f"{name} has empty cells"
route_s = r["routes"][0]["duration"]
table_s = t["durations"][0][1]
assert abs(table_s - route_s) <= 0.1 * route_s, f"table {table_s:.0f} s vs route {route_s:.0f} s"
print(f"distance matrix {n}x{n}: A→B {table_s / 60:.0f} min, B→A {t['durations'][1][0] / 60:.0f} min")
PY
}

echo "Llobregat Express · smoke test"
check redpanda redpanda
check redpanda-console console
check timescaledb timescaledb
check migrations migrations
check metadata metadata
check bronze-raw bronze_raw
check db-access db_access
check consumer consumer
check rustfs rustfs
check grafana grafana
check dagster dagster
if [[ "${SKIP_OSRM:-0}" == "1" ]]; then
  echo "  SKIP  osrm, osrm-table"
else
  check osrm osrm
  check osrm-table osrm_table
fi

echo ""
echo "  $pass passed, $fail failed"
[[ $fail -eq 0 ]]
