-- 004 · Bronze vehicle streams: GPS pings, telemetry and trip reports
--
-- gps_pings and vehicle_telemetry are TimescaleDB hypertables partitioned by event_time.
-- Storage lifecycle of both: row store while hot, compressed to the columnstore after one day,
-- chunks dropped after 30 days. Raw messages older than that live in the RustFS archive bucket.
-- The primary key (vehicle_id, event_time) makes a replayed Kafka message a no-op
-- (INSERT ... ON CONFLICT DO NOTHING).

CREATE TABLE bronze.gps_pings (
    vehicle_id   text NOT NULL,
    route_id     text,
    lat          double precision NOT NULL CHECK (lat BETWEEN 40.5 AND 42.9),
    lon          double precision NOT NULL CHECK (lon BETWEEN 0.1 AND 3.4),
    speed_kmh    real CHECK (speed_kmh >= 0),
    heading_deg  smallint CHECK (heading_deg BETWEEN 0 AND 359),
    accuracy_m   real CHECK (accuracy_m >= 0),
    source       text NOT NULL REFERENCES ops.data_sources,
    event_time   timestamptz NOT NULL,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (vehicle_id, event_time)
);
COMMENT ON TABLE bronze.gps_pings IS '{"owner": "fleet", "schema_version": 1}';
COMMENT ON COLUMN bronze.gps_pings.route_id IS 'Route the van is driving, NULL while it is not on a route.';
COMMENT ON COLUMN bronze.gps_pings.event_time IS 'GNSS fix time on the vehicle.';
SELECT create_hypertable('bronze.gps_pings', by_range('event_time', INTERVAL '1 day'));
ALTER TABLE bronze.gps_pings SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'vehicle_id',
    timescaledb.orderby = 'event_time DESC'
);
CALL add_columnstore_policy('bronze.gps_pings', after => INTERVAL '1 day');
SELECT add_retention_policy('bronze.gps_pings', drop_after => INTERVAL '30 days');
CREATE INDEX ON bronze.gps_pings (route_id, event_time DESC) WHERE route_id IS NOT NULL;

CREATE TABLE bronze.vehicle_telemetry (
    vehicle_id         text NOT NULL,
    route_id           text,
    speed_kmh          real CHECK (speed_kmh >= 0),
    odometer_km        numeric(9, 1) CHECK (odometer_km >= 0),
    ignition_on        boolean,
    energy_level_pct   real CHECK (energy_level_pct BETWEEN 0 AND 100),
    energy_used_total  numeric(10, 3) CHECK (energy_used_total >= 0),
    energy_unit        text CHECK (energy_unit IN ('kWh', 'l', 'kg')),
    cargo_door_open    boolean,
    readings           jsonb NOT NULL DEFAULT '{}',
    source             text NOT NULL REFERENCES ops.data_sources,
    event_time         timestamptz NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (vehicle_id, event_time),
    CHECK (jsonb_typeof(readings) = 'object')
);
COMMENT ON TABLE bronze.vehicle_telemetry IS '{"owner": "fleet", "schema_version": 1}';
COMMENT ON COLUMN bronze.vehicle_telemetry.energy_level_pct IS 'Battery state of charge, fuel level or CNG remaining, depending on the vehicle type.';
COMMENT ON COLUMN bronze.vehicle_telemetry.energy_used_total IS 'Cumulative energy counter of the vehicle, in energy_unit.';
COMMENT ON COLUMN bronze.vehicle_telemetry.readings IS 'Sensors that only some vehicle types have (tyre pressure, AdBlue level, CNG tank pressure, harsh braking), as they arrived.';
COMMENT ON COLUMN bronze.vehicle_telemetry.event_time IS 'Sensor reading time on the vehicle.';
SELECT create_hypertable('bronze.vehicle_telemetry', by_range('event_time', INTERVAL '1 day'));
ALTER TABLE bronze.vehicle_telemetry SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'vehicle_id',
    timescaledb.orderby = 'event_time DESC'
);
CALL add_columnstore_policy('bronze.vehicle_telemetry', after => INTERVAL '1 day');
SELECT add_retention_policy('bronze.vehicle_telemetry', drop_after => INTERVAL '30 days');

-- One trip report per route, sent by the telematics unit when the route ends. It aggregates the
-- telemetry counters, so the consumption survives the 30-day retention of the raw telemetry.
CREATE TABLE bronze.fuel_consumption (
    route_id              text PRIMARY KEY,
    vehicle_id            text NOT NULL,
    started_at            timestamptz NOT NULL,
    distance_km           numeric(6, 2) NOT NULL CHECK (distance_km >= 0),
    energy_used           numeric(8, 3) NOT NULL CHECK (energy_used >= 0),
    energy_unit           text NOT NULL CHECK (energy_unit IN ('kWh', 'l', 'kg')),
    idle_minutes          numeric(5, 1) CHECK (idle_minutes >= 0),
    consumption_per_100km numeric(7, 2) GENERATED ALWAYS AS
                              (CASE WHEN distance_km > 0 THEN round(energy_used / distance_km * 100, 2) END) STORED,
    source                text NOT NULL REFERENCES ops.data_sources,
    event_time            timestamptz NOT NULL,
    ingested_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (event_time > started_at)
);
COMMENT ON TABLE bronze.fuel_consumption IS '{"owner": "fleet", "schema_version": 1}';
COMMENT ON COLUMN bronze.fuel_consumption.event_time IS 'When the route ended and the trip report was sent.';
CREATE INDEX ON bronze.fuel_consumption (vehicle_id, event_time);
