"""Tests for backup (B1-B7) and restore (R1-R12) validation with mocks."""

import json
from unittest.mock import MagicMock

import pytest

from db_backup_orchestrator.config import BackupConfig, RestoreConfig
from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.postgres import PostgresDriver
from db_backup_orchestrator.validation import (
    validate_backup,
    validate_restore,
    _b1_required_args,
    _b2_driver_registry,
    _b7_output_dir,
    _r1_required_args,
    _r3_manifest_valid,
    _r4_manifest_status,
    _r5_driver_compat,
    _r6_requested_items_exist,
    _r7_files_exist,
    _r8_checksums,
    _r9_encryption_key,
)


def _make_backup_config(**overrides) -> BackupConfig:
    """Create a valid BackupConfig with sensible defaults."""
    defaults = dict(
        host="db.example.com",
        port=5432,
        user="admin",
        password="secret",
        driver="postgres",
        version="16",
        connection="prod-pg",
        full=True,
        output_dir="/backups",
        encrypt=False,
        encrypt_key=None,
    )
    defaults.update(overrides)
    return BackupConfig(**defaults)


def _make_restore_config(**overrides) -> RestoreConfig:
    """Create a valid RestoreConfig with sensible defaults."""
    defaults = dict(
        from_path="/backups/prod-pg/2026-03-18.001",
        host="db.example.com",
        port=5432,
        user="admin",
        password="secret",
        full=True,
        driver="postgres",
        version="16",
        connection="prod-pg",
    )
    defaults.update(overrides)
    return RestoreConfig(**defaults)


def _make_docker_runner_mock(
    check_docker_ok: bool = True,
    ensure_image_ok: bool = True,
    run_returncode: int = 0,
    run_stdout: str = "",
    run_stderr: str = "",
) -> MagicMock:
    """Create a mocked DockerRunner."""
    mock = MagicMock(spec=DockerRunner)
    mock.check_docker.return_value = check_docker_ok
    mock.ensure_image.return_value = ensure_image_ok
    mock.run.return_value = DockerResult(
        stdout=run_stdout, stderr=run_stderr, returncode=run_returncode
    )
    return mock


# ═══════════════════════════════════════════════════════════════════════════
# B1: Missing required args
# ═══════════════════════════════════════════════════════════════════════════


class TestB1RequiredArgs:
    """B1: missing args -> exit 1."""

    def test_missing_host(self):
        cfg = _make_backup_config(host="")
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_missing_user(self):
        cfg = _make_backup_config(user="")
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_missing_password(self):
        cfg = _make_backup_config(password="")
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_missing_driver(self):
        cfg = _make_backup_config(driver="")
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_missing_version(self):
        cfg = _make_backup_config(version="")
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_missing_connection(self):
        cfg = _make_backup_config(connection="")
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_no_mode_selected(self):
        cfg = _make_backup_config(
            full=False, databases=None, tables=None, globals_only=False
        )
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_encrypt_without_key(self):
        cfg = _make_backup_config(encrypt=True, encrypt_key=None)
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_schemas_with_tables_mode(self):
        cfg = _make_backup_config(
            full=False,
            tables=["app_store.public.users"],
            schemas=["inventory"],
        )
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_valid_config_passes(self):
        cfg = _make_backup_config()
        _b1_required_args(cfg)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# B2: Unknown driver
# ═══════════════════════════════════════════════════════════════════════════


class TestB2DriverRegistry:
    """B2: unknown driver -> exit 1."""

    def test_unknown_driver(self):
        cfg = _make_backup_config(driver="mssql")
        with pytest.raises(SystemExit) as exc_info:
            _b2_driver_registry(cfg)
        assert exc_info.value.code == 1

    def test_postgres_driver_accepted(self):
        cfg = _make_backup_config(driver="postgres", port=0)
        _b2_driver_registry(cfg)
        assert cfg.port == 5432

    def test_mysql_driver_accepted(self):
        cfg = _make_backup_config(driver="mysql", port=0)
        _b2_driver_registry(cfg)
        assert cfg.port == 3306

    def test_mariadb_driver_accepted(self):
        cfg = _make_backup_config(driver="mariadb", port=0)
        _b2_driver_registry(cfg)
        assert cfg.port == 3306

    def test_port_not_overwritten_if_set(self):
        cfg = _make_backup_config(driver="postgres", port=15432)
        _b2_driver_registry(cfg)
        assert cfg.port == 15432


