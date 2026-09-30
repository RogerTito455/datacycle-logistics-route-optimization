-- Phase 3 · DIKW: the four levels of the GPS ping, as queries on bronze.
--
-- Run against the platform after loading, planning and simulating 28 September 2026
-- (docs/phases/3-dikw.md, "Reproduce"):
--
--   docker compose exec -T timescaledb psql -U llobregat -d logistics < docs/phases/queries/3-dikw.sql
--
-- The silver and gold models of issue #10 will compute the same things as dbt models; until then
-- these queries read bronze directly. Times are shown in Barcelona time. The platform has one
-- hub, so the geofence is that hub's.

\pset pager off
\set service_date '2026-09-28'
\set route_id 'R-20260928-Z02-M1'
\set max_route_min 390
\set local_tz 'Europe/Madrid'

-- Metres between two points on the Earth (haversine). The platform has no PostGIS.
CREATE OR REPLACE FUNCTION pg_temp.dist_m(lat1 float8, lon1 float8, lat2 float8, lon2 float8)
RETURNS float8 LANGUAGE sql IMMUTABLE AS $$
    SELECT 2 * 6371000 * asin(sqrt(
        sin(radians(lat2 - lat1) / 2) ^ 2 +
        cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ^ 2))
$$;

-- Minutes between two timestamps.
CREATE OR REPLACE FUNCTION pg_temp.minutes(from_ts timestamptz, to_ts timestamptz)
RETURNS float8 LANGUAGE sql IMMUTABLE AS $$
    SELECT extract(epoch FROM to_ts - from_ts) / 60
$$;

-- One row per route of the baseline plan, measured as the KPI measures it: from the first ping
-- outside the hub geofence to the last delivered or failed scan.
CREATE TEMP TABLE routes AS
WITH departures AS (
    SELECT g.route_id, min(g.event_time) AS departed_at
    FROM bronze.gps_pings g, bronze.hubs h
    WHERE g.route_id IS NOT NULL
      AND pg_temp.dist_m(g.lat, g.lon, h.lat, h.lon) > h.geofence_radius_m
    GROUP BY g.route_id
),
completions AS (
    SELECT route_id, max(event_time) AS completed_at
    FROM bronze.delivery_events
    WHERE status IN ('delivered', 'failed')
    GROUP BY route_id
)
SELECT p.route_id, p.service_date, p.wave, p.zone_id, p.vehicle_id, p.stops,
       p.planned_departure, p.planned_completion, d.departed_at, c.completed_at,
       pg_temp.minutes(p.planned_departure, p.planned_completion) AS planned_min,
       pg_temp.minutes(d.departed_at, c.completed_at) AS actual_min
FROM bronze.route_plans p
JOIN departures d USING (route_id)
JOIN completions c USING (route_id)
WHERE p.plan_version = 0;

-- The last delivered or failed scan of every route up to a cutoff, with how late it came against
-- the planned arrival at that stop: the route's lateness on the clock at that moment.
CREATE OR REPLACE FUNCTION pg_temp.last_scan_before(cutoff timestamptz)
RETURNS TABLE (route_id text, stop_sequence smallint, status text, scanned_at timestamptz,
               minutes_late float8)
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (e.route_id) e.route_id, e.stop_sequence, e.status, e.event_time,
           pg_temp.minutes(s.planned_arrival, e.event_time)
    FROM bronze.delivery_events e
    JOIN bronze.route_plan_stops s
      ON s.route_id = e.route_id AND s.plan_version = 0 AND s.stop_sequence = e.stop_sequence
    WHERE e.status IN ('delivered', 'failed') AND e.event_time <= cutoff
    ORDER BY e.route_id, e.event_time DESC
$$;

\echo '== Data: the pings of the route as its van leaves the hub'
SELECT g.vehicle_id, g.route_id, g.event_time AT TIME ZONE :'local_tz' AS local_time,
       g.lat, g.lon, g.speed_kmh, g.heading_deg, g.accuracy_m, g.source, g.schema_version,
       round(pg_temp.dist_m(g.lat, g.lon, h.lat, h.lon)) AS metres_from_hub
FROM bronze.gps_pings g, bronze.hubs h, routes r
WHERE r.route_id = :'route_id' AND g.route_id = r.route_id
  AND g.event_time BETWEEN r.departed_at - interval '10 s' AND r.departed_at + interval '5 s'
ORDER BY g.event_time;

\echo '== Data: how much of it arrived that day'
SELECT (SELECT count(*) FROM bronze.gps_pings
         WHERE (event_time AT TIME ZONE :'local_tz')::date = :'service_date') AS gps_pings,
       (SELECT count(*) FROM bronze.delivery_events
         WHERE (event_time AT TIME ZONE :'local_tz')::date = :'service_date') AS handheld_scans;

