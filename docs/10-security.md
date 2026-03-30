# DB Backup Orchestrator - Security

← [Back to index](../README.md)

## Security Considerations

- **Credentials are NEVER written to disk** - not in `manifest.json`, not in restore logs, not in any persisted file. Only `host`, `port`, and `driver` are recorded.
- **Credentials are NEVER logged** - even in `--verbose` mode, `DB_USER`, `DB_PASSWORD`, `BACKUP_ENCRYPT_KEY`, `PGPASSWORD`, `MYSQL_PWD`, and other sensitive values are redacted in all log output via pattern-based scrubbing
- **Credentials are passed only as ephemeral container env vars** (`-e PGPASSWORD=...`) which are not visible in `docker ps` output and are destroyed when the container exits
- **No credentials in the Docker image** - everything is passed at runtime
- **Docker socket access** - the orchestrator container needs access to the host Docker socket; this is a privileged operation that should be restricted to authorized users/jobs only
- **Dump files may contain sensitive data** - use `--encrypt` for at-rest protection, and restrict the NFS mount / `/backups` directory permissions
- `--dry-run` mode redacts passwords and encryption keys in printed commands
- **Path traversal protection** - database, schema, and table names are sanitized before use in file paths. Characters like `/`, `\`, null bytes, and leading dots are stripped to prevent writing outside the backup directory.
- **SQL injection protection** - database names used in `check_database_exists()` queries are escaped (single quotes doubled) to prevent SQL injection via malicious manifest data.
- **Manifest thread safety** - all manifest mutations are protected by a lock, ensuring safe concurrent access during parallel dumps (`--parallel`).
- **Signal handling** - the entrypoint handles `SIGTERM` and `SIGINT` for graceful shutdown when the container is stopped.
