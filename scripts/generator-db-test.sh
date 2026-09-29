#!/usr/bin/env bash
# Integration test of the generator against the running stack: load the reference data, load it
# again, generate one service date, generate it again, and check the bronze tables with SQL.
#
#   ./scripts/generator-db-test.sh [--sample] [DATE]    DATE defaults to 2026-09-28, a past Monday
#
# The generator needs the platform (make up) and downloads about 70 MB of open data the first time.
# --sample loads the 560 committed test addresses instead, offline, from a download cache built by
# services/generator/scripts/sample_cache.py; CI uses it on a fresh stack.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

if [[ "${1:-}" == "--sample" ]]; then
  shift
  GENERATOR_CACHE_DIR=$(mktemp -d)
  export GENERATOR_CACHE_DIR
  trap 'rm -rf "$GENERATOR_CACHE_DIR"' EXIT
  uv run --project services/generator --frozen python services/generator/scripts/sample_cache.py "$GENERATOR_CACHE_DIR"
fi
DATE="${1:-2026-09-28}"
KEY="orders/date=${DATE}/orders.parquet"
psql_admin() { docker compose exec -T timescaledb psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA "$@"; }

# Rows and newest ingested_at of every reference table: a second load must leave both unchanged.
reference_state() {
  psql_admin -c "
    SELECT string_agg(t || ' ' || n || ' ' || coalesce(latest::text, '-'), E'\n' ORDER BY t) FROM (
      SELECT 'hubs' t, count(*) n, max(ingested_at) latest FROM bronze.hubs
      UNION ALL SELECT 'zones', count(*), max(ingested_at) FROM bronze.zones
      UNION ALL SELECT 'shifts', count(*), max(ingested_at) FROM bronze.shifts
      UNION ALL SELECT 'vehicle_types', count(*), max(ingested_at) FROM bronze.vehicle_types
      UNION ALL SELECT 'vehicles', count(*), max(ingested_at) FROM bronze.vehicles
      UNION ALL SELECT 'drivers', count(*), max(ingested_at) FROM bronze.drivers
      UNION ALL SELECT 'shippers', count(*), max(ingested_at) FROM bronze.shippers
      UNION ALL SELECT 'streets', count(*), max(ingested_at) FROM bronze.streets
      UNION ALL SELECT 'addresses', count(*), max(ingested_at) FROM bronze.addresses
      UNION ALL SELECT 'icgc_addresses', count(*), max(ingested_at) FROM bronze.icgc_addresses) s"
}
# Rows of the date and a digest of their order ids: a second run must give the same orders.
day_state() {
  psql_admin -c "SELECT count(*) || ' ' || coalesce(md5(string_agg(order_id, ',' ORDER BY order_id)), '-')
                 FROM bronze.orders WHERE service_date = '${DATE}' AND source = 'generator/orders'"
}

echo "== load-reference, twice"
make --no-print-directory load-reference
first=$(reference_state)
second=$(make --no-print-directory load-reference)
echo "$second"
! grep -q "(written)" <<<"$second" || { echo "FAIL: the second load wrote a file"; exit 1; }
[[ "$(reference_state)" == "$first" ]] || { echo "FAIL: the second load changed a reference table"; exit 1; }

echo "== generate ${DATE}, twice"
make --no-print-directory generate DATE="$DATE"
once=$(day_state)
make --no-print-directory generate DATE="$DATE"
twice=$(day_state)
[[ "$once" == "$twice" ]] || { echo "FAIL: the second run of ${DATE} gave '${twice}', the first '${once}'"; exit 1; }

echo "== checks"
failed=$(psql_admin -c "
  WITH day AS (SELECT * FROM bronze.orders WHERE service_date = '${DATE}' AND source = 'generator/orders'),
  checks(name, ok) AS (VALUES
    ('1 hub, 14 zones, 2 shifts, 6 vehicle types',
     (SELECT count(*) FROM bronze.hubs) = 1 AND (SELECT count(*) FROM bronze.zones) = 14
     AND (SELECT count(*) FROM bronze.shifts) = 2 AND (SELECT count(*) FROM bronze.vehicle_types) = 6),
    ('30 vehicles, 48 drivers, 40 shippers',
     (SELECT count(*) FROM bronze.vehicles) = 30 AND (SELECT count(*) FROM bronze.drivers) = 48
     AND (SELECT count(*) FROM bronze.shippers) = 40),
    ('streets and addresses loaded',
     (SELECT count(*) FROM bronze.streets) > 0 AND (SELECT count(*) FROM bronze.addresses) > 0
     AND (SELECT count(*) FROM bronze.icgc_addresses) > 0),
    ('raw_object_key on every row loaded from a file',
     NOT EXISTS (SELECT 1 FROM bronze.vehicles WHERE raw_object_key IS NULL)
     AND NOT EXISTS (SELECT 1 FROM bronze.drivers WHERE raw_object_key IS NULL)
     AND NOT EXISTS (SELECT 1 FROM bronze.shippers WHERE raw_object_key IS NULL)
     AND NOT EXISTS (SELECT 1 FROM bronze.streets WHERE raw_object_key IS NULL)
     AND NOT EXISTS (SELECT 1 FROM bronze.addresses WHERE raw_object_key IS NULL)
     AND NOT EXISTS (SELECT 1 FROM bronze.icgc_addresses WHERE raw_object_key IS NULL)),
    ('orders for the date', (SELECT count(*) FROM day) > 0),
    ('source, event_time, ingested_at and raw_object_key on every order',
     NOT EXISTS (SELECT 1 FROM day WHERE event_time IS NULL OR ingested_at IS NULL
                 OR raw_object_key IS DISTINCT FROM '${KEY}')),
    ('one ingested_at for the date, after every registration',
     (SELECT count(DISTINCT ingested_at) FROM day) = 1
     AND NOT EXISTS (SELECT 1 FROM day WHERE event_time > ingested_at)),
    ('every address_ref resolves',
     NOT EXISTS (SELECT 1 FROM day o WHERE NOT EXISTS (SELECT 1 FROM bronze.addresses a WHERE a.address_ref = o.address_ref)
                 AND NOT EXISTS (SELECT 1 FROM bronze.icgc_addresses i WHERE i.address_id = o.address_ref))),
    ('orders in all 14 zones', (SELECT count(DISTINCT destination_zone_id) FROM day) = 14))
  SELECT coalesce(string_agg(name, '; '), '') FROM checks WHERE NOT ok")
[[ -z "$failed" ]] || { echo "FAIL: $failed"; exit 1; }
echo "PASS: reference data loaded once, ${DATE} generated twice with the same ${twice%% *} orders, 9 checks"
