-- 002 · Bronze reference data
--
-- Hub, zones, shifts and vehicle types come from the AI-generated company profile
-- (services/generator/seed/company.json); vehicles and drivers are generated from it.
-- Reference tables carry source and ingested_at; they describe things, not events, so they
-- have no event_time. Coordinates are checked against a bounding box of Catalonia, the area the
-- OSRM road graph covers, which also catches swapped latitude and longitude.

CREATE TABLE bronze.hubs (
    hub_id                            text PRIMARY KEY,
    name                              text NOT NULL,
    address                           text NOT NULL,
    municipality                      text NOT NULL,
    lat                               double precision NOT NULL CHECK (lat BETWEEN 40.5 AND 42.9),
    lon                               double precision NOT NULL CHECK (lon BETWEEN 0.1 AND 3.4),
    floor_area_m2                     integer CHECK (floor_area_m2 > 0),
    loading_docks                     smallint CHECK (loading_docks > 0),
    sorting_capacity_parcels_per_hour integer CHECK (sorting_capacity_parcels_per_hour > 0),
    inbound_from                      time,
    inbound_to                        time,
    sorting_from                      time,
    sorting_to                        time,
    first_departure                   time,
    last_departure                    time CHECK (last_departure >= first_departure),
    same_day_cutoff                   time,
    source                            text NOT NULL REFERENCES ops.data_sources,
    ingested_at                       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.hubs IS '{"owner": "operations", "schema_version": 1}';

CREATE TABLE bronze.zones (
    zone_id                     text PRIMARY KEY CHECK (zone_id ~ '^Z[0-9]{2}$'),
    name                        text NOT NULL UNIQUE,
    municipality                text NOT NULL,
    districts                   text[] NOT NULL,
    centroid_lat                double precision NOT NULL CHECK (centroid_lat BETWEEN 40.5 AND 42.9),
    centroid_lon                double precision NOT NULL CHECK (centroid_lon BETWEEN 0.1 AND 3.4),
    distance_from_hub_km        numeric(5, 1) CHECK (distance_from_hub_km > 0),
    share_of_daily_parcels      numeric(4, 3) NOT NULL CHECK (share_of_daily_parcels BETWEEN 0 AND 1),
    stops_per_route             smallint NOT NULL CHECK (stops_per_route > 0),
    minutes_per_stop            numeric(3, 1) NOT NULL CHECK (minutes_per_stop > 0),
    delivery_difficulty         text NOT NULL CHECK (delivery_difficulty IN ('low', 'medium', 'high')),
    difficulty_factors          text[] NOT NULL DEFAULT '{}',
    preferred_vehicle_type_ids  text[] NOT NULL DEFAULT '{}',
    source                      text NOT NULL REFERENCES ops.data_sources,
    ingested_at                 timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.zones IS '{"owner": "operations", "schema_version": 1}';
COMMENT ON COLUMN bronze.zones.distance_from_hub_km IS 'As claimed by the generating model. Mostly short of the real route; use OSRM for distances.';

CREATE TABLE bronze.shifts (
    shift_id       text PRIMARY KEY,
    name           text NOT NULL,
    start_time     time NOT NULL,
    end_time       time NOT NULL CHECK (end_time > start_time),
    break_minutes  smallint NOT NULL CHECK (break_minutes >= 0),
    drivers        smallint NOT NULL CHECK (drivers >= 0),
    source         text NOT NULL REFERENCES ops.data_sources,
    ingested_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.shifts IS '{"owner": "operations", "schema_version": 1}';

CREATE TABLE bronze.vehicle_types (
    type_id                  text PRIMARY KEY,
    description              text NOT NULL,
    planned_count            smallint NOT NULL CHECK (planned_count >= 0),
    energy                   text NOT NULL CHECK (energy IN ('electric', 'plug-in hybrid', 'diesel', 'CNG')),
    dgt_label                text NOT NULL CHECK (dgt_label IN ('0', 'ECO', 'C')),
    payload_kg               integer NOT NULL CHECK (payload_kg > 0),
    cargo_volume_m3          numeric(4, 1) NOT NULL CHECK (cargo_volume_m3 > 0),
    parcel_capacity          smallint NOT NULL CHECK (parcel_capacity > 0),
    consumption_value        numeric(5, 1) NOT NULL CHECK (consumption_value > 0),
    consumption_unit         text NOT NULL CHECK (consumption_unit IN ('kWh/100km', 'l/100km', 'kg/100km')),
    range_km                 integer NOT NULL CHECK (range_km > 0),
    urban_average_speed_kmh  numeric(4, 1) NOT NULL CHECK (urban_average_speed_kmh > 0),
    telemetry_sensors        text[] NOT NULL DEFAULT '{}',
    source                   text NOT NULL REFERENCES ops.data_sources,
    ingested_at              timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.vehicle_types IS '{"owner": "fleet", "schema_version": 1}';

CREATE TABLE bronze.vehicles (
    vehicle_id       text PRIMARY KEY,
    plate            text NOT NULL UNIQUE,
    type_id          text NOT NULL REFERENCES bronze.vehicle_types,
    home_zone_id     text REFERENCES bronze.zones,
    commissioned_on  date,
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reserve', 'maintenance', 'retired')),
    source           text NOT NULL REFERENCES ops.data_sources,
    ingested_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.vehicles IS '{"owner": "fleet", "schema_version": 1}';

CREATE TABLE bronze.drivers (
    driver_id     text PRIMARY KEY,
    full_name     text NOT NULL,
    shift_id      text REFERENCES bronze.shifts,
    home_zone_id  text REFERENCES bronze.zones,
    hired_on      date,
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reserve', 'on_leave')),
    source        text NOT NULL REFERENCES ops.data_sources,
    ingested_at   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.drivers IS '{"owner": "operations", "schema_version": 1}';
COMMENT ON COLUMN bronze.drivers.full_name IS 'Fictional, AI-generated. Personal data in a real company: bronze is not readable by Grafana.';
