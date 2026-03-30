"""Backup retention management.

Runs after every backup to enforce retention limits per connection.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from db_backup_orchestrator.utils.logging import get_logger


class RetentionManager:
    """Scan, classify, and delete old backups according to retention policy."""

    def __init__(self) -> None:
        self.logger = get_logger()

    def run(
        self,
        output_dir: str,
        connection: str,
        current_status: str,
        retain_successful: int,
        retain_partial: int,
    ) -> None:
        """Execute retention cleanup.

        Args:
            output_dir: Base output directory (e.g. /backups).
            connection: Logical connection name.
            current_status: Final status of the current backup ('success', 'partial', 'failed').
            retain_successful: Max successful backups to keep.
            retain_partial: Max partial backups to keep.
        """
        # Exit 1 (fatal) — touch nothing
        if current_status == "failed" and not self._current_has_dir(
            output_dir, connection
        ):
            self.logger.info("Retention: skipping — fatal error, nothing was produced.")
            return

        conn_dir = Path(output_dir) / connection
        if not conn_dir.exists():
            self.logger.debug(
                "Retention: connection directory %s does not exist.", conn_dir
            )
            return

        # Scan all backup directories
        successful: list[tuple[str, Path]] = []
        partial: list[tuple[str, Path]] = []

        for d in sorted(conn_dir.iterdir()):
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            status = self._read_status(manifest_path)
            ts = self._read_timestamp(manifest_path)
            sort_key = ts or d.name

            if status == "success":
                successful.append((sort_key, d))
            else:
                # partial, failed, initialized, running, missing manifest → all partial
                partial.append((sort_key, d))

        # Sort newest first
        successful.sort(key=lambda x: x[0], reverse=True)
        partial.sort(key=lambda x: x[0], reverse=True)

        self.logger.info(
            "Retention: scanning %s — found %d successful, %d partial backups.",
            conn_dir,
            len(successful),
            len(partial),
        )

        # Apply deletion rules based on current backup result
        if current_status == "success":
            # Successful run: can evict both old successful and old partial
            self._evict(successful, retain_successful, "successful")
            self._evict(partial, retain_partial, "partial")
        elif current_status in ("partial", "failed"):
            # Partial/failed run: only evict old partial, keep good backups safe
            self._evict(partial, retain_partial, "partial")
        # If current_status implies fatal with no output, we already returned above

    def _evict(
        self,
        items: list[tuple[str, Path]],
        limit: int,
        label: str,
    ) -> None:
        """Delete items beyond the retention limit (oldest first)."""
        if len(items) <= limit:
            return

        to_delete = items[limit:]
        for sort_key, path in to_delete:
            self.logger.info(
                "Retention: removing 1 %s backup beyond limit (%d): %s",
                label,
                limit,
                path.name,
            )
            try:
                shutil.rmtree(path)
            except OSError as exc:
                self.logger.warning("Retention: failed to delete %s: %s", path, exc)

    def _read_status(self, manifest_path: Path) -> str:
        """Read the status from a manifest file. Returns 'partial' on any error."""
        try:
            with open(manifest_path) as f:
                data = json.load(f)
            return data.get("status", "partial")
        except (OSError, json.JSONDecodeError, KeyError):
            return "partial"

    def _read_timestamp(self, manifest_path: Path) -> Optional[str]:
        """Read timestamp_start for sorting. Returns None on error."""
        try:
            with open(manifest_path) as f:
                data = json.load(f)
            return data.get("timestamp_start")
        except (OSError, json.JSONDecodeError):
            return None

    def _current_has_dir(self, output_dir: str, connection: str) -> bool:
        """Check if the current run produced any output directory."""
        conn_dir = Path(output_dir) / connection
        return conn_dir.exists() and any(conn_dir.iterdir())
