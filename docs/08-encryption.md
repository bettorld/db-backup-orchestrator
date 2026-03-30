# DB Backup Orchestrator - Encryption

← [Back to index](../README.md)

## Encryption

Backup files may contain sensitive data (user records, credentials, business data). Encryption ensures files are safe at rest, even on shared storage like NFS.

### How it works

| Argument | Env Var | Description |
|---|---|---|
| `--encrypt` | - | Enable encryption (off by default) |
| `--encrypt-key` | `BACKUP_ENCRYPT_KEY` | Passphrase for AES-256 encryption (required if `--encrypt` is used) |

**Pipeline per file:** dump → gzip (default) → encrypt → write to disk

```
pg_dump ... | gzip | openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_ENCRYPT_KEY > schema.public.sql.gz.enc
```

### Implementation

Uses `openssl enc` (available in the Python slim image via `openssl` package) with:
- **Algorithm:** AES-256-CBC
- **Key derivation:** PBKDF2 (resistant to brute-force)
- **Passphrase:** from `BACKUP_ENCRYPT_KEY` env var - never written to disk or logs
- **Salt:** random per file (default OpenSSL behavior)

### File extensions

| Compression | Encryption | Extension |
|---|---|---|
| Yes (default) | No | `.sql.gz` |
| Yes (default) | Yes | `.sql.gz.enc` |
| No (`--no-compress`) | No | `.sql` |
| No (`--no-compress`) | Yes | `.sql.enc` |

### Manual Decryption and Restore (without the pipeline)

If you need to manually decrypt, decompress, and restore a backup file without using the orchestrator, follow these steps.

#### 1. Find the backup files

```bash
# List the backup directory contents
ls -la /path/to/backups/vanguard_dev/2026-03-26.001/

# You'll see something like:
# manifest.json
# globals.sql.gz.enc
# vanguard/full.sql.gz.enc
# homs/full.sql.gz.enc
```

Check the manifest to see what was backed up:

```bash
cat /path/to/backups/vanguard_dev/2026-03-26.001/manifest.json | python3 -m json.tool
```

#### 2. Decrypt a file

```bash
# Encrypted + compressed (.sql.gz.enc) - most common
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in vanguard/full.sql.gz.enc \
  -out vanguard/full.sql.gz \
  -pass pass:YOUR_ENCRYPTION_KEY

# Encrypted only (.sql.enc) - if backup used --no-compress
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in vanguard/full.sql.enc \
  -out vanguard/full.sql \
  -pass pass:YOUR_ENCRYPTION_KEY
```

> **Tip:** Use `-pass env:BACKUP_ENCRYPT_KEY` instead of `-pass pass:...` to avoid the key appearing in your shell history:
> ```bash
> export BACKUP_ENCRYPT_KEY="your-key-here"
> openssl enc -d -aes-256-cbc -pbkdf2 -in file.sql.gz.enc -out file.sql.gz -pass env:BACKUP_ENCRYPT_KEY
> ```

#### 3. Decompress

```bash
# If the file was compressed (default)
gunzip vanguard/full.sql.gz
# Result: vanguard/full.sql
```

Or decrypt + decompress in one step (piped):

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
  -pass pass:YOUR_KEY \
  -in vanguard/full.sql.gz.enc | gunzip > vanguard/full.sql
```

#### 4. Inspect the SQL (optional)

```bash
# Check the first few lines
head -50 vanguard/full.sql

# For MySQL --databases dumps, you'll see:
# CREATE DATABASE /*!32312 IF NOT EXISTS*/ `vanguard` ...
# USE `vanguard`;
# CREATE TABLE ...
```

#### 5. Restore to a database

**MySQL / MariaDB:**

```bash
# Schema dump (mysqldump --databases) - includes CREATE DATABASE + USE
mysql -h TARGET_HOST -P TARGET_PORT -u root -p < vanguard/full.sql

# Globals (users/grants)
mysql -h TARGET_HOST -P TARGET_PORT -u root -p < globals.sql

# If you need to drop the database first:
mysql -h TARGET_HOST -P TARGET_PORT -u root -p -e "DROP DATABASE IF EXISTS vanguard;"
mysql -h TARGET_HOST -P TARGET_PORT -u root -p < vanguard/full.sql
```

**PostgreSQL:**

```bash
# Schema dump - restore into a specific database
psql -h TARGET_HOST -p TARGET_PORT -U postgres -d app_store < app_store/schema.public.sql

# Globals (roles/users)
psql -h TARGET_HOST -p TARGET_PORT -U postgres -d postgres < globals.sql

# If you need to drop and recreate the database first:
psql -h TARGET_HOST -p TARGET_PORT -U postgres -d postgres -c 'DROP DATABASE IF EXISTS "app_store";'
psql -h TARGET_HOST -p TARGET_PORT -U postgres -d postgres -c 'CREATE DATABASE "app_store";'
psql -h TARGET_HOST -p TARGET_PORT -U postgres -d app_store < app_store/schema.public.sql
```

#### 6. Verify checksums (optional)

```bash
# Compare the SHA-256 of the encrypted file against the manifest
sha256sum vanguard/full.sql.gz.enc
# Compare output with manifest.json → files[].checksum_sha256
```

#### Quick reference - decrypt + decompress + restore in one line

```bash
# MySQL: decrypt → decompress → restore (piped, no intermediate files)
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_ENCRYPT_KEY \
  -in vanguard/full.sql.gz.enc | gunzip | \
  mysql -h TARGET_HOST -P TARGET_PORT -u root -p

# PostgreSQL: decrypt → decompress → restore
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_ENCRYPT_KEY \
  -in app_store/schema.public.sql.gz.enc | gunzip | \
  psql -h TARGET_HOST -p TARGET_PORT -U postgres -d app_store
```

### Validation

- If `--encrypt` is passed without `--encrypt-key` or `BACKUP_ENCRYPT_KEY` → exit 1:
  ```
  [ERROR] Fatal: --encrypt requires --encrypt-key or BACKUP_ENCRYPT_KEY env var.
  ```
- If `--encrypt-key` is passed without `--encrypt` → `[WARN]` and ignored
- The encryption key is **never logged**, even in `--verbose` mode
- The manifest records `"encrypt": true` and `"encrypt_algorithm": "aes-256-cbc"` but never the key
