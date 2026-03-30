# DB Backup Orchestrator - Restore

← [Back to index](../README.md)

## Restore

The restore operation is the inverse of backup. It reads a backup's `manifest.json` to know what to restore, in what order, and how to decrypt/decompress. Same Docker-out-of-Docker (DooD) approach - ephemeral containers from official DB images.

### Restore CLI

```
entrypoint.py restore [args]
```

#### Required Arguments

| Argument | Env Var | Description |
|---|---|---|
| `--from` | - | Path to backup directory (e.g., `/backups/prod-main/2026-03-18.001`) |
| `--host` | `BACKUP_HOST` | **Target** DB host to restore into |
| `--user` | `DB_USER` or `BACKUP_USER` | Target DB user |
| `--password` | `DB_PASSWORD` or `BACKUP_PASSWORD` | Target DB password |

**Note:** `--driver`, `--version`, `--connection` are read from the backup's `manifest.json` - no need to pass them again. If `--driver` or `--version` is passed, it must match the manifest or the script exits 1 (cross-driver/version restore is blocked). Use `--version-override` to force a different client version.

#### Restore Mode (mutually exclusive - exactly one required)

| Argument | Description |
|---|---|
| `--full` | Restore globals + all databases/schemas from the backup |
| `--databases-only` | Restore all databases from the backup, no globals |
| `--databases DB [DB ...]` | Restore only specific databases from the backup (must exist in backup) |
| `--tables DB.SCHEMA.TABLE [...]` | Restore only specific tables (PG: `db.schema.table`, MySQL: `db.table`) (must exist in backup) |
| `--globals-only` | Restore only roles/users/permissions |

#### Restore Flags

| Argument | Description |
|---|---|
| `--drop-databases` | Drop and recreate databases/schemas before restoring. **Without this, restore fails if target already exists.** |
| `--drop-users` | Drop all non-system users on the target before restoring globals. Syncs users to match the source backup. |
| `--version-override VERSION` | Use a different client version than the manifest. Logs `[WARN]` about compatibility risk. |

#### Restore Options

| Argument | Default | Description |
|---|---|---|
| `--port` | Auto from driver | Target DB port |
| `--timeout` | `7200` (2 hours) | Timeout in seconds per individual restore operation. Env var: `RESTORE_TIMEOUT` (falls back to `BACKUP_TIMEOUT`). |
| `--connect-timeout` | `30` | Timeout for target DB connectivity check |
| `--encrypt-key` | `BACKUP_ENCRYPT_KEY` | Decryption passphrase (required if backup was encrypted - detected from manifest) |
| `--dry-run` | `false` | Preview what would be restored without touching the target DB |
| `--verbose` | `false` | Detailed progress output |

### Cross-Driver Restore

Cross-driver restore is **blocked**. The manifest `driver` must match the target database engine. You cannot restore a PostgreSQL backup into a MySQL server (or vice versa). If the drivers do not match, the script exits 1:

```
[ERROR] Fatal: Cross-driver restore is not supported. Backup driver: postgres, requested: mysql.
```

If the manifest `driver_version` does not match, the script warns and exits 1 unless `--version-override` is used:

```
[WARN] Manifest version is 15, but restore will use postgres:16. Proceeding due to --version-override.
```

### Restore Order

Restore always follows this order to satisfy dependencies:

1. **Globals** - roles/users must exist before schemas that reference them (ownership, grants)
2. **Databases** - create database if it doesn't exist (PostgreSQL)
3. **Schemas** - restore in manifest order, one at a time (sequential, not parallel)

**Why no parallel restore?** Schemas may have cross-dependencies (foreign keys, shared types). Sequential is safer. The `--timeout` per operation prevents any single restore from hanging indefinitely.

### Restore Validation Pipeline

For the full restore validation pipeline (R1-R12), see [Restore Validation](./04-restore-validation.md).

All 12 validation steps must pass before any data is written to the target DB.

### Restore Pipeline (per file)

Inverse of backup:

```
.sql.gz.enc → openssl dec → gunzip → psql/mysql (target DB)
```

```
.sql.gz → gunzip → psql/mysql
.sql.enc → openssl dec → psql/mysql
.sql → psql/mysql
```

The script reads the file extension to determine the pipeline automatically.

### Safety: No Implicit Overwrite

By default, if a target database/schema already exists, the restore **stops with an error**:

```
[ERROR] Database 'app_production' already exists on staging-db.example.com. Use --drop-databases to drop and recreate.
```

With `--drop-databases`:
```
[WARN] Dropping database 'app_production' on staging-db.example.com before restore.
```

### Restore Idempotency

With `--drop-databases`, re-running a restore drops everything and starts fresh - this makes `--drop-databases` the **idempotent** option. You can safely re-run the same restore command and get the same result.

Without `--drop-databases`, restore fails if the target already exists. This is a safety net - it prevents accidentally overwriting a database that was already restored or that contains other data.

### Drop Users

With `--drop-users`, the orchestrator drops all non-system users on the target database before restoring globals. This ensures the target's user list matches the source backup exactly -- no leftover users from previous restores or manual changes.

**MySQL/MariaDB:** Drops all users except `root`, `mysql.sys`, `mysql.session`, `mysql.infoschema`, and `debian-sys-maint`.

**PostgreSQL:** Drops all roles except `postgres` and system roles (`pg_*`).

```
[INFO] Dropping non-system users on staging-db.example.com before restoring globals.
[INFO] Dropping user: app_readonly@%
[INFO] Dropping user: reporting@localhost
```

