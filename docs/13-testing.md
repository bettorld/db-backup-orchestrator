# DB Backup Orchestrator - Testing

← [Back to index](../README.md)

All tests run **inside a container** - no Python, pytest, or ruff needed on the host machine. Only Docker is required. `Dockerfile.test` builds on top of the production image and adds pytest and ruff. `Dockerfile.test.dockerignore` is configured to allow tests through into the test image.

```bash
make test             # Run all tests (test-unit + test-integration) inside container
make test-unit        # Run unit tests inside container
make test-integration # Run integration tests inside container
make test-coverage    # Run unit tests with coverage report inside container
make lint             # Lint inside container (no local ruff needed)
```

The test image is tagged as `${DOCKER_REGISTRY}/db-backup-orchestrator:IMAGE_TAG-test` (e.g., `production-test`, `1.0.0-test`).

## Tests - Unit

- CLI parsing and arg validation (B1, B2)
- Validation pipeline (B3-B7 with mocked Docker runner)
- Driver command generation (mock Docker runner - verify correct `docker run` commands are built)
- Manifest lifecycle (create → running → finalize, atomic writes, crash recovery)
- Retention logic (simulate directories with manifests, verify correct ones are deleted)
- Retry logic (mock failures, verify only failed dumps are retried)
- Compression pipeline (verify gzip output)
- Encryption pipeline (verify openssl commands, decrypt round-trip)
- Restore validation (R1-R12 with mocked backup dirs and manifests)
- Restorer logic (mock Docker runner, verify correct restore commands per driver)
- Restore log lifecycle (create → running → finalize)
- Verification fingerprint (backup: hash generation from mocked query results, manifest storage; restore: hash comparison, PASS/FAIL logic, skip when manifest has no verification data)
- SHA-256 checksum utility (known content, empty files, large files, binary content, missing files)
- Logging credential redaction (all 8 redaction patterns: PGPASSWORD, MYSQL_PWD, password fields, encryption keys)
- Result file writing (path written, not written when unset, bad path non-fatal)

## Tests - Integration

Full end-to-end tests using real database containers with fake data. Tests are **parametrized across multiple versions** of each engine - the same test code runs against every version automatically.

### Version matrix

Configured in `tests/integration/conftest.py`:

| Driver | Versions tested |
|---|---|
| PostgreSQL | 14, 15, 16, 17 |
| MySQL | 8.0, 8.4 |
| MariaDB | 10.6, 10.11, 11.4 |

To add or remove versions, edit the lists at the top of `conftest.py`:

```python
POSTGRES_VERSIONS = ["14", "15", "16", "17"]
MYSQL_VERSIONS = ["8.0", "8.4"]
MARIADB_VERSIONS = ["10.6", "10.11", "11.4"]
```

### How parametrized tests work

Each integration test uses a `db_instance` fixture that is parametrized over all (driver, version) combos. Pytest automatically runs the test for each version:

```python
def test_full_backup(db_instance, backup_output_dir):
    """This test runs 9 times - once per version in the matrix."""
    # db_instance.driver = "postgres", db_instance.version = "14"
    # db_instance.driver = "postgres", db_instance.version = "15"
    # ...
    # db_instance.driver = "mariadb", db_instance.version = "11.4"
```

For single-driver tests, use the driver-specific fixture:

```python
def test_pg_specific(pg_instance, backup_output_dir):
    """Runs once per PostgreSQL version (14, 15, 16, 17)."""

def test_mysql_specific(mysql_instance, backup_output_dir):
    """Runs once per MySQL version (8.0, 8.4)."""
```

### Running specific versions

```bash
# All versions, all drivers
pytest tests/integration/ -v

# Only PostgreSQL
pytest tests/integration/ -k "postgres"

# Only MySQL 8.0
pytest tests/integration/ -k "mysql_8_0"

# Only MariaDB 10.11
pytest tests/integration/ -k "mariadb_10_11"

# Only PostgreSQL 16 and MySQL 8.0
pytest tests/integration/ -k "pg_16 or mysql_8_0"
```

### Container management

Containers are spawned **directly via `docker run`** (not docker-compose) with:
- Random free port on localhost (no port conflicts between versions)
- Seed SQL mounted from `tests/fixtures/seed/{driver}/`
- Cached per session - each (driver, version) is started once and reused across all tests
- Automatic cleanup at session end

No docker-compose is needed for integration tests. The `docker-compose.yml` is kept for manual local development only.

### Test infrastructure (`tests/fixtures/`)

