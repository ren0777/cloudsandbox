-- Two roles (PLAN §6): the OWNER runs migrations / maintenance; the APP role serves requests and has
-- no UPDATE/DELETE/TRUNCATE on append-only tables (granted in migration 0001).
CREATE ROLE cloudlabs_owner LOGIN PASSWORD 'owner';
CREATE ROLE cloudlabs_app LOGIN PASSWORD 'app';
CREATE DATABASE cloudlabs OWNER cloudlabs_owner;
CREATE DATABASE cloudlabs_test OWNER cloudlabs_owner;
\connect cloudlabs
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO cloudlabs_owner;
GRANT USAGE ON SCHEMA public TO cloudlabs_app;
\connect cloudlabs_test
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO cloudlabs_owner;
GRANT USAGE ON SCHEMA public TO cloudlabs_app;
