# DB Backup Orchestrator

[![CI](https://github.com/bettorld/db-backup-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/bettorld/db-backup-orchestrator/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/bettorld/db-backup-orchestrator/branch/main/graph/badge.svg)](https://codecov.io/gh/bettorld/db-backup-orchestrator)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/docker/v/bettorld/db-backup-orchestrator?label=Docker%20Hub&sort=semver)](https://hub.docker.com/r/bettorld/db-backup-orchestrator)
[![GitHub Release](https://img.shields.io/github/v/release/bettorld/db-backup-orchestrator)](https://github.com/bettorld/db-backup-orchestrator/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A generic, driver-based database backup and restore tool that runs inside a Docker container. Supports PostgreSQL, MySQL, and MariaDB via ephemeral database-specific containers (Docker-out-of-Docker (DooD)).

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

## Makefile

```bash
make build            # Build container image
make build-dev        # Build with no cache
make build-test       # Build test container (pytest + ruff)
make build-multi      # Build multi-platform (amd64 + arm64)
make bake             # Build using docker-bake.hcl
make test             # Run all tests (unit + integration)
make test-unit        # Run unit tests inside container
make test-integration # Run integration tests inside container
make test-coverage    # Run unit tests with coverage report
make lint             # Lint inside container (no local ruff needed)
make format           # Auto-format code (runs locally)
make clean            # Remove images, containers, and caches
make help             # Show all available targets
```

Push is controlled via a flag, not a separate target:

```bash
make build PUSH=true                # Build and push to registry
make build IMAGE_TAG=1.0.0 PUSH=true  # Build tagged version and push
make build PUSH=true CLEAN=true     # Build, push, then clean up local images
```

**Variables:**

| Variable | Default | Description |
|---|---|---|
| `IMAGE_TAG` | `production` | Image tag |
| `PUSH` | `false` | Push after build |
| `CLEAN` | `false` | Remove local image after build |
| `PLATFORM` | `linux/amd64` | Build platform |
| `PLATFORMS` | `linux/amd64,linux/arm64` | Multi-platform list (used by `build-multi`) |

All tests and linting run **inside a container** - no Python, pytest, or ruff needed on the host machine. Only Docker is required. `Dockerfile.test` builds on top of the production image and adds pytest and ruff. `Dockerfile.test.dockerignore` allows tests through into the test image. The test image is tagged as `${DOCKER_REGISTRY}/db-backup-orchestrator:IMAGE_TAG-test` (e.g., `production-test`, `1.0.0-test`).

The Makefile uses `.SILENT` and a `print_box` helper for visual output during builds.

---

## Quick Start

### 1. Build

```bash
docker build -t db-backup-orchestrator:production .
```

### 2. Backup

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/backups:/backups \
  -e DB_USER="$DB_USER" \
  -e DB_PASSWORD="$DB_PASSWORD" \
  db-backup-orchestrator:production \
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
  db-backup-orchestrator:production \
  restore --from /backups/prod-mysql/2026-03-18.001 \
  --host staging-db.example.com \
  --full --drop-databases
```

For more examples (encryption, custom retention, restore), see the **[Usage Guide](./docs/15-usage-guide.md)**.

---

## Building the Container

### Docker build

```bash
docker build -t db-backup-orchestrator:production .
docker build -t db-backup-orchestrator:1.0.0 .
```

### Docker Buildx

```bash
docker buildx create --name dbo-builder --use
docker buildx build \
  --platform linux/amd64 \
  --tag ${DOCKER_REGISTRY}/db-backup-orchestrator:production \
  --push .
```

### Docker Bake (HCL)

```bash
docker buildx bake
DOCKER_REGISTRY=docker.io VERSION=1.0.0 docker buildx bake
```
