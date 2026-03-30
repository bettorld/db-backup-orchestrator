# DB Backup Orchestrator - Architecture

← [Back to index](../README.md)

## Overview

A generic, driver-based Python **backup and restore** tool that runs inside a lightweight **orchestrator** Docker container. Instead of bundling every database client into one image, the orchestrator spawns **ephemeral database-specific containers** (official images) via Docker-out-of-Docker (DooD) to execute the actual dump/restore commands. This guarantees version-matched client tools with zero environment drift.

The same container image handles both operations - the subcommand (`backup` or `restore`) determines which operation to run.

---

## Backup Architecture

```
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:latest \
  backup --full --driver mysql --version 8.0 \
  --host db.prod.example.com --connection prod-mysql

┌──────────────────────────────────────────────────────────────────────────┐
│  db-backup-orchestrator container (Python 3.12 + Docker CLI)             │
│                                                                          │
│  ┌─ VALIDATION PIPELINE (all must pass → else exit 1) ───────────────┐  │
│  │  B1. Required args & format         (offline, instant)            │  │
│  │  B2. Driver in registry             (offline, instant)            │  │
│  │  B3. Docker socket available        (local, 5s timeout)           │  │
│  │  B4. Image exists (cache or pull)   (network, 60s timeout)        │  │
│  │  B5. DB host reachable (TCP)        (remote, --connect-timeout)   │  │
│  │  B6. DB auth + SELECT 1             (remote, --connect-timeout)   │  │
│  │  B7. Output dir writable            (local, instant)              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                            │ all passed                                  │
│                            ▼                                             │
│  ┌─ BACKUP ──────────────────────────────────────────────────────────┐  │
│  │  1. Create /backups/{conn}/{YYYY-MM-DD}.{NNN}/                    │  │
│  │  2. Write manifest.json → status: "initialized"                   │  │
│  │  3. Update manifest → status: "running"                           │  │
│  │                                                                    │  │
│  │  4. Spawn ephemeral DB containers for dumps:                      │  │
│  │     ┌────────────────────────────────────────────────────────┐    │  │
│  │     │ docker run --rm --network host                         │    │  │
│  │     │   -e PGPASSWORD="$DB_PASSWORD"                         │    │  │
│  │     │   postgres:16 pg_dumpall --globals-only                │    │  │
│  │     │   → .../2026-03-18.001/globals.sql                     │    │  │
│  │     ├────────────────────────────────────────────────────────┤    │  │
│  │     │ Auto-discover DBs → [app_production, analytics]         │    │  │
│  │     │ Per DB: discover schemas (or filter via --schemas)     │    │  │
│  │     ├────────────────────────────────────────────────────────┤    │  │
│  │     │ postgres:16 pg_dump -d app_production -n public        │    │  │
│  │     │   → .../2026-03-18.001/app_production/schema.public    │    │  │
│  │     ├────────────────────────────────────────────────────────┤    │  │
│  │     │ postgres:16 pg_dump -d app_production -n sales         │    │  │
│  │     │   → .../2026-03-18.001/app_production/schema.sales     │    │  │
│  │     ├────────────────────────────────────────────────────────┤    │  │
│  │     │ postgres:16 pg_dump -d analytics -n reporting          │    │  │
│  │     │   → .../2026-03-18.001/analytics/schema.reporting      │    │  │
│  │     └────────────────────────────────────────────────────────┘    │  │
│  │     Each dump: --timeout per op, flush manifest after each        │  │
│  │                                                                    │  │
│  │  5. Any failures? → RETRY (up to --retries, wait --retry-delay)   │  │
│  │     Only re-runs failed dumps, never re-dumps successful ones     │  │
│  │     Each attempt logged in manifest.retries.attempts[]            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                            │                                             │
│                            ▼                                             │
│  ┌─ FINALIZE ────────────────────────────────────────────────────────┐  │
│  │  6. Finalize manifest → status: "success" / "partial" / "failed"  │  │
│  │     Write summary: total, succeeded, failed, size, duration       │  │
│  │  7. Retention cleanup:                                            │  │
│  │     - Keep --retain-successful (default 30) successful backups    │  │
│  │     - Keep --retain-partial (default 5) partial backups           │  │
│  │     - Success run → can evict old successful + partial            │  │
│  │     - Partial run → can only evict old partial                    │  │
│  │     - Fatal run  → touches nothing                                │  │
│  │  8. Exit 0 (all ok) / 1 (fatal) / 2 (partial after retries)      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘

/backups/ (mounted volume)
└── prod-main/
    ├── 2026-03-17.001/
    │   ├── manifest.json         (status: "success")
    │   ├── globals.sql.gz
    │   ├── app_production/
    │   │   ├── schema.public.sql.gz
    │   │   └── schema.sales.sql.gz
    │   └── analytics/
    │       └── schema.reporting.sql.gz
    ├── 2026-03-18.001/           ← first run of the day (partial)
    │   ├── manifest.json         (status: "partial", attempts: 3)
    │   ├── globals.sql.gz
    │   └── app_production/
    │       └── schema.public.sql.gz
    └── 2026-03-18.002/           ← second run of the day
        ├── manifest.json         (status: "success", attempts: 1)
        ├── globals.sql.gz
        ├── app_production/
        │   ├── schema.public.sql.gz
        │   └── schema.sales.sql.gz
        └── analytics/
            └── schema.reporting.sql.gz
```

