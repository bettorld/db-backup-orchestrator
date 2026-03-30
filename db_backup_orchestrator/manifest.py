"""Manifest and RestoreLog management with atomic writes."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db_backup_orchestrator.utils.logging import get_logger


class Manifest:
    """Manages the backup manifest.json lifecycle.

    Writes are atomic: data goes to a temp file first, then renamed
    to manifest.json. Flushed after each file addition for crash safety.
    Thread-safe: all mutations are protected by a lock for parallel dumps.
    """

    def __init__(self, backup_dir: Path) -> None:
        self.backup_dir = backup_dir
        self.manifest_path = backup_dir / "manifest.json"
        self.data: dict[str, Any] = {}
        self.logger = get_logger()
        self._lock = threading.Lock()

    def create(
        self,
        connection: str,
        driver: str,
        driver_version: str,
        host: str,
        port: int,
        mode: str,
        globals_included: bool,
        compress: bool,
        encrypt: bool,
        retries_max: int,
        retry_delay: int,
    ) -> None:
        """Phase 1: Write initial manifest with status 'initialized'."""
        self.data = {
            "version": "1.0",
            "status": "initialized",
            "timestamp_start": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "timestamp_end": None,
            "connection": connection,
            "driver": driver,
            "driver_version": driver_version,
            "databases": [],
            "host": host,
            "port": port,
            "mode": mode,
            "globals_included": globals_included,
            "compress": compress,
            "encrypt": encrypt,
            "retries": {
                "max_attempts": retries_max,
                "delay_seconds": retry_delay,
                "attempts": [],
            },
            "files": [],
            "summary": None,
        }
        if encrypt:
            self.data["encrypt_algorithm"] = "aes-256-cbc"
        self._flush()
        self.logger.debug("Manifest initialized at %s", self.manifest_path)

    def set_status(self, status: str) -> None:
        """Update the top-level status field."""
        with self._lock:
            self.data["status"] = status
            self._flush()

    def set_databases(self, databases: list[str]) -> None:
        """Update the discovered database list."""
        with self._lock:
            self.data["databases"] = databases
            self._flush()

    def add_file(self, file_entry: dict[str, Any]) -> None:
        """Append a file result and flush to disk immediately."""
        with self._lock:
            self.data["files"].append(file_entry)
            self._flush()

    def update_file(self, filename: str, updates: dict[str, Any]) -> None:
        """Update an existing file entry by filename."""
        with self._lock:
            for f in self.data["files"]:
                if f.get("filename") == filename:
                    f.update(updates)
                    break
            self._flush()

    def remove_file(self, filename: str) -> None:
        """Remove a file entry by filename (for retry overwrites)."""
        with self._lock:
            self.data["files"] = [
                f for f in self.data["files"] if f.get("filename") != filename
            ]
            self._flush()

    def add_attempt(self, attempt_entry: dict[str, Any]) -> None:
        """Append a retry attempt record."""
        with self._lock:
            self.data["retries"]["attempts"].append(attempt_entry)
            self._flush()

    def set_verification(self, fingerprint: dict[str, str]) -> None:
        """Write the verification fingerprint section to the manifest."""
        with self._lock:
            combined = fingerprint.get("combined", "")
            checks = {k: v for k, v in fingerprint.items() if k != "combined"}
            self.data["verification"] = {
                "timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "combined": combined,
                "checks": checks,
            }
            self._flush()
            self.logger.debug("Verification fingerprint written to manifest.")

    def finalize(
        self,
        status: str,
        total_files: int,
        total_databases: int,
        succeeded: int,
        failed: int,
        total_size_bytes: int,
        total_duration_seconds: float,
        total_attempts: int,
    ) -> None:
        """Phase 3: Set final status and write summary."""
        with self._lock:
            self.data["status"] = status
            self.data["timestamp_end"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            self.data["summary"] = {
                "total_files": total_files,
                "total_databases": total_databases,
                "succeeded": succeeded,
                "failed": failed,
                "total_size_bytes": total_size_bytes,
                "total_duration_seconds": round(total_duration_seconds, 1),
                "total_attempts": total_attempts,
            }
            self._flush()
            self.logger.debug("Manifest finalized: status=%s", status)

    def _flush(self) -> None:
        """Atomic write: tmp file + rename."""
        fd, tmp_path = tempfile.mkstemp(
            dir=self.backup_dir, prefix=".manifest.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self.manifest_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


class RestoreLog:
    """Manages the restore log lifecycle.

    Written inside the backup directory being restored from.
    File name: restore.{YYYY-MM-DD}.{NNN}.json
    """

    def __init__(self, backup_dir: Path) -> None:
        self.backup_dir = backup_dir
        self.log_path = self._next_log_path()
        self.data: dict[str, Any] = {}
        self.logger = get_logger()
        self._writable = True

    def _next_log_path(self) -> Path:
        """Determine the next restore log filename with auto-increment counter.

        Uses O_CREAT | O_EXCL for atomic creation to avoid race conditions
        when multiple restore processes target the same backup directory.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        counter = 1
        while True:
            name = f"restore.{today}.{counter:03d}.json"
            path = self.backup_dir / name
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return path
            except FileExistsError:
                counter += 1
            except OSError:
                # Fallback if directory is read-only — pick the name anyway
                return path

    def create(
        self,
        source: str,
        host: str,
        port: int,
        driver: str,
        driver_version: str,
        mode: str,
        drop_databases: bool,
        restore_timeout: int,
        drop_users: bool = False,
    ) -> None:
        """Initialize the restore log with status 'initialized'."""
        self.data = {
            "version": "1.0",
            "type": "restore",
            "status": "initialized",
            "timestamp_start": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "timestamp_end": None,
            "source": source,
            "target": {
                "host": host,
                "port": port,
                "driver": driver,
                "driver_version": driver_version,
            },
            "mode": f"restore-{mode}",
            "drop_databases": drop_databases,
            "drop_users": drop_users,
            "restore_timeout": restore_timeout,
            "files_restored": [],
            "summary": None,
        }
        self._flush()

    def set_status(self, status: str) -> None:
        self.data["status"] = status
        self._flush()

    def add_file(self, file_entry: dict[str, Any]) -> None:
        self.data["files_restored"].append(file_entry)
        self._flush()

    def finalize(
        self,
        status: str,
        total_files: int,
        succeeded: int,
        failed: int,
        total_duration_seconds: float,
    ) -> None:
        self.data["status"] = status
        self.data["timestamp_end"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self.data["summary"] = {
            "status": status,
            "total_files": total_files,
            "succeeded": succeeded,
            "failed": failed,
            "total_duration_seconds": round(total_duration_seconds, 1),
        }
        self._flush()

    def _flush(self) -> None:
        """Atomic write to restore log. Graceful fallback if read-only."""
        if not self._writable:
            return
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self.backup_dir, prefix=".restore.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self.data, f, indent=2)
                    f.write("\n")
                os.replace(tmp_path, self.log_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            self._writable = False
            self.logger.warning(
                "Backup directory is read-only — restore log will not be persisted to disk."
            )
