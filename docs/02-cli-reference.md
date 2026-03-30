# DB Backup Orchestrator - CLI Reference

← [Back to index](../README.md)

## Subcommands

The tool has two subcommands: `backup` and `restore`. The subcommand determines which operation to run.

### Backup

```
entrypoint.py backup [args]
```

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:latest \
  backup --full --driver postgres --version 16 \
  --host db.prod.example.com --connection prod-main
```

### Restore

```
entrypoint.py restore [args]
```

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com --full
```

---

## Shared Arguments (both subcommands)

| Argument | Env Var | Default | Description |
|---|---|---|---|
| `--host` | `BACKUP_HOST` | (required) | Database host |
| `--port` | `BACKUP_PORT` | Auto from driver (postgres=5432, mysql/mariadb=3306) | Database port |
| `--user` | `DB_USER` or `BACKUP_USER` | (required) | Database user |
| `--password` | `DB_PASSWORD` or `BACKUP_PASSWORD` | (required) | Database password |
| `--connect-timeout` | `BACKUP_CONNECT_TIMEOUT` | `30` | Timeout for DB connectivity check |
| `--encrypt-key` | `BACKUP_ENCRYPT_KEY` | - | Encryption/decryption passphrase |
| `--dry-run` | - | `false` | Run validation + discovery, show what would be dumped, but create no files or directories |
| `--verbose` | - | `false` | Detailed output |
| `--docker-network` | - | `host` | Docker network for ephemeral containers. Use this when the DB is in a different Docker network (e.g., docker-compose). |
| `--docker-platform` | - | `linux/amd64` | Docker platform for ephemeral containers (e.g., `linux/arm64`). |
| `--verify` | - | `false` | Run verification fingerprint after backup/restore to validate database integrity |

---

## Backup Arguments

### Required

| Argument | Env Var | Description |
|---|---|---|
| `--driver` | `BACKUP_DRIVER` | Database engine (`postgres`, `mysql`, `mariadb`) |
| `--version` | `BACKUP_VERSION` | Engine version (maps to Docker image tag) |
| `--connection` | `BACKUP_CONNECTION` | Logical connection name (used for folder structure) |

### Mode (mutually exclusive - exactly one required)

| Argument | Description |
|---|---|
| `--full` | Auto-discover all databases, dump globals + all data. |
| `--databases-only` | Auto-discover all databases, no globals. |
| `--databases DB [DB ...]` | Dump specific database(s). For PostgreSQL, dumps all schemas in each DB (or filtered by `--schemas`). For MySQL/MariaDB, dumps the full database. |
| `--tables DB.TABLE [DB.TABLE ...]` | Dump specific tables. For PostgreSQL use `db.schema.table`, for MySQL/MariaDB use `db.table`. |
| `--globals-only` | Dump only roles, users, and permissions. No data. |

### Optional Flags

| Argument | Description |
|---|---|
| `--schemas SCHEMA [SCHEMA ...]` | **PostgreSQL only.** Filter which schemas to dump within the targeted databases. If omitted, all schemas are auto-discovered and dumped. Ignored with a `[WARN]` for MySQL/MariaDB (database = schema). |

### Optional Arguments

| Argument | Env Var | Default | Description |
|---|---|---|---|
| `--output-dir` | `BACKUP_OUTPUT_DIR` | `/backups` | Base output directory inside the container |
| `--no-compress` | - | `false` | Disable gzip compression (compression is **on** by default) |
| `--encrypt` | - | `false` | Encrypt dump files after compression using AES-256 |
| `--parallel` | - | `1` | Number of schemas to dump in parallel |
| `--timeout` | `BACKUP_TIMEOUT` | `1800` | Timeout in seconds per individual dump operation |
| `--retries` | - | `3` | Max retry attempts for failed/partial dumps |
| `--retry-delay` | - | `300` | Seconds to wait between retry attempts |
| `--retain-successful` | - | `30` | Max fully successful backups to keep per connection |
| `--retain-partial` | - | `5` | Max partial backups to keep per connection |
| `--result-file` | - | - | Write the backup path (`connection/YYYY-MM-DD.NNN`) to this file after completion. Useful for automation scripts. Non-fatal if the write fails. |

---

## Restore Arguments

### Required

| Argument | Description |
|---|---|
| `--from` | Path to backup directory (e.g., `/backups/prod-main/2026-03-18.001`) |
| `--host` | Target DB host to restore into |

**Note:** `--driver`, `--version`, and `--connection` are read from the backup's `manifest.json` - no need to pass them again. If `--driver` or `--version` is passed, it **must match** the manifest value or the script exits 1 (cross-driver/version restore is blocked). Use `--version-override` to force a different client version.

### Mode (mutually exclusive - exactly one required)

| Argument | Description |
|---|---|
| `--full` | Restore globals + all databases/schemas from the backup |
| `--databases-only` | Restore all databases from the backup, no globals |
| `--databases DB [DB ...]` | Restore only specific databases from the backup (must exist in backup) |
| `--tables DB.SCHEMA.TABLE [...]` | Restore only specific tables (PG: `db.schema.table`, MySQL: `db.table`) (must exist in backup) |
| `--globals-only` | Restore only roles/users/permissions |

### Optional Flags

| Argument | Description |
|---|---|
| `--drop-databases` | Drop and recreate databases/schemas before restoring. **Without this, restore fails if target already exists.** |
| `--drop-users` | Drop all non-system users on the target before restoring globals. Syncs users to match the source backup. |
| `--version-override VERSION` | Use a different client version than the manifest. Logs `[WARN]` about compatibility risk. |

### Optional Arguments

| Argument | Default | Description |
|---|---|---|
| `--timeout` | `7200` (2 hours) | Timeout in seconds per individual restore operation. Env var: `RESTORE_TIMEOUT` (falls back to `BACKUP_TIMEOUT`). Higher default than backup. |

---

## Mode + Flag Combinations

These apply to both `backup` and `restore` subcommands:

| Command | What gets backed up / restored |
|---|---|
| `--full` | Globals + all databases + all schemas |
| `--full --schemas public sales` | Globals + all databases, but only `public` and `sales` schemas in each (backup only) |
| `--databases-only` | All databases (auto-discover), no globals |
| `--databases dbA` | All schemas in dbA (auto-discover) |
| `--databases dbA --schemas public sales` | Only `public` and `sales` schemas in dbA (backup only) |
| `--databases dbA dbB --schemas public` | Only `public` schema in both dbA and dbB (backup only) |
| `--tables dbA.sales.orders` | Only that specific table |
| `--globals-only` | Globals only |

---

## Database/Schema Equivalence

| Concept | PostgreSQL | MySQL / MariaDB |
|---|---|---|
| `--databases sales` | Dump/restore all schemas in the `sales` database | Dump/restore the `sales` database (database = schema) |
| `--schemas public` | Filter to only the `public` schema | Ignored with `[WARN]` - not applicable |
| `--tables sales.public.orders` | Table `orders` in schema `public` in database `sales` | N/A (use `sales.orders` instead) |
| `--tables sales.orders` | N/A (need `db.schema.table` for PG) | Table `orders` in database `sales` |

---

## Manifest Tracking

The backup manifest records metadata used by both backup and restore:

- `mode` - the backup mode used (`full`, `databases-only`, `databases`, `tables`, `globals-only`)
- `globals_included` - whether globals were included in the backup (`true` / `false`)
- `driver` - the database engine used for the backup
- `driver_version` - the engine version (Docker image tag)

Restore reads these fields to determine what is available and to enforce compatibility (cross-driver restore is blocked).

---

CLI args always take precedence over env vars.