---

## Restore Architecture

The same container image is used for restore - use the `restore` subcommand instead of `backup`.

```
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full

┌──────────────────────────────────────────────────────────────────────────┐
│  db-backup-orchestrator container (Python 3.12 + Docker CLI)             │
│                                                                          │
│  ┌─ RESTORE VALIDATION (all must pass → else exit 1) ────────────────┐  │
│  │  R1.  Required args present           (offline, instant)          │  │
│  │  R2.  Backup directory exists          (local, instant)           │  │
│  │  R3.  manifest.json valid              (local, instant)           │  │
│  │  R4.  Manifest status check            (local, instant)           │  │
│  │  R5.  Driver compatibility             (local, instant)           │  │
│  │  R6.  Requested items exist in backup  (local, instant)           │  │
│  │  R7.  Backup files exist on disk       (local, instant)           │  │
│  │  R8.  Checksums match (SHA-256)        (local, instant)           │  │
│  │  R9.  Encryption key provided          (local, instant)           │  │
│  │  R10. Decryption test                  (local, instant)           │  │
│  │  R11. Docker socket + image available  (local/network, 60s)       │  │
│  │  R12. Target DB reachable + auth       (remote, --connect-timeout)│  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                            │ all passed                                  │
│                            ▼                                             │
│  ┌─ RESTORE ────────────────────────────────────────────────────────┐  │
│  │  1. Write restore log → status: "initialized"                     │  │
│  │  2. Update restore log → status: "running"                        │  │
│  │                                                                    │  │
│  │  3. Restore in dependency order:                                  │  │
│  │     ┌────────────────────────────────────────────────────────┐    │  │
│  │     │ a. Globals first (roles/users must exist before schemas)│    │  │
│  │     │    .sql.gz.enc → decrypt → decompress → psql           │    │  │
│  │     ├────────────────────────────────────────────────────────┤    │  │
│  │     │ b. Create databases if not exist (--drop-databases      │    │  │
│  │     │    drops and recreates before restore)                 │    │  │
│  │     ├────────────────────────────────────────────────────────┤    │  │
│  │     │ c. Schemas one at a time (sequential, not parallel):   │    │  │
│  │     │    postgres:16 psql -d app_production < schema.public  │    │  │
│  │     │    postgres:16 psql -d app_production < schema.sales   │    │  │
│  │     │    postgres:16 psql -d analytics < schema.reporting    │    │  │
│  │     └────────────────────────────────────────────────────────┘    │  │
│  │     Each restore: --timeout per op (default 2h)                    │  │
│  │     Flush restore log after each file                             │  │
│  │                                                                    │  │
│  │  4. STOPS on first failure (no continue-on-failure for restore)   │  │
│  │     Half-restored state is dangerous → operator must investigate   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                            │                                             │
│                            ▼                                             │
│  ┌─ FINALIZE ────────────────────────────────────────────────────────┐  │
│  │  5. Finalize restore log → status: "success" / "partial" / "failed│  │
│  │  6. Exit 0 (all ok) / 1 (fatal) / 2 (partial - stopped mid-way)  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘

Restore log stored inside the source backup directory:
/backups/prod-main/2026-03-18.001/
├── manifest.json                          ← backup manifest (unchanged)
├── globals.sql.gz
├── app_production/
│   ├── schema.public.sql.gz
│   └── schema.sales.sql.gz
├── analytics/
│   └── schema.reporting.sql.gz
├── restore.2026-03-20.001.json            ← first restore from this backup
└── restore.2026-03-22.001.json            ← second restore (different day)
```

