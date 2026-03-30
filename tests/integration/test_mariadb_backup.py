"""Integration tests for MariaDB backup operations.

Tests run against real MariaDB containers (parametrized across versions).
Each test builds a BackupConfig, creates a DockerRunner + driver, and calls
BackupOrchestrator().run() directly.
"""

from pathlib import Path

import pytest

from db_backup_orchestrator.config import BackupConfig
from db_backup_orchestrator.docker_runner import DockerRunner
from db_backup_orchestrator.drivers import get_driver
from db_backup_orchestrator.orchestrator import BackupOrchestrator
from db_backup_orchestrator.utils.logging import setup_logger

from tests.integration.conftest import DBInstance, DOCKER_NETWORK
from tests.integration.helpers import (
    assert_file_is_gzipped,
    assert_manifest_valid,
)

pytestmark = pytest.mark.integration

setup_logger(verbose=True)

# ── Helpers ──────────────────────────────────────────────────────────────

CONNECTION_NAME = "test-mariadb"


def _make_backup_config(
    instance: DBInstance,
    output_dir: Path,
    *,
    full: bool = False,
    databases: list[str] | None = None,
    globals_only: bool = False,
    databases_only: bool = False,
    schemas: list[str] | None = None,
    no_compress: bool = False,
    dry_run: bool = False,
    host_override: str | None = None,
    retries: int = 0,
    retry_delay: int = 0,
) -> BackupConfig:
    """Build a BackupConfig from a DBInstance and test-specific overrides."""
    # MariaDB uses root user for full dump capabilities
    return BackupConfig(
        host=host_override or instance.host,
        port=instance.port,
        user="root",
        password=instance.password,
        driver=instance.driver,
        version=instance.version,
        connection=CONNECTION_NAME,
        full=full,
        databases=databases,
        globals_only=globals_only,
        databases_only=databases_only,
        schemas=schemas,
        output_dir=str(output_dir),
        no_compress=no_compress,
        dry_run=dry_run,
        retries=retries,
        retry_delay=retry_delay,
        timeout=120,
        connect_timeout=30,
        docker_network=DOCKER_NETWORK,
    )


def _run_backup(config: BackupConfig) -> int:
    """Instantiate driver + docker runner and execute a backup."""
    docker_runner = DockerRunner(
        network=config.docker_network, platform=config.docker_platform
    )
    driver = get_driver(config.driver, version=config.version)
    orchestrator = BackupOrchestrator()
    return orchestrator.run(config, driver, docker_runner)


def _find_backup_dir(output_dir: Path) -> Path:
    """Find the latest dated backup directory under output_dir/connection."""
    conn_dir = output_dir / CONNECTION_NAME
    assert conn_dir.exists(), f"Connection dir does not exist: {conn_dir}"
    dirs = sorted(conn_dir.iterdir())
    assert len(dirs) >= 1, f"Expected at least one backup dir, found: {dirs}"
    return dirs[-1]


# ── Tests ────────────────────────────────────────────────────────────────


def test_full_backup(mariadb_instance: DBInstance, backup_output_dir: Path):
    """Full backup creates globals + all database subfolders + manifest success."""
    config = _make_backup_config(mariadb_instance, backup_output_dir, full=True)
    exit_code = _run_backup(config)

    assert exit_code == 0
    backup_dir = _find_backup_dir(backup_output_dir)

    # Globals file exists
    globals_files = list(backup_dir.glob("globals.sql*"))
    assert len(globals_files) >= 1, "globals.sql(.gz) not found"

    # Database subfolders for seeded databases
    app_store_dir = backup_dir / "app_store"
    analytics_dir = backup_dir / "analytics"
    assert app_store_dir.is_dir(), "app_store subfolder missing"
    assert analytics_dir.is_dir(), "analytics subfolder missing"

    # Full dump files inside each DB folder
    app_store_files = list(app_store_dir.glob("full.*"))
    assert len(app_store_files) >= 1, "No full dump in app_store"

    analytics_files = list(analytics_dir.glob("full.*"))
    assert len(analytics_files) >= 1, "No full dump in analytics"

    # Manifest
    manifest_path = backup_dir / "manifest.json"
    manifest = assert_manifest_valid(manifest_path, expected_status="success")
    assert manifest["globals_included"] is True
    assert manifest["driver"] == "mariadb"