This flag is independent of `--drop-databases` -- you can use either or both.

### Restore on Timeout / Failure

Unlike backup (continue-on-failure), restore **stops immediately** on any error or timeout:

- A timed-out or failed restore may leave the database in a half-restored state (partial data, missing constraints)
- Continuing to restore the next schema on top of that could compound the problem
- The operator must investigate and decide: retry, `--drop-databases` and start over, or fix the target

Exit codes:
- `0` - all restores succeeded
- `1` - fatal (can't start: bad args, corrupted backup, target unreachable)
- `2` - partial (restore started but failed/timed out mid-way)

### Restore Verification

When `--verify` is used during restore, the orchestrator compares the target database's fingerprint against the backup manifest's verification data. This runs the same read-only `information_schema` / catalog queries that were used during backup, hashes each result with SHA-256, and compares against the stored hashes.

**Checks:** databases, table structure (columns/types), indexes, foreign keys, views, routines, triggers, events (MySQL/MariaDB only), users, collations.

All queries are read-only `information_schema` / catalog queries -- zero risk, milliseconds to run.

**Output:**

```
[INFO] Verification: comparing restored DB to backup fingerprint...
[INFO]   databases:           PASS
[INFO]   tables:              PASS
[INFO]   indexes:             PASS
[INFO]   foreign_keys:        PASS
[INFO]   views:               PASS
[INFO]   routines:            PASS
[INFO]   triggers:            PASS
[INFO]   events:              PASS
[INFO]   users:               PASS
[INFO]   collations:          PASS
[INFO] Verification complete: 10/10 checks passed.
```

Mismatches are logged as warnings but do not change the exit code -- the restore itself succeeded; verification is informational.

If the backup was made without `--verify`, restore verification is skipped with a warning:

```
[WARN] Backup manifest has no verification data (backup was made without --verify). Skipping restore verification.
```

### Restore Log

A JSON log file is written inside the **backup directory** it was restored from. This ties the restore history to its source backup.

**Location:** `{backup_dir}/restore.{YYYY-MM-DD}.{NNN}.json`

Counter works like backup directories - auto-increments per date.

```
/backups/prod-main/2026-03-18.001/
├── manifest.json
├── globals.sql.gz
├── app_production/
│   ├── schema.public.sql.gz
│   └── schema.sales.sql.gz
├── restore.2026-03-20.001.json       ← first restore from this backup
└── restore.2026-03-22.001.json       ← second restore (different day)
```

#### Restore log structure

```json
{
  "version": "1.0",
  "type": "restore",
  "status": "success",
  "timestamp_start": "2026-03-20T09:15:00Z",
  "timestamp_end": "2026-03-20T09:22:30Z",
  "source": "/backups/prod-main/2026-03-18.001",
  "target": {
    "host": "staging-db.example.com",
    "port": 5432,
    "driver": "postgres",
    "driver_version": "16"
  },
  "mode": "restore-full",
  "drop_databases": true,
  "drop_users": false,
  "restore_timeout": 7200,
  "files_restored": [
    {
      "filename": "globals.sql.gz",
      "type": "globals",
      "status": "success",
      "duration_seconds": 1.5,
      "checksum_verified": true
    },
    {
      "filename": "app_production/schema.public.sql.gz",
      "type": "schema",
      "database": "app_production",
      "schema": "public",
      "status": "success",
      "duration_seconds": 45.2,
      "checksum_verified": true
    },
    {
      "filename": "app_production/schema.sales.sql.gz",
      "type": "schema",
      "database": "app_production",
      "schema": "sales",
      "status": "timeout",
      "duration_seconds": 7200.0,
      "checksum_verified": true,
      "error": "Restore timed out after 7200s"
    }
  ],
  "summary": {
    "status": "partial",
    "total_files": 3,
    "succeeded": 2,
    "failed": 1,
    "total_duration_seconds": 3646.7
  }
}
```

**Note:** No `user`, `password`, or any credential is ever written to the restore log. Only the host/port/driver are recorded - enough to identify the target without exposing auth.

#### Restore log lifecycle

Same as backup manifest - written progressively and crash-safe:

1. `status: "initialized"` - written immediately when restore starts
2. `status: "running"` - updated after validation passes, before first file
3. Each `files_restored[]` entry flushed to disk as it completes
4. `status: "success"` / `"partial"` / `"failed"` - set at the end in `summary`

If the script crashes mid-restore, the log stays at `initialized` or `running` - this is visible evidence that a restore was interrupted.

#### Restore log retention

Restore logs are small JSON files and are **NOT** cleaned up by backup retention. They persist as long as the backup directory exists. If you delete a backup directory (via retention or manually), its restore logs go with it.

#### Read-only backup directory

If the backup directory is read-only (e.g., mounted as a read-only volume), the restore log cannot be written to disk. In this case, the restore log is written to **stderr only** with a `[WARN]`:

```
[WARN] Backup directory is read-only - restore log will not be persisted to disk.
```

The restore proceeds normally; only the log persistence is affected.

### Restore Usage Examples

#### Full restore to staging

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full
```

#### Restore single database with drop

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --databases app_production \
  --drop-databases
```

#### Restore encrypted backup

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="admin" \
  -e DB_PASSWORD="s3cret" \
  -e BACKUP_ENCRYPT_KEY="my-key" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full
```

#### Restore specific tables

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --tables app_production.sales.orders
```

#### Restore globals only

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --globals-only
```

#### Restore with version override

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full \
  --version-override 16
```

#### Dry run (preview restore without executing)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full --dry-run
```