### Key differences from backup

| Aspect | Backup | Restore |
|---|---|---|
| Triggered by | `backup --full`, `backup --databases`, `backup --tables`, `backup --globals-only` | `restore --from PATH` + `restore --full`, etc. |
| Validation | B1-B7 (7 steps) | R1-R12 (12 steps - includes driver compat, item check, checksum + decryption) |
| On failure | Continue + retry failed dumps | Stop immediately (half-restored state is unsafe) |
| Parallelism | `--parallel` supported | Always sequential (dependency order) |
| Retries | `--retries` / `--retry-delay` | No retries (operator must decide) |
| Timeout default | 1800s (30 min) per dump | 7200s (2 hours) per restore |
| Output | New backup dir + manifest.json | Restore log inside source backup dir |
| Retention | Auto-cleanup old backups | N/A (restore doesn't produce new backup dirs) |

**Cross-driver restore is blocked:** The manifest `driver` must match the target. You cannot restore a PostgreSQL backup into a MySQL server (or vice versa). If `--driver` is passed explicitly and does not match the manifest, the script exits 1.

**Version mismatch warning:** If the manifest `driver_version` does not match the target engine version, the script logs a `[WARN]` about potential compatibility issues. Use `--version-override` to force a different client version (e.g., restoring a PG 15 backup using the PG 16 client).

---

### Why Docker-out-of-Docker (DooD)?

| Benefit | Detail |
|---|---|
| **Version-matched clients** | `pg_dump` from `postgres:16` talks to a Postgres 16 server - no version mismatch warnings or compatibility bugs |
| **Multi-engine support** | MySQL 5.7, MySQL 8, MariaDB 10.11, Postgres 14/15/16 - just change the image tag |
| **Lightweight orchestrator** | The orchestrator image only needs Python 3 + Docker CLI (~50 MB), no DB clients |
| **No environment drift** | The caller doesn't need any DB tools installed; everything is containerized |

### How DooD works here

The orchestrator container **does not run a Docker daemon**. It mounts the **host's Docker socket** (`/var/run/docker.sock`) so it can issue `docker run` commands that execute on the host. This is sometimes called "Docker-out-of-Docker" (DooD) and is the approach used by this tool.

---

## Supported Database Engines

| Driver | Official Image | Dump Tool | Globals Support |
|---|---|---|---|
| `postgres` | `postgres:{version}` | `pg_dump`, `pg_dumpall` | `pg_dumpall --globals-only` (roles, grants) |
| `mysql` | `mysql:{version}` | `mysqldump` | `mysqldump --no-data --no-create-info --skip-lock-tables --flush-privileges mysql` + user/grant extraction |
| `mariadb` | `mariadb:{version}` | `mariadb-dump` / `mysqldump` | Same approach as MySQL |
