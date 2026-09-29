-- 001 · Metadata registry
--
-- The three mandatory metadata elements (ADR 0001, decision 20) are implemented like this:
--   source                 a column on every table, a key into ops.data_sources below, which
--                          records the origin system and its license;
--   event_time/ingested_at columns on every event table (reference tables carry ingested_at);
--   owner, schema_version  a JSON table comment, readable through ops.table_metadata.

CREATE TABLE ops.data_sources (
    source_id    text PRIMARY KEY CHECK (source_id ~ '^[a-z0-9-]+/[a-z0-9_-]+$'),
    kind         text NOT NULL CHECK (kind IN ('real', 'ai-generated', 'simulated', 'platform')),
    provider     text NOT NULL,
    description  text NOT NULL,
    license      text NOT NULL,
    url          text,
    ingested_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.data_sources IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN ops.data_sources.source_id IS 'Value that every table stores in its source column: <system>/<feed>.';
COMMENT ON COLUMN ops.data_sources.kind IS 'real: external open data; ai-generated: produced from a prompt in prompts/; simulated: produced by the simulator code; platform: produced by the platform itself.';

INSERT INTO ops.data_sources (source_id, kind, provider, description, license, url) VALUES
    ('generator/company-profile', 'ai-generated', 'Llobregat Express generator',
     'Company profile: hub, zones, shifts and vehicle types (services/generator/seed/company.json, prompt 001)',
     'MIT, this repository', 'prompts/001-company-profile.md'),
    ('generator/fleet', 'ai-generated', 'Llobregat Express generator',
     'One row per vehicle, expanded from the vehicle types of the company profile', 'MIT, this repository', 'prompts/'),
    ('generator/drivers', 'ai-generated', 'Llobregat Express generator',
     'Fictional drivers assigned to the shifts of the company profile', 'MIT, this repository', 'prompts/'),
    ('generator/orders', 'ai-generated', 'Llobregat Express generator',
     'Daily order batch at real Barcelona addresses, with free-text delivery notes', 'MIT, this repository', 'prompts/'),
    ('generator/route-history', 'ai-generated', 'Llobregat Express generator',
     'Ninety days of completed routes, the baseline of the KPI', 'MIT, this repository', 'prompts/'),
    ('generator/traffic', 'ai-generated', 'Llobregat Express generator',
     'Synthetic fallback for the Open Data BCN traffic feeds', 'MIT, this repository', 'prompts/'),
    ('generator/weather', 'ai-generated', 'Llobregat Express generator',
     'Synthetic fallback for Open-Meteo', 'MIT, this repository', 'prompts/'),
    ('simulator/gps', 'simulated', 'Llobregat Express simulator',
     'GPS pings of every van moving along its OSRM route, via topic gps.pings', 'MIT, this repository', NULL),
    ('simulator/telemetry', 'simulated', 'Llobregat Express simulator',
     'Vehicle sensor readings, via topic vehicle.telemetry', 'MIT, this repository', NULL),
    ('simulator/handheld', 'simulated', 'Llobregat Express simulator',
     'Driver handheld scans (loaded, arrived, delivered, failed, returned), via topic delivery.events',
     'MIT, this repository', NULL),
    ('simulator/trip-report', 'simulated', 'Llobregat Express simulator',
     'End-of-route trip report of the telematics unit: distance and energy used', 'MIT, this repository', NULL),
    ('simulator/pod-photos', 'simulated', 'Llobregat Express simulator',
     'Proof-of-delivery placeholder images in the RustFS bronze bucket', 'MIT, this repository', NULL),
    ('optimizer/route-planner', 'platform', 'Llobregat Express optimizer',
     'Route plans: the baseline plan before departure and every OR-Tools re-plan', 'MIT, this repository', NULL),
    ('dagster/platform_health', 'platform', 'Llobregat Express platform',
     'Health probes of every platform service', 'MIT, this repository', NULL),
    ('opendata-bcn/trams', 'real', 'Ajuntament de Barcelona, Open Data BCN',
     'Traffic state (0-6) per street section and its 15-minute forecast, every 5 minutes', 'CC BY 4.0',
     'https://opendata-ajuntament.barcelona.cat/data/dataset/trams'),
    ('opendata-bcn/itineraris', 'real', 'Ajuntament de Barcelona, Open Data BCN',
     'Travel time per itinerary, current and forecast, every 5 minutes', 'CC BY 4.0',
     'https://opendata-ajuntament.barcelona.cat/data/dataset/itineraris'),
    ('opendata-bcn/transit-relacio-trams', 'real', 'Ajuntament de Barcelona, Open Data BCN',
     'Description and geometry of the traffic sections', 'CC BY 4.0',
     'https://opendata-ajuntament.barcelona.cat/data/dataset/transit-relacio-trams'),
    ('opendata-bcn/taula-direle', 'real', 'Ajuntament de Barcelona, Open Data BCN',
     'Postal addresses of Barcelona, used by the order generator', 'CC BY 4.0',
     'https://opendata-ajuntament.barcelona.cat/data/dataset/taula-direle'),
    ('open-meteo/forecast', 'real', 'Open-Meteo',
     'Current weather conditions at the hub and every zone centroid', 'CC BY 4.0, non-commercial use',
     'https://open-meteo.com/en/docs'),
    ('minetur/carburantes', 'real', 'Ministerio para la Transición Ecológica (MITECO / MINETUR)',
     'Fuel prices per service station in the province of Barcelona', 'CC BY 4.0',
     'https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/'),
    ('openstreetmap/cataluna', 'real', 'OpenStreetMap contributors, Geofabrik extract',
     'Road network of Catalonia, routed by OSRM', 'ODbL 1.0',
     'https://download.geofabrik.de/europe/spain/cataluna.html');

-- Owner and schema version of every table, parsed from its JSON comment. Tables whose comment
-- is not JSON (dbt writes plain-text descriptions) show NULL instead of breaking the view.
CREATE VIEW ops.table_metadata AS
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view' ELSE 'table' END AS kind,
       m.meta ->> 'owner' AS owner,
       (m.meta ->> 'schema_version')::int AS schema_version,
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
