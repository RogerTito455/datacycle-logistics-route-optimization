-- 009 · Generator reference data: shippers, fleet and roster fields, street names, town addresses
--
-- Issue #3 loads the AI-generated fleet register (prompt 002), driver roster (prompt 003) and
-- demand model (prompt 004), and the real postal addresses the order generator draws from.
--
-- 1. bronze.shippers: the shippers of the demand model.
-- 2. bronze.vehicles and bronze.drivers: the fields the fleet register and the driver roster
--    publish that version 2 of the tables had no column for.
-- 3. bronze.streets: the Open Data BCN street register. taula-direle identifies the street of an
--    address by its code only; the register gives the name.
-- 4. bronze.icgc_addresses: the five neighbouring municipalities are not in taula-direle, so their
--    addresses come from the ICGC simplified address register of Catalonia.
-- 5. bronze.orders: the shipper, delivery wave and kind of time window of each order.
-- 6. The data sources of the above, registered or updated.
--
-- Bronze stays raw: no CHECK constraints (migration 007).

-- 1 · Shippers --------------------------------------------------------------------------------

CREATE TABLE bronze.shippers (
    shipper_id                text PRIMARY KEY,
    name                      text,
    segment                   text,
    description               text,
    share_of_daily_parcels    numeric(5, 4),
    parcel_mix_small          numeric(4, 3),
    parcel_mix_medium         numeric(4, 3),
    parcel_mix_large          numeric(4, 3),
    same_day_share            numeric(4, 3),
    recipient_type            text,
    business_share            numeric(4, 3),
    arrives_at_hub            text,
    business_recipient_zones  text[],
    source                    text NOT NULL REFERENCES ops.data_sources,
    ingested_at               timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE bronze.shippers IS '{"owner": "operations", "schema_version": 1}';
COMMENT ON COLUMN bronze.shippers.share_of_daily_parcels IS 'Share of the parcels of a mean weekday, as the demand model (prompt 004) gives it.';
COMMENT ON COLUMN bronze.shippers.business_share IS 'Share of the shipper''s parcels that go to business recipients: 0 for consumer shippers, 1 for business shippers.';
COMMENT ON COLUMN bronze.shippers.arrives_at_hub IS 'overnight linehaul, morning injection or midday injection. Only midday-injection shippers sell same-day delivery.';
COMMENT ON COLUMN bronze.shippers.business_recipient_zones IS 'Zones where the shipper''s business recipients concentrate.';

-- 2 · Fleet register and driver roster fields -------------------------------------------------

ALTER TABLE bronze.vehicles
    ADD COLUMN registration_year            smallint,
    ADD COLUMN odometer_km                  integer,
    ADD COLUMN battery_state_of_health_pct  numeric(4, 1),
    ADD COLUMN runs_afternoon_wave          boolean,
    ADD COLUMN telematics_unit_id           text,
    ADD COLUMN maintenance_note             text;
COMMENT ON TABLE bronze.vehicles IS '{"owner": "fleet", "schema_version": 3}';
COMMENT ON COLUMN bronze.vehicles.commissioned_on IS 'Not in the fleet register, which gives the registration year only.';
COMMENT ON COLUMN bronze.vehicles.odometer_km IS 'Reading in the fleet register when it was generated. Live readings are in bronze.vehicle_telemetry.';
COMMENT ON COLUMN bronze.vehicles.battery_state_of_health_pct IS 'Electric vehicles only; NULL for the others.';
COMMENT ON COLUMN bronze.vehicles.runs_afternoon_wave IS 'The vehicle also runs an afternoon-evening route after a midday recharge or refuel.';
COMMENT ON COLUMN bronze.vehicles.maintenance_note IS 'Free text from the fleet register: a service due soon or a known minor defect.';

ALTER TABLE bronze.drivers
    ADD COLUMN first_name                    text,
    ADD COLUMN last_names                    text,
    ADD COLUMN roster_group                  text,
    ADD COLUMN contract                      text,
    ADD COLUMN hired_year                    smallint,
    ADD COLUMN years_driving_professionally  smallint,
    ADD COLUMN home_municipality             text,
    ADD COLUMN languages                     text[],
    ADD COLUMN zone_knowledge                text[],
    ADD COLUMN qualified_vehicle_types       text[],
    ADD COLUMN planning_note                 text;
COMMENT ON TABLE bronze.drivers IS '{"owner": "operations", "schema_version": 3}';
COMMENT ON COLUMN bronze.drivers.shift_id IS 'NULL for the relief pool, which covers either shift week by week.';
COMMENT ON COLUMN bronze.drivers.home_zone_id IS 'Not in the driver roster, which gives the home municipality and the zones each driver knows.';
COMMENT ON COLUMN bronze.drivers.hired_on IS 'Not in the driver roster, which gives the hiring year only.';
COMMENT ON COLUMN bronze.drivers.first_name IS 'Fictional, AI-generated, as are last_names and home_municipality. Personal data in a real company: bronze is not readable by Grafana.';
COMMENT ON COLUMN bronze.drivers.roster_group IS 'shift as published in the roster: Morning wave, Afternoon-evening wave or Relief pool.';
COMMENT ON COLUMN bronze.drivers.zone_knowledge IS 'Zones the driver knows well, one to four.';
COMMENT ON COLUMN bronze.drivers.planning_note IS 'Free text from the roster that affects planning, without health details.';

-- 3 · Street names ----------------------------------------------------------------------------

-- Open Data BCN carrerer, one row per street. Columns keep the published values.
CREATE TABLE bronze.streets (
    street_code      text PRIMARY KEY,
    ine_street_code  text,
    street_type      text,
    short_name       text,
    official_name    text,
    number_min       text,
    number_max       text,
    source           text NOT NULL REFERENCES ops.data_sources,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    raw_object_key   text
);
COMMENT ON TABLE bronze.streets IS '{"owner": "operations", "schema_version": 1}';
COMMENT ON COLUMN bronze.streets.street_code IS 'codi_via: the street code that bronze.addresses.street_code holds.';
COMMENT ON COLUMN bronze.streets.ine_street_code IS 'codi_carrer_ine: street code of the Spanish National Institute of Statistics.';
COMMENT ON COLUMN bronze.streets.official_name IS 'nom_oficial: full official name, such as Carrer dels Almogàvers.';
COMMENT ON COLUMN bronze.streets.number_min IS 'nre_min: lowest street number, zero-padded as published. number_max is the highest.';

-- 4 · Addresses of the neighbouring municipalities --------------------------------------------

-- ICGC Adreces simplificat, street addresses (the adrecavia file) of L'Hospitalet de Llobregat,
-- El Prat de Llobregat, Cornellà de Llobregat, Esplugues de Llobregat and Sant Boi de Llobregat.
-- Text columns keep the published values, including a single space for an empty field. The file
-- has more columns (comarca, province, population unit, area); it is kept whole in the RustFS
-- bronze bucket under raw_object_key.
CREATE TABLE bronze.icgc_addresses (
    address_id          text PRIMARY KEY,
    municipality_code   text,
    municipality        text,
    street_id           text,
    street_type         text,
    street_article      text,
    street_name         text,
    address_type        text,
    number_from         text,
    number_from_suffix  text,
    number_to           text,
    number_to_suffix    text,
    block               text,
    postcode            text,
    x_etrs89            double precision,
    y_etrs89            double precision,
    lon                 double precision,
    lat                 double precision,
    source              text NOT NULL REFERENCES ops.data_sources,
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    raw_object_key      text
);
COMMENT ON TABLE bronze.icgc_addresses IS '{"owner": "operations", "schema_version": 1}';
COMMENT ON COLUMN bronze.icgc_addresses.address_id IS 'idadrvia: identifier of the address in the ICGC register. bronze.orders.address_ref holds it for orders outside Barcelona.';
COMMENT ON COLUMN bronze.icgc_addresses.municipality_code IS 'codmuni: six-digit INE municipality code, such as 081017 for L''Hospitalet de Llobregat.';
COMMENT ON COLUMN bronze.icgc_addresses.street_article IS 'nexevia: the particle between street type and name (de, del, de l''), as published.';
COMMENT ON COLUMN bronze.icgc_addresses.address_type IS 'tipusadr: vianum for a street and number, viabloc for a block.';
COMMENT ON COLUMN bronze.icgc_addresses.number_from IS 'numini: street number, or the first number of a range. number_to (numfi) is 0 when the address is a single number.';
COMMENT ON COLUMN bronze.icgc_addresses.x_etrs89 IS 'coor_utmx: UTM zone 31N easting, ETRS89 (EPSG:25831). y_etrs89 is coor_utmy, the northing.';
COMMENT ON COLUMN bronze.icgc_addresses.lon IS 'Not published: converted by the loader from x_etrs89 and y_etrs89 to WGS84 (EPSG:4326) with PROJ, rounded to 7 decimals like taula-direle. lat likewise.';

-- 5 · Orders: shipper, wave and window --------------------------------------------------------

ALTER TABLE bronze.orders
    ADD COLUMN shipper_id   text,
    ADD COLUMN wave         text,
    ADD COLUMN window_type  text;
COMMENT ON TABLE bronze.orders IS '{"owner": "operations", "schema_version": 3}';
COMMENT ON COLUMN bronze.orders.shipper_id IS 'Shipper in bronze.shippers. shipper_name repeats its name.';
COMMENT ON COLUMN bronze.orders.wave IS 'Delivery wave: morning (08:00-14:00) or afternoon (15:00-21:00).';
COMMENT ON COLUMN bronze.orders.window_type IS 'slot: the consumer chose a 120-minute slot; wave: the consumer accepts any time in the wave and the window spans it, until route planning sets the 120-minute promise; opening_hours: a business recipient, with a 120-minute window inside its opening hours.';
COMMENT ON COLUMN bronze.orders.address_ref IS 'Destination address: bronze.addresses.address_ref (Open Data BCN taula-direle) in Barcelona, bronze.icgc_addresses.address_id (ICGC) in the neighbouring municipalities.';
COMMENT ON COLUMN bronze.orders.origin_address IS 'Where the parcel comes from. The demand model gives no shipper addresses, so the generator writes the shipper and how its parcels reach the hub.';

-- 6 · Data sources ----------------------------------------------------------------------------

INSERT INTO ops.data_sources (source_id, kind, provider, description, license, url) VALUES
    ('generator/demand-model', 'ai-generated', 'Llobregat Express generator',
     'Shippers of the demand model (services/generator/seed/demand.json, prompt 004)',
     'MIT, this repository', 'prompts/004-demand-model.md'),
    ('opendata-bcn/carrerer', 'real', 'Ajuntament de Barcelona, Open Data BCN',
     'Official names of the streets of Barcelona, joined to taula-direle by street code', 'CC BY 4.0',
     'https://opendata-ajuntament.barcelona.cat/data/dataset/carrerer'),
    ('icgc/adreces-simplificat', 'real', 'Institut Cartogràfic i Geològic de Catalunya (ICGC)',
     'Postal addresses of L''Hospitalet de Llobregat, El Prat de Llobregat, Cornellà de Llobregat, '
     'Esplugues de Llobregat and Sant Boi de Llobregat, used by the order generator', 'CC BY 4.0',
     'https://www.icgc.cat/ca/Geoinformacio-i-mapes/Dades-i-productes/Geoinformacio-cartografica/Adreces-simplificat');

UPDATE ops.data_sources
SET description = 'Fleet register, one row per vehicle (services/generator/seed/fleet.json, prompt 002)',
    url = 'prompts/002-fleet-register.md'
WHERE source_id = 'generator/fleet';
UPDATE ops.data_sources
SET description = 'Driver roster, one row per fictional driver (services/generator/seed/drivers.json, prompt 003)',
    url = 'prompts/003-driver-roster.md'
WHERE source_id = 'generator/drivers';
UPDATE ops.data_sources
SET description = 'Orders drawn from the demand model (prompt 004) at real addresses from Open Data BCN and ICGC, '
                  'one Parquet file per service date, with free-text delivery notes',
    url = 'services/generator/README.md'
WHERE source_id = 'generator/orders';
