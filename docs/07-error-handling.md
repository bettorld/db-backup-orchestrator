# DB Backup Orchestrator - Error Handling

← [Back to index](../README.md)

## Error Handling Strategy

### Continue-on-failure with retries

The script does **not** stop on the first error. Instead:

1. Each dump operation is executed independently
2. If a dump fails, the error is logged and recorded in `manifest.json`
3. The script continues to the next schema/table
4. After all dumps in the current attempt finish, if any failed → wait `--retry-delay` seconds and **retry only the failed dumps**
5. Repeat up to `--retries` times (default 3)
6. After all attempts are exhausted, set final exit code based on results

This ensures the best possible backup (retries fix transient issues) + a clear exit code signal for the caller to act on.

### Retry Logic

| Argument | Default | Description |
|---|---|---|
| `--retries` | `3` | Max retry attempts for failed/partial dumps |
| `--retry-delay` | `300` (5 min) | Seconds to wait between retry attempts |

**How retries work:**

```
Attempt 1: dump globals, schema.public, schema.sales, schema.analytics
  → globals ✓, public ✓, sales ✗ (timeout), analytics ✗ (permission denied)

  [WARN] Attempt 1: 2/4 succeeded, 2 failed. Retrying in 300s...

  ── wait 300s ──

Attempt 2: retry only → schema.sales, schema.analytics
  → sales ✓, analytics ✗ (permission denied)

  [WARN] Attempt 2: 1/2 succeeded, 1 still failing. Retrying in 300s...

  ── wait 300s ──

Attempt 3: retry only → schema.analytics
  → analytics ✗ (permission denied)

  [WARN] Attempt 3: 0/1 succeeded. Max retries exhausted.
  [WARN] Backup partially completed. 3/4 succeeded. Failed: [analytics]

Exit 2 (partial)
```

**Retry rules:**

1. Only **failed/timed-out dumps** are retried - successful dumps are never re-run
2. On retry, the failed dump file is overwritten (not appended)
3. If a retry succeeds, the file entry in `manifest.json` is updated with the new checksum, size, and the attempt number it succeeded on
4. Each attempt is recorded in `manifest.json` → `retries.attempts[]` for full audit trail
5. The `--retry-delay` wait happens via `time.sleep()` inside the orchestrator container - no new containers are spawned during the wait
6. If `--retries 0` is passed, no retries are attempted (single-shot mode)

**What is NOT retried:**

- Fatal errors (exit 1) - bad args, Docker unavailable, DB connection failure. These indicate infrastructure problems that won't self-heal in 5 minutes
- Connectivity check failure - if the DB is unreachable before any dump starts, the script exits 1 immediately without retries. The connectivity check itself is a one-shot gate.

### Exit Codes

| Code | Meaning | Log Output |
|---|---|---|
| `0` | All dumps succeeded (possibly after retries) | `[INFO] Backup completed successfully. {N} files, {size} total. Attempts: {N}.` |
| `1` | Fatal error - could not start backup at all (bad args, Docker unavailable, DB connection refused/timeout) | `[ERROR] Fatal: {reason}. No backups were created.` |
| `2` | Partial failure - some dumps succeeded but others still failing after all retry attempts exhausted | `[WARN] Backup partially completed after {N} attempts. {succeeded}/{total} succeeded. Failed: {list}` |

**Exit 1 (fatal) triggers:**
- Invalid or missing CLI arguments
- Docker socket not available / Docker daemon not running
- DB image pull failure (network issue, image not found)
- DB connection failure (host unreachable, auth rejected, **connection timeout**)
- Output directory not writable
- All dumps failed after exhausting all retry attempts (total failure)

**Exit 2 (partial) triggers - after all retries exhausted:**
- Some schemas dumped successfully but others errored (e.g., permission denied on one schema)
- Globals dump failed but schema dumps succeeded (or vice versa)
- A single dump operation timed out (`--timeout`) but others completed

Exit 1 means "nothing useful was produced, investigate infrastructure or permissions". Exit 2 means "partial backup exists, investigate specific failures in manifest.json". The caller (CI, cron, script) can use these codes to decide on alerts.

**Log messages by exit code:**

- Exit 0: `[INFO] Backup completed successfully. {N} files, {size} bytes total. Attempts: {N}.`
- Exit 1 (validation): `[ERROR] Fatal: {reason}.`
- Exit 1 (all dumps failed): `[ERROR] Backup failed - all {N} dumps failed after {N} attempts. Failed: {list}`
- Exit 2 (partial): `[WARN] Backup partially completed after {N} attempts. {succeeded}/{total} succeeded. Failed: {list}`

### Disk Space Errors

If a dump fails due to disk full (or any I/O error during write):

