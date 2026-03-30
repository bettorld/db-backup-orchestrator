# DB Backup Orchestrator - Project Structure

← [Back to index](../README.md)

## Project File Structure

```
db_backup_orchestrator/
├── docs/                       # documentation (split by topic)
│   └── README.md               # index + quick start + build instructions
├── Dockerfile
├── docker-bake.hcl             # buildx bake configuration (amd64)
├── Makefile                    # build, build-dev, build-test, build-multi, bake, test, lint, format, clean targets
├── requirements.txt            # minimal: none or just standard lib
├── entrypoint.py               # CLI entry point (subcommand: backup | restore)
├── db_backup_orchestrator/
│   ├── __init__.py
│   ├── cli.py                  # argument parsing and validation
│   ├── config.py               # configuration dataclass from args + env vars
│   ├── validation.py           # B1-B7 validation pipeline
│   ├── orchestrator.py         # main backup orchestration logic
│   ├── restorer.py             # restore orchestration logic
│   ├── manifest.py             # manifest.json generation
│   ├── retention.py            # backup rotation / cleanup logic
│   ├── docker_runner.py        # wrapper around Docker CLI commands
│   ├── drivers/
│   │   ├── __init__.py
│   │   ├── base.py             # abstract base driver
│   │   ├── postgres.py         # PostgreSQL-specific dump commands
│   │   ├── mysql.py            # MySQL-specific dump commands
│   │   └── mariadb.py          # MariaDB-specific dump commands
│   └── utils/
│       ├── __init__.py
│       ├── logging.py          # structured logging
│       ├── checksum.py         # SHA-256 file hashing
│       └── encryption.py       # openssl encryption wrapper
└── tests/
    ├── __init__.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_cli.py
    │   ├── test_validation.py
    │   ├── test_orchestrator.py
    │   ├── test_restorer.py
    │   ├── test_retention.py
    │   ├── test_docker_runner.py
    │   ├── test_manifest.py
    │   ├── test_encryption.py
    │   ├── test_checksum.py
    │   ├── test_logging.py
    │   ├── test_verify.py
    │   └── test_drivers/
    │       ├── test_postgres.py
    │       ├── test_mysql.py
    │       └── test_mariadb.py
    ├── integration/
    │   ├── __init__.py
    │   ├── conftest.py             # session fixture: start/stop DB containers
    │   ├── helpers.py              # validation helpers (assert_gzipped, etc.)
    │   ├── test_postgres_backup.py
    │   ├── test_mysql_backup.py
    │   ├── test_mariadb_backup.py
    │   ├── test_postgres_restore.py
    │   ├── test_mysql_restore.py
    │   └── test_mariadb_restore.py
    └── fixtures/
        ├── docker-compose.yml      # optional: manual local dev only (not used by test suite)
        └── seed/
            ├── postgres/
            │   ├── init.sql        # databases, schemas, tables, roles
            │   └── data.sql        # lorem ipsum fake data
            ├── mysql/
            │   ├── init.sql
            │   └── data.sql
            └── mariadb/
                ├── init.sql
                └── data.sql
```

---

## Implementation Steps

### Step 1: Project Scaffold
- Create directory structure
- `requirements.txt` (minimal - standard lib only if possible)
- `__init__.py` files

### Step 2: Configuration & CLI (`cli.py`, `config.py`)
- argparse setup with all arguments + env var fallbacks
- Build a `BackupConfig` dataclass from parsed args
- **B1 validation**: required args present, mutually exclusive modes, format checks
- **B2 validation**: driver in `DRIVER_REGISTRY`, auto-fill default port

### Step 3: Docker Runner (`docker_runner.py`)
- Wrapper to execute `docker run --rm ...` via `subprocess`
- Handle: container stdout/stderr capture, timeout, exit codes
- `check_docker()` - **B3**: verify Docker socket (5s timeout)
- `ensure_image(image, version)` - **B4**: local inspect → pull if missing (60s timeout)
- `run(command, env, timeout)` - execute a container and return stdout/stderr/exit code

### Step 4: Validation Pipeline (`validation.py`)
- Orchestrates B1→B7 in order, exits 1 on first failure
- `validate_args(config)` - B1 + B2 (called from CLI)
- `validate_infrastructure(config, docker_runner)` - B3 + B4 (Docker + image)
- `validate_connectivity(config, docker_runner, driver)` - B5 + B6 (host reachable + SELECT 1)
- `validate_output_dir(config)` - B7 (writable check)
- Logs each step as `[INFO] [B1] Arguments validated.` etc.

