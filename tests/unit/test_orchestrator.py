"""Tests for orchestrator with fully mocked DockerRunner and driver."""

import json
from unittest.mock import MagicMock

import pytest

from db_backup_orchestrator.config import BackupConfig
from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.postgres import PostgresDriver
from db_backup_orchestrator.orchestrator import BackupOrchestrator


def _make_config(tmp_path, **overrides) -> BackupConfig:
    """Create a valid BackupConfig pointing to a real tmp directory."""
    defaults = dict(
        host="db.example.com",
        port=5432,
        user="admin",
        password="secret",
        driver="postgres",
        version="16",
        connection="test-conn",
        full=True,
        output_dir=str(tmp_path),
        encrypt=False,
        encrypt_key=None,
        no_compress=True,  # Disable compression for simpler test assertions
        retries=0,
        retry_delay=0,
        retain_successful=30,
        retain_partial=5,
    )
    defaults.update(overrides)
    return BackupConfig(**defaults)


def _make_mock_runner() -> MagicMock:
    """Create a fully mocked DockerRunner that passes all validations."""
    mock = MagicMock(spec=DockerRunner)
    mock.check_docker.return_value = True
    mock.ensure_image.return_value = True
    mock.run.return_value = DockerResult(
        stdout="-- SQL dump\nCREATE TABLE test;\n",
        stderr="",
        returncode=0,
    )
    return mock


def _dump_side_effect(content: str):
    """Create a side_effect that writes content to output_path and returns DockerResult."""

    def side_effect(*args, **kwargs):
        output_path = kwargs.get("output_path")
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
        return DockerResult(
            stdout="" if output_path else content, stderr="", returncode=0
        )

    return side_effect


def _make_mock_driver() -> MagicMock:
    """Create a mocked PostgresDriver."""
    mock = MagicMock(spec=PostgresDriver)
    mock.engine = "postgres"
    mock.image = "postgres"
    mock.password_env_var = "PGPASSWORD"
    mock.check_reachable.return_value = DockerResult(stdout="", stderr="", returncode=0)
    mock.check_connection.return_value = DockerResult(
        stdout="", stderr="", returncode=0
    )
    mock.list_databases.return_value = ["app_store", "analytics"]
    mock.list_schemas.return_value = ["public", "inventory"]
    mock.dump_globals.side_effect = _dump_side_effect(
        "-- Globals\nCREATE ROLE testuser;\n"
    )
    mock.dump_schema.side_effect = _dump_side_effect(
        "-- Schema dump\nCREATE TABLE products;\n"
    )
    mock.dump_table.side_effect = _dump_side_effect(
        "-- Table dump\nCREATE TABLE users;\n"
    )
    return mock


class TestFullBackupMode:
    """Test full backup mode creates correct directory structure."""

    def test_full_backup_creates_dirs_and_files(self, tmp_path):
        config = _make_config(tmp_path)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code == 0

        # Find the backup directory
        conn_dir = tmp_path / "test-conn"
        assert conn_dir.exists()
        backup_dirs = list(conn_dir.iterdir())
        assert len(backup_dirs) == 1

        backup_dir = backup_dirs[0]

        # Check manifest exists
        manifest_path = backup_dir / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["status"] == "success"
        assert manifest["driver"] == "postgres"
        assert manifest["mode"] == "full"
        assert manifest["globals_included"] is True
        assert len(manifest["files"]) > 0

        # Globals file should exist
        globals_file = [f for f in manifest["files"] if f["type"] == "globals"]
        assert len(globals_file) == 1

        # Schema files should exist
        schema_files = [f for f in manifest["files"] if f["type"] == "schema"]
        assert len(schema_files) > 0

        # Database subdirectories should exist
        for f in schema_files:
            db = f["database"]
            db_dir = backup_dir / db
            assert db_dir.exists()

    def test_full_backup_manifest_summary(self, tmp_path):
        config = _make_config(tmp_path)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        orchestrator = BackupOrchestrator()
        orchestrator.run(config, mock_driver, mock_runner)

        conn_dir = tmp_path / "test-conn"
        backup_dir = list(conn_dir.iterdir())[0]
        manifest = json.loads((backup_dir / "manifest.json").read_text())

        assert manifest["summary"] is not None
        assert manifest["summary"]["failed"] == 0
        assert manifest["summary"]["succeeded"] > 0
        assert manifest["summary"]["total_attempts"] >= 1


