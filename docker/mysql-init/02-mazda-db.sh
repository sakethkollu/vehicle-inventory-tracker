#!/bin/bash
set -euo pipefail

MAZDA_DB="${MAZDA_DATABASE:-mazda_inventory}"

mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" <<-SQL
CREATE DATABASE IF NOT EXISTS \`${MAZDA_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON \`${MAZDA_DB}\`.* TO '${MYSQL_USER}'@'%';
FLUSH PRIVILEGES;
SQL

mysql -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" "${MAZDA_DB}" < /docker-entrypoint-initdb.d/01-schema.sql
