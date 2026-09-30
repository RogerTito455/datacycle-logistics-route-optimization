-- Phase 3 · DIKW: the four levels of the GPS ping, as queries on bronze.
--
-- Run against the platform after loading, planning and simulating 28 September 2026
-- (docs/phases/3-dikw.md, "Reproduce"):
--
--   docker compose exec -T timescaledb psql -U llobregat -d logistics < docs/phases/queries/3-dikw.sql
--
-- The silver and gold models of issue #10 will compute the same things as dbt models; until then
-- these queries read bronze directly. Times are shown in Barcelona time.

\pset pager off

-- Metres between two points on the Earth (haversine). The platform has no PostGIS.
CREATE OR REPLACE FUNCTION pg_temp.dist_m(lat1 float8, lon1 float8, lat2 float8, lon2 float8)
RETURNS float8 LANGUAGE sql IMMUTABLE AS $$
  SELECT 2 * 6371000 * asin(sqrt(
    sin(radians(lat2 - lat1) / 2) ^ 2 +
    cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ^ 2))
$$;

-- Departure of every route: its first ping outside the hub geofence, as the KPI defines it.
CREATE TEMP VIEW departures AS
SELECT g.route_id, min(g.event_time) AS departed_at
FROM bronze.gps_pings g, bronze.hubs h
WHERE g.route_id IS NOT NULL
  AND pg_temp.dist_m(g.lat, g.lon, h.lat, h.lon) > h.geofence_radius_m
GROUP BY g.route_id;

-- Completion of every route: its last delivered or failed scan.
CREATE TEMP VIEW completions AS
SELECT route_id, max(event_time) AS completed_at
FROM bronze.delivery_events
WHERE status IN ('delivered', 'failed')
GROUP BY route_id;

\echo '== Data: the pings of van V-08 as it leaves the hub'
SELECT g.vehicle_id, g.route_id, g.event_time AT TIME ZONE 'Europe/Madrid' AS local_time,
       g.lat, g.lon, g.speed_kmh, g.heading_deg, g.accuracy_m,
       round(pg_temp.dist_m(g.lat, g.lon, h.lat, h.lon)) AS metres_from_hub
FROM bronze.gps_pings g, bronze.hubs h, departures d
WHERE g.route_id = 'R-20260928-Z02-M1' AND d.route_id = g.route_id
  AND g.event_time BETWEEN d.departed_at - interval '10 s' AND d.departed_at + interval '5 s'
ORDER BY g.event_time;

\echo '== Information: route R-20260928-Z02-M1 at 09:30'
WITH t AS (SELECT timestamptz '2026-09-28 09:30 Europe/Madrid' AS at),
last_scan AS (
  SELECT DISTINCT ON (e.route_id) e.route_id, e.stop_sequence, e.status, e.event_time
  FROM bronze.delivery_events e, t
  WHERE e.status IN ('delivered', 'failed') AND e.event_time <= t.at
  ORDER BY e.route_id, e.event_time DESC
),
last_ping AS (
  SELECT DISTINCT ON (g.route_id) g.route_id, g.lat, g.lon, g.speed_kmh
  FROM bronze.gps_pings g, t
  WHERE g.event_time <= t.at
  ORDER BY g.route_id, g.event_time DESC
)
SELECT p.route_id, p.vehicle_id, p.zone_id, p.stops,
       p.planned_departure AT TIME ZONE 'Europe/Madrid' AS planned_departure,
       d.departed_at AT TIME ZONE 'Europe/Madrid' AS departed,
       ls.stop_sequence AS last_stop_done, ls.status AS its_status,
       (SELECT count(*) FROM bronze.route_plan_stops s, t
         WHERE s.route_id = p.route_id AND s.plan_version = 0 AND s.planned_arrival <= t.at) AS stops_due_by_now,
       round(extract(epoch FROM ls.event_time - s.planned_arrival) / 60) AS minutes_behind,
       lp.lat, lp.lon, lp.speed_kmh
FROM bronze.route_plans p
JOIN departures d USING (route_id)
JOIN last_scan ls USING (route_id)
JOIN last_ping lp USING (route_id)
JOIN bronze.route_plan_stops s
  ON s.route_id = p.route_id AND s.plan_version = 0 AND s.stop_sequence = ls.stop_sequence
