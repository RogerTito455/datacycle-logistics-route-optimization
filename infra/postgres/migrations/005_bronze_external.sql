-- 005 · Bronze external signals: traffic, weather and fuel prices
--
-- Parsed rows of the open data feeds. The payload of every poll is stored as it arrived in the
-- RustFS bronze bucket, and each row keeps its key in raw_object_key.

-- Street sections of the Open Data BCN traffic feeds (transit_relacio_trams.csv), loaded once.
CREATE TABLE bronze.traffic_sections (
    section_id   integer PRIMARY KEY,
    description  text NOT NULL,
    coordinates  text NOT NULL,
    source       text NOT NULL REFERENCES ops.data_sources,
    ingested_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.traffic_sections IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN bronze.traffic_sections.coordinates IS 'Section polyline as published: "lon,lat,lon,lat,...".';

-- Two feeds share the table. trams gives a state from 0 (no data) to 6 (closed) per section;
-- itineraris gives travel times per itinerary. raw_line keeps the '#'-delimited line as published,
-- so fields that are not parsed yet are never lost.
CREATE TABLE bronze.traffic_state (
    feed                    text NOT NULL CHECK (feed IN ('trams', 'itineraris')),
    section_id              integer NOT NULL,
    state_current           smallint CHECK (state_current BETWEEN 0 AND 6),
    state_forecast          smallint CHECK (state_forecast BETWEEN 0 AND 6),
    travel_time_s           integer,
    travel_time_forecast_s  integer,
    raw_line                text NOT NULL,
    source                  text NOT NULL REFERENCES ops.data_sources,
    event_time              timestamptz NOT NULL,
    ingested_at             timestamptz NOT NULL DEFAULT now(),
    raw_object_key          text,
    PRIMARY KEY (feed, section_id, event_time),
    CHECK (feed <> 'trams' OR state_current IS NOT NULL)
);
COMMENT ON TABLE bronze.traffic_state IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN bronze.traffic_state.state_forecast IS 'trams: expected state in 15 minutes.';
COMMENT ON COLUMN bronze.traffic_state.travel_time_s IS 'itineraris: tempsActual, current travel time.';
COMMENT ON COLUMN bronze.traffic_state.travel_time_forecast_s IS 'itineraris: tempsPrevist, forecast travel time.';
COMMENT ON COLUMN bronze.traffic_state.event_time IS 'Timestamp in the feed (published in Europe/Madrid local time, stored as UTC).';
SELECT create_hypertable('bronze.traffic_state', by_range('event_time', INTERVAL '1 day'));
ALTER TABLE bronze.traffic_state SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'feed, section_id',
    timescaledb.orderby = 'event_time DESC'
);
CALL add_columnstore_policy('bronze.traffic_state', after => INTERVAL '1 day');
SELECT add_retention_policy('bronze.traffic_state', drop_after => INTERVAL '90 days');

-- Current conditions from Open-Meteo at the hub and at every zone centroid, one row per poll.
CREATE TABLE bronze.weather (
    location_id            text NOT NULL,
    lat                    double precision NOT NULL CHECK (lat BETWEEN 40.5 AND 42.9),
    lon                    double precision NOT NULL CHECK (lon BETWEEN 0.1 AND 3.4),
    temperature_c          real,
    relative_humidity_pct  real CHECK (relative_humidity_pct BETWEEN 0 AND 100),
    precipitation_mm       real CHECK (precipitation_mm >= 0),
    rain_mm                real CHECK (rain_mm >= 0),
    weather_code           smallint CHECK (weather_code BETWEEN 0 AND 99),
    cloud_cover_pct        real CHECK (cloud_cover_pct BETWEEN 0 AND 100),
    wind_speed_kmh         real CHECK (wind_speed_kmh >= 0),
    wind_gusts_kmh         real CHECK (wind_gusts_kmh >= 0),
    is_day                 boolean,
    source                 text NOT NULL REFERENCES ops.data_sources,
    event_time             timestamptz NOT NULL,
    ingested_at            timestamptz NOT NULL DEFAULT now(),
    raw_object_key         text,
    PRIMARY KEY (location_id, event_time)
);
COMMENT ON TABLE bronze.weather IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN bronze.weather.location_id IS 'hub id or zone id the coordinates belong to.';
COMMENT ON COLUMN bronze.weather.weather_code IS 'WMO weather interpretation code.';
COMMENT ON COLUMN bronze.weather.event_time IS 'Time of the current conditions in the Open-Meteo response.';

-- Prices per service station and product. MINETUR publishes every product in every station;
-- product keeps its name without the "Precio " prefix (Gasoleo A, Gas Natural Comprimido, Adblue).
CREATE TABLE bronze.fuel_prices (
    station_id      integer NOT NULL,
    product         text NOT NULL,
    price_eur       numeric(6, 3) NOT NULL CHECK (price_eur > 0),
    station_brand   text,
    municipality    text,
    lat             double precision CHECK (lat BETWEEN 40.5 AND 42.9),
    lon             double precision CHECK (lon BETWEEN 0.1 AND 3.4),
    source          text NOT NULL REFERENCES ops.data_sources,
    event_time      timestamptz NOT NULL,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    raw_object_key  text,
    PRIMARY KEY (station_id, product, event_time)
);
COMMENT ON TABLE bronze.fuel_prices IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN bronze.fuel_prices.station_id IS 'IDEESS of the station in the MINETUR registry.';
COMMENT ON COLUMN bronze.fuel_prices.event_time IS 'Fecha of the MINETUR response: the time the prices were in force.';
SELECT create_hypertable('bronze.fuel_prices', by_range('event_time', INTERVAL '7 days'));
SELECT add_retention_policy('bronze.fuel_prices', drop_after => INTERVAL '365 days');
