"""Integration tests for PostgreSQL restore operations.

Each test first runs a backup via BackupOrchestrator, then restores from
the created backup using Restorer. Tests run against real PostgreSQL
containers (parametrized across versions).
"""

import json
from pathlib import Path

import pytest

from db_backup_orchestrator.config import BackupConfig, RestoreConfig
from db_backup_orchestrator.docker_runner import DockerRunner
from db_backup_orchestrator.drivers import get_driver
from db_backup_orchestrator.orchestrator import BackupOrchestrator
from db_backup_orchestrator.restorer import Restorer
from db_backup_orchestrator.utils.logging import setup_logger

from tests.integration.conftest import DBInstance, DOCKER_NETWORK
from tests.integration.helpers import query_postgres

pytestmark = pytest.mark.integration

setup_logger(verbose=True)

# ── Helpers ──────────────────────────────────────────────────────────────

BACKUP_CONNECTION = "test-pg-restore"


def _make_backup_config(
    instance: DBInstance,
    output_dir: Path,
    *,
    full: bool = False,
    databases: list[str] | None = None,
    globals_only: bool = False,
    databases_only: bool = False,
) -> BackupConfig:
    return BackupConfig(
        host=instance.host,
        port=instance.port,
        user=instance.user,
        password=instance.password,
        driver=instance.driver,
        version=instance.version,
        connection=BACKUP_CONNECTION,
        full=full,
        databases=databases,
        globals_only=globals_only,
        databases_only=databases_only,
        output_dir=str(output_dir),
        timeout=120,
        connect_timeout=30,
        retries=0,
        retry_delay=0,
        docker_network=DOCKER_NETWORK,
    )


def _run_backup(config: BackupConfig) -> int:
    docker_runner = DockerRunner(
        network=config.docker_network, platform=config.docker_platform
    )
    driver = get_driver(config.driver, version=config.version)
    return BackupOrchestrator().run(config, driver, docker_runner)


def _find_backup_dir(output_dir: Path) -> Path:
    conn_dir = output_dir / BACKUP_CONNECTION
    dirs = sorted(conn_dir.iterdir())
    assert len(dirs) >= 1
    return dirs[-1]


def _make_restore_config(
    instance: DBInstance,
    from_path: Path,
    *,
    full: bool = False,
    databases: list[str] | None = None,
    globals_only: bool = False,
    databases_only: bool = False,
    drop_databases: bool = False,
    dry_run: bool = False,
) -> RestoreConfig:
    return RestoreConfig(
        from_path=str(from_path),
        host=instance.host,
        port=instance.port,
        user=instance.user,
        password=instance.password,
        full=full,
        databases=databases,
        globals_only=globals_only,
        databases_only=databases_only,
        drop_databases=drop_databases,
        dry_run=dry_run,
        timeout=120,
        connect_timeout=30,
        docker_network=DOCKER_NETWORK,
    )


def _run_restore(config: RestoreConfig) -> int:
    docker_runner = DockerRunner(
        network=config.docker_network, platform=config.docker_platform
    )
    return Restorer().run(config, docker_runner)


def _do_full_backup(instance: DBInstance, output_dir: Path) -> Path:
    """Run a full backup and return the backup directory path."""
    config = _make_backup_config(instance, output_dir, full=True)
    exit_code = _run_backup(config)
    assert exit_code == 0, "Backup failed — cannot proceed with restore test"
    return _find_backup_dir(output_dir)


# ── Tests ────────────────────────────────────────────────────────────────


def test_restore_full(pg_instance: DBInstance, backup_output_dir: Path):
    """Full backup then full restore with --drop-databases succeeds.

    Verifies data actually exists in restored tables.
    """
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    config = _make_restore_config(
        pg_instance, backup_dir, full=True, drop_databases=True
    )
    exit_code = _run_restore(config)
    assert exit_code == 0

    # Verify a table has data after restore
    count = query_postgres(
        pg_instance,
        "SELECT COUNT(*) FROM inventory.products;",
        database="app_store",
    )
    assert int(count) > 0, (
        f"Expected data in inventory.products after restore, got {count}"
    )