def test_full_backup_compressed(mariadb_instance: DBInstance, backup_output_dir: Path):
    """Default full backup produces gzip-compressed files."""
    config = _make_backup_config(mariadb_instance, backup_output_dir, full=True)
    exit_code = _run_backup(config)
    assert exit_code == 0

    backup_dir = _find_backup_dir(backup_output_dir)

    all_dump_files = [
        f for f in backup_dir.rglob("*") if f.is_file() and f.name != "manifest.json"
    ]
    assert len(all_dump_files) >= 1

    for f in all_dump_files:
        assert f.name.endswith(".gz"), f"Expected .gz extension, got: {f.name}"
        assert_file_is_gzipped(f)


def test_full_backup_no_compress(mariadb_instance: DBInstance, backup_output_dir: Path):
    """--no-compress produces raw .sql files."""
    config = _make_backup_config(
        mariadb_instance, backup_output_dir, full=True, no_compress=True
    )
    exit_code = _run_backup(config)
    assert exit_code == 0

    backup_dir = _find_backup_dir(backup_output_dir)

    all_dump_files = [
        f for f in backup_dir.rglob("*") if f.is_file() and f.name != "manifest.json"
    ]
    assert len(all_dump_files) >= 1

    for f in all_dump_files:
        assert f.name.endswith(".sql"), f"Expected .sql extension, got: {f.name}"
        with open(f, "rb") as fh:
            magic = fh.read(2)
        assert magic != b"\x1f\x8b", (
            f"File {f.name} has gzip magic but should be raw SQL"
        )


def test_specific_databases(mariadb_instance: DBInstance, backup_output_dir: Path):
    """--databases app_store backs up only that database."""
    config = _make_backup_config(
        mariadb_instance, backup_output_dir, databases=["app_store"]
    )
    exit_code = _run_backup(config)
    assert exit_code == 0

    backup_dir = _find_backup_dir(backup_output_dir)

    assert (backup_dir / "app_store").is_dir(), "app_store subfolder missing"
    assert not (backup_dir / "analytics").exists(), "analytics should not exist"

    globals_files = list(backup_dir.glob("globals.sql*"))
    assert len(globals_files) == 0, "globals should not exist with --databases mode"


def test_databases_only(mariadb_instance: DBInstance, backup_output_dir: Path):
    """--databases-only auto-discovers all databases without globals."""
    config = _make_backup_config(
        mariadb_instance, backup_output_dir, databases_only=True
    )
    exit_code = _run_backup(config)
    assert exit_code == 0

    backup_dir = _find_backup_dir(backup_output_dir)

    # No globals
    globals_files = list(backup_dir.glob("globals.sql*"))
    assert len(globals_files) == 0, "globals should not exist with --databases-only"

    # Database subfolders should exist (auto-discovered)
    app_store_dir = backup_dir / "app_store"
    analytics_dir = backup_dir / "analytics"
    assert app_store_dir.is_dir(), "app_store subfolder missing"
    assert analytics_dir.is_dir(), "analytics subfolder missing"


def test_globals_only(mariadb_instance: DBInstance, backup_output_dir: Path):
    """--globals-only produces only globals, no database subfolders."""
    config = _make_backup_config(mariadb_instance, backup_output_dir, globals_only=True)
    exit_code = _run_backup(config)
    assert exit_code == 0

    backup_dir = _find_backup_dir(backup_output_dir)

    globals_files = list(backup_dir.glob("globals.sql*"))
    assert len(globals_files) >= 1, "globals.sql(.gz) not found"

    subdirs = [d for d in backup_dir.iterdir() if d.is_dir()]
    assert len(subdirs) == 0, f"Expected no DB subfolders, found: {subdirs}"


