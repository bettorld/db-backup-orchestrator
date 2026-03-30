# Contributing

Thanks for your interest in contributing to DB Backup Orchestrator!

## Prerequisites

- Docker (all tests run inside containers — no local Python needed)
- Make

## Getting Started

```bash
git clone https://github.com/bettorld/db-backup-orchestrator.git
cd db-backup-orchestrator
cp .env.example .env      # adjust DOCKER_REGISTRY if needed
make help                  # see all available targets
```

## Running Tests

```bash
make test             # unit + integration tests
make test-unit        # unit tests only
make test-coverage    # unit tests with coverage report
make test-integration # integration tests (requires Docker socket)
make lint             # ruff check + format check
```

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting. Run `make format` to auto-format locally, or `make lint` to check inside a container.

## Pull Requests

1. Fork the repo and create a feature branch from `main`
2. Make your changes
3. Ensure `make lint` and `make test` pass
4. Open a PR with a clear description of what and why

## Reporting Issues

Open a GitHub issue with:
- What you expected
- What happened instead
- Steps to reproduce
- Driver/version if relevant (e.g., PostgreSQL 16, MySQL 8.4)

## Security

If you find a security vulnerability, please open a GitHub issue or contact the maintainers directly rather than posting publicly.
