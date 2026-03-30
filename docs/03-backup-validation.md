# DB Backup Orchestrator - Backup Validation Pipeline (B1-B7)

← [Back to index](../README.md)

## Backup Validation Pipeline

All validation runs **before any dump or manifest initialization**. A validation failure produces a clean exit 1 with no leftover directories. Each step has its own timeout to prevent the script from hanging indefinitely.

```
Step B1: Required args     ──→ Step B2: Driver registry  ──→ Step B3: Docker socket
  (offline, instant)            (offline, instant)             (local, 5s timeout)
                                                                      │
                                                                      ▼
Step B6: DB health check   ←── Step B5: DB connectivity  ←── Step B4: Image exists
  (remote, connect-timeout)     (remote, connect-timeout)      (network, 60s timeout)
         │
         ▼
     All passed → create output dir → write manifest → start dumps
```

### Step B1: Required arguments

**When:** Immediately on startup (arg parsing)
**Timeout:** None (instant, offline)

Validates that all required arguments are present - either via CLI or env var. Also validates:

- Exactly one mode is selected (`--full`, `--databases`, `--tables`, `--globals-only`)
- Exactly one mode is selected (`--full`, `--databases-only`, `--databases`, `--tables`, `--globals-only`)
- `--schemas` filter is only allowed with `--full` or `--databases` modes
- `--schemas` with MySQL/MariaDB driver → `[WARN]` and ignored
- `--tables` values match the expected format per driver: `db.schema.table` for PostgreSQL, `db.table` for MySQL/MariaDB
- Numeric args are positive integers (`--port`, `--timeout`, `--retries`, etc.)
- `--output-dir` path is absolute
- If `--encrypt` is set, `--encrypt-key` or `BACKUP_ENCRYPT_KEY` must be provided
- If `--encrypt-key` is set without `--encrypt`, warn and ignore

```
[ERROR] Fatal: Missing required argument '--host'. Provide via CLI or BACKUP_HOST env var.
[ERROR] Fatal: --encrypt requires --encrypt-key or BACKUP_ENCRYPT_KEY env var.
[ERROR] Fatal: Exactly one mode required. Got both '--full' and '--databases'.
[ERROR] Fatal: '--tables' values must be in 'db.schema.table' format for postgres. Got: 'sales.orders'
[WARN] --schemas is not applicable for driver 'mysql' (database = schema). Ignoring.
```

### Step B2: Driver registry

**When:** After arg parsing
**Timeout:** None (instant, offline)

The script maintains a hardcoded map of supported drivers:

```python
DRIVER_REGISTRY = {
    "postgres": {"image": "postgres", "default_port": 5432},
    "mysql":    {"image": "mysql",    "default_port": 3306},
    "mariadb":  {"image": "mariadb",  "default_port": 3306},
}
```

Validates:
- `--driver` is a known key in the registry
- If `--port` was not provided, auto-fills from the driver's default

```
[ERROR] Fatal: Unknown driver 'mssql'. Supported drivers: postgres, mysql, mariadb.
```

### Step B3: Docker socket

**When:** After driver validation
**Timeout:** 5 seconds

Checks that the Docker daemon is reachable:

```bash
docker info > /dev/null 2>&1
```

```
[ERROR] Fatal: Docker is not available. Ensure /var/run/docker.sock is mounted and Docker daemon is running.
```

### Step B4: Image exists

**When:** After Docker is confirmed available
**Timeout:** 60 seconds for pull

Two-phase check:

1. **Local cache** (fast path): `docker image inspect {image}:{version}` - if found, skip pull
2. **Remote pull** (slow path): `docker pull {image}:{version}` - if pull fails, exit 1

```
[INFO] Image postgres:16 found in local cache - skipping pull.
```
or
```
[INFO] Image postgres:16 not found locally - pulling...
[INFO] Image postgres:16 pulled successfully.
```
or
```
[ERROR] Fatal: Docker image 'postgres:99' not found. Verify --driver 'postgres' and --version '99' are correct.
```

### Step B5: DB host reachability

**When:** After image is available
**Timeout:** `--connect-timeout` (default 30s)