# ═══════════════════════════════════════════════════════════════════════════
# B3-B4: Docker checks (mocked)
# ═══════════════════════════════════════════════════════════════════════════


class TestB3B4DockerChecks:
    """B3: Docker not available -> exit 1. B4: Image not found -> exit 1."""

    def test_b3_docker_not_available(self):
        cfg = _make_backup_config()
        mock_runner = _make_docker_runner_mock(check_docker_ok=False)
        driver = PostgresDriver()
        with pytest.raises(SystemExit) as exc_info:
            validate_backup(cfg, mock_runner, driver)
        assert exc_info.value.code == 1

    def test_b4_image_not_found(self):
        cfg = _make_backup_config()
        mock_runner = _make_docker_runner_mock(
            check_docker_ok=True, ensure_image_ok=False
        )
        driver = PostgresDriver()
        with pytest.raises(SystemExit) as exc_info:
            validate_backup(cfg, mock_runner, driver)
        assert exc_info.value.code == 1


# ═══════════════════════════════════════════════════════════════════════════
# R5: Cross-driver mismatch
# ═══════════════════════════════════════════════════════════════════════════


class TestR5DriverCompat:
    """R5: cross-driver mismatch -> exit 1."""

    def test_cross_driver_mismatch(self):
        cfg = _make_restore_config(driver="mysql")
        manifest = {
            "driver": "postgres",
            "driver_version": "16",
            "version": "1.0",
            "status": "success",
            "mode": "full",
            "globals_included": True,
            "files": [],
        }
        with pytest.raises(SystemExit) as exc_info:
            _r5_driver_compat(cfg, manifest)
        assert exc_info.value.code == 1

    def test_matching_driver_passes(self):
        cfg = _make_restore_config(driver="postgres")
        manifest = {
            "driver": "postgres",
            "driver_version": "16",
            "version": "1.0",
            "status": "success",
            "mode": "full",
            "globals_included": True,
            "files": [],
        }
        driver = _r5_driver_compat(cfg, manifest)
        assert driver is not None
        assert driver.engine == "postgres"


# ═══════════════════════════════════════════════════════════════════════════
# R6: Requested database not in manifest
# ═══════════════════════════════════════════════════════════════════════════


class TestR6RequestedItems:
    """R6: requested database not in manifest -> exit 1."""

    def test_database_not_in_manifest(self):
        cfg = _make_restore_config(
            full=False,
            databases=["nonexistent_db"],
        )
        manifest = {
            "files": [
                {
                    "filename": "app_store/schema.public.sql",
                    "database": "app_store",
                    "type": "schema",
                    "status": "success",
                },
            ],
        }
        with pytest.raises(SystemExit) as exc_info:
            _r6_requested_items_exist(cfg, manifest)
        assert exc_info.value.code == 1

    def test_database_found_in_manifest(self):
        cfg = _make_restore_config(
            full=False,
            databases=["app_store"],
        )
        manifest = {
            "files": [
                {
                    "filename": "app_store/schema.public.sql",
                    "database": "app_store",
                    "type": "schema",
                    "status": "success",
                },
            ],
        }
        _r6_requested_items_exist(cfg, manifest)  # Should not raise

    def test_full_mode_skips_check(self):
        cfg = _make_restore_config(full=True, databases=None)
        manifest = {"files": []}
        _r6_requested_items_exist(cfg, manifest)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# R11: Docker image for restore (mocked)
# ═══════════════════════════════════════════════════════════════════════════