class TestRetryLoop:
    """Test retry loop retries only failed dumps."""

    def test_retry_only_failed_dumps(self, tmp_path):
        config = _make_config(tmp_path, retries=2, retry_delay=0)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        # First call to dump_schema fails for "analytics", then succeeds on retry
        call_count = {"analytics": 0}

        def side_effect_dump_schema(*args, **kwargs):
            database = kwargs.get("database") or (args[7] if len(args) > 7 else "")
            output_path = kwargs.get("output_path")
            if database == "analytics":
                call_count["analytics"] += 1
                if call_count["analytics"] == 1:
                    if output_path:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_text("")
                    return DockerResult(
                        stdout="", stderr="connection lost", returncode=1
                    )
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("-- Schema\nCREATE TABLE t;\n")
            return DockerResult(stdout="", stderr="", returncode=0)

        mock_driver.dump_schema.side_effect = side_effect_dump_schema

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code == 0

        conn_dir = tmp_path / "test-conn"
        backup_dir = list(conn_dir.iterdir())[0]
        manifest = json.loads((backup_dir / "manifest.json").read_text())

        # Should have retry attempts recorded
        assert len(manifest["retries"]["attempts"]) >= 2
        assert manifest["status"] == "success"


class TestExitCodes:
    """Test exit codes 0, 1, 2."""

    def test_exit_code_0_all_success(self, tmp_path):
        config = _make_config(tmp_path)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)
        assert exit_code == 0

    def test_exit_code_1_validation_failure(self, tmp_path):
        """B3: Docker not available -> exit 1."""
        config = _make_config(tmp_path)
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.check_docker.return_value = False
        mock_driver = _make_mock_driver()

        orchestrator = BackupOrchestrator()
        with pytest.raises(SystemExit) as exc_info:
            orchestrator.run(config, mock_driver, mock_runner)
        assert exc_info.value.code == 1

    def test_exit_code_2_partial_failure(self, tmp_path):
        config = _make_config(tmp_path, retries=0)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        # Make one schema dump always fail
        call_count = {"calls": 0}

        def side_effect_dump_schema(*args, **kwargs):
            output_path = kwargs.get("output_path")
            call_count["calls"] += 1
            if call_count["calls"] == 1:
                if output_path:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text("")
                return DockerResult(stdout="", stderr="disk full", returncode=1)
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("-- Schema\nCREATE TABLE t;\n")
            return DockerResult(stdout="", stderr="", returncode=0)

        mock_driver.dump_schema.side_effect = side_effect_dump_schema

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)
        assert exit_code == 2

    def test_exit_code_1_all_dumps_failed(self, tmp_path):
        """All dumps failing after retries returns exit code 1 (total failure)."""
        config = _make_config(tmp_path, retries=0)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        # Make ALL dumps fail
        def _fail_dump(*args, **kwargs):
            output_path = kwargs.get("output_path")
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("")
            return DockerResult(stdout="", stderr="connection refused", returncode=1)

        mock_driver.dump_globals.side_effect = _fail_dump
        mock_driver.dump_schema.side_effect = _fail_dump

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)
        assert exit_code == 1

    def test_dry_run_returns_0(self, tmp_path):
        config = _make_config(tmp_path, dry_run=True)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)
        assert exit_code == 0