\echo '== Information: the route at 09:30'
WITH cutoff AS (SELECT (:'service_date' || ' 09:30')::timestamp AT TIME ZONE :'local_tz' AS cutoff_time),
last_ping AS (
    SELECT g.lat, g.lon, g.speed_kmh
    FROM bronze.gps_pings g, cutoff
    WHERE g.route_id = :'route_id' AND g.event_time <= cutoff.cutoff_time
    ORDER BY g.event_time DESC
    LIMIT 1
)
SELECT r.route_id, r.vehicle_id, r.zone_id, r.stops,
       r.planned_departure AT TIME ZONE :'local_tz' AS planned_departure,
       r.departed_at AT TIME ZONE :'local_tz' AS left_geofence,
       ls.stop_sequence AS last_stop_done, ls.status AS last_stop_status,
       (SELECT count(*) FROM bronze.route_plan_stops s
         WHERE s.route_id = r.route_id AND s.plan_version = 0
           AND s.planned_arrival <= cutoff.cutoff_time) AS stops_due_by_now,
       round(ls.minutes_late) AS minutes_late,
       lp.lat, lp.lon, lp.speed_kmh
FROM routes r, cutoff, last_ping lp, pg_temp.last_scan_before(cutoff.cutoff_time) ls
WHERE r.route_id = :'route_id' AND ls.route_id = r.route_id;

\echo '== Information: the route at the end'
SELECT r.route_id, r.planned_completion AT TIME ZONE :'local_tz' AS planned_completion,
       r.completed_at AT TIME ZONE :'local_tz' AS completed,
       round(pg_temp.minutes(r.planned_completion, r.completed_at)) AS minutes_late,
       round(r.planned_min) AS planned_min, round(r.actual_min) AS actual_min
FROM routes r
WHERE r.route_id = :'route_id';

\echo '== Knowledge: every route of the day against its plan'
SELECT coalesce(wave, 'day') AS wave, count(*) AS routes,
       round(avg(actual_min)) AS avg_actual_min, round(avg(planned_min)) AS avg_planned_min,
       round(avg(actual_min - planned_min)) AS avg_delay_min,
       count(*) FILTER (WHERE planned_min > :max_route_min) AS planned_past_max,
       count(*) FILTER (WHERE actual_min > :max_route_min) AS finished_past_max
FROM routes
WHERE service_date = :'service_date'
GROUP BY ROLLUP (wave)
ORDER BY wave;

\echo '== Knowledge: deliveries inside the promised window'
SELECT round(100.0 * count(*) FILTER (WHERE e.event_time BETWEEN s.window_start AND s.window_end)
             / count(*), 1) AS pct_delivered_in_window
FROM bronze.delivery_events e
JOIN bronze.route_plan_stops s
  ON s.route_id = e.route_id AND s.plan_version = 0 AND s.stop_sequence = e.stop_sequence
JOIN routes r ON r.route_id = e.route_id
WHERE e.status = 'delivered' AND r.service_date = :'service_date';

\echo '== Knowledge: the morning by zone'
SELECT r.zone_id, z.name, count(*) AS routes,
       round(avg(r.actual_min)) AS avg_actual_min,
       round(avg(r.actual_min - r.planned_min)) AS avg_delay_min
FROM routes r
JOIN bronze.zones z ON z.zone_id = r.zone_id
WHERE r.service_date = :'service_date' AND r.wave = 'morning'
GROUP BY r.zone_id, z.name
ORDER BY avg_delay_min DESC;

-- Action: at 10:00, project every morning route's length from where it stands. Its projected
-- completion is the planned completion moved by its lateness at the last scan; its projected
-- length runs from the geofence exit to that completion, as the KPI measures it.
CREATE TEMP TABLE morning_at_10 AS
SELECT r.route_id, r.vehicle_id, r.zone_id, r.stops, r.planned_min, r.actual_min,
       ls.stop_sequence AS last_stop_done, ls.minutes_late,
       pg_temp.minutes(r.departed_at, r.planned_completion) + ls.minutes_late AS projected_min
FROM routes r,
     pg_temp.last_scan_before((:'service_date' || ' 10:00')::timestamp AT TIME ZONE :'local_tz') ls
WHERE ls.route_id = r.route_id AND r.service_date = :'service_date' AND r.wave = 'morning';

\echo '== Action: the list at 10:00'
SELECT m.route_id, m.vehicle_id, z.name AS zone, m.last_stop_done || ' of ' || m.stops AS progress,
       round(m.minutes_late) AS minutes_late, round(m.projected_min) AS projected_min
FROM morning_at_10 m
JOIN bronze.zones z ON z.zone_id = m.zone_id
WHERE m.projected_min > :max_route_min
ORDER BY m.minutes_late DESC, m.route_id;

\echo '== Action: was the list right? Flagged at 10:00 against what happened'
SELECT projected_min > :max_route_min AS flagged_at_10,
       actual_min > :max_route_min AS finished_past_max,
       count(*) AS routes,
       count(*) FILTER (WHERE planned_min > :max_route_min) AS already_past_max_in_the_plan
FROM morning_at_10
GROUP BY 1, 2
ORDER BY 1, 2;
