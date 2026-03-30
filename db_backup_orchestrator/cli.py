"""CLI argument parsing with env-var fallbacks.

Returns a BackupConfig or RestoreConfig dataclass depending on the
chosen subcommand.
"""

import argparse
import os
import sys
from typing import Union

from db_backup_orchestrator.config import (
    BackupConfig,
    RestoreConfig,
)


def _env(name: str, *alt_names: str) -> str | None:
    """Return the first set env var among *name* and *alt_names*."""
    for n in (name, *alt_names):
        val = os.environ.get(n)
        if val:
            return val
    return None


def _build_shared_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by both backup and restore subcommands."""
    parser.add_argument("--host", default=None, help="Database host")
    parser.add_argument("--port", type=int, default=None, help="Database port")
    parser.add_argument("--user", default=None, help="Database user")
    parser.add_argument("--password", default=None, help="Database password")
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=None,
        help="Timeout for DB connectivity check (default 30)",
    )
    parser.add_argument("--encrypt-key", default=None, help="Encryption passphrase")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without executing"
    )
    parser.add_argument("--verbose", action="store_true", help="Detailed output")
    parser.add_argument(
        "--docker-network",
        default=None,
        help="Docker network for ephemeral containers (default: host)",
    )
    parser.add_argument(
        "--docker-platform",
        default=None,
        help="Docker platform for ephemeral containers (default: linux/amd64)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run verification fingerprint after backup/restore",
    )


def _build_mode_args(parser: argparse.ArgumentParser) -> None:
    """Add mutually-exclusive mode arguments used by both subcommands."""
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--full", action="store_true", help="Full backup/restore")
    mode_group.add_argument(
        "--databases",
        nargs="+",
        metavar="DB",
        default=None,
        help="Specific database(s)",
    )
    mode_group.add_argument(
        "--tables",
        nargs="+",
        metavar="TABLE",
        default=None,
        help="Specific table(s)",
    )
    mode_group.add_argument(
        "--globals-only",
        action="store_true",
        help="Globals only (roles/users/permissions)",
    )
    mode_group.add_argument(
        "--databases-only",
        action="store_true",
        help="All databases, no globals",
    )


def _build_backup_parser(subparsers: argparse._SubParsersAction) -> None:
    bp = subparsers.add_parser("backup", help="Run a database backup")
    _build_shared_args(bp)
    _build_mode_args(bp)

    # Backup-only required
    bp.add_argument(
        "--driver", default=None, help="Database engine (postgres, mysql, mariadb)"
    )
    bp.add_argument("--version", default=None, help="Engine version (Docker image tag)")
    bp.add_argument("--connection", default=None, help="Logical connection name")

    # Backup-only optional
    bp.add_argument(
        "--schemas",
        nargs="+",
        metavar="SCHEMA",
        default=None,
        help="PostgreSQL only: filter schemas",
    )
    bp.add_argument(
        "--output-dir", default=None, help="Base output directory (default /backups)"
    )
    bp.add_argument(
        "--no-compress", action="store_true", help="Disable gzip compression"
    )
    bp.add_argument("--encrypt", action="store_true", help="Encrypt dump files")
    bp.add_argument(
        "--parallel", type=int, default=None, help="Parallel schema dumps (default 1)"
    )
    bp.add_argument(
        "--timeout", type=int, default=None, help="Timeout per dump (default 1800)"
    )
    bp.add_argument(
        "--retries", type=int, default=None, help="Max retry attempts (default 3)"
    )
    bp.add_argument(
        "--retry-delay",
        type=int,
        default=None,
        help="Retry delay seconds (default 300)",
    )
    bp.add_argument(
        "--retain-successful",
        type=int,
        default=None,
        help="Successful backups to keep (default 30)",
    )
    bp.add_argument(
        "--retain-partial",
        type=int,
        default=None,
        help="Partial backups to keep (default 5)",
    )
    bp.add_argument(
        "--result-file",
        default=None,
        help="Write the backup path (connection/YYYY-MM-DD.NNN) to this file after completion",
    )


def _build_restore_parser(subparsers: argparse._SubParsersAction) -> None:
    rp = subparsers.add_parser("restore", help="Restore from a backup")
    _build_shared_args(rp)
    _build_mode_args(rp)

    # Restore-only required
    rp.add_argument(
        "--from", dest="from_path", default=None, help="Path to backup directory"
    )

    # Restore-only optional
    rp.add_argument("--driver", default=None, help="Override driver check")
    rp.add_argument("--version", default=None, help="Override version check")
    rp.add_argument(
        "--drop-databases", action="store_true", help="Drop and recreate before restore"
    )
    rp.add_argument(
        "--drop-users",
        action="store_true",
        help="Drop non-system users on target before restoring globals (syncs users to match source)",
    )
    rp.add_argument(
        "--version-override", default=None, help="Force a different client version"
    )
    rp.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Timeout per restore op (default 7200)",
    )


def parse_args(argv: list[str] | None = None) -> Union[BackupConfig, RestoreConfig]:
    """Parse CLI arguments and return the appropriate config dataclass.

    CLI args take precedence over environment variables.
    """
    parser = argparse.ArgumentParser(
        prog="db-backup-orchestrator",
        description="Docker-based database backup and restore tool",
    )
    subparsers = parser.add_subparsers(dest="subcommand")
    _build_backup_parser(subparsers)
    _build_restore_parser(subparsers)

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help(sys.stderr)
        sys.exit(1)

    if args.subcommand == "backup":
        return _build_backup_config(args)
    else:
        return _build_restore_config(args)


def _build_backup_config(args: argparse.Namespace) -> BackupConfig:
    """Construct a BackupConfig from parsed args + env fallbacks."""
    host = args.host or _env("BACKUP_HOST")
    user = args.user or _env("DB_USER", "BACKUP_USER")
    password = args.password or _env("DB_PASSWORD", "BACKUP_PASSWORD")
    driver = args.driver or _env("BACKUP_DRIVER")
    version = args.version or _env("BACKUP_VERSION")
    connection = args.connection or _env("BACKUP_CONNECTION")
    encrypt_key = args.encrypt_key or _env("BACKUP_ENCRYPT_KEY")
    connect_timeout = args.connect_timeout or int(
        _env("BACKUP_CONNECT_TIMEOUT") or "30"
    )
    output_dir = args.output_dir or _env("BACKUP_OUTPUT_DIR") or "/backups"
    timeout = args.timeout or int(_env("BACKUP_TIMEOUT") or "1800")
    docker_network = args.docker_network or "host"
    docker_platform = args.docker_platform or "linux/amd64"

    # Determine port — CLI > env > driver default (filled later in validation)
    port_raw = args.port or _env("BACKUP_PORT")
    port = int(port_raw) if port_raw else 0

    return BackupConfig(
        host=host or "",
        port=port,
        user=user or "",
        password=password or "",
        driver=driver or "",
        version=version or "",
        connection=connection or "",
        full=args.full,
        databases=args.databases,
        tables=args.tables,
        globals_only=args.globals_only,
        databases_only=args.databases_only,
        schemas=args.schemas,
        output_dir=output_dir,
        no_compress=args.no_compress,
        encrypt=args.encrypt,
        encrypt_key=encrypt_key,
        parallel=args.parallel or 1,
        timeout=timeout,
        retries=args.retries if args.retries is not None else 3,
        retry_delay=args.retry_delay if args.retry_delay is not None else 300,
        retain_successful=args.retain_successful
        if args.retain_successful is not None
        else 30,
        retain_partial=args.retain_partial if args.retain_partial is not None else 5,
        connect_timeout=connect_timeout,
        verify=args.verify,
        dry_run=args.dry_run,
        verbose=args.verbose,
        docker_network=docker_network,
        docker_platform=docker_platform,
        result_file=args.result_file,
    )


def _build_restore_config(args: argparse.Namespace) -> RestoreConfig:
    """Construct a RestoreConfig from parsed args + env fallbacks."""
    host = args.host or _env("BACKUP_HOST")
    user = args.user or _env("DB_USER", "BACKUP_USER")
    password = args.password or _env("DB_PASSWORD", "BACKUP_PASSWORD")
    encrypt_key = args.encrypt_key or _env("BACKUP_ENCRYPT_KEY")
    connect_timeout = args.connect_timeout or int(
        _env("BACKUP_CONNECT_TIMEOUT") or "30"
    )
    timeout = args.timeout or int(_env("RESTORE_TIMEOUT", "BACKUP_TIMEOUT") or "7200")
    docker_network = args.docker_network or "host"
    docker_platform = args.docker_platform or "linux/amd64"

    port_raw = args.port or _env("BACKUP_PORT")
    port = int(port_raw) if port_raw else 0

    return RestoreConfig(
        from_path=args.from_path or "",
        host=host or "",
        port=port,
        user=user or "",
        password=password or "",
        full=args.full,
        databases=args.databases,
        tables=args.tables,
        globals_only=args.globals_only,
        databases_only=args.databases_only,
        drop_databases=args.drop_databases,
        drop_users=args.drop_users,
        version_override=args.version_override,
        timeout=timeout,
        connect_timeout=connect_timeout,
        encrypt_key=encrypt_key,
        verify=args.verify,
        dry_run=args.dry_run,
        verbose=args.verbose,
        docker_network=docker_network,
        docker_platform=docker_platform,
        driver=args.driver,
        version=args.version,
    )
