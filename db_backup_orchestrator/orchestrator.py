"""Backup orchestrator — main backup flow implementation."""

import gzip
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from db_backup_orchestrator.config import BackupConfig
from db_backup_orchestrator.docker_runner import DockerRunner
from db_backup_orchestrator.drivers.base import BaseDriver
from db_backup_orchestrator.manifest import Manifest
from db_backup_orchestrator.retention import RetentionManager
from db_backup_orchestrator.utils.checksum import sha256_file
from db_backup_orchestrator.utils.encryption import encrypt_file
from db_backup_orchestrator.utils.logging import get_logger
from db_backup_orchestrator.validation import validate_backup


def _safe_name(name: str) -> str:
    """Sanitize a database/schema/table name for safe use in file paths.

    Replaces path separators and other dangerous characters to prevent
    path traversal attacks (e.g., a DB named '../../etc').
    """
    # Replace path separators and null bytes
    sanitized = name.replace("/", "_").replace("\\", "_").replace("\x00", "_")
    # Prevent directory traversal via leading dots
    sanitized = sanitized.lstrip(".")
    # Fallback for empty result
    return sanitized or "_"


class BackupOrchestrator:
    """Orchestrates the full backup lifecycle."""

    def run(
        self, config: BackupConfig, driver: BaseDriver, docker_runner: DockerRunner
    ) -> int:
        """Execute the backup and return an exit code (0, 1, or 2)."""
        logger = get_logger()

        # ── Validate B1-B7 ────────────────────────────────────────────
        validate_backup(config, docker_runner, driver)

        # ── Discover work items ───────────────────────────────────────
        work_items = self._discover_work(config, driver, docker_runner, manifest=None)

        if config.dry_run:
            logger.info("[DRY RUN] Would execute %d dump operations.", len(work_items))
            for item in work_items:
                logger.info("[DRY RUN]   %s", item["filename"])
            logger.info("[DRY RUN] No files or directories were created.")
            return 0

        # ── Create output directory ───────────────────────────────────
        backup_dir = self._create_backup_dir(config)
        logger.info("Backup directory: %s", backup_dir)

        # ── Initialize manifest ───────────────────────────────────────
        manifest = Manifest(backup_dir)
        manifest.create(
            connection=config.connection,
            driver=config.driver,
            driver_version=config.version,
            host=config.host,
            port=config.port,
            mode=config.mode,
            globals_included=config.globals_included,
            compress=config.compress,
            encrypt=config.encrypt,
            retries_max=config.retries,
            retry_delay=config.retry_delay,
        )
        databases = list(set(i["database"] for i in work_items if i.get("database")))
        manifest.set_databases(databases)

        # ── Set encryption key in env if needed ───────────────────────
        if config.encrypt and config.encrypt_key:
            os.environ["BACKUP_ENCRYPT_KEY"] = config.encrypt_key

        manifest.set_status("running")

        # ── Execute dumps with retry loop ─────────────────────────────
        attempt = 0
        total_attempts = 0
        pending = list(work_items)
        all_start = time.monotonic()

        while attempt <= config.retries and pending:
            attempt += 1
            total_attempts = attempt
            logger.info("Attempt %d: running %d dump(s)...", attempt, len(pending))

            succeeded_names: list[str] = []
            failed_names: list[str] = []
            errors: dict[str, str] = {}

            if config.parallel > 1 and len(pending) > 1:
                results = self._run_parallel(
                    config,
                    driver,
                    docker_runner,
                    manifest,
                    pending,
                    backup_dir,
                    attempt_number=attempt,
                )
            else:
                results = self._run_sequential(
                    config,
                    driver,
                    docker_runner,
                    manifest,
                    pending,
                    backup_dir,
                    attempt_number=attempt,
                )

            next_pending = []
            for item, success, error_msg in results:
                if success:
                    succeeded_names.append(item["filename"])
                else:
                    failed_names.append(item["filename"])
                    errors[item["filename"]] = error_msg or "unknown error"
                    next_pending.append(item)

            # Record attempt
            attempt_result = (
                "success"
                if not failed_names
                else ("partial" if succeeded_names else "failed")
            )
            manifest.add_attempt(
                {
                    "attempt": attempt,
                    "timestamp": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "result": attempt_result,
                    "succeeded": succeeded_names,
                    "failed": failed_names,
                    "errors": errors,
                }
            )

            if not next_pending:
                logger.info(
                    "Attempt %d: all %d succeeded.", attempt, len(succeeded_names)
                )
                break

            if attempt <= config.retries:
                logger.warning(
                    "Attempt %d: %d/%d succeeded, %d failed. Retrying in %ds...",
                    attempt,
                    len(succeeded_names),
                    len(succeeded_names) + len(failed_names),
                    len(failed_names),
                    config.retry_delay,
                )
                time.sleep(config.retry_delay)

            pending = next_pending

        # ── Verification fingerprint ──────────────────────────────────
        all_succeeded = not any(
            f.get("status") != "success" for f in manifest.data.get("files", [])
        )
        if config.verify and all_succeeded:
            logger.info("Running verification fingerprint on source database...")
            fingerprint = driver.verify_fingerprint(
                docker_runner,
                config.image,
                config.version,
                config.host,
                config.port,
                config.user,
                config.password,
                databases,
                config.timeout,
            )
            manifest.set_verification(fingerprint)
            logger.info(
                "Verification fingerprint: %d checks computed.", len(fingerprint)
            )

        # ── Compute final status ──────────────────────────────────────
        all_files = manifest.data.get("files", [])
        succeeded_count = sum(1 for f in all_files if f.get("status") == "success")
        failed_count = sum(1 for f in all_files if f.get("status") != "success")
        total_size = sum(
            f.get("size_bytes", 0) for f in all_files if f.get("status") == "success"
        )
        all_duration = time.monotonic() - all_start

        databases_set = set()
        for f in all_files:
            db = f.get("database")
            if db:
                databases_set.add(db)

        if failed_count == 0:
            final_status = "success"
            exit_code = 0
        elif succeeded_count > 0:
            final_status = "partial"
            exit_code = 2
        else:
            final_status = "failed"
            exit_code = 1

        manifest.finalize(
            status=final_status,
            total_files=len(all_files),
            total_databases=len(databases_set),
            succeeded=succeeded_count,
            failed=failed_count,
            total_size_bytes=total_size,
            total_duration_seconds=all_duration,
            total_attempts=total_attempts,
        )

        # ── Log summary ──────────────────────────────────────────────
        if exit_code == 0:
            logger.info(
                "Backup completed successfully: %s — %d files, %d bytes total. Attempts: %d.",
                f"{config.connection}/{backup_dir.name}",
                succeeded_count,
                total_size,
                total_attempts,
            )
        elif exit_code == 2:
            failed_list = [
                f.get("filename") for f in all_files if f.get("status") != "success"
            ]
            logger.warning(
                "Backup partially completed after %d attempts. %d/%d succeeded. Failed: %s",
                total_attempts,
                succeeded_count,
                len(all_files),
                failed_list,
            )
        else:
            failed_list = [
                f.get("filename") for f in all_files if f.get("status") != "success"
            ]
            logger.error(
                "Backup failed — all %d dumps failed after %d attempts. Failed: %s",
                len(all_files),
                total_attempts,
                failed_list,
            )

        # ── Retention ─────────────────────────────────────────────────
        retention = RetentionManager()
        try:
            retention.run(
                output_dir=config.output_dir,
                connection=config.connection,
                current_status=final_status,
                retain_successful=config.retain_successful,
                retain_partial=config.retain_partial,
            )
        except Exception as exc:
            logger.warning("Retention failed (non-fatal): %s", exc)

        # ── Write result file ─────────────────────────────────────────
        if config.result_file:
            try:
                relative_path = f"{config.connection}/{backup_dir.name}"
                Path(config.result_file).write_text(relative_path + "\n")
                logger.info(
                    "Result file written: %s → %s", relative_path, config.result_file
                )
            except OSError as exc:
                logger.warning("Failed to write result file (non-fatal): %s", exc)

        return exit_code

    # ── Directory creation ────────────────────────────────────────────

    def _create_backup_dir(self, config: BackupConfig) -> Path:
        """Create the dated output directory with YYYY-MM-DD.NNN counter."""
        conn_dir = Path(config.output_dir) / config.connection
        conn_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        counter = 1

        # Scan existing directories to find the highest counter for today
        for d in conn_dir.iterdir():
            if d.is_dir() and d.name.startswith(f"{today}."):
                try:
                    existing_counter = int(d.name.split(".")[-1])
                    counter = max(counter, existing_counter + 1)
                except ValueError:
                    pass

        backup_dir = conn_dir / f"{today}.{counter:03d}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    # ── Work discovery ────────────────────────────────────────────────

    def _discover_work(
        self,
        config: BackupConfig,
        driver: BaseDriver,
        docker_runner: DockerRunner,
        manifest: Optional[Manifest] = None,
    ) -> list[dict[str, Any]]:
        """Build the list of dump work items based on mode."""
        logger = get_logger()
        items: list[dict[str, Any]] = []

        # Globals
        if config.globals_included and not config.tables:
            items.append(
                {
                    "type": "globals",
                    "filename": "globals.sql",
                    "database": None,
                    "schema": None,
                    "table": None,
                }
            )

        if config.globals_only:
            return items

        if config.tables:
            for table_spec in config.tables:
                parts = table_spec.split(".")
                if config.driver == "postgres" and len(parts) == 3:
                    db, schema, table = parts
                    items.append(
                        {
                            "type": "table",
                            "filename": f"{_safe_name(db)}/table.{_safe_name(schema)}.{_safe_name(table)}.sql",
                            "database": db,
                            "schema": schema,
                            "table": table,
                        }
                    )
                elif len(parts) == 2:
                    db, table = parts
                    items.append(
                        {
                            "type": "table",
                            "filename": f"{_safe_name(db)}/table.{_safe_name(table)}.sql",
                            "database": db,
                            "schema": None,
                            "table": table,
                        }
                    )
            if manifest:
                databases = list(set(i["database"] for i in items if i.get("database")))
                manifest.set_databases(databases)
            return items

        # Determine databases to process
        if config.full or config.databases_only:
            databases = driver.list_databases(
                docker_runner,
                config.image,
                config.version,
                config.host,
                config.port,
                config.user,
                config.password,
                config.timeout,
            )
            if not databases:
                if config.databases_only:
                    logger.warning(
                        "No user databases found on the server. Nothing to back up."
                    )
                else:
                    logger.warning(
                        "No user databases found on the server. Only globals will be backed up."
                    )
        elif config.databases:
            databases = config.databases
        else:
            databases = []

        if manifest:
            manifest.set_databases(databases)

        for db in databases:
            if config.driver in ("mysql", "mariadb"):
                # MySQL/MariaDB: one dump per database (full.sql)
                items.append(
                    {
                        "type": "schema",
                        "filename": f"{_safe_name(db)}/full.sql",
                        "database": db,
                        "schema": None,
                        "table": None,
                    }
                )
            else:
                # PostgreSQL: discover schemas then dump each
                schemas = driver.list_schemas(
                    docker_runner,
                    config.image,
                    config.version,
                    config.host,
                    config.port,
                    config.user,
                    config.password,
                    db,
                    config.timeout,
                )
                if schemas is None:
                    schemas = []

                # Apply --schemas filter if provided
                if config.schemas:
                    schemas = [s for s in schemas if s in config.schemas]

                for schema in schemas:
                    items.append(
                        {
                            "type": "schema",
                            "filename": f"{_safe_name(db)}/schema.{_safe_name(schema)}.sql",
                            "database": db,
                            "schema": schema,
                            "table": None,
                        }
                    )

        logger.info(
            "Discovered %d dump operations across %d database(s).",
            len(items),
            len(databases),
        )
        return items

    # ── Execution ─────────────────────────────────────────────────────

    def _run_sequential(
        self,
        config: BackupConfig,
        driver: BaseDriver,
        docker_runner: DockerRunner,
        manifest: Manifest,
        items: list[dict[str, Any]],
        backup_dir: Path,
        attempt_number: int = 1,
    ) -> list[tuple[dict[str, Any], bool, Optional[str]]]:
        """Run dump items one at a time."""
        results = []
        for item in items:
            success, error = self._execute_dump(
                config,
                driver,
                docker_runner,
                manifest,
                item,
                backup_dir,
                attempt_number=attempt_number,
            )
            results.append((item, success, error))
        return results

    def _run_parallel(
        self,
        config: BackupConfig,
        driver: BaseDriver,
        docker_runner: DockerRunner,
        manifest: Manifest,
        items: list[dict[str, Any]],
        backup_dir: Path,
        attempt_number: int = 1,
    ) -> list[tuple[dict[str, Any], bool, Optional[str]]]:
        """Run dump items in parallel using ThreadPoolExecutor."""
        results: list[tuple[dict[str, Any], bool, Optional[str]]] = []

        # Globals always run first, sequentially
        globals_items = [i for i in items if i["type"] == "globals"]
        other_items = [i for i in items if i["type"] != "globals"]

        for item in globals_items:
            success, error = self._execute_dump(
                config,
                driver,
                docker_runner,
                manifest,
                item,
                backup_dir,
                attempt_number=attempt_number,
            )
            results.append((item, success, error))

        with ThreadPoolExecutor(max_workers=config.parallel) as executor:
            futures = {
                executor.submit(
                    self._execute_dump,
                    config,
                    driver,
                    docker_runner,
                    manifest,
                    item,
                    backup_dir,
                    attempt_number,
                ): item
                for item in other_items
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    success, error = future.result()
                    results.append((item, success, error))
                except Exception as exc:
                    results.append((item, False, str(exc)))

        return results

    def _execute_dump(
        self,
        config: BackupConfig,
        driver: BaseDriver,
        docker_runner: DockerRunner,
        manifest: Manifest,
        item: dict[str, Any],
        backup_dir: Path,
        attempt_number: int = 1,
    ) -> tuple[bool, Optional[str]]:
        """Execute a single dump operation and record it in the manifest.

        Returns (success, error_message).
        """
        logger = get_logger()
        filename = item["filename"]
        item_type = item["type"]
        database = item.get("database")
        schema = item.get("schema")
        table = item.get("table")

        logger.info("Dumping %s ...", filename)

        # Remove previous failed entry if retrying
        manifest.remove_file(filename)

        # Ensure parent directory exists
        file_path = backup_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.monotonic()

        try:
            # Stream dump directly to a raw .sql file on disk (no memory buffering)
            raw_path = file_path
            raw_path.parent.mkdir(parents=True, exist_ok=True)

            if item_type == "globals":
                result = driver.dump_globals(
                    docker_runner,
                    config.image,
                    config.version,
                    config.host,
                    config.port,
                    config.user,
                    config.password,
                    config.timeout,
                    output_path=raw_path,
                )
            elif item_type == "schema":
                result = driver.dump_schema(
                    docker_runner,
                    config.image,
                    config.version,
                    config.host,
                    config.port,
                    config.user,
                    config.password,
                    database or "",
                    schema,
                    config.timeout,
                    output_path=raw_path,
                )
            elif item_type == "table":
                result = driver.dump_table(
                    docker_runner,
                    config.image,
                    config.version,
                    config.host,
                    config.port,
                    config.user,
                    config.password,
                    database or "",
                    schema,
                    table or "",
                    config.timeout,
                    output_path=raw_path,
                )
            else:
                return False, f"Unknown item type: {item_type}"

            duration = time.monotonic() - start_time

            if result.returncode == -1:
                # Timeout
                logger.warning(
                    "Dump of %s timed out after %ds — skipping.",
                    filename,
                    config.timeout,
                )
                raw_path.unlink(missing_ok=True)
                manifest.add_file(
                    {
                        "filename": filename,
                        "type": item_type,
                        "database": database,
                        **({"schema": schema} if schema else {}),
                        "size_bytes": 0,
                        "checksum_sha256": None,
                        "duration_seconds": round(duration, 1),
                        "status": "timeout",
                    }
                )
                return False, f"Timed out after {config.timeout}s"

            if result.returncode != 0:
                error_msg = result.stderr.strip()
                logger.error("Dump of %s failed: %s", filename, error_msg)
                raw_path.unlink(missing_ok=True)
                manifest.add_file(
                    {
                        "filename": filename,
                        "type": item_type,
                        "database": database,
                        **({"schema": schema} if schema else {}),
                        "size_bytes": 0,
                        "checksum_sha256": None,
                        "duration_seconds": round(duration, 1),
                        "status": "failed",
                    }
                )
                return False, error_msg

            # Pipeline: compress → encrypt (reading from the raw file on disk)
            final_filename = filename
            if config.compress:
                final_filename += ".gz"
            if config.encrypt:
                final_filename += ".enc"

            final_path = backup_dir / final_filename
            final_path.parent.mkdir(parents=True, exist_ok=True)

            if config.compress and config.encrypt:
                gz_path = backup_dir / (filename + ".gz")
                try:
                    with open(raw_path, "rb") as f_in, gzip.open(gz_path, "wb") as gz:
                        while True:
                            chunk = f_in.read(65536)
                            if not chunk:
                                break
                            gz.write(chunk)
                    encrypt_file(gz_path, final_path)
                finally:
                    gz_path.unlink(missing_ok=True)
                    raw_path.unlink(missing_ok=True)
            elif config.compress:
                with open(raw_path, "rb") as f_in, gzip.open(final_path, "wb") as gz:
                    while True:
                        chunk = f_in.read(65536)
                        if not chunk:
                            break
                        gz.write(chunk)
                raw_path.unlink(missing_ok=True)
            elif config.encrypt:
                try:
                    encrypt_file(raw_path, final_path)
                finally:
                    raw_path.unlink(missing_ok=True)
            else:
                # No compression or encryption — raw file is the final file
                if raw_path != final_path:
                    raw_path.rename(final_path)

            # Compute checksum on the FINAL file
            checksum = sha256_file(final_path)
            size_bytes = final_path.stat().st_size

            if size_bytes == 0:
                logger.warning("Dump produced empty file: %s", final_path)
                manifest.add_file(
                    {
                        "filename": final_filename,
                        "type": item_type,
                        "database": database,
                        **({"schema": schema} if schema else {}),
                        "size_bytes": 0,
                        "checksum_sha256": None,
                        "duration_seconds": round(duration, 1),
                        "status": "failed",
                        "attempt": attempt_number,
                    }
                )
                return False, "Dump produced empty file"

            file_entry: dict[str, Any] = {
                "filename": final_filename,
                "type": item_type,
                "database": database,
                "size_bytes": size_bytes,
                "checksum_sha256": checksum,
                "duration_seconds": round(duration, 1),
                "status": "success",
                "attempt": attempt_number,
            }
            if schema:
                file_entry["schema"] = schema

            manifest.add_file(file_entry)
            logger.info(
                "Dumped %s (%d bytes, %.1fs)", final_filename, size_bytes, duration
            )
            return True, None

        except Exception as exc:
            duration = time.monotonic() - start_time
            error_msg = str(exc)
            logger.error("Dump of %s failed: %s", filename, error_msg)
            manifest.add_file(
                {
                    "filename": filename,
                    "type": item_type,
                    "database": database,
                    **({"schema": schema} if schema else {}),
                    "size_bytes": 0,
                    "checksum_sha256": None,
                    "duration_seconds": round(duration, 1),
                    "status": "failed",
                }
            )
            return False, error_msg