```
tests/
├── fixtures/
│   ├── docker-compose.yml          # optional: manual local dev (single version per driver)
│   ├── seed/
│   │   ├── postgres/
│   │   │   ├── init.sql            # create databases, schemas, tables, roles
│   │   │   └── data.sql            # insert fake data (lorem ipsum)
│   │   ├── mysql/
│   │   │   ├── init.sql            # create databases, tables, users
│   │   │   └── data.sql            # insert fake data
│   │   └── mariadb/
│   │       ├── init.sql
│   │       └── data.sql
├── integration/
│   ├── conftest.py                 # parametrized fixtures, container management
│   ├── helpers.py                  # assertion helpers
│   ├── test_postgres_backup.py
│   ├── test_mysql_backup.py
│   ├── test_mariadb_backup.py
│   ├── test_postgres_restore.py
│   ├── test_mysql_restore.py
│   └── test_mariadb_restore.py
```

> **Note:** A `docker-compose.yml` is included in `tests/fixtures/` for manual local development (spinning up a single version of each engine with fixed ports). It is **NOT** used by the test suite - the conftest handles all container lifecycle automatically.

### Seed data structure

Each engine gets 2 databases with fake data:

**PostgreSQL seed (`init.sql`):**
```sql
-- Database 1: app_store
CREATE DATABASE app_store;
\c app_store
CREATE SCHEMA inventory;
CREATE SCHEMA customers;
CREATE TABLE inventory.products (id SERIAL PRIMARY KEY, name TEXT, description TEXT, price NUMERIC);
CREATE TABLE customers.users (id SERIAL PRIMARY KEY, name TEXT, email TEXT, bio TEXT);

-- Database 2: analytics
CREATE DATABASE analytics;
\c analytics
CREATE SCHEMA reporting;
CREATE TABLE reporting.events (id SERIAL PRIMARY KEY, event_type TEXT, payload JSONB, created_at TIMESTAMP);

-- Roles
CREATE ROLE app_readonly LOGIN PASSWORD 'test-readonly-pass';
GRANT CONNECT ON DATABASE app_store TO app_readonly;
GRANT USAGE ON SCHEMA inventory TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA inventory TO app_readonly;
```

**PostgreSQL seed (`data.sql`):**
```sql
\c app_store
INSERT INTO inventory.products (name, description, price) VALUES
  ('Widget Alpha', 'Lorem ipsum dolor sit amet consectetur adipiscing elit', 29.99),
  ('Widget Beta', 'Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua', 49.99),
  -- ... 50+ rows per table
;
INSERT INTO customers.users (name, email, bio) VALUES
  ('Alice Johnson', 'alice@example.com', 'Ut enim ad minim veniam quis nostrud exercitation'),
  ('Bob Smith', 'bob@example.com', 'Duis aute irure dolor in reprehenderit in voluptate'),
  -- ... 50+ rows
;
\c analytics
INSERT INTO reporting.events (event_type, payload, created_at) VALUES
  ('page_view', '{"page": "/home", "user_id": 1}', '2026-03-01 10:00:00'),
  -- ... 100+ rows
;
```

**MySQL/MariaDB seed** - similar structure but using databases instead of schemas.

### Test matrix

Each integration test runs the actual `db_backup_orchestrator` orchestrator against the seeded container and validates the output.

**Per driver (PostgreSQL, MySQL, MariaDB):**

| Test | Mode | Flags | Validates |
|---|---|---|---|
| `test_full_backup` | `backup --full` | - | Globals file exists, all databases have subfolders, all schemas dumped, manifest status = success |
| `test_full_backup_compressed` | `backup --full` | (default) | All files end in `.gz`, can be gunzipped |
| `test_full_backup_no_compress` | `backup --full` | `--no-compress` | All files end in `.sql`, no gzip header |
| `test_full_backup_encrypted` | `backup --full` | `--encrypt` | All files end in `.gz.enc`, can be decrypted with key |
| `test_specific_databases` | `backup --databases app_store` | - | Only `app_store/` subfolder exists, no `analytics/` |
| `test_databases_only` | `backup --databases-only` | - | All database subfolders exist, no `globals.sql` |
| `test_filtered_schemas` | `backup --databases app_store` | `--schemas inventory` | Only `app_store/schema.inventory.sql` exists (PG only) |
| `test_schemas_ignored_mysql` | `backup --databases app_store` | `--schemas inventory` | `[WARN]` logged, schemas ignored (MySQL/MariaDB only) |
| `test_specific_tables` | `backup --tables ...` | - | Only specified table files exist |
| `test_globals_only` | `backup --globals-only` | - | Only `globals.sql` exists, no database subfolders |
| `test_manifest_success` | `backup --full` | - | manifest.json: status=success, all files listed, checksums valid |
| `test_manifest_partial` | `backup --databases nonexistent real_db` | - | manifest.json: status=partial, failed file has error |
| `test_retry_on_failure` | `backup --databases ...` | `--retries 2` | manifest.json: attempts[] has >1 entry if failure occurred |
| `test_retention` | `backup --full` | `--retain-successful 2` | Old backups beyond limit are deleted |
| `test_dry_run` | `backup --full` | `--dry-run` | No files or directories created, discovery results printed |
| `test_exit_code_0` | `backup --full` | - | Process exits 0 |
| `test_exit_code_1_bad_host` | `backup --full` | `--host nonexistent` | Process exits 1 |
| `test_exit_code_1_bad_driver` | `backup --full` | `--driver mssql` | Process exits 1 |
| `test_exit_code_2_partial` | `backup --databases real_db nonexistent` | - | Process exits 2, real_db dumped, nonexistent failed |
| `test_counter_increments` | `backup --full` (run twice) | - | First run creates `.001`, second creates `.002` |

