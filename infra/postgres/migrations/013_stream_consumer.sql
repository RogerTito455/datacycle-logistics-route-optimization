-- 013 · The stream consumer (issue #8)
--
-- The consumer (services/consumer) writes the simulator's three topics into bronze: gps.pings into
-- bronze.gps_pings, vehicle.telemetry into bronze.vehicle_telemetry and delivery.events into
-- bronze.delivery_events, in batches, once per key.
--
-- 1. schema_version on the three tables: the version of the message format each row was parsed
--    from, as the message carried it. The table's own version stays in its comment.
-- 2. extra_fields on gps_pings and delivery_events: the fields of a message the table has no column
--    for, as they arrived, so a field a producer adds is kept, not dropped. Telemetry keeps them in
--    readings, which already holds the sensors of each vehicle type.
-- 3. ops.dead_letters: every message the consumer cannot store as a row, with its raw bytes, topic,
--    partition, offset and the error. A bad message is set aside; it never blocks its partition.
-- 4. ops.consumer_lag: per topic and partition, every 10 seconds, the messages not written yet and
--    the newest event_time written, for the freshness panels of Grafana.
-- 5. The data sources of both, and grafana_reader reads the dead letters without their payload.
--
-- Bronze stays raw: no CHECK constraints (migration 007).

-- 5 · Data sources, first: the new tables point to them --------------------------------------

INSERT INTO ops.data_sources (source_id, kind, provider, description, license, url) VALUES
    ('consumer/dead_letters', 'platform', 'Llobregat Express platform',
     'Stream messages the consumer could not store as bronze rows: raw bytes, topic, partition, offset and the error',
     'MIT, this repository', 'services/consumer/README.md'),
    ('consumer/lag', 'platform', 'Llobregat Express platform',
     'Lag of the stream consumer and the newest event_time it wrote, per topic and partition, every 10 seconds',
     'MIT, this repository', 'services/consumer/README.md');

-- 1 and 2 · The message's schema version and its fields without a column ---------------------

ALTER TABLE bronze.gps_pings ADD COLUMN schema_version smallint;
ALTER TABLE bronze.gps_pings ADD COLUMN extra_fields jsonb;
ALTER TABLE bronze.vehicle_telemetry ADD COLUMN schema_version smallint;
ALTER TABLE bronze.delivery_events ADD COLUMN schema_version smallint;
ALTER TABLE bronze.delivery_events ADD COLUMN extra_fields jsonb;

COMMENT ON COLUMN bronze.gps_pings.schema_version IS 'Version of the gps.pings message format the row was parsed from, as the message carried it. The table''s own version is in its comment.';
COMMENT ON COLUMN bronze.gps_pings.extra_fields IS 'Fields of the message this table has no column for, as they arrived. NULL when there were none.';
COMMENT ON COLUMN bronze.vehicle_telemetry.schema_version IS 'Version of the vehicle.telemetry message format the row was parsed from, as the message carried it. The table''s own version is in its comment.';
COMMENT ON COLUMN bronze.vehicle_telemetry.readings IS 'Every field of the message without a column of its own, as it arrived: the sensors only some vehicle types have (charging, tyre_pressure_bar, engine_rpm, adblue_level_pct, cng_tank_pressure_bar) and any field a producer adds. {} when there were none.';
COMMENT ON COLUMN bronze.delivery_events.schema_version IS 'Version of the delivery.events message format the row was parsed from, as the message carried it. The table''s own version is in its comment.';
COMMENT ON COLUMN bronze.delivery_events.extra_fields IS 'Fields of the message this table has no column for, as they arrived. NULL when there were none.';
COMMENT ON COLUMN bronze.delivery_events.status IS 'As the handheld sent it: out_for_delivery, arrived, delivered or failed.';

COMMENT ON TABLE bronze.gps_pings IS '{"owner": "fleet", "schema_version": 3}';
COMMENT ON TABLE bronze.vehicle_telemetry IS '{"owner": "fleet", "schema_version": 3}';
COMMENT ON TABLE bronze.delivery_events IS '{"owner": "operations", "schema_version": 3}';

-- 3 · Dead letters -----------------------------------------------------------------------------

-- A platform ledger, like the migration ledger: it records messages, not events of the business, so
-- it has no event_time. kafka_timestamp is when the producer sent the message.
CREATE TABLE ops.dead_letters (
    topic            text NOT NULL,
    kafka_partition  integer NOT NULL,
    kafka_offset     bigint NOT NULL,
    kafka_timestamp  timestamptz,
    message_key      bytea,
    payload          bytea,
    reason           text NOT NULL,
    error            text NOT NULL,
    source           text NOT NULL DEFAULT 'consumer/dead_letters' REFERENCES ops.data_sources,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (topic, kafka_partition, kafka_offset)
);
COMMENT ON TABLE ops.dead_letters IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN ops.dead_letters.kafka_offset IS 'With topic and kafka_partition, the message''s place in Redpanda: the key, so a replayed message is recorded once.';
COMMENT ON COLUMN ops.dead_letters.kafka_timestamp IS 'The message''s timestamp in Redpanda: when the producer sent it.';
COMMENT ON COLUMN ops.dead_letters.payload IS 'The message value exactly as it arrived, bytes and all; NULL for a message without a value. encode(payload, ''escape'') reads it. Raw data: not readable by grafana_reader.';
COMMENT ON COLUMN ops.dead_letters.message_key IS 'The message key as it arrived (the vehicle id for the simulator''s topics). Not readable by grafana_reader.';
COMMENT ON COLUMN ops.dead_letters.reason IS 'Short code: empty_message, invalid_json, not_an_object, missing_field, unsupported_schema_version, invalid_field, unknown_source or rejected_by_database.';
COMMENT ON COLUMN ops.dead_letters.error IS 'What was wrong, in words.';
CREATE INDEX ON ops.dead_letters (ingested_at);

-- 4 · Consumer lag -----------------------------------------------------------------------------

CREATE TABLE ops.consumer_lag (
    event_time        timestamptz NOT NULL,
    consumer_group    text NOT NULL,
    topic             text NOT NULL,
    kafka_partition   integer NOT NULL,
    committed_offset  bigint,
    end_offset        bigint NOT NULL,
    lag               bigint NOT NULL,
    last_event_time   timestamptz,
    last_ingested_at  timestamptz,
    source            text NOT NULL DEFAULT 'consumer/lag' REFERENCES ops.data_sources,
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_group, topic, kafka_partition, event_time)
);
COMMENT ON TABLE ops.consumer_lag IS '{"owner": "platform", "schema_version": 1}';
COMMENT ON COLUMN ops.consumer_lag.event_time IS 'When the lag was measured.';
COMMENT ON COLUMN ops.consumer_lag.committed_offset IS 'The next offset the group reads: every message before it is in bronze or in ops.dead_letters. NULL before the group''s first commit.';
COMMENT ON COLUMN ops.consumer_lag.end_offset IS 'The partition''s high watermark: the offset its next message will get.';
COMMENT ON COLUMN ops.consumer_lag.lag IS 'Messages in the partition not written yet: end_offset minus committed_offset, or minus the oldest offset kept before the first commit.';
COMMENT ON COLUMN ops.consumer_lag.last_event_time IS 'The newest event_time written from the partition; now() minus it is how old the freshest data is.';
COMMENT ON COLUMN ops.consumer_lag.last_ingested_at IS 'When a row from the partition was last written.';
SELECT create_hypertable('ops.consumer_lag', by_range('event_time', INTERVAL '1 day'));
-- A measurement of the pipeline, not raw data: kept 30 days, enough for any dashboard window.
SELECT add_retention_policy('ops.consumer_lag', drop_after => INTERVAL '30 days');

-- 5 · Access -----------------------------------------------------------------------------------

-- Tables in ops are readable by grafana_reader (migration 006, default privileges). A dead letter
-- holds a raw message, which in a real company carries personal data like bronze, so the dashboards
-- read what went wrong and where, not the bytes.
REVOKE ALL ON ops.dead_letters FROM grafana_reader;
GRANT SELECT (topic, kafka_partition, kafka_offset, kafka_timestamp, reason, error, source, ingested_at)
    ON ops.dead_letters TO grafana_reader;