def test_manifest_success(mariadb_instance: DBInstance, backup_output_dir: Path):
    """Manifest has correct structure, status, and valid checksums."""
    config = _make_backup_config(mariadb_instance, backup_output_dir, full=True)
    exit_code = _run_backup(config)
    assert exit_code == 0

    backup_dir = _find_backup_dir(backup_output_dir)
    manifest_path = backup_dir / "manifest.json"

    manifest = assert_manifest_valid(manifest_path, expected_status="success")

    assert manifest["version"] == "1.0"
    assert manifest["driver"] == "mariadb"
    assert manifest["driver_version"] == mariadb_instance.version
    assert manifest["mode"] == "full"
    assert manifest["globals_included"] is True
    assert manifest["compress"] is True
    assert isinstance(manifest["files"], list)
    assert len(manifest["files"]) >= 1

    for f in manifest["files"]:
        assert "filename" in f
        assert "status" in f
        assert f["status"] == "success"
        assert "checksum_sha256" in f
        assert "size_bytes" in f
        assert f["size_bytes"] > 0

    summary = manifest["summary"]
    assert summary is not None
    assert summary["succeeded"] >= 1
    assert summary["failed"] == 0


def test_dry_run(mariadb_instance: DBInstance, backup_output_dir: Path):
    """--dry-run creates no files or directories."""
    config = _make_backup_config(
        mariadb_instance, backup_output_dir, full=True, dry_run=True
    )
    exit_code = _run_backup(config)
    assert exit_code == 0

    # No backup directory should be created
    conn_dir = backup_output_dir / CONNECTION_NAME
    if conn_dir.exists():
        backup_dirs = [d for d in conn_dir.iterdir() if d.is_dir()]
        assert len(backup_dirs) == 0, (
            f"Dry run should not create backup directories, found: {backup_dirs}"
        )


def test_exit_code_0(mariadb_instance: DBInstance, backup_output_dir: Path):
    """Successful backup returns exit code 0."""
    config = _make_backup_config(mariadb_instance, backup_output_dir, full=True)
    exit_code = _run_backup(config)
    assert exit_code == 0


def test_exit_code_1_bad_host(mariadb_instance: DBInstance, backup_output_dir: Path):
    """Unreachable host causes validation failure (sys.exit(1))."""
    config = _make_backup_config(
        mariadb_instance,
        backup_output_dir,
        full=True,
        host_override="192.0.2.1",
    )
    config.connect_timeout = 5

    with pytest.raises(SystemExit) as exc_info:
        _run_backup(config)

    assert exc_info.value.code == 1


def test_counter_increments(mariadb_instance: DBInstance, backup_output_dir: Path):
    """Running backup twice creates .001 and .002 directories."""
    config1 = _make_backup_config(
        mariadb_instance, backup_output_dir, globals_only=True
    )
    exit_code1 = _run_backup(config1)
    assert exit_code1 == 0

    config2 = _make_backup_config(
        mariadb_instance, backup_output_dir, globals_only=True
    )
    exit_code2 = _run_backup(config2)
    assert exit_code2 == 0

    conn_dir = backup_output_dir / CONNECTION_NAME
    dirs = sorted(d.name for d in conn_dir.iterdir() if d.is_dir())
    assert len(dirs) == 2

    assert dirs[0].endswith(".001"), f"First dir should end with .001, got: {dirs[0]}"
    assert dirs[1].endswith(".002"), f"Second dir should end with .002, got: {dirs[1]}"


def test_schemas_ignored(mariadb_instance: DBInstance, backup_output_dir: Path, caplog):
    """--schemas with MariaDB logs a warning and ignores the filter.

    The validation step (B1) sets config.schemas = None for mysql/mariadb
    and logs a warning, so the backup proceeds normally.
    """
    config = _make_backup_config(
        mariadb_instance,
        backup_output_dir,
        databases=["app_store"],
        schemas=["inventory"],
    )

    exit_code = _run_backup(config)
    assert exit_code == 0

    # Verify schemas was cleared (validation sets it to None for mariadb)
    assert config.schemas is None
