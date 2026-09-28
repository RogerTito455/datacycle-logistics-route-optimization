#!/usr/bin/env bash
# Runs once, the first time the TimescaleDB volume is created: extension, schemas, roles and the
# Dagster database. Tables are created by the versioned migrations in infra/postgres/migrations,
# which the db-migrate service applies on every start, so they also reach an existing volume.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS ops;

COMMENT ON SCHEMA bronze IS 'Raw data exactly as it arrived. Write-once.';
COMMENT ON SCHEMA silver IS 'Cleaned and typed data, built by dbt staging models.';
COMMENT ON SCHEMA gold   IS 'Business marts and KPIs. The only layer Grafana reads for analysis.';
COMMENT ON SCHEMA ops    IS 'Platform bookkeeping: health checks, pipeline runs.';

-- Platform health, written by the Dagster platform_health asset.
CREATE TABLE IF NOT EXISTS ops.service_health (
    event_time   timestamptz NOT NULL,
    service      text        NOT NULL,
    ok           boolean     NOT NULL,
    detail       text,
    source       text        NOT NULL DEFAULT 'dagster/platform_health',
    ingested_at  timestamptz NOT NULL DEFAULT now()
);
SELECT create_hypertable('ops.service_health', by_range('event_time', INTERVAL '1 day'), if_not_exists => TRUE);
COMMENT ON TABLE ops.service_health IS '{"owner": "platform", "schema_version": 1}';

-- Read-only role for Grafana.
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader') THEN
    CREATE ROLE grafana_reader LOGIN PASSWORD '${GRAFANA_DB_PASSWORD}';
  END IF;
END
\$\$;
GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO grafana_reader;
GRANT USAGE ON SCHEMA gold, ops TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA gold, ops TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops  GRANT SELECT ON TABLES TO grafana_reader;

-- Separate database for Dagster's own run and event storage.
CREATE DATABASE dagster;
EOSQL
