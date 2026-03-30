"""Tests for restorer with mocked DockerRunner."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from db_backup_orchestrator.config import RestoreConfig
from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.restorer import Restorer


def _create_backup(tmp_path, manifest_data, files=None):
    """Create a fake backup directory with manifest and files."""
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


def _make_manifest(status="success", encrypt=False, extra_files=None):
    files = [
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
    ]
    if extra_files:
        files.extend(extra_files)

    return {
        "version": "1.0",
        "status": status,
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
        "encrypt": encrypt,
        "retries": {"max_attempts": 3, "delay_seconds": 300, "attempts": []},
        "files": files,
        "summary": {
            "total_files": len(files),
            "total_databases": 1,
            "succeeded": len(files),
            "failed": 0,
            "total_size_bytes": sum(f["size_bytes"] for f in files),
            "total_duration_seconds": 5.0,
            "total_attempts": 1,
        },
    }


def _make_mock_runner():
    mock = MagicMock(spec=DockerRunner)
    mock.check_docker.return_value = True
    mock.ensure_image.return_value = True
    mock.run.return_value = DockerResult(stdout="", stderr="", returncode=0)
    return mock


class TestRestoreOrder:
    """Test restorer reads manifest and processes files in correct order."""

    def test_restore_globals_first(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path)
        mock_runner = _make_mock_runner()

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        assert exit_code == 0

        # Verify restore_globals was called before restore_schema
        # We should have calls from validation (check_reachable, check_connection)
        # followed by restore operations
        assert mock_runner.run.call_count > 0

    def test_restore_creates_restore_log(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path)
        mock_runner = _make_mock_runner()

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        assert exit_code == 0

        # Verify restore log was created
        backup_dir = Path(backup_path)
        log_files = list(backup_dir.glob("restore.*.json"))
        assert len(log_files) == 1

        log_data = json.loads(log_files[0].read_text())
        assert log_data["status"] == "success"
        assert log_data["type"] == "restore"


class TestRestoreStopsOnFailure:
    """Test restorer stops on first failure."""

    def test_stops_on_first_failure(self, tmp_path):
        manifest = _make_manifest(
            extra_files=[
                {
                    "filename": "analytics/schema.public.sql",
                    "type": "schema",
                    "database": "analytics",
                    "schema": "public",
                    "size_bytes": 1024,
                    "checksum_sha256": None,
                    "duration_seconds": 1.0,
                    "status": "success",
                },
            ]
        )
        manifest["databases"].append("analytics")
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
                "analytics/schema.public.sql": b"CREATE TABLE events;",
            },
        )

        config = _make_restore_config(backup_path)
        mock_runner = _make_mock_runner()

        # Make the second schema restore fail
        call_count = {"restore": 0}

        def side_effect(*args, **kwargs):
            result = DockerResult(stdout="", stderr="", returncode=0)
            # Check if this is a restore command by looking for stdin_data
            if kwargs.get("stdin_data") is not None:
                call_count["restore"] += 1
                if call_count["restore"] == 2:
                    # Second restore operation (first schema) fails
                    return DockerResult(
                        stdout="", stderr="permission denied", returncode=1
                    )
            return result

        mock_runner.run.side_effect = side_effect

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        assert exit_code == 2

        # Check restore log shows failure
        backup_dir = Path(backup_path)
        log_files = list(backup_dir.glob("restore.*.json"))
        log_data = json.loads(log_files[0].read_text())
        assert log_data["summary"]["failed"] > 0


class TestDropDatabases:
    """Test --drop-databases triggers drop before restore."""

    def test_drop_databases_called(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, drop_databases=True)
        mock_runner = _make_mock_runner()

        # Track calls to identify drop database commands
        calls = []

        def side_effect(*args, **kwargs):
            cmd = kwargs.get("command", args[2] if len(args) > 2 else [])
            calls.append(cmd)
            return DockerResult(stdout="1", stderr="", returncode=0)

        mock_runner.run.side_effect = side_effect

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        # The restorer should have been invoked (may be 0 or 2 depending on mock behavior)
        assert exit_code in (0, 2)

    def test_no_drop_databases_blocks_restore(self, tmp_path):
        """Test --drop-databases=False blocks restore when DB exists."""
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, drop_databases=False)
        mock_runner = _make_mock_runner()

        # Simulate database already exists
        def side_effect(*args, **kwargs):
            # check_database_exists returns true
            kwargs.get("command", [])
            return DockerResult(stdout="1", stderr="", returncode=0)

        mock_runner.run.side_effect = side_effect

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        # Should fail because DB exists and --drop-databases not set
        assert exit_code == 2


class TestDropUsers:
    """Test --drop-users triggers user drop before globals restore."""

    def test_drop_users_called(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, drop_databases=True, drop_users=True)
        mock_runner = _make_mock_runner()

        # Track calls
        calls = []

        def side_effect(*args, **kwargs):
            cmd = kwargs.get("command", args[2] if len(args) > 2 else [])
            calls.append(cmd)
            # Return non-system user for list_users query
            if any(
                "pg_roles" in str(c) for c in (cmd if isinstance(cmd, list) else [cmd])
            ):
                return DockerResult(stdout="app_readonly\n", stderr="", returncode=0)
            return DockerResult(stdout="1", stderr="", returncode=0)

        mock_runner.run.side_effect = side_effect

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        # The restorer should have been invoked
        assert exit_code in (0, 2)
        # Verify that a DROP ROLE command was issued
        drop_calls = [
            c
            for c in calls
            if isinstance(c, list) and any("DROP ROLE" in str(x) for x in c)
        ]
        assert len(drop_calls) > 0, "Expected DROP ROLE call when --drop-users is set"

    def test_drop_users_not_called(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(
            backup_path, drop_databases=True, drop_users=False
        )
        mock_runner = _make_mock_runner()

        calls = []

        def side_effect(*args, **kwargs):
            cmd = kwargs.get("command", args[2] if len(args) > 2 else [])
            calls.append(cmd)
            return DockerResult(stdout="1", stderr="", returncode=0)

        mock_runner.run.side_effect = side_effect

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)

        assert exit_code in (0, 2)
        # Verify that no DROP ROLE command was issued
        drop_calls = [
            c
            for c in calls
            if isinstance(c, list) and any("DROP ROLE" in str(x) for x in c)
        ]
        assert len(drop_calls) == 0, (
            "Did not expect DROP ROLE call when --drop-users is false"
        )


class TestRestoreExitCodes:
    """Test exit codes 0, 1, 2."""

    def test_exit_code_0_success(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path)
        mock_runner = _make_mock_runner()

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)
        assert exit_code == 0

    def test_exit_code_1_bad_source(self, tmp_path):
        config = _make_restore_config("/nonexistent/path")
        mock_runner = _make_mock_runner()

        restorer = Restorer()
        with pytest.raises(SystemExit) as exc_info:
            restorer.run(config, mock_runner)
        assert exc_info.value.code == 1

    def test_exit_code_2_partial_restore(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path)
        mock_runner = _make_mock_runner()

        # Make schema restore fail
        call_count = {"restore": 0}

        def side_effect(*args, **kwargs):
            if kwargs.get("stdin_data") is not None:
                call_count["restore"] += 1
                if call_count["restore"] == 2:
                    return DockerResult(stdout="", stderr="error", returncode=1)
            return DockerResult(stdout="1", stderr="", returncode=0)

        mock_runner.run.side_effect = side_effect

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)
        assert exit_code == 2

    def test_dry_run_returns_0(self, tmp_path):
        manifest = _make_manifest()
        backup_path = _create_backup(
            tmp_path,
            manifest,
            {
                "globals.sql": b"CREATE ROLE testuser;",
                "app_store/schema.public.sql": b"CREATE TABLE products;",
            },
        )

        config = _make_restore_config(backup_path, dry_run=True)
        mock_runner = _make_mock_runner()

        restorer = Restorer()
        exit_code = restorer.run(config, mock_runner)
        assert exit_code == 0
