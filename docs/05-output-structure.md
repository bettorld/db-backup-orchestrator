# DB Backup Orchestrator - Output Structure

← [Back to index](../README.md)

## Output Structure

```
/backups/
└── {CONNECTION}/
    └── {YYYY-MM-DD}.{NNN}/
        ├── manifest.json
        ├── globals.sql.gz[.enc]                           # --full or --globals-only
        ├── {DATABASE_1}/                              # subfolder per database
        │   ├── schema.public.sql.gz[.enc]
        │   ├── schema.sales.sql.gz[.enc]
        │   └── schema.inventory.sql.gz[.enc]
        ├── {DATABASE_2}/
        │   ├── schema.public.sql.gz[.enc]
        │   └── schema.reporting.sql.gz[.enc]
        └── {DATABASE_N}/
            └── table.sales.orders.sql.gz[.enc]            # --tables mode
```

**Example - `--full` (PostgreSQL, 2 databases auto-discovered):**

```
/backups/prod-main/2026-03-18.001/
├── manifest.json
├── globals.sql.gz
├── app_production/
│   ├── schema.public.sql.gz
│   └── schema.sales.sql.gz
└── analytics/
    ├── schema.public.sql.gz
    └── schema.reporting.sql.gz
```

**Example - `--databases app_production` (all schemas auto-discovered):**

```
/backups/prod-main/2026-03-18.001/
├── manifest.json
└── app_production/
    ├── schema.public.sql.gz
    └── schema.sales.sql.gz
```

**Example - `--databases app_production --schemas public` (filtered schemas):**

```
/backups/prod-main/2026-03-18.001/
├── manifest.json
└── app_production/
    └── schema.public.sql.gz
```

**Example - `--databases-only` (PostgreSQL, all databases auto-discovered, no globals):**

```
/backups/prod-main/2026-03-18.001/
├── manifest.json
├── app_production/
│   ├── schema.public.sql.gz
│   └── schema.sales.sql.gz
└── analytics/
    ├── schema.public.sql.gz
    └── schema.reporting.sql.gz
```

**Example - `--tables app_production.sales.orders app_production.sales.customers` (PostgreSQL):**

```
/backups/prod-main/2026-03-18.001/
├── manifest.json
└── app_production/
    ├── table.sales.orders.sql.gz
    └── table.sales.customers.sql.gz
```

**Example - `--full` (MySQL, 2 databases auto-discovered):**

```
/backups/prod-analytics/2026-03-18.001/
├── manifest.json
├── globals.sql.gz
├── analytics/
│   └── full.sql.gz
└── reporting/
    └── full.sql.gz
```

**Example - `--tables analytics.orders analytics.customers` (MySQL):**

```
/backups/prod-analytics/2026-03-18.001/
├── manifest.json
└── analytics/
    ├── table.orders.sql.gz
    └── table.customers.sql.gz
```

### Directory counter (NNN)

The counter is a zero-padded 3-digit number that auto-increments per date per connection:

- First backup of the day → `2026-03-18.001`
- If you re-run the same day → `2026-03-18.002`
- Next day resets → `2026-03-19.001`

**How it works:** on startup, the orchestrator scans `{output-dir}/{connection}/` for existing directories matching `{today's date}.*`, finds the highest counter, and increments by 1. If none exist, starts at `001`.

This is cleaner than timestamps because:
- Easy to see how many runs happened per day at a glance
- Sorts naturally in file explorers and `ls`
- No ambiguity about timezones (just the date matters)

### Naming Conventions

File extensions depend on compression (default on) and encryption (default off):

| Compression | Encryption | Extension example |
|---|---|---|
| Yes (default) | No | `schema.public.sql.gz` |
| Yes (default) | Yes | `schema.public.sql.gz.enc` |
| No (`--no-compress`) | No | `schema.public.sql` |
| No (`--no-compress`) | Yes | `schema.public.sql.enc` |

**PostgreSQL:**

| Backup Type | Path |
|---|---|
| Globals (roles/users/permissions) | `globals.sql{.gz}{.enc}` (root of backup dir) |
| Schema dump | `{DATABASE}/schema.{SCHEMA_NAME}.sql{.gz}{.enc}` |
| Table dump | `{DATABASE}/table.{SCHEMA_NAME}.{TABLE_NAME}.sql{.gz}{.enc}` |
| Manifest | `manifest.json` (root of backup dir, never compressed/encrypted) |

**MySQL / MariaDB:**

| Backup Type | Path |
|---|---|
| Globals (users/grants) | `globals.sql{.gz}{.enc}` (root of backup dir) |
| Database dump (full) | `{DATABASE}/full.sql{.gz}{.enc}` |
| Table dump | `{DATABASE}/table.{TABLE_NAME}.sql{.gz}{.enc}` |
| Manifest | `manifest.json` (root of backup dir, never compressed/encrypted) |

### Checksum and Manifest Notes

- **Checksum is computed on the final file**: after compression and encryption (if enabled). This means the `checksum_sha256` in the manifest corresponds to the `.sql.gz.enc` file on disk, not the raw SQL.
- **`manifest.json` is never compressed or encrypted.** It must always be human-readable and machine-parseable for the retention module, restore validation, and debugging.

### manifest.json - Lifecycle

The manifest is the **first file written** and the **last file updated**. It acts as both a status tracker and the final report.

#### Manifest statuses

