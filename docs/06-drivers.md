# DB Backup Orchestrator - Drivers

← [Back to index](../README.md)

## Driver Implementations

### PostgreSQL

All PostgreSQL commands receive credentials via environment variables (`-e PGPASSWORD`, `-e PGUSER`) passed to the ephemeral container. The orchestrator reads `DB_USER` / `DB_PASSWORD` from its own environment and forwards them as the appropriate engine-specific env vars.

#### Globals dump
```bash
docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  postgres:16 \
  pg_dumpall \
    -h db.prod.example.com -p 5432 -U "$DB_USER" \
    --globals-only --no-tablespaces
```

Output → `globals.sql`

#### Listing databases (for --full mode)
```bash
docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  postgres:16 \
  psql -h HOST -p PORT -U "$DB_USER" -d postgres -t -A -c \
    "SELECT datname FROM pg_database
     WHERE datistemplate = false
     AND datname NOT IN ('postgres');"
```

#### Listing schemas within a database
```bash
docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  postgres:16 \
  psql -h HOST -p PORT -U "$DB_USER" -d app_production -t -A -c \
    "SELECT schema_name FROM information_schema.schemata
     WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast');"
```

#### Schema dump (one per schema per database)
```bash
docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  postgres:16 \
  pg_dump \
    -h db.prod.example.com -p 5432 -U "$DB_USER" \
    -d app_production \
    -n sales \
    --no-tablespaces
```

Output → `app_production/schema.sales.sql`

#### Table dump
```bash
docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  postgres:16 \
  pg_dump \
    -h db.prod.example.com -p 5432 -U "$DB_USER" \
    -d app_production \
    -t sales.orders
```

Output → `app_production/table.sales.orders.sql`

#### Connectivity check
```bash
docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  postgres:16 \
  psql -h HOST -p PORT -U "$DB_USER" -d DB -c "SELECT 1;"
```
Executed with `subprocess.run(timeout=connect_timeout)`. Failure → exit 1.

---

### MySQL

All MySQL commands receive credentials via environment variables. `MYSQL_PWD` is used for the password (avoids the `-pPASS` warning in logs). The orchestrator maps `DB_USER` → `-u` arg and `DB_PASSWORD` → `MYSQL_PWD` env var.

#### Globals dump (users + grants)
```bash
# For each user: CREATE USER with auth plugin + password hash + SHOW GRANTS
docker run --rm --network host \
  -e MYSQL_PWD="$DB_PASSWORD" \
  mysql:8.0 \
  bash -c '
    USERS=$(mysql -h HOST -P PORT -u "$DB_USER" -N -B -e \
      "SELECT DISTINCT CONCAT(user, \"@\", host) FROM mysql.user \
       WHERE user NOT IN (\"mysql.sys\",\"mysql.session\",\"mysql.infoschema\",\"root\",\"debian-sys-maint\");" 2>/dev/null)

    echo "$USERS" | while read userhost; do
      u=$(echo "$userhost" | cut -d@ -f1)
      h=$(echo "$userhost" | cut -d@ -f2)

      # Get auth plugin and password hash directly from mysql.user
      AUTH_INFO=$(mysql -h HOST -P PORT -u "$DB_USER" -N -B -e \
        "SELECT plugin, authentication_string FROM mysql.user \
         WHERE user=\"${u}\" AND host=\"${h}\";" 2>/dev/null)
      PLUGIN=$(echo "$AUTH_INFO" | cut -f1)
      HASH=$(echo "$AUTH_INFO" | cut -f2)

      # CREATE USER with password hash (preserves original password)
      if [ -n "$HASH" ] && [ -n "$PLUGIN" ]; then
        echo "CREATE USER IF NOT EXISTS \"${u}\"@\"${h}\" IDENTIFIED WITH \"${PLUGIN}\" AS \"${HASH}\";"
      else
        echo "CREATE USER IF NOT EXISTS \"${u}\"@\"${h}\";"
      fi

      # GRANT statements
      mysql -h HOST -P PORT -u "$DB_USER" -N -B -e "SHOW GRANTS FOR \"${u}\"@\"${h}\";" 2>/dev/null | sed "s/$/;/"
      echo ""
    done
  '
```

> Reads the auth plugin and password hash directly from `mysql.user`, then constructs `CREATE USER ... IDENTIFIED WITH 'plugin' AS 'hash'`. This preserves original passwords and is compatible across MySQL 5.7, 8.0, and 8.4 when source and target use the same auth plugin. If plugins differ, the restore will error - reset passwords manually on the target.

Output → `globals.sql`

#### Listing databases (for --full mode)

In MySQL/MariaDB, databases and schemas are the same concept. This query discovers all user databases:

```bash
docker run --rm --network host \
  -e MYSQL_PWD="$DB_PASSWORD" \
  mysql:8.0 \
  mysql -h HOST -P PORT -u "$DB_USER" \
    -N -e "SELECT schema_name FROM information_schema.schemata
    WHERE schema_name NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');"
```

#### Database dump (one per database)
```bash
docker run --rm --network host \
  -e MYSQL_PWD="$DB_PASSWORD" \
  mysql:8.0 \
  mysqldump \
    -h HOST -P PORT -u "$DB_USER" \
    --single-transaction --routines --triggers --events \
    --databases sales
```

Output → `sales/full.sql`

#### Table dump
```bash
docker run --rm --network host \
  -e MYSQL_PWD="$DB_PASSWORD" \
  mysql:8.0 \
  mysqldump \
    -h HOST -P PORT -u "$DB_USER" \
    --single-transaction \
    sales orders
```

Output → `sales/table.orders.sql`

#### Connectivity check
```bash
docker run --rm --network host \
  -e MYSQL_PWD="$DB_PASSWORD" \
  mysql:8.0 \
  mysql -h HOST -P PORT -u "$DB_USER" \
    -e "SELECT 1;"
```
Executed with `subprocess.run(timeout=connect_timeout)`. Failure → exit 1.

---

### MariaDB

Same as MySQL with these differences:

| Aspect | MySQL | MariaDB |
|---|---|---|
| Image | `mysql:{version}` | `mariadb:{version}` |
| Dump tool | `mysqldump` | `mariadb-dump` (v10.5+) or `mysqldump` (legacy) |
| Grant syntax | `SHOW GRANTS` | `SHOW GRANTS` (same) |
| System schemas to skip | `mysql, information_schema, performance_schema, sys` | Same + `mysql` internal tables may differ |

The script detects MariaDB version and uses the appropriate binary.
