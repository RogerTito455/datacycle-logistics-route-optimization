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
check rustfs rustfs
check grafana grafana
check dagster dagster
if [[ "${SKIP_OSRM:-0}" == "1" ]]; then echo "  SKIP  osrm"; else check osrm osrm; fi

echo ""
echo "  $pass passed, $fail failed"
[[ $fail -eq 0 ]]