| Status | Meaning | When set |
|---|---|---|
| `initialized` | Manifest created, backup not started yet | Immediately after output dir is created |
| `running` | Dumps are in progress | After validation pipeline passes (B1-B7), before first dump |
| `success` | All dumps completed successfully | End of run - all files succeeded |
| `partial` | Some dumps succeeded, some failed | End of run - mixed results |
| `failed` | No dumps succeeded or fatal error after init | End of run - everything failed, or unrecoverable error |

**If the script crashes or is killed**, the manifest stays at `initialized` or `running` - this is how the retention module detects interrupted backups (treated as `partial` for retention purposes).

#### Phase 1: Initialization (written immediately)

```json
{
  "version": "1.0",
  "status": "initialized",
  "timestamp_start": "2026-03-18T14:30:00Z",
  "timestamp_end": null,
  "connection": "prod-main",
  "driver": "postgres",
  "driver_version": "16",
  "databases": [],
  "host": "db.prod.example.com",
  "port": 5432,
  "mode": "full",
  "globals_included": true,
  "compress": true,
  "encrypt": false,
  "retries": {
    "max_attempts": 3,
    "delay_seconds": 300,
    "attempts": []
  },
  "files": [],
  "summary": null
}
```

#### Phase 2: Running (updated as each dump completes)

The `databases` field is populated as they are discovered (for `--full`) or confirmed (for `--databases`).

```json
{
  "status": "running",
  "databases": ["app_production", "analytics"],
  "files": [
    {
      "filename": "globals.sql",
      "type": "globals",
      "database": null,
      "size_bytes": 4521,
      "checksum_sha256": "abc123...",
      "duration_seconds": 1.2,
      "status": "success"
    },
    {
      "filename": "app_production/schema.public.sql",
      "type": "schema",
      "database": "app_production",
      "schema": "public",
      "size_bytes": 1048576,
      "checksum_sha256": "def456...",
      "duration_seconds": 12.5,
      "status": "success"
    }
  ]
}
```

Each file entry is appended as its dump finishes. The manifest is flushed to disk after each file - so even if the script crashes mid-run, you have a record of what completed.

#### Phase 3: Final (end of all attempts)

```json
{
  "version": "1.0",
  "status": "success",
  "timestamp_start": "2026-03-18T14:30:00Z",
  "timestamp_end": "2026-03-18T14:32:15Z",
  "connection": "prod-main",
  "driver": "postgres",
  "driver_version": "16",
  "databases": ["app_production", "analytics"],
  "host": "db.prod.example.com",
  "port": 5432,
  "mode": "full",
  "globals_included": true,
  "compress": true,
  "encrypt": false,
  "retries": {
    "max_attempts": 3,
    "delay_seconds": 300,
    "attempts": [
      {
        "attempt": 1,
        "timestamp": "2026-03-18T14:30:00Z",
        "result": "partial",
        "succeeded": ["globals.sql", "app_production/schema.public.sql", "analytics/schema.public.sql"],
        "failed": ["app_production/schema.sales.sql"],
        "errors": {
          "app_production/schema.sales.sql": "pg_dump: error: permission denied for schema sales"
        }
      },
      {
        "attempt": 2,
        "timestamp": "2026-03-18T14:35:05Z",
        "result": "success",
        "succeeded": ["app_production/schema.sales.sql"],
        "failed": [],
        "errors": {}
      }
    ]
  },
  "files": [
    {
      "filename": "globals.sql",
      "type": "globals",
      "database": null,
      "size_bytes": 4521,
      "checksum_sha256": "abc123...",
      "duration_seconds": 1.2,
      "status": "success",
      "attempt": 1
    },
    {
      "filename": "app_production/schema.public.sql",
      "type": "schema",
      "database": "app_production",
      "schema": "public",
      "size_bytes": 1048576,
      "checksum_sha256": "def456...",
      "duration_seconds": 12.5,
      "status": "success",
      "attempt": 1
    },
    {
      "filename": "app_production/schema.sales.sql",
      "type": "schema",
      "database": "app_production",
      "schema": "sales",
      "size_bytes": 524288,
      "checksum_sha256": "ghi789...",
      "duration_seconds": 8.3,
      "status": "success",
      "attempt": 2
    },
    {
      "filename": "analytics/schema.public.sql",
      "type": "schema",
      "database": "analytics",
      "schema": "public",
      "size_bytes": 262144,
      "checksum_sha256": "jkl012...",
      "duration_seconds": 5.1,
      "status": "success",
      "attempt": 1
    }
  ],
  "verification": {
    "timestamp": "2026-03-18T14:32:16Z",
    "combined": "sha256:a1b2c3d4e5f6...",
    "checks": {
      "databases": "sha256:...",
      "tables": "sha256:...",
      "indexes": "sha256:...",
      "foreign_keys": "sha256:...",
      "views": "sha256:...",
      "routines": "sha256:...",
      "triggers": "sha256:...",
      "events": "sha256:...",
      "users": "sha256:...",
      "collations": "sha256:..."
    }
  },
  "summary": {
    "total_files": 4,
    "total_databases": 2,
    "succeeded": 4,
    "failed": 0,
    "total_size_bytes": 1839489,
    "total_duration_seconds": 327.0,
    "total_attempts": 2
  }
}
```

> **Note:** The `verification` section only appears when `--verify` is used during backup. It contains SHA-256 hashes of read-only `information_schema` / catalog queries (databases, tables, indexes, foreign keys, views, routines, triggers, events, users, collations). During `restore --verify`, these hashes are compared against the target database to detect mismatches. The `events` check applies to MySQL/MariaDB only.