**Restore tests (per driver) - run a backup first, then test restore:**

| Test | Mode | Flags | Validates |
|---|---|---|---|
| `test_restore_full` | `restore --full` | `--drop-databases` | All data restored, tables exist and contain data, globals users created |
| `test_restore_specific_database` | `restore --databases app_store` | `--drop-databases` | Only `app_store` restored, `analytics` untouched |
| `test_restore_specific_tables` | `restore --tables ...` | `--drop-databases` | Only specified tables restored |
| `test_restore_globals_only` | `restore --globals-only` | - | Roles recreated on target |
| `test_restore_encrypted` | `restore --full` | `--drop-databases` | Backup with `--encrypt`, restore with same key succeeds |
| `test_restore_wrong_key` | `restore --full` | wrong `--encrypt-key` | Exit 1, decryption test fails at R10 |
| `test_restore_no_drop_databases` | `restore --full` | (no `--drop-databases`) | Exit 1 if target DB already exists |
| `test_restore_drop_users` | `restore --full` | `--drop-databases --drop-users` | Non-system users dropped before globals restore, then recreated from backup |
| `test_restore_dry_run` | `restore --full` | `--dry-run` | No data written to target, commands printed |
| `test_restore_log_created` | `restore --full` | `--drop-databases` | `restore.YYYY-MM-DD.001.json` exists in backup dir with correct status |
| `test_restore_exit_code_0` | `restore --full` | `--drop-databases` | Process exits 0 |
| `test_restore_exit_code_1_bad_source` | `restore --full` | `restore --from /nonexistent` | Process exits 1 |
| `test_restore_checksum_mismatch` | `restore --full` | corrupt a file | Exit 1 at R8, checksum mismatch |
| `test_restore_no_credentials_in_log` | `restore --full` | `--drop-databases` | Restore log JSON contains no `user`, `password`, or key fields |
| `test_restore_nonexistent_database` | `restore --databases nonexistent` | `--from` valid backup | Exit 1, requested database not found in backup manifest (R6) |
| `test_restore_cross_driver_blocked` | `restore --full` | backup from postgres, `--driver mysql` | Exit 1, driver mismatch detected at R5 |
| `test_restore_version_mismatch_warning` | `restore --full` | backup from postgres:15 | Restore uses postgres:15 (from manifest), logs version match |
| `test_restore_version_override` | `restore --full` | `--version-override 16` on postgres:15 backup | Succeeds with `[WARN]` about version mismatch |
| `test_restore_databases_only` | `restore --databases-only` | `--drop-databases` | All databases restored, no globals |
| `test_backup_verify` | `backup --full` | `--verify` | Manifest contains `verification` section with `combined` hash and all 9-10 check hashes |
| `test_restore_verify_pass` | `restore --full` | `--drop-databases --verify` | All verification checks log PASS, exit code 0 |
| `test_restore_verify_no_backup_verify` | `restore --full` | `--drop-databases --verify` (backup made without `--verify`) | Warning logged, verification skipped, exit code 0 |
| `test_restore_verify_mismatch` | `restore --full` | `--drop-databases --verify` (target modified after restore) | Mismatched checks log WARN, exit code still 0 |

### Validation helpers (`tests/integration/helpers.py`)

```python
def assert_file_is_gzipped(path):
    """Verify file has gzip magic bytes (1f 8b)."""

def assert_file_is_encrypted(path):
    """Verify file is not readable as plain text or gzip."""

def assert_file_decrypts(path, key):
    """Decrypt file with key and verify it produces valid SQL."""

def assert_manifest_valid(path, expected_status, expected_files):
    """Load manifest.json, check status, file list, checksums."""

def assert_sql_contains(path, expected_strings):
    """Decompress/decrypt if needed, verify SQL contains expected content."""

def assert_checksum_matches(path, expected_sha256):
    """Verify file SHA-256 matches manifest entry."""

def wait_for_healthy(container_name, timeout=30):
    """Poll docker inspect until container is healthy."""
```

### Running integration tests

All tests run inside containers. The `conftest.py` fixtures handle all DB container lifecycle automatically - no manual setup required.

```bash
# Run all tests (unit + integration) inside container
make test

# Run only integration tests inside container
make test-integration

# Clean up any leftover test containers and .ruff_cache
make clean
```
