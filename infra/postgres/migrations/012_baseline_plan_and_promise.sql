-- 012 · The baseline route plan and the promised window of each stop (issue #7)
--
-- 1. planner/baseline: the data source of the baseline plan, the fixed plan of each delivery wave
--    that the company's planners make before the vans leave (plan version 0). The simulator's
--    baseline planner stands in for them; the optimizer (issue #16) writes re-plans (versions 1 and
--    up) under its own source, optimizer/route-planner.
-- 2. bronze.route_plan_stops.window_start and window_end: the 120-minute window promised to the
--    customer at that stop. A consumer who accepted any time in the wave gets it when the routes are
--    planned (demand model, prompt 004), so bronze.orders only has the whole wave; slot and business
--    orders keep their own. The on-time share is measured against it (issue #16).
-- 3. The handheld's scans are the statuses the simulator emits.
--
-- Bronze stays raw: no CHECK constraints (migration 007).

-- 1 · Data sources ----------------------------------------------------------------------------

INSERT INTO ops.data_sources (source_id, kind, provider, description, license, url) VALUES
    ('planner/baseline', 'simulated', 'Llobregat Express simulator',
     'Baseline route plans: the fixed plan of each delivery wave made before the vans leave (plan version 0), '
     'by the rules of the company''s planners: zone routes, nearest-neighbour stop order on OSRM travel times',
     'MIT, this repository', 'services/simulator/README.md');

UPDATE ops.data_sources
SET description = 'Re-plans of the OR-Tools optimizer (plan version 1 and up); the baseline plan (version 0) '
                  'is planner/baseline'
WHERE source_id = 'optimizer/route-planner';
UPDATE ops.data_sources
SET description = 'Driver handheld scans (out_for_delivery, arrived, delivered, failed), via topic delivery.events',
    url = 'services/simulator/README.md'
WHERE source_id = 'simulator/handheld';

-- 2 · The promised window ---------------------------------------------------------------------

ALTER TABLE bronze.route_plan_stops
    ADD COLUMN window_start timestamptz,
    ADD COLUMN window_end   timestamptz;
COMMENT ON TABLE bronze.route_plan_stops IS '{"owner": "operations", "schema_version": 3}';
COMMENT ON COLUMN bronze.route_plan_stops.window_start IS 'Start of the 120-minute window promised to the customer. For an order with window_type wave, set from the planned arrival when the baseline plan is made; otherwise the order''s own window. window_end is its end.';
COMMENT ON COLUMN bronze.route_plans.source IS 'planner/baseline for version 0, the baseline plan; optimizer/route-planner for the re-plans.';
COMMENT ON COLUMN bronze.route_plans.event_time IS 'When the plan was made. For the baseline plan, the planning time of its wave on the service date (06:00 for the morning, 13:45 for the afternoon), also when a past date is planned again.';
COMMENT ON COLUMN bronze.route_plans.zone_id IS 'The zone with the most stops of the route; a route can take stops of neighbouring zones.';
COMMENT ON COLUMN bronze.route_plans.planned_completion IS 'When the last stop is planned to end: the planned completed_at of the KPI.';
