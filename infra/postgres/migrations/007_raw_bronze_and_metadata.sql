-- 007 · Raw bronze, full metadata, addresses and review fixes
--
-- Migrations 001-006 are applied and never edited; this one changes what they created.
--
-- 1. Bronze is raw and write-once. It keeps what makes it a reliable store: primary and unique
--    keys (a replayed message or reloaded file writes nothing twice), the foreign keys among the
--    reference tables and to ops.data_sources, and NOT NULL on key and metadata columns. Every
--    rule that judges a value goes: bounding boxes, closed value lists, ranges and cross-column
--    rules. A raw record is never rejected; silver flags it with dbt tests (issue #10).
-- 2. No retention policies until the archiving job (issue #20) exports chunks to the RustFS
--    archive bucket. Raw GPS pings and telemetry exist nowhere else. Compression stays.
-- 3. The metadata elements of ADR 0001, decision 20, on the ops tables as well.
-- 4. Hub geofence radius, a platform assumption the KPI's departed_at needs.
-- 5. Fuel consumption is derived from bronze.vehicle_telemetry, not sent as a trip report.
-- 6. traffic_state.section_id holds an itinerary id for the itineraris feed, so it is renamed.
-- 7. bronze.addresses, the Open Data BCN postal address table (loaded by issue #3).
-- 8. ops.table_metadata tolerates a comment whose schema_version is not a number.
--
-- schema_version is bumped on every table whose columns or constraints change here.

-- 1 · Bronze accepts every raw record ---------------------------------------------------------

DO $$
DECLARE
    rule record;
BEGIN
    FOR rule IN
        SELECT conrelid::regclass AS table_name, conname
        FROM pg_constraint
        WHERE contype = 'c' AND connamespace = 'bronze'::regnamespace
        ORDER BY conrelid::regclass::text, conname
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', rule.table_name, rule.conname);
    END LOOP;
END
$$;

-- NOT NULL stays on primary, unique and foreign key columns, on the *_id join keys, on the
-- metadata columns (source, event_time, ingested_at) and on traffic_state.raw_line, the record
-- itself. Every other column may be empty in a raw record.
ALTER TABLE bronze.hubs
    ALTER COLUMN name DROP NOT NULL,
    ALTER COLUMN address DROP NOT NULL,
    ALTER COLUMN municipality DROP NOT NULL,
    ALTER COLUMN lat DROP NOT NULL,
    ALTER COLUMN lon DROP NOT NULL;
ALTER TABLE bronze.zones
    ALTER COLUMN municipality DROP NOT NULL,
    ALTER COLUMN districts DROP NOT NULL,
    ALTER COLUMN centroid_lat DROP NOT NULL,
    ALTER COLUMN centroid_lon DROP NOT NULL,
    ALTER COLUMN share_of_daily_parcels DROP NOT NULL,
    ALTER COLUMN stops_per_route DROP NOT NULL,
    ALTER COLUMN minutes_per_stop DROP NOT NULL,
    ALTER COLUMN delivery_difficulty DROP NOT NULL,
    ALTER COLUMN difficulty_factors DROP NOT NULL,
    ALTER COLUMN preferred_vehicle_type_ids DROP NOT NULL;
ALTER TABLE bronze.shifts
    ALTER COLUMN name DROP NOT NULL,
    ALTER COLUMN start_time DROP NOT NULL,
    ALTER COLUMN end_time DROP NOT NULL,
    ALTER COLUMN break_minutes DROP NOT NULL,
    ALTER COLUMN drivers DROP NOT NULL;
ALTER TABLE bronze.vehicle_types
    ALTER COLUMN description DROP NOT NULL,
    ALTER COLUMN planned_count DROP NOT NULL,
    ALTER COLUMN energy DROP NOT NULL,
    ALTER COLUMN dgt_label DROP NOT NULL,
    ALTER COLUMN payload_kg DROP NOT NULL,
    ALTER COLUMN cargo_volume_m3 DROP NOT NULL,
    ALTER COLUMN parcel_capacity DROP NOT NULL,
    ALTER COLUMN consumption_value DROP NOT NULL,
    ALTER COLUMN consumption_unit DROP NOT NULL,
    ALTER COLUMN range_km DROP NOT NULL,
    ALTER COLUMN urban_average_speed_kmh DROP NOT NULL,
    ALTER COLUMN telemetry_sensors DROP NOT NULL;
ALTER TABLE bronze.vehicles
    ALTER COLUMN status DROP NOT NULL;
ALTER TABLE bronze.drivers
    ALTER COLUMN full_name DROP NOT NULL,
    ALTER COLUMN status DROP NOT NULL;
ALTER TABLE bronze.orders
    ALTER COLUMN service_date DROP NOT NULL,
    ALTER COLUMN service_level DROP NOT NULL,
    ALTER COLUMN priority DROP NOT NULL,
    ALTER COLUMN customer_type DROP NOT NULL,
    ALTER COLUMN shipper_name DROP NOT NULL,
    ALTER COLUMN origin_address DROP NOT NULL,
    ALTER COLUMN destination_address DROP NOT NULL,
    ALTER COLUMN destination_municipality DROP NOT NULL,
    ALTER COLUMN destination_lat DROP NOT NULL,
    ALTER COLUMN destination_lon DROP NOT NULL,
    ALTER COLUMN parcels DROP NOT NULL,
    ALTER COLUMN parcel_size DROP NOT NULL;
ALTER TABLE bronze.delivery_events
    ALTER COLUMN status DROP NOT NULL;
ALTER TABLE bronze.route_plans
    ALTER COLUMN planner DROP NOT NULL,
    ALTER COLUMN replan_reason DROP NOT NULL,
    ALTER COLUMN service_date DROP NOT NULL,
    ALTER COLUMN wave DROP NOT NULL,
    ALTER COLUMN stops DROP NOT NULL,
    ALTER COLUMN planned_departure DROP NOT NULL,
    ALTER COLUMN planned_completion DROP NOT NULL;
ALTER TABLE bronze.route_plan_stops
    ALTER COLUMN planned_arrival DROP NOT NULL;
ALTER TABLE bronze.route_history
    ALTER COLUMN service_date DROP NOT NULL,
    ALTER COLUMN wave DROP NOT NULL,
    ALTER COLUMN completed_at DROP NOT NULL,
    ALTER COLUMN stops_planned DROP NOT NULL,
    ALTER COLUMN stops_delivered DROP NOT NULL,
    ALTER COLUMN stops_failed DROP NOT NULL;
ALTER TABLE bronze.gps_pings
    ALTER COLUMN lat DROP NOT NULL,
    ALTER COLUMN lon DROP NOT NULL;
ALTER TABLE bronze.vehicle_telemetry
    ALTER COLUMN readings DROP NOT NULL;
ALTER TABLE bronze.fuel_consumption
    ALTER COLUMN started_at DROP NOT NULL,
    ALTER COLUMN distance_km DROP NOT NULL,
    ALTER COLUMN energy_used DROP NOT NULL,
    ALTER COLUMN energy_unit DROP NOT NULL;
ALTER TABLE bronze.traffic_sections
    ALTER COLUMN description DROP NOT NULL,
    ALTER COLUMN coordinates DROP NOT NULL;
ALTER TABLE bronze.weather
    ALTER COLUMN lat DROP NOT NULL,
    ALTER COLUMN lon DROP NOT NULL;
ALTER TABLE bronze.fuel_prices
    ALTER COLUMN price_eur DROP NOT NULL;

-- Write-once: deleting a plan must not silently delete its stops.
ALTER TABLE bronze.route_plan_stops
    DROP CONSTRAINT route_plan_stops_route_id_plan_version_fkey,
    ADD CONSTRAINT route_plan_stops_route_id_plan_version_fkey
        FOREIGN KEY (route_id, plan_version) REFERENCES bronze.route_plans;

-- 2 · Keep every chunk until it is archived ---------------------------------------------------

SELECT remove_retention_policy('bronze.gps_pings');
SELECT remove_retention_policy('bronze.vehicle_telemetry');
SELECT remove_retention_policy('bronze.traffic_state');
SELECT remove_retention_policy('bronze.fuel_prices');

-- 3 · source and ingested_at on the ops tables ------------------------------------------------

INSERT INTO ops.data_sources (source_id, kind, provider, description, license, url) VALUES
    ('platform/migrations', 'platform', 'Llobregat Express platform',
     'Rows written by the versioned SQL migrations: the data source registry and the migration ledger',
     'MIT, this repository', 'infra/postgres/migrations/'),
    ('derived/vehicle_telemetry', 'platform', 'Llobregat Express platform',
     'Consumption per route, aggregated from the energy counter and odometer in bronze.vehicle_telemetry',
     'MIT, this repository', 'docs/data-model.md');
DELETE FROM ops.data_sources WHERE source_id = 'simulator/trip-report';
UPDATE ops.data_sources
SET description = 'Orders at real Barcelona addresses, in micro-batches through the day (next-day orders nightly), with free-text delivery notes'
WHERE source_id = 'generator/orders';

ALTER TABLE ops.data_sources
    ADD COLUMN source text NOT NULL DEFAULT 'platform/migrations' REFERENCES ops.data_sources;
COMMENT ON TABLE ops.data_sources IS '{"owner": "platform", "schema_version": 2}';
COMMENT ON COLUMN ops.data_sources.source IS 'Who registered the source: platform/migrations for every row written by a migration.';

ALTER TABLE ops.schema_migrations
    ADD COLUMN source text NOT NULL DEFAULT 'platform/migrations' REFERENCES ops.data_sources,
    ADD COLUMN ingested_at timestamptz NOT NULL DEFAULT now();
UPDATE ops.schema_migrations SET ingested_at = applied_at;
COMMENT ON TABLE ops.schema_migrations IS '{"owner": "platform", "schema_version": 2}';
COMMENT ON COLUMN ops.schema_migrations.ingested_at IS 'When the row was written, the same moment as applied_at.';

ALTER TABLE ops.service_health ADD FOREIGN KEY (source) REFERENCES ops.data_sources;
COMMENT ON TABLE ops.service_health IS '{"owner": "platform", "schema_version": 2}';

-- 4 · Hub geofence ----------------------------------------------------------------------------

ALTER TABLE bronze.hubs ADD COLUMN geofence_radius_m smallint DEFAULT 400;
COMMENT ON COLUMN bronze.hubs.geofence_radius_m IS 'Platform assumption, not in company.json: a van is inside the hub within this distance of (lat, lon). The hub point is 284 m from the nearest drivable road (prompt 001 validation), so 400 m reaches the gate. departed_at of the KPI is the first GPS ping outside it.';

-- 5 · Fuel consumption derived from telemetry -------------------------------------------------

ALTER TABLE bronze.fuel_consumption ALTER COLUMN source SET DEFAULT 'derived/vehicle_telemetry';
COMMENT ON COLUMN bronze.fuel_consumption.source IS 'derived/vehicle_telemetry: computed by the platform when a route ends, from the telemetry of that vehicle and route.';
COMMENT ON COLUMN bronze.fuel_consumption.started_at IS 'First telemetry reading of the route.';
COMMENT ON COLUMN bronze.fuel_consumption.event_time IS 'Last telemetry reading of the route, when it ended.';
COMMENT ON COLUMN bronze.fuel_consumption.energy_used IS 'Difference of energy_used_total between the first and the last reading, in energy_unit.';
COMMENT ON COLUMN bronze.fuel_consumption.distance_km IS 'Difference of odometer_km between the first and the last reading.';

-- 6 · traffic_state: one id column for two feeds ----------------------------------------------

ALTER TABLE bronze.traffic_state RENAME COLUMN section_id TO feed_item_id;
COMMENT ON COLUMN bronze.traffic_state.feed_item_id IS 'Depends on feed. trams: street section id, which joins bronze.traffic_sections. itineraris: itinerary id, which has no geometry table.';

-- 7 · Postal addresses ------------------------------------------------------------------------

-- Open Data BCN taula-direle, one row per street number. Columns keep the published values; the
-- CSV field name is given where the column name differs.
CREATE TABLE bronze.addresses (
    street_code          text NOT NULL,
    street_number        text NOT NULL,
    number_letter        text NOT NULL,
    number_type          text,
    district_code        text,
    neighbourhood_code   text,
    statistical_section  text,
    census_section       text,
    postal_district      text,
    x_ed50               numeric(10, 3),
    y_ed50               numeric(11, 3),
    x_etrs89             numeric(10, 3),
    y_etrs89             numeric(11, 3),
    lon                  double precision,
    lat                  double precision,
    address_ref          text GENERATED ALWAYS AS (street_code || '-' || street_number || btrim(number_letter)) STORED UNIQUE,
    source               text NOT NULL REFERENCES ops.data_sources,
    ingested_at          timestamptz NOT NULL DEFAULT now(),
    raw_object_key       text,
    PRIMARY KEY (street_code, street_number, number_letter)
);
COMMENT ON TABLE bronze.addresses IS '{"owner": "operations", "schema_version": 1}';
COMMENT ON COLUMN bronze.addresses.street_code IS 'codi_carrer: street code of the city street register.';
COMMENT ON COLUMN bronze.addresses.street_number IS 'numpost: street number, zero-padded as published.';
COMMENT ON COLUMN bronze.addresses.number_letter IS 'llepost: letter after the number (14B); a single space when there is none, as published.';
COMMENT ON COLUMN bronze.addresses.number_type IS 'tipusnum, as published.';
COMMENT ON COLUMN bronze.addresses.district_code IS 'districte: city district, 01-10.';
COMMENT ON COLUMN bronze.addresses.neighbourhood_code IS 'barri: neighbourhood, 01-73.';
COMMENT ON COLUMN bronze.addresses.statistical_section IS 'secc_est: statistical section, as published.';
COMMENT ON COLUMN bronze.addresses.census_section IS 'secc_cens: census section within the district.';
COMMENT ON COLUMN bronze.addresses.postal_district IS 'dist_post: the last two digits of the 080NN postcode.';
COMMENT ON COLUMN bronze.addresses.x_ed50 IS 'UTM zone 31N easting, ED50 datum. y_ed50 is the northing.';
COMMENT ON COLUMN bronze.addresses.x_etrs89 IS 'UTM zone 31N easting, ETRS89 datum. y_etrs89 is the northing.';
COMMENT ON COLUMN bronze.addresses.lon IS 'longitud_wgs84. lat is latitud_wgs84.';
COMMENT ON COLUMN bronze.addresses.address_ref IS 'Street code, number and letter in one value: the key bronze.orders.address_ref points to.';
COMMENT ON COLUMN bronze.orders.address_ref IS 'Destination in bronze.addresses (Open Data BCN taula-direle), by its address_ref.';

-- 8 · ops.table_metadata: a comment with a non-numeric schema_version shows NULL ---------------

CREATE OR REPLACE VIEW ops.table_metadata AS
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view' ELSE 'table' END AS kind,
       m.meta ->> 'owner' AS owner,
       CASE WHEN m.meta ->> 'schema_version' ~ '^[0-9]{1,9}$'
            THEN (m.meta ->> 'schema_version')::int END AS schema_version,
       EXISTS (SELECT 1 FROM timescaledb_information.hypertables h
               WHERE h.hypertable_schema = n.nspname AND h.hypertable_name = c.relname) AS is_hypertable,
       EXISTS (SELECT 1 FROM pg_attribute a
               WHERE a.attrelid = c.oid AND a.attname = 'source' AND NOT a.attisdropped) AS has_source,
       EXISTS (SELECT 1 FROM pg_attribute a
               WHERE a.attrelid = c.oid AND a.attname = 'event_time' AND NOT a.attisdropped) AS has_event_time,
       EXISTS (SELECT 1 FROM pg_attribute a
               WHERE a.attrelid = c.oid AND a.attname = 'ingested_at' AND NOT a.attisdropped) AS has_ingested_at
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL (
    SELECT CASE WHEN pg_input_is_valid(obj_description(c.oid, 'pg_class'), 'jsonb')
                THEN obj_description(c.oid, 'pg_class')::jsonb END AS meta
) m
WHERE n.nspname IN ('bronze', 'silver', 'gold', 'ops')
  AND c.relkind IN ('r', 'p', 'v', 'm');
COMMENT ON VIEW ops.table_metadata IS '{"owner": "platform", "schema_version": 1}';

COMMENT ON SCHEMA ops IS 'Platform bookkeeping: data source registry, migration ledger, table metadata and service health checks.';

-- Tables whose columns or constraints changed above.
COMMENT ON TABLE bronze.hubs IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.zones IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.shifts IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.vehicle_types IS '{"owner": "fleet", "schema_version": 2}';
COMMENT ON TABLE bronze.vehicles IS '{"owner": "fleet", "schema_version": 2}';
COMMENT ON TABLE bronze.drivers IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.orders IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.delivery_events IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.route_plans IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.route_plan_stops IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.route_history IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON TABLE bronze.gps_pings IS '{"owner": "fleet", "schema_version": 2}';
COMMENT ON TABLE bronze.vehicle_telemetry IS '{"owner": "fleet", "schema_version": 2}';
COMMENT ON TABLE bronze.fuel_consumption IS '{"owner": "fleet", "schema_version": 2}';
COMMENT ON TABLE bronze.traffic_sections IS '{"owner": "platform", "schema_version": 2}';
COMMENT ON TABLE bronze.traffic_state IS '{"owner": "platform", "schema_version": 2}';
COMMENT ON TABLE bronze.weather IS '{"owner": "platform", "schema_version": 2}';
COMMENT ON TABLE bronze.fuel_prices IS '{"owner": "platform", "schema_version": 2}';