class TestR11DockerImage:
    """R11: Docker not available or image missing -> exit 1."""

    def test_r11_docker_not_available(self, tmp_path):
        manifest_data = {
            "version": "1.0",
            "status": "success",
            "driver": "postgres",
            "driver_version": "16",
            "mode": "full",
            "globals_included": True,
            "encrypt": False,
            "files": [],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        cfg = _make_restore_config(from_path=str(tmp_path))
        mock_runner = _make_docker_runner_mock(check_docker_ok=False)

        with pytest.raises(SystemExit) as exc_info:
            validate_restore(cfg, mock_runner)
        assert exc_info.value.code == 1


# ═══════════════════════════════════════════════════════════════════════════
# B1: --parallel validation
# ═══════════════════════════════════════════════════════════════════════════


class TestB1ParallelValidation:
    """B1: --parallel must be >= 1."""

    def test_parallel_zero_rejected(self):
        cfg = _make_backup_config(parallel=0)
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_parallel_negative_rejected(self):
        cfg = _make_backup_config(parallel=-1)
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_parallel_one_accepted(self):
        cfg = _make_backup_config(parallel=1)
        _b1_required_args(cfg)  # Should not raise

    def test_parallel_many_accepted(self):
        cfg = _make_backup_config(parallel=8)
        _b1_required_args(cfg)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# B1: Tables format validation
# ═══════════════════════════════════════════════════════════════════════════


class TestB1TablesFormat:
    """B1: --tables format per driver."""

    def test_postgres_tables_need_three_parts(self):
        cfg = _make_backup_config(full=False, tables=["db.table"])
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_postgres_tables_three_parts_ok(self):
        cfg = _make_backup_config(full=False, tables=["db.schema.table"])
        _b1_required_args(cfg)  # Should not raise

    def test_mysql_tables_need_two_parts(self):
        cfg = _make_backup_config(
            full=False, driver="mysql", tables=["db.schema.table"]
        )
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_mysql_tables_two_parts_ok(self):
        cfg = _make_backup_config(full=False, driver="mysql", tables=["db.table"])
        _b1_required_args(cfg)  # Should not raise

    def test_negative_timeout_rejected(self):
        cfg = _make_backup_config(timeout=-1)
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_output_dir_must_be_absolute(self):
        cfg = _make_backup_config(output_dir="relative/path")
        with pytest.raises(SystemExit) as exc_info:
            _b1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_schemas_ignored_for_mysql(self):
        cfg = _make_backup_config(driver="mysql", schemas=["public"])
        _b1_required_args(cfg)
        assert cfg.schemas is None  # Should be cleared with warning


# ═══════════════════════════════════════════════════════════════════════════
# B7: Output directory
# ═══════════════════════════════════════════════════════════════════════════


class TestB7OutputDir:
    """B7: output dir must exist and be writable."""

    def test_nonexistent_dir(self, tmp_path):
        cfg = _make_backup_config(output_dir=str(tmp_path / "nonexistent"))
        with pytest.raises(SystemExit) as exc_info:
            _b7_output_dir(cfg)
        assert exc_info.value.code == 1

    def test_existing_dir_passes(self, tmp_path):
        cfg = _make_backup_config(output_dir=str(tmp_path))
        _b7_output_dir(cfg)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# R1: Restore required args
# ═══════════════════════════════════════════════════════════════════════════


class TestR1RequiredArgs:
    """R1: missing restore args -> exit 1."""

    def test_missing_from_path(self):
        cfg = _make_restore_config(from_path="")
        with pytest.raises(SystemExit) as exc_info:
            _r1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_missing_host(self):
        cfg = _make_restore_config(host="")
        with pytest.raises(SystemExit) as exc_info:
            _r1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_no_mode_selected(self):
        cfg = _make_restore_config(
            full=False, databases=None, tables=None, globals_only=False
        )
        with pytest.raises(SystemExit) as exc_info:
            _r1_required_args(cfg)
        assert exc_info.value.code == 1

    def test_valid_config_passes(self):
        cfg = _make_restore_config()
        _r1_required_args(cfg)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# R3-R4: Manifest validation
# ═══════════════════════════════════════════════════════════════════════════


class TestR3R4Manifest:
    """R3/R4: manifest must be valid and have acceptable status."""

    def test_r3_missing_manifest(self, tmp_path):
        cfg = _make_restore_config(from_path=str(tmp_path))
        with pytest.raises(SystemExit) as exc_info:
            _r3_manifest_valid(cfg)
        assert exc_info.value.code == 1

    def test_r3_invalid_json(self, tmp_path):
        (tmp_path / "manifest.json").write_text("not json")
        cfg = _make_restore_config(from_path=str(tmp_path))
        with pytest.raises(SystemExit) as exc_info:
            _r3_manifest_valid(cfg)
        assert exc_info.value.code == 1

    def test_r3_missing_required_field(self, tmp_path):
        (tmp_path / "manifest.json").write_text(json.dumps({"version": "1.0"}))
        cfg = _make_restore_config(from_path=str(tmp_path))
        with pytest.raises(SystemExit) as exc_info:
            _r3_manifest_valid(cfg)
        assert exc_info.value.code == 1

    def test_r4_failed_status_blocked(self):
        manifest = {"status": "failed"}
        with pytest.raises(SystemExit) as exc_info:
            _r4_manifest_status(manifest)
        assert exc_info.value.code == 1

    def test_r4_running_status_blocked(self):
        manifest = {"status": "running"}
        with pytest.raises(SystemExit) as exc_info:
            _r4_manifest_status(manifest)
        assert exc_info.value.code == 1

    def test_r4_success_passes(self):
        _r4_manifest_status({"status": "success"})  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════
# R7-R9: File and checksum validation
# ═══════════════════════════════════════════════════════════════════════════


class TestR7R8R9:
    """R7/R8/R9: file existence, checksums, encryption key."""

    def test_r7_missing_file(self, tmp_path):
        (tmp_path / "manifest.json").write_text("{}")
        cfg = _make_restore_config(from_path=str(tmp_path))
        manifest = {
            "files": [{"filename": "missing.sql", "status": "success"}],
        }
        with pytest.raises(SystemExit) as exc_info:
            _r7_files_exist(cfg, manifest)
        assert exc_info.value.code == 1

    def test_r7_all_files_present(self, tmp_path):
        (tmp_path / "test.sql").write_text("data")
        cfg = _make_restore_config(from_path=str(tmp_path))
        manifest = {
            "files": [{"filename": "test.sql", "status": "success"}],
        }
        _r7_files_exist(cfg, manifest)  # Should not raise

    def test_r8_checksum_mismatch(self, tmp_path):
        (tmp_path / "test.sql").write_text("data")
        cfg = _make_restore_config(from_path=str(tmp_path))
        manifest = {
            "files": [
                {
                    "filename": "test.sql",
                    "status": "success",
                    "checksum_sha256": "wrong",
                }
            ],
        }
        with pytest.raises(SystemExit) as exc_info:
            _r8_checksums(cfg, manifest)
        assert exc_info.value.code == 1

    def test_r9_encrypted_without_key(self):
        cfg = _make_restore_config(encrypt_key=None)
        manifest = {"encrypt": True}
        with pytest.raises(SystemExit) as exc_info:
            _r9_encryption_key(cfg, manifest)
        assert exc_info.value.code == 1

    def test_r9_encrypted_with_key(self):
        cfg = _make_restore_config(encrypt_key="secret")
        manifest = {"encrypt": True}
        _r9_encryption_key(cfg, manifest)  # Should not raise

    def test_r9_not_encrypted_passes(self):
        cfg = _make_restore_config(encrypt_key=None)
        manifest = {"encrypt": False}
        _r9_encryption_key(cfg, manifest)  # Should not raise