WHERE p.route_id = 'R-20260928-Z02-M1' AND p.plan_version = 0;

\echo '== Knowledge: every route of the day against its plan'
WITH r AS (
  SELECT p.route_id, p.wave, p.zone_id,
         extract(epoch FROM c.completed_at - d.departed_at) / 60 AS actual_min,
         extract(epoch FROM p.planned_completion - p.planned_departure) / 60 AS planned_min
  FROM bronze.route_plans p
  JOIN departures d USING (route_id)
  JOIN completions c USING (route_id)
  WHERE p.plan_version = 0 AND p.service_date = '2026-09-28'
)
SELECT coalesce(wave, 'day') AS wave, count(*) AS routes,
       round(avg(actual_min)) AS avg_actual_min, round(avg(planned_min)) AS avg_planned_min,
       round(avg(actual_min - planned_min)) AS avg_delay_min,
       count(*) FILTER (WHERE actual_min > 390) AS over_390_min
FROM r
GROUP BY ROLLUP (wave)
ORDER BY wave;

\echo '== Knowledge: the morning by zone'
SELECT p.zone_id, z.name, count(*) AS routes,
       round(avg(extract(epoch FROM c.completed_at - d.departed_at) / 60)) AS avg_actual_min,
       round(avg(extract(epoch FROM (c.completed_at - d.departed_at)
                                  - (p.planned_completion - p.planned_departure)) / 60)) AS avg_delay_min
FROM bronze.route_plans p
JOIN departures d USING (route_id)
JOIN completions c USING (route_id)
JOIN bronze.zones z ON z.zone_id = p.zone_id
WHERE p.plan_version = 0 AND p.service_date = '2026-09-28' AND p.wave = 'morning'
GROUP BY p.zone_id, z.name
ORDER BY avg_delay_min DESC;

-- Action: at 10:00, the routes whose delay so far, added to their planned length, takes them past
-- the 390-minute maximum. The delay of a route is how late its last scan came against the planned
-- arrival at that stop.
CREATE TEMP VIEW at_risk_at_10 AS
WITH t AS (SELECT timestamptz '2026-09-28 10:00 Europe/Madrid' AS at),
last_scan AS (
  SELECT DISTINCT ON (e.route_id) e.route_id, e.stop_sequence, e.event_time
  FROM bronze.delivery_events e, t
  WHERE e.status IN ('delivered', 'failed') AND e.event_time <= t.at
  ORDER BY e.route_id, e.event_time DESC
)
SELECT p.route_id, p.vehicle_id, p.zone_id, p.stops, ls.stop_sequence AS last_stop_done,
       extract(epoch FROM ls.event_time - s.planned_arrival) / 60 AS behind_min,
       extract(epoch FROM p.planned_completion - p.planned_departure) / 60 AS planned_min,
       extract(epoch FROM p.planned_completion - p.planned_departure) / 60
         + extract(epoch FROM ls.event_time - s.planned_arrival) / 60 AS projected_min
FROM bronze.route_plans p
JOIN last_scan ls USING (route_id)
JOIN bronze.route_plan_stops s
  ON s.route_id = p.route_id AND s.plan_version = 0 AND s.stop_sequence = ls.stop_sequence
WHERE p.plan_version = 0 AND p.service_date = '2026-09-28' AND p.wave = 'morning';

\echo '== Action: the list at 10:00'
SELECT route_id, vehicle_id, zone_id, last_stop_done || ' of ' || stops AS progress,
       round(behind_min) AS behind_min, round(projected_min) AS projected_min
FROM at_risk_at_10
WHERE projected_min > 390
ORDER BY behind_min DESC;

\echo '== Action: was the list right? Flagged at 10:00 against what happened'
SELECT a.projected_min > 390 AS flagged_at_10,
       extract(epoch FROM c.completed_at - d.departed_at) / 60 > 390 AS finished_past_390,
       count(*) AS routes,
       count(*) FILTER (WHERE a.planned_min > 390) AS already_past_390_in_the_plan
FROM at_risk_at_10 a
JOIN departures d USING (route_id)
JOIN completions c USING (route_id)
GROUP BY 1, 2
ORDER BY 1, 2;
