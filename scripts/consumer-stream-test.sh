#!/usr/bin/env bash
# Integration test of the stream consumer on the running stack (CI's compose job):
#
#   1. its pytest suite with the database tests, in scratch schemas that copy bronze and ops;
#   2. a fixed set of messages produced to the three topics, a few valid and one malformed per
#      topic, which the consumer service must write to bronze and ops.dead_letters, checked with SQL;
#   3. a replay: the consumer group is sent back to the start of every topic, and the consumer must
#      read everything again and write nothing twice.
#
#   ./scripts/consumer-stream-test.sh
#
# Each run sends its own van, V-CI-<run>, on 3 January 2000, so it checks only its own rows and can
# run again. It leaves them behind, with three dead letters keyed by that van, so it is meant for a
# throwaway stack like CI's. On a stack whose topics hold a simulated day, the replay reads that day
# again too: harmless, and under a minute.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

COMPOSE="docker compose"
GROUP="llobregat-consumer"
psql_admin() { $COMPOSE exec -T timescaledb psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA "$@"; }
produce() { $COMPOSE exec -T redpanda rpk topic produce "$1" -k "$2" >/dev/null; }  # produce <topic> <key>, one value per line
group_lag() { $COMPOSE exec -T redpanda rpk group describe "$GROUP" | awk '$1 == "TOTAL-LAG" {print $2}'; }

