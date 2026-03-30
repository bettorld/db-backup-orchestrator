# DB Backup Orchestrator - Restore Validation Pipeline (R1-R12)

← [Back to index](../README.md)

## Restore Validation Pipeline

All validation runs **before any data is written to the target DB**. A validation failure produces a clean exit 1. Each step has its own timeout to prevent the script from hanging indefinitely.

| Step | Check | Failure |
|---|---|---|
| R1 | Required args present | Exit 1: `Missing --from` |
| R2 | Backup directory exists | Exit 1: `Backup directory not found` |
| R3 | `manifest.json` is valid and readable | Exit 1: `Invalid or missing manifest.json` |
| R4 | Manifest status is `success` or `partial` | Exit 1 on `initialized`/`running` (corrupted backup). `[WARN]` on `partial` (some files may be missing). |
| R5 | Driver compatibility | Exit 1 if manifest driver does not match target. `[WARN]` on version mismatch (unless `--version-override`). |
| R6 | Requested databases/tables exist in manifest | Exit 1: `Database 'sales' not found in backup manifest. Available: [app_production, analytics]` |
| R7 | Requested files exist in backup | Exit 1: `File {name} listed in manifest but missing from disk` |
| R8 | Checksums match (SHA-256 verification) | Exit 1: `Checksum mismatch for {file} - backup may be corrupted` |
| R9 | If backup is encrypted, `--encrypt-key` is provided | Exit 1: `Backup is encrypted but no --encrypt-key provided` |
| R10 | Decryption test (decrypt first file header) | Exit 1: `Decryption failed - wrong key?` |
| R11 | Docker socket + image available | Exit 1: `Docker not available` / `Image not found` |
| R12 | Target DB reachable + auth works | Exit 1: `Target DB unreachable` / `Auth failed` |

### Validation log output

```
[INFO] [R1] Arguments validated.
[INFO] [R2] Backup directory found: /backups/prod-main/2026-03-18.001
[INFO] [R3] Manifest loaded: status=success, 4 files, driver=postgres:16
[INFO] [R4] Backup status: success.
[INFO] [R5] Driver compatibility: manifest=postgres:16, target=postgres. OK.
[INFO] [R6] Requested databases found in manifest: [app_production].
[INFO] [R7] All 4 backup files present on disk.
[INFO] [R8] Checksums verified for all 4 files.
[INFO] [R9] Backup is encrypted - decryption key provided.
[INFO] [R10] Decryption test passed.
[INFO] [R11] Docker available, image postgres:16 ready.
[INFO] [R12] Target DB reachable: staging-db.example.com:5432.
[INFO] Validation complete - starting restore.
```

### Step R1: Required arguments

**When:** Immediately on startup (arg parsing)
**Timeout:** None (instant, offline)

Validates that `restore --from`, `--host`, `--user`, and `--password` are provided (via CLI or env var). Also validates that exactly one restore mode is selected (`--full`, `--databases`, `--tables`, `--globals-only`).

### Step R2: Backup directory exists

**When:** After arg parsing
**Timeout:** None (instant, local)

Verifies the path specified by `--from` exists and is a directory.

### Step R3: Manifest is valid

**When:** After directory check
**Timeout:** None (instant, local)

Reads `manifest.json` from the backup directory. Validates it is valid JSON and contains the required fields (`version`, `status`, `driver`, `driver_version`, `mode`, `globals_included`, `files`).

### Step R4: Manifest status check

**When:** After manifest is loaded
**Timeout:** None (instant, local)

- `status: "success"` - proceed normally
- `status: "partial"` - log `[WARN]` that some files may be missing, proceed
- `status: "initialized"` or `"running"` - exit 1 (backup was interrupted, cannot safely restore)
- `status: "failed"` - exit 1 (no successful dumps to restore)

### Step R5: Driver compatibility

**When:** After manifest status is confirmed
**Timeout:** None (instant, local)

Cross-driver restore is **blocked**: the manifest `driver` must match the target. If `--driver` is passed explicitly and does not match the manifest, the script exits 1:

```
[ERROR] Fatal: Cross-driver restore is not supported. Backup driver: postgres, requested: mysql.
```

If the manifest `driver_version` does not match the version that would be used for restore, the script logs a warning:

```
[WARN] Manifest version is 15, but restore will use postgres:16. Use --version-override to acknowledge.
```

Without `--version-override`, a version mismatch exits 1. With `--version-override`, the warning is logged and restore proceeds.

### Step R6: Requested databases/tables exist in manifest

**When:** After driver compatibility check
**Timeout:** None (instant, local)

When `--databases` or `--tables` is used, validates that every requested item exists in the backup manifest. If a requested database or table is not found:

```
[ERROR] Fatal: Database 'sales' not found in backup manifest. Available: [app_production, analytics]
```

```
[ERROR] Fatal: Table 'app_production.sales.orders' not found in backup manifest. Available: [app_production.public.users, app_production.public.accounts]
```

This prevents confusing errors later in the restore pipeline.

### Step R7: Backup files exist on disk

**When:** After item existence check
**Timeout:** None (instant, local)

For each file listed in `manifest.files[]` that will be restored, verify the corresponding file exists on disk in the backup directory.

### Step R8: Checksum verification

**When:** After file existence check
**Timeout:** Proportional to file sizes

Computes SHA-256 for each file and compares against `checksum_sha256` in the manifest. Any mismatch indicates corruption (disk error, partial write, tampering).

### Step R9: Encryption key check

**When:** After checksums pass
**Timeout:** None (instant)

If `manifest.encrypt` is `true`, verifies that `--encrypt-key` or `BACKUP_ENCRYPT_KEY` env var is provided. If the backup is not encrypted but a key is provided, logs `[WARN]` and ignores.

### Step R10: Decryption test

**When:** After key is confirmed available (only if encrypted)
**Timeout:** 10 seconds

Attempts to decrypt the first few bytes of the first backup file to verify the key is correct. This catches wrong-key errors before starting the full restore.

### Step R11: Docker + image available

**When:** After decryption test (or after R9 if not encrypted)
**Timeout:** 5s for Docker socket, 60s for image pull

Same as backup validation - verifies Docker daemon is reachable and the required DB image (`driver:version` from manifest) is available locally or can be pulled. If `--version-override` is used, the overridden version image is checked instead.

### Step R12: Target DB reachable + auth

**When:** After Docker/image check
**Timeout:** `--connect-timeout` (default 30s)

Connects to the **target** database host with the provided credentials and runs a health check (`SELECT 1`). This validates that the restore target is accessible before any data is written.
