"""Tests for the database verification fingerprint feature."""

import hashlib
import json
from unittest.mock import MagicMock


from db_backup_orchestrator.config import BackupConfig, RestoreConfig
from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.mysql import MySQLDriver
from db_backup_orchestrator.drivers.postgres import PostgresDriver
from db_backup_orchestrator.orchestrator import BackupOrchestrator
from db_backup_orchestrator.restorer import Restorer


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_backup_config(tmp_path, **overrides) -> BackupConfig:
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
        no_compress=True,
        retries=0,
        retry_delay=0,
        retain_successful=30,
        retain_partial=5,
    )
    defaults.update(overrides)
    return BackupConfig(**defaults)


def _make_mock_runner() -> MagicMock:
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
    mock = MagicMock(spec=PostgresDriver)
    mock.engine = "postgres"
    mock.image = "postgres"
    mock.password_env_var = "PGPASSWORD"
    mock.check_reachable.return_value = DockerResult(stdout="", stderr="", returncode=0)
    mock.check_connection.return_value = DockerResult(
        stdout="", stderr="", returncode=0
    )
    mock.list_databases.return_value = ["app_store"]
    mock.list_schemas.return_value = ["public"]
    mock.dump_globals.side_effect = _dump_side_effect(
        "-- Globals\nCREATE ROLE testuser;\n"
    )
    mock.dump_schema.side_effect = _dump_side_effect(
        "-- Schema dump\nCREATE TABLE products;\n"
    )
    return mock


def _create_backup(tmp_path, manifest_data, files=None):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(exist_ok=True)
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data))
    if files:
        for filename, content in files.items():
            file_path = backup_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
    return str(backup_dir)


def _make_restore_config(from_path, **overrides) -> RestoreConfig:
    defaults = dict(
        from_path=from_path,
        host="db.example.com",
        port=5432,
        user="admin",
        password="secret",
        full=True,
        driver="postgres",
        version="16",
        connection="test-conn",
        drop_databases=True,
    )
    defaults.update(overrides)
    return RestoreConfig(**defaults)


def _make_manifest(verification=None):
    manifest = {
        "version": "1.0",
        "status": "success",
        "timestamp_start": "2026-03-18T10:00:00Z",
        "timestamp_end": "2026-03-18T10:05:00Z",
        "connection": "test-conn",
        "driver": "postgres",
        "driver_version": "16",
        "databases": ["app_store"],
        "host": "db.example.com",
        "port": 5432,
        "mode": "full",
        "globals_included": True,
        "compress": False,
        "encrypt": False,
        "retries": {"max_attempts": 3, "delay_seconds": 300, "attempts": []},
        "files": [
            {
                "filename": "globals.sql",
                "type": "globals",
                "database": None,
                "size_bytes": 100,
                "checksum_sha256": None,
                "duration_seconds": 1.0,
                "status": "success",
            },
            {
                "filename": "app_store/schema.public.sql",
                "type": "schema",
                "database": "app_store",
                "schema": "public",
                "size_bytes": 2048,
                "checksum_sha256": None,
                "duration_seconds": 2.0,
                "status": "success",
            },
        ],
        "summary": {
            "total_files": 2,
            "total_databases": 1,
            "succeeded": 2,
            "failed": 0,
            "total_size_bytes": 2148,
            "total_duration_seconds": 5.0,
            "total_attempts": 1,
        },
    }
    if verification:
        manifest["verification"] = verification
    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# verify_fingerprint returns correct dict structure
# ═══════════════════════════════════════════════════════════════════════════


class TestPostgresVerifyFingerprint:
    """Test PostgresDriver.verify_fingerprint returns correct dict structure."""

    def test_returns_correct_keys(self):
        driver = PostgresDriver()
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.run.return_value = DockerResult(
            stdout="some|data|here\n", stderr="", returncode=0
        )

        result = driver.verify_fingerprint(
            docker_runner=mock_runner,
            image="postgres",
            version="16",
            host="db.example.com",
            port=5432,
            user="admin",
            password="secret",
            databases=["testdb"],
            timeout=30,
        )

        expected_keys = {
            "databases",
            "tables",
            "indexes",
            "foreign_keys",
            "views",
            "routines",
            "triggers",
            "users",
            "collations",
            "combined",
        }
        assert set(result.keys()) == expected_keys

    def test_hashes_are_sha256_prefixed(self):
        driver = PostgresDriver()
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.run.return_value = DockerResult(
            stdout="data\n", stderr="", returncode=0
        )

        result = driver.verify_fingerprint(
            docker_runner=mock_runner,
            image="postgres",
            version="16",
            host="localhost",
            port=5432,
            user="user",
            password="pass",
            databases=[],
            timeout=30,
        )

        for key, value in result.items():
            assert value.startswith("sha256:"), (
                f"Key '{key}' value does not start with sha256:"
            )
            hex_part = value[len("sha256:") :]
            assert len(hex_part) == 64, f"Key '{key}' hash is not 64 hex chars"

    def test_combined_hash_is_consistent(self):
        driver = PostgresDriver()
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.run.return_value = DockerResult(
            stdout="consistent output\n", stderr="", returncode=0
        )

        result = driver.verify_fingerprint(
            docker_runner=mock_runner,
            image="postgres",
            version="16",
            host="localhost",
            port=5432,
            user="user",
            password="pass",
            databases=[],
            timeout=30,
        )

        # Recompute combined hash manually
        checks = {k: v for k, v in result.items() if k != "combined"}
        combined_input = "".join(checks[k] for k in sorted(checks.keys()))
        expected_combined = (
            f"sha256:{hashlib.sha256(combined_input.encode()).hexdigest()}"
        )
        assert result["combined"] == expected_combined

    def test_failed_query_hashes_empty_string(self):
        driver = PostgresDriver()
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.run.return_value = DockerResult(
            stdout="error output", stderr="some error", returncode=1
        )

        result = driver.verify_fingerprint(
            docker_runner=mock_runner,
            image="postgres",
            version="16",
            host="localhost",
            port=5432,
            user="user",
            password="pass",
            databases=[],
            timeout=30,
        )

        # All checks should hash the empty string since returncode != 0
        empty_hash = f"sha256:{hashlib.sha256(b'').hexdigest()}"
        for key, value in result.items():
            if key != "combined":
                assert value == empty_hash


