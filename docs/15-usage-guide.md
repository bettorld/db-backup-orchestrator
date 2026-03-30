# DB Backup Orchestrator - Usage Guide

← [Back to index](../README.md)

## Prerequisites

### Required

- **Docker** - the orchestrator container and all DB client containers run via Docker
- **Docker socket access** - the host's `/var/run/docker.sock` must be mounted into the container

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DB_USER` | Yes | Database user for backup/restore |
| `DB_PASSWORD` | Yes | Database password |
| `BACKUP_ENCRYPT_KEY` | Only if `--encrypt` | Passphrase for AES-256 encryption/decryption |

**Never hardcode credentials.** Pass them as environment variables at runtime.

### Generating an encryption key

```bash
# Option 1: Random 32-character passphrase
openssl rand -base64 32

# Option 2: Random 64-character hex string
openssl rand -hex 32
```

Store the key securely (vault, secrets manager, etc.) - you'll need the **same key** to restore encrypted backups.

---

## Exit Codes

| Code | Meaning | Action |
|---|---|---|
| `0` | All operations succeeded | No action needed |
| `1` | Fatal error - could not start (bad args, Docker unavailable, DB unreachable) or all dumps failed | Investigate infrastructure |
| `2` | Partial failure - some operations failed after retries (backup) or stopped mid-way (restore) | Check `manifest.json` or restore log for details |

In automation systems, both exit 1 and exit 2 are non-zero and can trigger alert handlers.

---

## Backup Examples

### Full backup - MySQL

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --full \
  --driver mysql --version 8.0 \
  --host mysql.prod.internal \
  --connection prod-mysql
```

### Full backup with encryption

```bash
# Generate key once, store securely
export BACKUP_ENCRYPT_KEY=$(openssl rand -base64 32)

docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  -e BACKUP_ENCRYPT_KEY="$BACKUP_ENCRYPT_KEY" \
  db-backup-orchestrator:production \
  backup --full --encrypt \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main
```

### All databases without globals

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --databases-only \
  --driver mysql --version 8.0 \
  --host mysql.prod.internal \
  --connection prod-mysql
```

### Filtered schemas - PostgreSQL

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --databases app_production --schemas public sales \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main
```

### Specific tables - MariaDB

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --tables app_db.orders app_db.customers \
  --driver mariadb --version 10.11 \
  --host maria.prod.internal \
  --connection prod-mariadb
```

### Globals only

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --globals-only \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-roles
```

### Custom retention and retries

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --full \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --retain-successful 60 --retain-partial 10 \
  --retries 5 --retry-delay 600 \
  --timeout 600
```

### Uncompressed backup

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --databases app_production --no-compress \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main
```

### Backup with verification fingerprint

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --full --verify --verbose \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main
```

### Write backup path to a result file

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --full \
  --driver mysql --version 8.0 \
  --host mysql.prod.internal \
  --connection prod-mysql \
  --result-file /backups/latest-bkp
```

The result file contains a single line like `prod-mysql/2026-03-18.001` - useful for automation scripts or build descriptions.

### Dry run (validate + discover, no files created)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  backup --full --dry-run \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main
```

---

## Restore Examples

### Full restore to staging

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full --drop-databases
```

### Restore encrypted backup

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  -e BACKUP_ENCRYPT_KEY="$BACKUP_ENCRYPT_KEY" \
  db-backup-orchestrator:production \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full --drop-databases
```

### Restore single database

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --databases app_production --drop-databases
```

### Restore globals only

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --globals-only
```

### Restore with drop users

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full --drop-databases --drop-users
```

### Restore with verification

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full --drop-databases --verify --verbose
```

### Restore dry run

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
  restore --from /backups/prod-main/2026-03-18.001 \
  --host staging-db.example.com \
  --full --dry-run
```