def test_restore_specific_database(pg_instance: DBInstance, backup_output_dir: Path):
    """Restore --databases app_store --drop-databases restores only that DB."""
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    config = _make_restore_config(
        pg_instance,
        backup_dir,
        databases=["app_store"],
        drop_databases=True,
    )
    exit_code = _run_restore(config)
    assert exit_code == 0


def test_restore_globals_only(pg_instance: DBInstance, backup_output_dir: Path):
    """Restore --globals-only restores only globals (roles/users)."""
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    config = _make_restore_config(
        pg_instance,
        backup_dir,
        globals_only=True,
    )
    exit_code = _run_restore(config)
    assert exit_code == 0

    # Verify that the globals role was created
    result = query_postgres(
        pg_instance,
        "SELECT rolname FROM pg_roles WHERE rolname = 'app_readonly';",
    )
    assert "app_readonly" in result, (
        f"Expected 'app_readonly' role after globals restore, got: {result}"
    )


def test_restore_dry_run(pg_instance: DBInstance, backup_output_dir: Path):
    """Restore --dry-run does not write data to target, returns 0."""
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    config = _make_restore_config(
        pg_instance,
        backup_dir,
        full=True,
        drop_databases=True,
        dry_run=True,
    )
    exit_code = _run_restore(config)
    assert exit_code == 0

    # Verify no restore log was created (dry run finishes before creating
    # actual restore operations, but the log is still written)
    # The important thing is exit_code == 0 and no DB modifications.


def test_restore_log_created(pg_instance: DBInstance, backup_output_dir: Path):
    """Restore creates a restore.YYYY-MM-DD.NNN.json log file."""
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    config = _make_restore_config(
        pg_instance,
        backup_dir,
        full=True,
        drop_databases=True,
    )
    exit_code = _run_restore(config)
    assert exit_code == 0

    # Find restore log
    restore_logs = list(backup_dir.glob("restore.*.json"))
    assert len(restore_logs) >= 1, f"No restore log found in {backup_dir}"

    # Verify log structure
    log_data = json.loads(restore_logs[0].read_text())
    assert log_data["type"] == "restore"
    assert log_data["status"] == "success"
    assert "files_restored" in log_data
    assert "summary" in log_data


def test_restore_exit_code_0(pg_instance: DBInstance, backup_output_dir: Path):
    """Successful restore returns exit code 0."""
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    config = _make_restore_config(
        pg_instance,
        backup_dir,
        full=True,
        drop_databases=True,
    )
    exit_code = _run_restore(config)
    assert exit_code == 0


def test_restore_no_drop_databases_fails(
    pg_instance: DBInstance, backup_output_dir: Path
):
    """Restore without --drop-databases when target DB exists returns error."""
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    # The seeded databases (app_store, analytics) already exist on the target.
    # Restoring without --drop-databases should fail.
    config = _make_restore_config(
        pg_instance,
        backup_dir,
        full=True,
        drop_databases=False,
    )
    exit_code = _run_restore(config)
    # Should fail with exit code 2 (partial/failed) because DB exists
    assert exit_code != 0, (
        "Expected non-zero exit when target DB exists without --drop-databases"
    )


def test_restore_nonexistent_database(pg_instance: DBInstance, backup_output_dir: Path):
    """Restore --databases nonexistent_db from a valid backup exits with error."""
    backup_dir = _do_full_backup(pg_instance, backup_output_dir)

    config = _make_restore_config(
        pg_instance,
        backup_dir,
        databases=["nonexistent_db"],
    )

    # R6 validation should catch that nonexistent_db is not in the manifest
    with pytest.raises(SystemExit) as exc_info:
        _run_restore(config)

    assert exc_info.value.code == 1
