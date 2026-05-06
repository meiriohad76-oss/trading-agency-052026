DO
$$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'agency_app') THEN
    CREATE ROLE agency_app LOGIN PASSWORD 'agency';
  END IF;
END
$$;

SELECT 'CREATE DATABASE agency OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'agency')\gexec

\connect agency

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS agency AUTHORIZATION agency_app;
GRANT CONNECT ON DATABASE agency TO agency_app;
GRANT USAGE, CREATE ON SCHEMA agency TO agency_app;
ALTER ROLE agency_app IN DATABASE agency SET search_path = agency;
