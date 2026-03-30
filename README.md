# DB Backup Orchestrator

[![CI](https://github.com/bettorld/db-backup-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/bettorld/db-backup-orchestrator/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/bettorld/db-backup-orchestrator/branch/main/graph/badge.svg)](https://codecov.io/gh/bettorld/db-backup-orchestrator)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![GHCR](https://img.shields.io/badge/GHCR-bettorld%2Fdb--backup--orchestrator-blue?logo=github)](https://github.com/bettorld/db-backup-orchestrator/pkgs/container/db-backup-orchestrator)
[![GitHub Release](https://img.shields.io/github/v/release/bettorld/db-backup-orchestrator)](https://github.com/bettorld/db-backup-orchestrator/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A generic, driver-based database backup and restore tool that runs entirely inside a Docker container. It spins up ephemeral database-specific containers using Docker-out-of-Docker (DooD) to perform backups and restores — no database client tools needed on the host.

## Supported Databases

| Engine | Tested Versions | Driver |
|---|---|---|
| **PostgreSQL** | 14, 15, 16, 17 | `postgres` |
| **MySQL** | 8.0, 8.4 | `mysql` |
| **MariaDB** | 10.6, 10.11, 11.4 | `mariadb` |

Other versions may work but are not part of the integration test matrix.

## Features

- **Full and selective backup** — all databases, specific databases, schemas, tables, or globals only
- **Full and selective restore** — with `--drop-databases`, `--drop-users`, and database/table filtering
- **Compression** — gzip on by default (`--no-compress` to disable)
- **Encryption** — AES-256 encryption at rest via `--encrypt`
- **Verification** — post-backup and post-restore fingerprint comparison via `--verify`
- **Checksums** — SHA-256 validation for every dumped file
- **Manifests** — JSON manifest per backup with status, file list, checksums, and crash recovery
- **Retention** — automatic cleanup of old backups via `--retain-successful`
- **Retries** — configurable retry logic for failed dumps
- **Dry-run** — preview what would happen without writing anything
- **Credential redaction** — passwords and keys are never logged
- **Containerized testing** — no local Python needed, all tests run inside Docker

## Prerequisites

- Docker

That's it. Everything else (Python, database clients, test tools) runs inside containers.

---

## Quick Start

### 1. Build

```bash
docker build -t db-backup-orchestrator:latest .
```

### 2. Backup

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:latest \
  backup --full \
  --driver mysql --version 8.0 \
  --host db.prod.example.com \
  --connection prod-mysql
```

### 3. Restore

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:latest \
  restore --from /backups/prod-mysql/2026-03-18.001 \
  --host staging-db.example.com \
  --full --drop-databases
```

For more examples (encryption, custom retention, restore), see the **[Usage Guide](./docs/15-usage-guide.md)**.

---

## Configuration

Copy the example environment file and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `DOCKER_REGISTRY` | `ghcr.io/bettorld` | Registry prefix for image tags |

The `.env` file is loaded by the Makefile and `docker buildx bake` automatically.

---

## Building

```bash
make build                          # Build image
make build IMAGE_TAG=1.0.0         # Build with custom tag
make build PUSH=true               # Build and push to registry
make build-dev                      # Build with no cache
make build-multi                    # Build multi-platform (amd64 + arm64)
make bake                           # Build using docker-bake.hcl
```

| Variable | Default | Description |
|---|---|---|
| `IMAGE_TAG` | `latest` | Image tag |
| `PUSH` | `false` | Push after build |
| `CLEAN` | `false` | Remove local image after build |
| `PLATFORM` | `linux/amd64` | Build platform |
| `PLATFORMS` | `linux/amd64,linux/arm64` | Multi-platform list (used by `build-multi`) |

---

## Testing

All tests run **inside containers** — no Python, pytest, or ruff needed on the host.

```bash
make test             # Run all tests (unit + integration)
make test-unit        # Unit tests only
make test-coverage    # Unit tests with coverage report
make test-integration # Integration tests (requires Docker socket)
make lint             # Lint with ruff (check + format)
make format           # Auto-format code (runs locally)
make clean            # Remove images, containers, and caches
```

See [Testing docs](./docs/13-testing.md) for details on the integration test matrix and fixtures.

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](./docs/01-architecture.md) | System overview, DooD approach, architecture diagram |
| [CLI Reference](./docs/02-cli-reference.md) | All arguments, modes, flags, and env vars |
| [Backup Validation](./docs/03-backup-validation.md) | Backup validation pipeline (B1-B7) |
| [Restore Validation](./docs/04-restore-validation.md) | Restore validation pipeline (R1-R12) |
| [Output Structure](./docs/05-output-structure.md) | Directory layout, naming conventions, manifest lifecycle |
| [Drivers](./docs/06-drivers.md) | PostgreSQL, MySQL, MariaDB implementation details |
| [Error Handling](./docs/07-error-handling.md) | Retries, timeouts, exit codes, retention |
| [Encryption](./docs/08-encryption.md) | AES-256 encryption at rest |
| [Restore](./docs/09-restore.md) | Restore CLI, restore log |
| [Security](./docs/10-security.md) | Credential handling, security guarantees |
| [Usage Examples](./docs/11-usage-examples.md) | Backup and restore command examples |
| [Project Structure](./docs/12-project-structure.md) | File layout and implementation steps |
| [Testing](./docs/13-testing.md) | Unit tests, integration tests, test fixtures |
| [Dockerfile](./docs/14-dockerfile.md) | Container build configuration |
| **[Usage Guide](./docs/15-usage-guide.md)** | **Prerequisites, env vars, encryption key setup, docker run examples** |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and PR guidelines.

## License

[MIT](LICENSE)
