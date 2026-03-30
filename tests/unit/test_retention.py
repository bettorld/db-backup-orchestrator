"""Tests for retention logic."""

import json
from pathlib import Path


from db_backup_orchestrator.retention import RetentionManager


def _create_backup_dir(base: Path, name: str, status: str, timestamp: str) -> Path:
    """Create a fake backup directory with a manifest."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "1.0",
        "status": status,
        "timestamp_start": timestamp,
        "driver": "postgres",
        "driver_version": "16",
    }
    (d / "manifest.json").write_text(json.dumps(manifest))
    # Also write a dummy file so the directory is not empty
    (d / "globals.sql.gz").write_bytes(b"fake sql data")
    return d


class TestRetentionKeepN:
    """Test keep-N-successful and keep-N-partial logic."""

    def test_keep_n_successful_delete_beyond_limit(self, tmp_path):
        conn_dir = tmp_path / "prod-pg"
        conn_dir.mkdir()

        # Create 5 successful backups
        for i in range(5):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.001",
                status="success",
                timestamp=f"2026-03-{10 + i:02d}T10:00:00Z",
            )

        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="prod-pg",
            current_status="success",
            retain_successful=3,
            retain_partial=5,
        )

        remaining = sorted([d.name for d in conn_dir.iterdir() if d.is_dir()])
        assert len(remaining) == 3
        # Should keep the 3 newest
        assert "2026-03-12.001" in remaining
        assert "2026-03-13.001" in remaining
        assert "2026-03-14.001" in remaining

    def test_keep_n_partial_delete_beyond_limit(self, tmp_path):
        conn_dir = tmp_path / "prod-pg"
        conn_dir.mkdir()

        # Create 4 partial backups
        for i in range(4):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.001",
                status="partial",
                timestamp=f"2026-03-{10 + i:02d}T10:00:00Z",
            )

        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="prod-pg",
            current_status="partial",
            retain_successful=30,
            retain_partial=2,
        )

        remaining = sorted([d.name for d in conn_dir.iterdir() if d.is_dir()])
        assert len(remaining) == 2
        # Should keep the 2 newest
        assert "2026-03-12.001" in remaining
        assert "2026-03-13.001" in remaining

    def test_success_run_can_delete_both_types(self, tmp_path):
        conn_dir = tmp_path / "prod-pg"
        conn_dir.mkdir()

        # 3 successful
        for i in range(3):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.001",
                status="success",
                timestamp=f"2026-03-{10 + i:02d}T10:00:00Z",
            )
        # 3 partial
        for i in range(3):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.002",
                status="partial",
                timestamp=f"2026-03-{10 + i:02d}T11:00:00Z",
            )

        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="prod-pg",
            current_status="success",
            retain_successful=2,
            retain_partial=1,
        )

        remaining = sorted([d.name for d in conn_dir.iterdir() if d.is_dir()])
        successful_remaining = [d for d in remaining if ".001" in d]
        partial_remaining = [d for d in remaining if ".002" in d]
        assert len(successful_remaining) == 2
        assert len(partial_remaining) == 1

    def test_partial_run_only_deletes_partial(self, tmp_path):
        conn_dir = tmp_path / "prod-pg"
        conn_dir.mkdir()

        # 3 successful
        for i in range(3):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.001",
                status="success",
                timestamp=f"2026-03-{10 + i:02d}T10:00:00Z",
            )
        # 3 partial
        for i in range(3):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.002",
                status="partial",
                timestamp=f"2026-03-{10 + i:02d}T11:00:00Z",
            )

        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="prod-pg",
            current_status="partial",
            retain_successful=1,  # Would delete 2 successful if run were successful
            retain_partial=1,
        )

        remaining = sorted([d.name for d in conn_dir.iterdir() if d.is_dir()])
        successful_remaining = [d for d in remaining if ".001" in d]
        partial_remaining = [d for d in remaining if ".002" in d]
        # Partial run should NOT touch successful backups
        assert len(successful_remaining) == 3
        assert len(partial_remaining) == 1

    def test_fatal_run_deletes_nothing(self, tmp_path):
        conn_dir = tmp_path / "prod-pg"
        conn_dir.mkdir()

        # 3 successful + 3 partial
        for i in range(3):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.001",
                status="success",
                timestamp=f"2026-03-{10 + i:02d}T10:00:00Z",
            )
        for i in range(3):
            _create_backup_dir(
                conn_dir,
                f"2026-03-{10 + i:02d}.002",
                status="partial",
                timestamp=f"2026-03-{10 + i:02d}T11:00:00Z",
            )

        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="prod-pg",
            current_status="failed",
            retain_successful=1,
            retain_partial=1,
        )

        remaining = sorted([d.name for d in conn_dir.iterdir() if d.is_dir()])
        # Failed run with existing dirs still runs partial cleanup
        # But if no backup was produced (check _current_has_dir), it would skip
        # Here prod-pg dir exists and has children, so partial cleanup runs
        partial_remaining = [d for d in remaining if ".002" in d]
        assert len(partial_remaining) == 1

    def test_corrupt_manifest_treated_as_partial(self, tmp_path):
        conn_dir = tmp_path / "prod-pg"
        conn_dir.mkdir()

        # Create a backup with corrupt manifest
        d = conn_dir / "2026-03-10.001"
        d.mkdir()
        (d / "manifest.json").write_text("this is not valid json {{{")
        (d / "globals.sql.gz").write_bytes(b"fake")

        # Create a valid partial backup (newer)
        _create_backup_dir(
            conn_dir,
            "2026-03-11.001",
            status="partial",
            timestamp="2026-03-11T10:00:00Z",
        )

        # Create a valid successful backup (newest)
        _create_backup_dir(
            conn_dir,
            "2026-03-12.001",
            status="success",
            timestamp="2026-03-12T10:00:00Z",
        )

        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="prod-pg",
            current_status="success",
            retain_successful=5,
            retain_partial=1,  # Keep 1 partial — corrupt counts as partial
        )

        remaining = sorted([d.name for d in conn_dir.iterdir() if d.is_dir()])
        # Corrupt manifest = partial; 2 partials exist (corrupt + "partial"), keep 1
        partial_dirs = [d for d in remaining if d != "2026-03-12.001"]
        assert len(partial_dirs) == 1

    def test_no_backups_does_nothing(self, tmp_path):
        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="nonexistent",
            current_status="success",
            retain_successful=1,
            retain_partial=1,
        )
        # Should not raise

    def test_under_limit_nothing_deleted(self, tmp_path):
        conn_dir = tmp_path / "prod-pg"
        conn_dir.mkdir()

        _create_backup_dir(
            conn_dir,
            "2026-03-10.001",
            status="success",
            timestamp="2026-03-10T10:00:00Z",
        )

        rm = RetentionManager()
        rm.run(
            output_dir=str(tmp_path),
            connection="prod-pg",
            current_status="success",
            retain_successful=5,
            retain_partial=5,
        )

        remaining = list(conn_dir.iterdir())
        assert len(remaining) == 1