Before attempting a real DB connection, verify the host+port is reachable at the network level. This catches DNS failures, firewall blocks, and wrong ports quickly - without waiting for the DB client to time out with a cryptic error.

Uses the DB container to run a TCP check:

```bash
# PostgreSQL
docker run --rm --network host postgres:16 \
  pg_isready -h HOST -p PORT -t $CONNECT_TIMEOUT

# MySQL / MariaDB
docker run --rm --network host mysql:8.0 \
  mysqladmin ping -h HOST -P PORT --connect-timeout=$CONNECT_TIMEOUT
```

`pg_isready` returns 0 if the server is accepting connections (no credentials needed). `mysqladmin ping` checks if the server is alive.

```
[INFO] Host db.prod.example.com:5432 is reachable.
```
or
```
[ERROR] Fatal: Host db.prod.example.com:5432 is not reachable. Connection timed out after 30s.
```

### Step B6: DB authentication & health check

**When:** After host is confirmed reachable
**Timeout:** `--connect-timeout` (default 30s)

Connects with the provided credentials and runs a lightweight query to confirm:
- Credentials are valid (auth works)
- The DB engine is responsive (not in recovery, not overloaded)

For PostgreSQL, connects to the default `postgres` database (always exists). For MySQL/MariaDB, connects without specifying a database. This validates auth at the server level - individual database access is validated during the dump phase.

```bash
# PostgreSQL - connect to default 'postgres' database
docker run --rm --network host \
  -e PGPASSWORD="$DB_PASSWORD" \
  postgres:16 \
  psql -h HOST -p PORT -U "$DB_USER" -d postgres -c "SELECT 1;" -o /dev/null

# MySQL / MariaDB - connect without specifying a database
docker run --rm --network host \
  -e MYSQL_PWD="$DB_PASSWORD" \
  mysql:8.0 \
  mysql -h HOST -P PORT -u "$DB_USER" -e "SELECT 1;"
```

```
[INFO] DB connection verified: db.prod.example.com:5432 - SELECT 1 OK.
```
or
```
[ERROR] Fatal: Authentication failed on db.prod.example.com:5432. Check DB_USER/DB_PASSWORD.
[ERROR] Fatal: DB health check timed out after 30s. Server may be overloaded or in recovery.
```

### Step B7: Output directory writable

**When:** After DB health check passes
**Timeout:** None (instant, local)

Verifies the output base directory exists and is writable before creating the dated subdirectory (YYYY-MM-DD.NNN):

```python
os.access(output_dir, os.W_OK)
```

```
[ERROR] Fatal: Output directory '/backups' is not writable. Check volume mount permissions.
```

### Validation summary

| Step | Check | Timeout | Failure |
|---|---|---|---|
| B1 | Required args present & valid | None | Exit 1: `Missing required argument '{name}'` |
| B2 | Driver in registry | None | Exit 1: `Unknown driver '{name}'` |
| B3 | Docker socket available | 5s | Exit 1: `Docker is not available` |
| B4 | Image exists (local or pull) | 60s | Exit 1: `Docker image '{image}:{version}' not found` |
| B5 | DB host reachable (TCP) | `--connect-timeout` | Exit 1: `Host {host}:{port} is not reachable` |
| B6 | DB auth + health (`SELECT 1`) | `--connect-timeout` | Exit 1: `Authentication failed` / `Database does not exist` / `Health check timed out` |
| B7 | Output dir writable | None | Exit 1: `Output directory is not writable` |

All 7 steps must pass before any output directory, manifest, or dump is created. The script logs each step as it passes:

```
[INFO] [B1] Arguments validated.
[INFO] [B2] Driver 'postgres' is supported.
[INFO] [B3] Docker daemon is available.
[INFO] [B4] Image postgres:16 ready (cached).
[INFO] [B5] Host db.prod.example.com:5432 is reachable.
[INFO] [B6] DB connection verified: db.prod.example.com:5432 - SELECT 1 OK.
[INFO] [B7] Output directory /backups is writable.
[INFO] Validation complete - starting backup.
```