wait_for() {  # wait_for <what> <seconds> <command...>: until the command succeeds
  local what="$1" seconds="$2"; shift 2
  for _ in $(seq 1 "$seconds"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done
  echo "FAIL: ${what} after ${seconds} s"; $COMPOSE logs --no-color --tail=30 consumer; exit 1
}

echo "== pytest, with the database"
CONSUMER_TEST_REQUIRE_DB=1 uv run --project services/consumer --frozen pytest -q services/consumer/tests

RUN=$(date +%s)
VAN="V-CI-${RUN}"
ROUTE="R-20000103-CI${RUN}-M1"
EVENT="8d0c5e1a-6b0e-5a55-9d5e-$(printf '%010x' "$RUN")"  # + two hex digits: a UUID of this run

echo "== a fixed set of messages to the three topics, van ${VAN}"
produce gps.pings "${VAN}" <<EOF
{"vehicle_id":"${VAN}","event_time":"2000-01-03T07:15:00Z","lat":41.3398,"lon":2.1362,"speed_kmh":0.0,"heading_deg":0,"accuracy_m":4.2,"source":"simulator/gps","schema_version":1}
{"vehicle_id":"${VAN}","route_id":"${ROUTE}","event_time":"2000-01-03T07:30:00Z","lat":41.3441,"lon":2.1402,"speed_kmh":22.5,"heading_deg":45,"accuracy_m":5.1,"source":"simulator/gps","schema_version":1,"satellites":11}
{"vehicle_id":"${VAN}","route_id":"${ROUTE}","event_time":"2000-01-03T07:30:05Z","lat":41.3444,"lon":2.1405,"speed_kmh":23.1,"heading_deg":46,"accuracy_m":4.8,"source":"simulator/gps","schema_version":1}
{"vehicle_id":"${VAN}","route_id":"${ROUTE}","event_time":"2000-01-03T07:30:05Z","lat":41.3444,"lon":2.1405,"speed_kmh":23.1,"heading_deg":46,"accuracy_m":4.8,"source":"simulator/gps","schema_version":1}
{"vehicle_id":"${VAN}","lat":41.3447,"lon":2.1408,"source":"simulator/gps","schema_version":1}
EOF
produce vehicle.telemetry "${VAN}" <<EOF
{"vehicle_id":"${VAN}","route_id":"${ROUTE}","event_time":"2000-01-03T07:30:00Z","speed_kmh":22.0,"odometer_km":10234.5,"ignition_on":true,"energy_level_pct":90.5,"energy_used_total":2048.125,"energy_unit":"kWh","cargo_door_open":false,"source":"simulator/telemetry","schema_version":1,"charging":false,"tyre_pressure_bar":[4.9,4.9,5.0,5.0]}
{"vehicle_id":"${VAN}","route_id":"${ROUTE}","event_time":"2000-01-03T07:30:30Z","speed_kmh":0.0,"odometer_km":10234.7,"ignition_on":false,"energy_level_pct":90.4,"energy_used_total":2048.161,"energy_unit":"kWh","cargo_door_open":true,"source":"simulator/telemetry","schema_version":1,"charging":false,"tyre_pressure_bar":[4.9,4.9,5.0,5.0]}
{"vehicle_id":"${VAN}","event_time":
EOF
produce delivery.events "${VAN}" <<EOF
{"event_id":"${EVENT}01","order_id":"O-20000103-00001","route_id":"${ROUTE}","stop_sequence":1,"vehicle_id":"${VAN}","driver_id":"D-CI","status":"out_for_delivery","lat":41.3395,"lon":2.1365,"event_time":"2000-01-03T07:30:00Z","source":"simulator/handheld","schema_version":1}
{"event_id":"${EVENT}02","order_id":"O-20000103-00001","route_id":"${ROUTE}","stop_sequence":1,"vehicle_id":"${VAN}","driver_id":"D-CI","status":"delivered","lat":41.3801,"lon":2.1617,"event_time":"2000-01-03T08:02:10Z","pod_object_key":"pod/2000-01-03/O-20000103-00001.jpg","source":"simulator/handheld","schema_version":1}
{"event_id":"${EVENT}03","order_id":"O-20000103-00002","route_id":"${ROUTE}","stop_sequence":2,"vehicle_id":"${VAN}","driver_id":"D-CI","status":"failed","lat":41.3812,"lon":2.1633,"event_time":"2000-01-03T08:09:40Z","failure_reason":"recipient_absent","source":"simulator/handheld","schema_version":1}
{"event_id":"not-a-uuid","order_id":"O-20000103-00003","route_id":"${ROUTE}","status":"arrived","event_time":"2000-01-03T08:15:00Z","source":"simulator/handheld","schema_version":1}
EOF

# What the consumer has written of this test: pings, telemetry, scans and dead letters.
state() {
  psql_admin -c "
    SELECT (SELECT count(*) FROM bronze.gps_pings WHERE vehicle_id = '${VAN}') || ' '
        || (SELECT count(*) FROM bronze.vehicle_telemetry WHERE vehicle_id = '${VAN}') || ' '
        || (SELECT count(*) FROM bronze.delivery_events WHERE route_id = '${ROUTE}') || ' '
        || (SELECT count(*) FROM ops.dead_letters WHERE message_key = '${VAN}'::bytea) || ' '
        || (SELECT coalesce(max(ingested_at)::text, '-') FROM bronze.gps_pings WHERE vehicle_id = '${VAN}')"
}
written() { [[ "$(state)" == "3 2 3 3 "* ]]; }
lag_zero() { [[ "$(group_lag)" == 0 ]]; }
wait_for "the consumer did not write the messages" 60 written
wait_for "the consumer group still lags" 30 lag_zero

echo "== checks"
failed=$(psql_admin -c "
  WITH pings AS (SELECT * FROM bronze.gps_pings WHERE vehicle_id = '${VAN}'),
  telemetry AS (SELECT * FROM bronze.vehicle_telemetry WHERE vehicle_id = '${VAN}'),
  scans AS (SELECT * FROM bronze.delivery_events WHERE route_id = '${ROUTE}'),
  dead AS (SELECT * FROM ops.dead_letters WHERE message_key = '${VAN}'::bytea),
  checks(name, ok) AS (VALUES
    ('3 pings (one sent twice), 2 telemetry readings, 3 scans',
     (SELECT count(*) FROM pings) = 3 AND (SELECT count(*) FROM telemetry) = 2 AND (SELECT count(*) FROM scans) = 3),
    ('source, event_time, ingested_at and schema_version 1 on every row',
     NOT EXISTS (SELECT 1 FROM pings WHERE source <> 'simulator/gps' OR ingested_at IS NULL OR schema_version <> 1)
     AND NOT EXISTS (SELECT 1 FROM telemetry WHERE source <> 'simulator/telemetry' OR schema_version <> 1)
     AND NOT EXISTS (SELECT 1 FROM scans WHERE source <> 'simulator/handheld' OR schema_version <> 1)
     AND NOT EXISTS (SELECT 1 FROM pings WHERE event_time > ingested_at)),
    ('the ping at the dock has no route, the others keep every field',
     (SELECT count(*) FROM pings WHERE route_id IS NULL) = 1
     AND (SELECT extra_fields FROM pings WHERE event_time = '2000-01-03 07:30:00+00') = '{\"satellites\": 11}'
     AND (SELECT count(*) FROM pings WHERE extra_fields IS NULL) = 2
     AND (SELECT heading_deg FROM pings WHERE event_time = '2000-01-03 07:30:05+00') = 46),
    ('telemetry keeps the sensors of the van type in readings',
     NOT EXISTS (SELECT 1 FROM telemetry
                 WHERE readings <> '{\"charging\": false, \"tyre_pressure_bar\": [4.9, 4.9, 5.0, 5.0]}')
     AND (SELECT sum(odometer_km) FROM telemetry) = 20469.2),
    ('the delivered scan names its photo, the failed one its reason',
     (SELECT pod_object_key FROM scans WHERE status = 'delivered') = 'pod/2000-01-03/O-20000103-00001.jpg'
     AND (SELECT failure_reason FROM scans WHERE status = 'failed') = 'recipient_absent'),
    ('one dead letter per topic, with its reason, raw bytes and place in the topic',
     (SELECT string_agg(topic || ':' || reason, ' ' ORDER BY topic) FROM dead)
       = 'delivery.events:invalid_field gps.pings:missing_field vehicle.telemetry:invalid_json'
     AND (SELECT encode(payload, 'escape') FROM dead WHERE topic = 'vehicle.telemetry')
       = '{\"vehicle_id\":\"${VAN}\",\"event_time\":'
     AND NOT EXISTS (SELECT 1 FROM dead WHERE kafka_offset IS NULL OR kafka_timestamp IS NULL OR error = '')),
    ('the lag of every partition is recorded, the newest event_time with it',
     (SELECT count(DISTINCT topic) FROM ops.consumer_lag WHERE consumer_group = '${GROUP}') = 3
     AND EXISTS (SELECT 1 FROM ops.consumer_lag WHERE last_event_time >= '2000-01-03 07:30:05+00')))
  SELECT coalesce(string_agg(name, '; '), '') FROM checks WHERE NOT ok")
[[ -z "$failed" ]] || { echo "FAIL: $failed"; exit 1; }
before=$(state)

echo "== replay: the group back to the start of every topic"
$COMPOSE stop consumer >/dev/null 2>&1
seek() { $COMPOSE exec -T redpanda rpk group seek "$GROUP" --to start; }
wait_for "could not send the group back to the start" 60 seek
$COMPOSE start consumer >/dev/null 2>&1
wait_for "the consumer did not catch up after the replay" 120 lag_zero  # the seek made it lag by every message
after=$(state)
[[ "$after" == "$before" ]] || { echo "FAIL: the replay changed bronze or the dead letters: '${before}' became '${after}'"; exit 1; }
lag_recorded() {  # the newest measurement of every partition says 0 and is recent
  [[ "$(psql_admin -c "
    SELECT count(*) > 0 AND bool_and(lag = 0) AND min(event_time) > now() - interval '30 seconds'
    FROM (SELECT DISTINCT ON (topic, kafka_partition) lag, event_time FROM ops.consumer_lag
          WHERE consumer_group = '${GROUP}' ORDER BY topic, kafka_partition, event_time DESC) latest")" == t ]]
}
wait_for "ops.consumer_lag has no recent measurement of 0 for every partition" 30 lag_recorded

echo "PASS: 3 pings (one sent twice), 2 telemetry readings and 3 scans written with every field," \
     "3 malformed messages dead-lettered, the replay of every topic wrote nothing twice"
