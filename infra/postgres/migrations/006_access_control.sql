-- 006 · Access control
--
-- grafana_reader, the role the dashboards use, reads gold and ops and nothing else. Bronze holds
-- raw and personal data and silver is an intermediate layer; neither is exposed.
-- The role is created with its password by infra/postgres/init/01-platform.sh.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        RAISE EXCEPTION 'role grafana_reader is missing; it is created by infra/postgres/init/01-platform.sh';
    END IF;
END
$$;

REVOKE ALL ON SCHEMA bronze, silver FROM PUBLIC, grafana_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA bronze, silver FROM PUBLIC, grafana_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA bronze, silver FROM PUBLIC, grafana_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA bronze, silver FROM PUBLIC, grafana_reader;

GRANT USAGE ON SCHEMA gold, ops TO grafana_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA gold, ops FROM grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA gold, ops TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT ON TABLES TO grafana_reader;
