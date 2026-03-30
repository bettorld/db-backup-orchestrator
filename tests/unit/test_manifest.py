"""Tests for manifest lifecycle — create, set_status, add_file, finalize."""

import json


from db_backup_orchestrator.manifest import Manifest, RestoreLog


class TestManifestLifecycle:
    """Test Manifest create, set_status, add_file, finalize."""

    def test_create_writes_initialized_status(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="prod-pg",
            driver="postgres",
            driver_version="16",
            host="db.example.com",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        manifest_path = tmp_path / "manifest.json"
        assert manifest_path.exists()

        data = json.loads(manifest_path.read_text())
        assert data["status"] == "initialized"
        assert data["driver"] == "postgres"
        assert data["driver_version"] == "16"
        assert data["connection"] == "prod-pg"
        assert data["host"] == "db.example.com"
        assert data["port"] == 5432
        assert data["mode"] == "full"
        assert data["globals_included"] is True
        assert data["compress"] is True
        assert data["encrypt"] is False
        assert data["files"] == []
        assert data["summary"] is None
        assert data["version"] == "1.0"
        assert data["timestamp_start"] is not None
        assert data["timestamp_end"] is None

    def test_set_status_updates_status(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        m.set_status("running")
        data = json.loads((tmp_path / "manifest.json").read_text())
        assert data["status"] == "running"

        m.set_status("success")
        data = json.loads((tmp_path / "manifest.json").read_text())
        assert data["status"] == "success"

    def test_add_file_appends_and_flushes(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )

        file_entry_1 = {
            "filename": "globals.sql.gz",
            "type": "globals",
            "database": None,
            "size_bytes": 1024,
            "checksum_sha256": "abc123",
            "duration_seconds": 1.5,
            "status": "success",
        }
        m.add_file(file_entry_1)

        data = json.loads((tmp_path / "manifest.json").read_text())
        assert len(data["files"]) == 1
        assert data["files"][0]["filename"] == "globals.sql.gz"

        file_entry_2 = {
            "filename": "app_store/schema.public.sql.gz",
            "type": "schema",
            "database": "app_store",
            "schema": "public",
            "size_bytes": 2048,
            "checksum_sha256": "def456",
            "duration_seconds": 3.2,
            "status": "success",
        }
        m.add_file(file_entry_2)

        data = json.loads((tmp_path / "manifest.json").read_text())
        assert len(data["files"]) == 2
        assert data["files"][1]["filename"] == "app_store/schema.public.sql.gz"

    def test_finalize_writes_summary(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        m.set_status("running")
        m.add_file(
            {
                "filename": "globals.sql.gz",
                "type": "globals",
                "database": None,
                "size_bytes": 1024,
                "checksum_sha256": "abc123",
                "duration_seconds": 1.5,
                "status": "success",
            }
        )

        m.finalize(
            status="success",
            total_files=1,
            total_databases=0,
            succeeded=1,
            failed=0,
            total_size_bytes=1024,
            total_duration_seconds=1.5,
            total_attempts=1,
        )

        data = json.loads((tmp_path / "manifest.json").read_text())
        assert data["status"] == "success"
        assert data["timestamp_end"] is not None
        assert data["summary"]["total_files"] == 1
        assert data["summary"]["total_databases"] == 0
        assert data["summary"]["succeeded"] == 1
        assert data["summary"]["failed"] == 0
        assert data["summary"]["total_size_bytes"] == 1024
        assert data["summary"]["total_duration_seconds"] == 1.5
        assert data["summary"]["total_attempts"] == 1

    def test_update_file_modifies_entry(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        m.add_file({"filename": "test.sql", "status": "running"})
        m.update_file("test.sql", {"status": "success", "size_bytes": 512})

        data = json.loads((tmp_path / "manifest.json").read_text())
        assert data["files"][0]["status"] == "success"
        assert data["files"][0]["size_bytes"] == 512

    def test_remove_file_deletes_entry(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        m.add_file({"filename": "test.sql", "status": "failed"})
        m.remove_file("test.sql")

        data = json.loads((tmp_path / "manifest.json").read_text())
        assert len(data["files"]) == 0

    def test_add_attempt_records_retry(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        m.add_attempt(
            {
                "attempt": 1,
                "timestamp": "2026-03-18T10:00:00Z",
                "result": "partial",
                "succeeded": ["globals.sql"],
                "failed": ["app_store/schema.public.sql"],
                "errors": {"app_store/schema.public.sql": "connection lost"},
            }
        )

        data = json.loads((tmp_path / "manifest.json").read_text())
        assert len(data["retries"]["attempts"]) == 1
        assert data["retries"]["attempts"][0]["result"] == "partial"

    def test_encrypt_algorithm_set_when_encrypted(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=True,
            retries_max=3,
            retry_delay=300,
        )
        data = json.loads((tmp_path / "manifest.json").read_text())
        assert data["encrypt_algorithm"] == "aes-256-cbc"

    def test_set_databases(self, tmp_path):
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        m.set_databases(["app_store", "analytics"])
        data = json.loads((tmp_path / "manifest.json").read_text())
        assert data["databases"] == ["app_store", "analytics"]


class TestManifestAtomicWrites:
    """Test that manifest uses atomic writes (tmp file + rename)."""

    def test_atomic_write_no_partial_json(self, tmp_path):
        """Verify that a read after write gives valid JSON."""
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        # Add many files rapidly to test concurrent flush
        for i in range(20):
            m.add_file({"filename": f"file_{i}.sql", "status": "success"})

        # Read and parse — should always be valid JSON
        data = json.loads((tmp_path / "manifest.json").read_text())
        assert len(data["files"]) == 20

    def test_tmp_file_cleaned_up(self, tmp_path):
        """After a successful write, no .tmp files should remain."""
        m = Manifest(tmp_path)
        m.create(
            connection="test",
            driver="postgres",
            driver_version="16",
            host="h",
            port=5432,
            mode="full",
            globals_included=True,
            compress=True,
            encrypt=False,
            retries_max=3,
            retry_delay=300,
        )
        # Check that no temp files linger
        tmp_files = list(tmp_path.glob(".manifest.*.tmp"))
        assert len(tmp_files) == 0


class TestRestoreLog:
    """Test RestoreLog lifecycle."""

    def test_restore_log_create(self, tmp_path):
        rl = RestoreLog(tmp_path)
        rl.create(
            source="/backups/prod-pg/2026-03-18.001",
            host="db.example.com",
            port=5432,
            driver="postgres",
            driver_version="16",
            mode="full",
            drop_databases=True,
            restore_timeout=3600,
        )
        # Find the created log file
        log_files = list(tmp_path.glob("restore.*.json"))
        assert len(log_files) == 1

        data = json.loads(log_files[0].read_text())
        assert data["status"] == "initialized"
        assert data["type"] == "restore"
        assert data["target"]["host"] == "db.example.com"
        assert data["target"]["driver"] == "postgres"
        assert data["drop_databases"] is True
        assert data["files_restored"] == []

    def test_restore_log_counter_increments(self, tmp_path):
        rl1 = RestoreLog(tmp_path)
        rl1.create(
            source="/backups/test",
            host="h",
            port=5432,
            driver="postgres",
            driver_version="16",
            mode="full",
            drop_databases=False,
            restore_timeout=3600,
        )

        rl2 = RestoreLog(tmp_path)
        rl2.create(
            source="/backups/test",
            host="h",
            port=5432,
            driver="postgres",
            driver_version="16",
            mode="full",
            drop_databases=False,
            restore_timeout=3600,
        )

        log_files = sorted(tmp_path.glob("restore.*.json"))
        assert len(log_files) == 2
        assert ".001." in log_files[0].name
        assert ".002." in log_files[1].name

    def test_restore_log_finalize(self, tmp_path):
        rl = RestoreLog(tmp_path)
        rl.create(
            source="/backups/test",
            host="h",
            port=5432,
            driver="postgres",
            driver_version="16",
            mode="full",
            drop_databases=True,
            restore_timeout=3600,
        )
        rl.set_status("running")
        rl.add_file(
            {
                "filename": "globals.sql.gz",
                "type": "globals",
                "status": "success",
                "duration_seconds": 2.1,
                "checksum_verified": True,
            }
        )
        rl.finalize(
            status="success",
            total_files=1,
            succeeded=1,
            failed=0,
            total_duration_seconds=2.1,
        )

        log_files = list(tmp_path.glob("restore.*.json"))
        data = json.loads(log_files[0].read_text())
        assert data["status"] == "success"
        assert data["timestamp_end"] is not None
        assert data["summary"]["total_files"] == 1
        assert data["summary"]["succeeded"] == 1

    def test_restore_log_records_drop_users(self, tmp_path):
        """drop_users flag is recorded in the restore log."""
        rl = RestoreLog(tmp_path)
        rl.create(
            source="/backups/test",
            host="h",
            port=5432,
            driver="postgres",
            driver_version="16",
            mode="full",
            drop_databases=True,
            restore_timeout=3600,
            drop_users=True,
        )

        log_files = list(tmp_path.glob("restore.*.json"))
        data = json.loads(log_files[0].read_text())
        assert data["drop_users"] is True

    def test_restore_log_drop_users_default_false(self, tmp_path):
        """drop_users defaults to False when not provided."""
        rl = RestoreLog(tmp_path)
        rl.create(
            source="/backups/test",
            host="h",
            port=5432,
            driver="postgres",
            driver_version="16",
            mode="full",
            drop_databases=False,
            restore_timeout=3600,
        )

        log_files = list(tmp_path.glob("restore.*.json"))
        data = json.loads(log_files[0].read_text())
        assert data["drop_users"] is False