### Step 5: Base Driver (`drivers/base.py`)
- Abstract base class defining the interface:
  - `check_reachable(host, port, timeout) -> bool` - B5: host-level check (`pg_isready` / `mysqladmin ping`)
  - `check_connection(host, port, user, password, timeout) -> bool` - B6: auth + `SELECT 1`
  - `list_databases() -> list[str]` - auto-discover all user databases on the server
  - `list_schemas(database) -> list[str]` - list schemas within a specific database
  - `dump_globals() -> bytes | str`
  - `dump_schema(database, schema_name) -> bytes | str`
  - `dump_table(database, schema_name, table_name) -> bytes | str`
- Each method returns the dump commands to pass to `docker_runner`

### Step 6: PostgreSQL Driver (`drivers/postgres.py`)
- Implement `list_databases`: query `pg_database` excluding templates
- Implement `list_schemas`: query `information_schema.schemata` for a given database
- Implement `dump_globals`: `pg_dumpall --globals-only --no-tablespaces`
- Implement `dump_schema`: `pg_dump -d {database} -n {schema}`
- Implement `dump_table`: `pg_dump -d {database} -t {schema.table}`
- Handle `PGPASSWORD` env var injection

### Step 7: MySQL Driver (`drivers/mysql.py`)
- Implement `list_databases`: query `information_schema.schemata` excluding system DBs
- Implement `list_schemas`: returns `None` (not applicable - database = schema in MySQL)
- Implement `dump_globals`: extract users + grants from `mysql.user`
- Implement `dump_database`: `mysqldump --databases {database}` (dumps full database)
- Implement `dump_table`: `mysqldump {database} {table}`
- Warn and ignore if `--schemas` was passed
- Handle password via `MYSQL_PWD` env var

### Step 8: MariaDB Driver (`drivers/mariadb.py`)
- Extend MySQL driver
- Override binary name (`mariadb-dump` vs `mysqldump` based on version)
- Handle any MariaDB-specific syntax differences

