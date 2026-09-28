-- 010 · raw_object_key on the tables loaded from the generator's Parquet files
--
-- Rows that come from a file keep raw_object_key, the key of that file in the RustFS bronze
-- bucket (data-model.md). The generator loads bronze.vehicles, bronze.drivers and bronze.shippers
-- from the fleet register, the driver roster and the shipper list, which it writes to the bucket
-- as Parquet files, but migration 009 gave these three tables no raw_object_key.
--
-- The loader writes the three files at fixed keys, so rows loaded before this migration get the
-- key of the file they came from. This fills a new column for rows that already exist; it changes
-- no loaded value.

-- 1 · The column --------------------------------------------------------------------------------

ALTER TABLE bronze.vehicles ADD COLUMN raw_object_key text;
ALTER TABLE bronze.drivers ADD COLUMN raw_object_key text;
ALTER TABLE bronze.shippers ADD COLUMN raw_object_key text;

COMMENT ON TABLE bronze.vehicles IS '{"owner": "fleet", "schema_version": 4}';
COMMENT ON TABLE bronze.drivers IS '{"owner": "operations", "schema_version": 4}';
COMMENT ON TABLE bronze.shippers IS '{"owner": "operations", "schema_version": 2}';
COMMENT ON COLUMN bronze.vehicles.raw_object_key IS 'Key of the fleet register''s Parquet file in the RustFS bronze bucket.';
COMMENT ON COLUMN bronze.drivers.raw_object_key IS 'Key of the driver roster''s Parquet file in the RustFS bronze bucket.';
COMMENT ON COLUMN bronze.shippers.raw_object_key IS 'Key of the shipper list''s Parquet file in the RustFS bronze bucket.';

-- 2 · Rows loaded before this migration -----------------------------------------------------------

UPDATE bronze.vehicles SET raw_object_key = 'reference/generator/fleet/vehicles.parquet'
WHERE source = 'generator/fleet' AND raw_object_key IS NULL;
UPDATE bronze.drivers SET raw_object_key = 'reference/generator/drivers/drivers.parquet'
WHERE source = 'generator/drivers' AND raw_object_key IS NULL;
UPDATE bronze.shippers SET raw_object_key = 'reference/generator/demand-model/shippers.parquet'
WHERE source = 'generator/demand-model' AND raw_object_key IS NULL;