1. The file is marked as `"status": "failed"` in `manifest.json`
2. The manifest is flushed to disk immediately (it is small enough to succeed even on a nearly-full disk)
3. The error is logged: `[ERROR] Dump of schema 'public' failed: No space left on device`
4. The script continues to the next dump (same behavior as any other per-file failure)
5. The failed file may be truncated or corrupt - its `checksum_sha256` will be `null` and `status` will be `"failed"`
6. At the end, the backup exits with code 2 (partial) if any dumps failed

### Restore Error Handling

Restore errors are handled differently from backup errors - the restorer **stops on first failure**. A partial restore can leave a database in an inconsistent state, so it is safer to halt immediately rather than continue. See [09-restore.md](./09-restore.md) for full details on restore error handling and exit codes.

### Timeout Handling

| Argument | Default | Description |
|---|---|---|
| `--timeout` | `1800` (30 min) | Timeout in seconds for **each individual dump operation** |
| `--connect-timeout` | `30` | Timeout in seconds for the initial DB connectivity check |

**How timeouts work:**

1. **Connection timeout (`--connect-timeout`)**: Before any dump starts, the orchestrator runs a lightweight connectivity check (e.g., `psql -c "SELECT 1"` or `mysql -e "SELECT 1"`). If this fails or exceeds `--connect-timeout` seconds, the script exits **1** immediately with:
   ```
   [ERROR] Fatal: Connection to db.prod.example.com:5432 timed out after 30s. No backups were created.
   ```

2. **Per-operation timeout (`--timeout`)**: Each dump operation (`pg_dump`, `mysqldump`, etc.) has its own timeout. If a single dump exceeds this, the Docker container is killed, the file is marked as `"status": "timeout"` in the manifest, and the orchestrator continues to the next dump. At the end, if any operation timed out, the script exits **2** (partial failure):
   ```
   [WARN] Dump of schema 'analytics' timed out after 1800s - skipping.
   [WARN] Backup partially completed. 4/5 succeeded. Failed: [analytics (timeout)]
   ```

3. Timeouts are implemented via `subprocess.run(timeout=...)` which sends `SIGKILL` to the Docker container process, and Docker's `--rm` ensures the container is cleaned up.

### Backup Retention

Retention runs automatically at the end of **every** backup - there is no way to disable it. This guarantees old backups never pile up silently and fill the disk.

| Argument | Default | Description |
|---|---|---|
| `--retain-successful` | `30` | Keep the N most recent fully successful (exit 0) backups per connection |
| `--retain-partial` | `5` | Keep the N most recent partial (exit 2) backups per connection |

**How it works:**

1. After the backup completes (regardless of exit code), the orchestrator scans `{output-dir}/{connection}/` for all existing dated backup directories
2. Each directory's `manifest.json` is read to classify it by the top-level `"status"` field:
   - `"status": "success"` → **successful**
   - `"status": "partial"` → **partial**
   - `"status": "failed"` → **partial** (treated same as partial for retention)
   - `"status": "initialized"` or `"running"` → **partial** (interrupted/crashed backup)
   - No `manifest.json` or unreadable → **partial** (corrupt directory)
3. Successful backups are sorted by timestamp, newest first. Everything beyond position N (`--retain-successful`) is deleted
4. Partial backups are sorted by timestamp, newest first. Everything beyond position N (`--retain-partial`) is deleted
5. The **current** backup is always included in the count - it's never deleted by its own retention run

**When retention deletes:**

| Current backup result | Deletes old successful? | Deletes old partial? |
|---|---|---|
| Exit 0 (all ok) | Yes, beyond limit | Yes, beyond limit |
| Exit 2 (partial) | No - don't remove good backups after a bad run | Yes, beyond limit |
| Exit 1 (fatal) | No - nothing was produced, don't touch anything | No |

This means:
- A successful run can evict both old successful and old partial backups
- A partial run can only evict old partial backups (your good backups are safe)
- A fatal run touches nothing

**Retention logging:**

```
[INFO] Retention: scanning /backups/prod-main/ - found 31 successful, 6 partial backups
[INFO] Retention: removing 1 successful backup beyond limit (30): 2026-02-15.001
[INFO] Retention: removing 1 partial backup beyond limit (5): 2026-02-20.001
```

**Retention failures are non-fatal** - if a directory can't be deleted (permissions, NFS issue), it's logged as `[WARN]` but does not change the exit code. The backup itself already completed.

### Logging

- All output goes to **stderr** (so stdout is clean for piping if needed)
- Format: `[TIMESTAMP] [LEVEL] message`
- Levels: `DEBUG`, `INFO`, `WARN`, `ERROR`
- `--verbose` enables `DEBUG` level