class TestEncryptOnlyPipeline:
    """Test --encrypt --no-compress produces .sql.enc files."""

    def test_encrypt_only_no_compress(self, tmp_path, monkeypatch):
        """Encrypt without compression writes .sql.enc files."""
        monkeypatch.setenv("BACKUP_ENCRYPT_KEY", "test-secret-key")

        config = _make_config(
            tmp_path,
            encrypt=True,
            encrypt_key="test-secret-key",
            no_compress=True,
        )
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()
        # Single DB, single schema for simplicity
        mock_driver.list_databases.return_value = ["testdb"]
        mock_driver.list_schemas.return_value = ["public"]

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code == 0

        conn_dir = tmp_path / "test-conn"
        backup_dir = list(conn_dir.iterdir())[0]
        manifest = json.loads((backup_dir / "manifest.json").read_text())

        # Verify files have .enc extension but NOT .gz
        for f in manifest["files"]:
            filename = f["filename"]
            assert filename.endswith(".enc"), f"Expected .enc, got: {filename}"
            assert ".gz" not in filename, f"Should not have .gz: {filename}"

        # Verify the encrypted files exist on disk
        for f in manifest["files"]:
            file_path = backup_dir / f["filename"]
            assert file_path.exists(), f"Encrypted file missing: {f['filename']}"
            assert f["size_bytes"] > 0


class TestResultFile:
    """Test --result-file writes the backup path."""

    def test_result_file_written(self, tmp_path):
        result_file = tmp_path / "workspace" / "latest-bkp"
        result_file.parent.mkdir(parents=True, exist_ok=True)

        config = _make_config(tmp_path, result_file=str(result_file))
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()
        mock_driver.list_databases.return_value = ["testdb"]
        mock_driver.list_schemas.return_value = ["public"]

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code == 0
        assert result_file.exists()
        content = result_file.read_text().strip()
        assert content.startswith("test-conn/")
        assert ".001" in content

    def test_result_file_not_written_when_not_set(self, tmp_path):
        config = _make_config(tmp_path, result_file=None)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()
        mock_driver.list_databases.return_value = ["testdb"]
        mock_driver.list_schemas.return_value = ["public"]

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code == 0
        # No result file should exist anywhere in tmp_path named "latest-bkp"
        assert not (tmp_path / "latest-bkp").exists()

    def test_result_file_bad_path_non_fatal(self, tmp_path):
        config = _make_config(tmp_path, result_file="/nonexistent/dir/latest-bkp")
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()
        mock_driver.list_databases.return_value = ["testdb"]
        mock_driver.list_schemas.return_value = ["public"]

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        # Should still succeed — result file failure is non-fatal
        assert exit_code == 0


class TestPathSanitization:
    """Test that database/schema names are sanitized in filenames."""

    def test_path_traversal_blocked(self, tmp_path):
        """DB names with path separators are sanitized."""
        from db_backup_orchestrator.orchestrator import _safe_name

        assert "/" not in _safe_name("../../etc/passwd")
        assert "\\" not in _safe_name("..\\..\\windows")
        assert _safe_name("../secret") == "_secret"
        assert _safe_name("normal_db") == "normal_db"

    def test_leading_dots_stripped(self):
        from db_backup_orchestrator.orchestrator import _safe_name

        assert _safe_name("..hidden") == "hidden"
        assert _safe_name(".secret") == "secret"

    def test_null_bytes_replaced(self):
        from db_backup_orchestrator.orchestrator import _safe_name

        assert "\x00" not in _safe_name("db\x00name")

    def test_empty_name_fallback(self):
        from db_backup_orchestrator.orchestrator import _safe_name

        assert _safe_name("") == "_"
        assert _safe_name("...") == "_"


class TestBackupDirectoryNaming:
    """Test backup directory counter increments."""

    def test_counter_increments(self, tmp_path):
        config = _make_config(tmp_path)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()
        # Single database, single schema for speed
        mock_driver.list_databases.return_value = ["testdb"]
        mock_driver.list_schemas.return_value = ["public"]

        orchestrator = BackupOrchestrator()

        # Run twice
        exit_code_1 = orchestrator.run(config, mock_driver, mock_runner)
        exit_code_2 = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code_1 == 0
        assert exit_code_2 == 0

        conn_dir = tmp_path / "test-conn"
        backup_dirs = sorted([d.name for d in conn_dir.iterdir() if d.is_dir()])
        assert len(backup_dirs) == 2
        assert backup_dirs[0].endswith(".001")
        assert backup_dirs[1].endswith(".002")
