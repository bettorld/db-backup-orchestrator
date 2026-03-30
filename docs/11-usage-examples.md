# DB Backup Orchestrator - Usage Examples

← [Back to index](../README.md)

## Usage Examples

### Full backup - auto-discover all databases (PostgreSQL)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --full --verbose
```

### Full backup - MySQL

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver mysql --version 8.0 \
  --host db.prod.example.com \
  --connection prod-mysql \
  --full
```

### Specific databases - PostgreSQL (all schemas auto-discovered)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --databases app_production analytics
```

### Specific databases + filtered schemas (PostgreSQL only)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --databases app_production --schemas public sales
```

### All databases, no globals

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver mysql --version 8.0 \
  --host analytics.internal --port 3306 \
  --connection prod-analytics \
  --databases-only
```

### Specific tables - PostgreSQL (db.schema.table)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --tables app_production.sales.orders app_production.sales.customers
```

### Specific tables - MariaDB (db.table)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver mariadb --version 10.11 \
  --host db.staging.example.com \
  --connection staging \
  --tables staging_app.orders staging_app.customers
```

### Globals only

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="postgres" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 15 \
  --host db.internal \
  --connection prod-roles \
  --globals-only
```

### Custom retention and retry settings

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --full \
  --retain-successful 60 --retain-partial 10 \
  --retries 5 --retry-delay 600 \
  --timeout 600 --connect-timeout 60
```

### Encrypted backup

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  -e BACKUP_ENCRYPT_KEY="my-strong-passphrase-here" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --full --encrypt
```

### Uncompressed backup

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --databases app_production --no-compress
```

### Dry run (preview commands without executing)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver postgres --version 16 \
  --host db.prod.example.com \
  --connection prod-main \
  --full --dry-run
```

### Write backup path to result file

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -v /workspace:/workspace \
  -e DB_USER="backup_admin" \
  -e DB_PASSWORD="s3cret" \
  db-backup-orchestrator:latest backup \
  --driver mysql --version 8.0 \
  --host db.prod.example.com \
  --connection prod-mysql \
  --full \
  --result-file /workspace/latest-bkp
```

The result file contains a single line like `prod-mysql/2026-03-26.001` - useful for automation scripts or downstream steps.
