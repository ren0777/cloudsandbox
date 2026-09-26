#!/bin/bash
# Runs once, on the first start of an EMPTY Postgres volume (after 00-init.sql created the roles and databases):
# replaces the development role passwords with the production secrets.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$CLOUDLABS_OWNER_PASSWORD" -v app_pw="$CLOUDLABS_APP_PASSWORD" <<'SQL'
ALTER ROLE cloudlabs_owner PASSWORD :'owner_pw';
ALTER ROLE cloudlabs_app PASSWORD :'app_pw';
DROP DATABASE IF EXISTS cloudlabs_test;
SQL