### Step 9: Orchestrator (`orchestrator.py`)
- Main orchestration loop:
  1. Run validation pipeline (B1→B7) → exit 1 on any failure
  2. Create dated output directory (YYYY-MM-DD.NNN)
  3. Write initial `manifest.json` with `"status": "initialized"`
  6. Update manifest to `"status": "running"`
  7. **Attempt 1**: Based on mode:
     - `--full`: dump globals + auto-discover databases → for each DB, discover schemas → dump all
     - `--full --schemas X Y`: same but filter to only schemas X and Y in each DB
     - `--databases dbA dbB`: for each specified DB, auto-discover schemas → dump all
     - `--databases dbA --schemas X Y`: only schemas X and Y in dbA
     - `--databases-only`: auto-discover databases, no globals
     - `--tables db.schema.table`: dump specified tables
     - `--globals-only`: dump globals only
     For each mode:
     - Run appropriate driver methods with per-operation `--timeout`
     - Write output files
     - Track success/failure/timeout per file
     - Flush manifest after each file completes
  8. **Retry loop** (if any failures and `--retries` > 0):
     - Wait `--retry-delay` seconds
     - Re-run only the failed dumps
     - Update manifest with new attempt + updated file entries
     - Repeat up to `--retries` times or until all succeed
  9. Finalize manifest: set `"status"` to `success` / `partial` / `failed`, write `summary`
  9b. If `--verify`: run verification fingerprint (9-10 read-only `information_schema` queries against source DB, hash each with SHA-256, store in manifest under `"verification"`)
  10. Run retention cleanup (based on final status - see retention rules)
  11. Print summary log
  12. Return exit code: 0 (all ok), 1 (fatal - shouldn't reach here), 2 (partial failure)
- Support `--parallel` via `concurrent.futures.ThreadPoolExecutor`
- Dump output is streamed directly to disk (never buffered in memory) - supports databases of any size
- Compression on by default (gzip), disable with `--no-compress`
- Support `--encrypt` via openssl AES-256-CBC
- Support `--dry-run` (run validation + discovery, show what would be dumped, create no files/dirs)
- Support `--retain-successful` / `--retain-partial` via retention module

### Step 10: Manifest Generation (`manifest.py`)
- `create()` - write initial manifest with `"status": "initialized"` (called before any dump)
- `set_status(status)` - update top-level status (`running`, `success`, `partial`, `failed`)
- `add_file(file_entry)` - append a file result and flush to disk immediately
- `add_attempt(attempt_entry)` - append a retry attempt record
- `finalize(summary)` - set final status, `timestamp_end`, and summary block
- Compute SHA-256 checksums for each completed file
- All writes are atomic: write to `.manifest.json.tmp` then rename to `manifest.json`

### Step 11: Retention (`retention.py`)
- Scan connection directory for existing backup dirs
- Read each `manifest.json` to classify as successful or partial
- Apply retention rules based on current backup exit code
- Delete expired directories (oldest first)
- Log all deletions, warn on failures without changing exit code

### Step 12: Encryption (`utils/encryption.py`)
- Wrapper around `openssl enc` via subprocess
- `encrypt_file(input_path, output_path, key)` - AES-256-CBC with PBKDF2
- `decrypt_file(input_path, output_path, key)` - inverse for tests
- Key is passed via env var to openssl (`-pass env:BACKUP_ENCRYPT_KEY`), never as CLI arg
- Called in the dump pipeline: dump → gzip → encrypt → write

### Step 13: Restore Validation (`validation.py` - extend)
- Add restore validation steps R1→R12
- `validate_restore_args(config)` - R1 (required args)
- `validate_backup_source(config)` - R2 + R3 + R4 (dir exists, manifest valid, status check)
- `validate_driver_compatibility(config, manifest)` - R5 (backup driver matches restore driver)
- `validate_requested_items_exist(config, manifest)` - R6 (requested databases/tables exist in backup)
- `validate_backup_integrity(config)` - R7 + R8 (files exist, checksums match)
- `validate_decryption(config)` - R9 + R10 (key provided if encrypted, test decrypt)
- `validate_restore_infrastructure(config, docker_runner)` - R11 (Docker + image)
- `validate_restore_connectivity(config, docker_runner, driver)` - R12 (target DB reachable + auth)

> **Note:** The manifest tracks `mode` (the backup mode used) and `globals_included` (whether globals were backed up), which are used during restore validation.

### Step 14: Restorer (`restorer.py`)
- Main restore orchestration:
  1. Run restore validation (R1→R12) → exit 1 on any failure
  2. Write restore log with `"status": "initialized"`
  3. Update to `"status": "running"`
  4. Based on mode (`restore --full`, `restore --databases`, `restore --tables`, `restore --globals-only`):
     - Restore globals first (if applicable)
     - Create databases if they don't exist (PostgreSQL)
     - If `--drop-databases`: drop target before restoring
     - For each file: decrypt (if encrypted) → decompress (if compressed) → pipe to DB client
     - Per-operation `--timeout` (default 7200s for restore), stop on first failure
     - Flush restore log after each file
  5. Finalize restore log: set `"status"` to `success` / `partial` / `failed`
  5b. If `--verify`: run verification fingerprint against target DB, compare hashes to manifest's `"verification"` section, log PASS/FAIL per check (informational - does not change exit code). If backup was made without `--verify`, warn and skip.
  6. Return exit code: 0 / 1 / 2

### Step 15: Base Driver - Restore Methods (`drivers/base.py` - extend)
- Add restore interface to base driver:
  - `restore_globals(sql_stream)` - pipe globals SQL into server
  - `create_database(database)` - create DB if not exists
  - `drop_database(database)` - drop DB (for `--drop-databases`)
  - `restore_schema(database, schema_name, sql_stream)` - pipe schema SQL into DB
  - `restore_table(database, schema_name, table_name, sql_stream)` - pipe table SQL into DB
  - `check_database_exists(database) -> bool` - for safety check before restore
- Implement in PostgreSQL, MySQL, MariaDB drivers

### Step 16: Logging & Utils (`utils/`)
- Structured logger to stderr
- SHA-256 checksum utility (computed **after** encryption, on the final file)
- File size formatting
- **Credential redaction** - utility to scrub any credential from log output

### Step 17: Entry Point (`entrypoint.py`)
- Parse subcommand: `backup` or `restore` (first positional argument)
- `backup`: parse backup args → build config → instantiate driver → run orchestrator
- `restore`: parse restore args (including `restore --from`) → build config → read manifest → instantiate driver → run restorer
- If no subcommand or unrecognized subcommand → print usage and exit 1
- Top-level exception handling → exit code 1 (fatal)

### Step 18: Dockerfile
- Build the orchestrator image
- Test locally:
  ```bash
  docker build -t db-backup-orchestrator .
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v $(pwd)/test-backups:/backups \
    -e DB_USER=postgres \
    -e DB_PASSWORD=test \
    db-backup-orchestrator backup \
    --driver postgres --version 16 \
    --host localhost --port 5432 \
    --connection local-test \
    --full --verbose
  ```
