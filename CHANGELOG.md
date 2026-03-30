# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-03-30

### Added

- Full and selective backup (databases, schemas, tables, globals)
- Full and selective restore with drop/recreate support
- PostgreSQL, MySQL, and MariaDB drivers
- Docker-out-of-Docker (DooD) architecture
- AES-256 encryption at rest
- Gzip compression (on by default)
- Post-backup and post-restore verification fingerprints
- SHA-256 checksum validation
- Manifest lifecycle with crash recovery
- Configurable retention policy
- Retry logic for failed dumps
- Dry-run mode for backup and restore
- Credential redaction in all logs
- Containerized test suite (unit + integration)
- Multi-version integration test matrix (PostgreSQL 14-17, MySQL 8.0-8.4, MariaDB 10.6-11.4)