class TestMySQLVerifyFingerprint:
    """Test MySQLDriver.verify_fingerprint returns correct dict structure."""

    def test_returns_correct_keys(self):
        driver = MySQLDriver()
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.run.return_value = DockerResult(
            stdout="some\tdata\there\n", stderr="", returncode=0
        )

        result = driver.verify_fingerprint(
            docker_runner=mock_runner,
            image="mysql",
            version="8.0",
            host="db.example.com",
            port=3306,
            user="root",
            password="secret",
            databases=["testdb"],
            timeout=30,
        )

        expected_keys = {
            "databases",
            "tables",
            "indexes",
            "foreign_keys",
            "views",
            "routines",
            "triggers",
            "events",
            "users",
            "collations",
            "combined",
        }
        assert set(result.keys()) == expected_keys

    def test_uses_client_binary(self):
        driver = MySQLDriver()
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.run.return_value = DockerResult(stdout="", stderr="", returncode=0)

        driver.verify_fingerprint(
            docker_runner=mock_runner,
            image="mysql",
            version="8.0",
            host="localhost",
            port=3306,
            user="root",
            password="pass",
            databases=[],
            timeout=30,
        )

        # All calls should use "mysql" as client binary
        for c in mock_runner.run.call_args_list:
            cmd = c.kwargs.get("command", c.args[0] if c.args else [])
            assert cmd[0] == "mysql"


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator triggers fingerprint when --verify is set
# ═══════════════════════════════════════════════════════════════════════════


class TestOrchestratorVerify:
    """Test that --verify triggers fingerprint computation in backup."""

    def test_verify_true_calls_verify_fingerprint(self, tmp_path):
        config = _make_backup_config(tmp_path, verify=True)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()
        mock_driver.verify_fingerprint.return_value = {
            "databases": "sha256:abc",
            "tables": "sha256:def",
            "combined": "sha256:ghi",
        }

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code == 0
        mock_driver.verify_fingerprint.assert_called_once()

        # Check manifest has verification section
        conn_dir = tmp_path / "test-conn"
        backup_dir = list(conn_dir.iterdir())[0]
        manifest = json.loads((backup_dir / "manifest.json").read_text())
        assert "verification" in manifest
        assert manifest["verification"]["combined"] == "sha256:ghi"
        assert "databases" in manifest["verification"]["checks"]

    def test_verify_false_does_not_call_verify_fingerprint(self, tmp_path):
        config = _make_backup_config(tmp_path, verify=False)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        orchestrator = BackupOrchestrator()
        exit_code = orchestrator.run(config, mock_driver, mock_runner)

        assert exit_code == 0
        mock_driver.verify_fingerprint.assert_not_called()

    def test_verify_not_called_on_partial_failure(self, tmp_path):
        config = _make_backup_config(tmp_path, verify=True, retries=0)
        mock_runner = _make_mock_runner()
        mock_driver = _make_mock_driver()

        # Make first dump fail
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
        # verify_fingerprint should NOT be called when there are pending failures
        mock_driver.verify_fingerprint.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# Restorer triggers fingerprint comparison when --verify is set
# ═══════════════════════════════════════════════════════════════════════════


class TestRestorerVerify:
    """Test that --verify triggers fingerprint comparison in restore."""

    def test_verify_compares_hashes(self, tmp_path):
        verification = {
            "timestamp": "2026-03-25T01:00:15Z",
            "combined": "sha256:abc123",
            "checks": {
                "databases": "sha256:db_hash",
                "tables": "sha256:tbl_hash",
            },
        }
        manifest = _make_manifest(verification=verification)
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, verify=True)
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.check_docker.return_value = True
        mock_runner.ensure_image.return_value = True
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        # Restore should succeed (exit_code 0)
        assert exit_code == 0

    def test_verify_skipped_when_no_verification_in_manifest(self, tmp_path):
        manifest = _make_manifest(verification=None)
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, verify=True)
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.check_docker.return_value = True
        mock_runner.ensure_image.return_value = True
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        # Should still succeed, just log a warning
        assert exit_code == 0

    def test_verify_false_does_not_compare(self, tmp_path):
        verification = {
            "timestamp": "2026-03-25T01:00:15Z",
            "combined": "sha256:abc123",
            "checks": {"databases": "sha256:db_hash"},
        }
        manifest = _make_manifest(verification=verification)
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, verify=False)
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.check_docker.return_value = True
        mock_runner.ensure_image.return_value = True
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        assert exit_code == 0

    def test_verify_mismatch_does_not_change_exit_code(self, tmp_path):
        """Verification failure is informational -- exit code stays 0."""
        verification = {
            "timestamp": "2026-03-25T01:00:15Z",
            "combined": "sha256:will_not_match",
            "checks": {"databases": "sha256:will_not_match"},
        }
        manifest = _make_manifest(verification=verification)
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, verify=True)
        mock_runner = MagicMock(spec=DockerRunner)
        mock_runner.check_docker.return_value = True
        mock_runner.ensure_image.return_value = True
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        # Exit code should remain 0 even if fingerprints don't match
        assert exit_code == 0
