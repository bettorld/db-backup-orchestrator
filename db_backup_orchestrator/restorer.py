"""Restore orchestrator — reads a backup manifest and restores to a target DB."""

import gzip
import os
import time
from pathlib import Path

from db_backup_orchestrator.config import RestoreConfig
from db_backup_orchestrator.docker_runner import DockerRunner
from db_backup_orchestrator.drivers import get_driver
from db_backup_orchestrator.manifest import RestoreLog
from db_backup_orchestrator.utils.encryption import decrypt_file
from db_backup_orchestrator.utils.logging import get_logger
from db_backup_orchestrator.validation import validate_restore, _get_files_to_restore


class Restorer:
    """Orchestrates the full restore lifecycle."""

    def run(self, config: RestoreConfig, docker_runner: DockerRunner) -> int:
        """Execute the restore and return an exit code (0, 1, or 2)."""
        logger = get_logger()

        # ── Validate R1-R12 ───────────────────────────────────────────
        manifest = validate_restore(config, docker_runner)

        # ── Set encryption key in env if needed ───────────────────────
        if manifest.get("encrypt") and config.encrypt_key:
            os.environ["BACKUP_ENCRYPT_KEY"] = config.encrypt_key

        # ── Resolve driver ────────────────────────────────────────────
        driver = get_driver(config.driver or manifest["driver"], version=config.effective_version)
        image = config.image
        version = config.effective_version

        # ── Initialize restore log ────────────────────────────────────
        backup_dir = Path(config.from_path)
        restore_log = RestoreLog(backup_dir)
        restore_log.create(
            source=config.from_path,
            host=config.host,
            port=config.port,
            driver=config.driver or manifest["driver"],
            driver_version=version,
            mode=config.mode,
            drop_databases=config.drop_databases,
            restore_timeout=config.timeout,
            drop_users=config.drop_users,
        )

        # ── Determine files to restore ────────────────────────────────
        all_files = manifest.get("files", [])
        files_to_restore = self._order_files(config, all_files)

        if config.dry_run:
            logger.info("[DRY RUN] Would restore %d file(s):", len(files_to_restore))
            for f in files_to_restore:
                logger.info("[DRY RUN]   %s", f.get("filename"))
            restore_log.set_status("success")
            return 0

        # ── Execute restore ───────────────────────────────────────────
        restore_log.set_status("running")
        all_start = time.monotonic()
        succeeded = 0
        failed = 0
        exit_code = 0
        dropped_databases: set[str] = (
            set()
        )  # Track DBs already dropped to avoid re-dropping

        for file_entry in files_to_restore:
            filename = file_entry.get("filename", "")
            file_type = file_entry.get("type", "")
            database = file_entry.get("database")
            file_path = backup_dir / filename

            logger.info("Restoring %s ...", filename)
            start_time = time.monotonic()

            try:
                # Read and decompose the file based on extension
                sql_data = self._read_file(file_path, manifest.get("encrypt", False))

                # Handle database creation / drop for non-globals files
                #
                # MySQL/MariaDB schema dumps (mysqldump --databases) include
                # CREATE DATABASE + USE in the SQL output, so the restorer
                # should NOT explicitly create/drop — the dump handles it.
                # Only PostgreSQL needs explicit DB management for schema restores.
                is_mysql_schema = (
                    config.driver in ("mysql", "mariadb")
                    and file_type == "schema"
                )

                # MySQL/MariaDB schema: dump SQL has CREATE DATABASE + USE,
                # so we only need to DROP if --drop-databases, skip CREATE.
                # Always attempt DROP IF EXISTS (not just when DB exists) to
                # clean up orphaned schema directories from failed restores.
                if is_mysql_schema and database and config.drop_databases and database not in dropped_databases:
                    logger.warning(
                        "Dropping database '%s' on %s before restore.",
                        database,
                        config.host,
                    )
                    drop_result = driver.drop_database(
                        docker_runner,
                        image,
                        version,
                        config.host,
                        config.port,
                        config.user,
                        config.password,
                        database,
                        config.timeout,
                    )
                    if drop_result.returncode != 0:
                        error_msg = f"Failed to drop database '{database}': {drop_result.stderr.strip()}"
                        logger.error(error_msg)
                        duration = time.monotonic() - start_time
                        restore_log.add_file(
                            {
                                "filename": filename,
                                "type": file_type,
                                **({"database": database} if database else {}),
                                "status": "failed",
                                "duration_seconds": round(duration, 1),
                                "checksum_verified": True,
                                "error": error_msg,
                            }
                        )
                        failed += 1
                        exit_code = 2
                        break
                    dropped_databases.add(database)
                elif is_mysql_schema and database and not config.drop_databases and database not in dropped_databases:
                    db_exists = driver.check_database_exists(
                        docker_runner,
                        image,
                        version,
                        config.host,
                        config.port,
                        config.user,
                        config.password,
                        database,
                        config.connect_timeout,
                    )
                    if db_exists:
                        error_msg = (
                            f"Database '{database}' already exists on {config.host}. "
                            f"Use --drop-databases to drop and recreate."
                        )
                        logger.error(error_msg)
                        duration = time.monotonic() - start_time
                        restore_log.add_file(
                            {
                                "filename": filename,
                                "type": file_type,
                                **({"database": database} if database else {}),
                                "status": "failed",
                                "duration_seconds": round(duration, 1),
                                "checksum_verified": True,
                                "error": error_msg,
                            }
                        )
                        failed += 1
                        exit_code = 2
                        break

                if file_type != "globals" and database and not is_mysql_schema:
                    db_exists = driver.check_database_exists(
                        docker_runner,
                        image,
                        version,
                        config.host,
                        config.port,
                        config.user,
                        config.password,
                        database,
                        config.connect_timeout,
                    )

                    # For schema restores, require --drop-databases if DB already exists
                    # (skip check if we already dropped this DB in this run)
                    if (
                        file_type == "schema"
                        and db_exists
                        and not config.drop_databases
                        and database not in dropped_databases
                    ):
                        error_msg = (
                            f"Database '{database}' already exists on {config.host}. "
                            f"Use --drop-databases to drop and recreate."
                        )
                        logger.error(error_msg)
                        duration = time.monotonic() - start_time
                        restore_log.add_file(
                            {
                                "filename": filename,
                                "type": file_type,
                                **({"database": database} if database else {}),
                                "status": "failed",
                                "duration_seconds": round(duration, 1),
                                "checksum_verified": True,
                                "error": error_msg,
                            }
                        )
                        failed += 1
                        exit_code = 2
                        break  # Stop on first failure

                    if (
                        file_type == "schema"
                        and db_exists
                        and config.drop_databases
                        and database not in dropped_databases
                    ):
                        logger.warning(
                            "Dropping database '%s' on %s before restore.",
                            database,
                            config.host,
                        )
                        drop_result = driver.drop_database(
                            docker_runner,
                            image,
                            version,
                            config.host,
                            config.port,
                            config.user,
                            config.password,
                            database,
                            config.timeout,
                        )
                        if drop_result.returncode != 0:
                            error_msg = f"Failed to drop database '{database}': {drop_result.stderr.strip()}"
                            logger.error(error_msg)
                            duration = time.monotonic() - start_time
                            restore_log.add_file(
                                {
                                    "filename": filename,
                                    "type": file_type,
                                    **({"database": database} if database else {}),
                                    "status": "failed",
                                    "duration_seconds": round(duration, 1),
                                    "checksum_verified": True,
                                    "error": error_msg,
                                }
                            )
                            failed += 1
                            exit_code = 2
                            break

                    # For table restores, DB existing is expected — just ensure it exists
                    # For schema restores, create after drop or if it didn't exist
                    if not db_exists or (
                        file_type == "schema"
                        and config.drop_databases
                        and database not in dropped_databases
                    ):
                        create_result = driver.create_database(
                            docker_runner,
                            image,
                            version,
                            config.host,
                            config.port,
                            config.user,
                            config.password,
                            database,
                            config.timeout,
                        )
                        if create_result.returncode != 0:
                            logger.debug(
                                "Create database '%s' returned %d (may already exist or be handled by dump).",
                                database,
                                create_result.returncode,
                            )
                        dropped_databases.add(database)

                # MySQL/MariaDB: table restores still need the DB to exist
                if file_type == "table" and database and config.driver in ("mysql", "mariadb"):
                    db_exists = driver.check_database_exists(
                        docker_runner,
                        image,
                        version,
                        config.host,
                        config.port,
                        config.user,
                        config.password,
                        database,
                        config.connect_timeout,
                    )
                    if not db_exists:
                        create_result = driver.create_database(
                            docker_runner,
                            image,
                            version,
                            config.host,
                            config.port,
                            config.user,
                            config.password,
                            database,
                            config.timeout,
                        )
                        if create_result.returncode != 0:
                            logger.debug(
                                "Create database '%s' returned %d.",
                                database,
                                create_result.returncode,
                            )

                # Drop non-system users before restoring globals if --drop-users
                if file_type == "globals" and config.drop_users:
                    logger.info(
                        "Dropping non-system users on %s before restoring globals.",
                        config.host,
                    )
                    try:
                        users_to_drop = driver.list_users(
                            docker_runner,
                            image,
                            version,
                            config.host,
                            config.port,
                            config.user,
                            config.password,
                            config.timeout,
                        )
                        for u in users_to_drop:
                            logger.info("Dropping user: %s", u)
                            drop_result = driver.drop_user(
                                docker_runner,
                                image,
                                version,
                                config.host,
                                config.port,
                                config.user,
                                config.password,
                                u,
                                config.timeout,
                            )
                            if drop_result.returncode != 0:
                                logger.warning(
                                    "Failed to drop user '%s': %s",
                                    u,
                                    drop_result.stderr.strip(),
                                )
                    except Exception as exc:
                        logger.warning("Error during user drop: %s", exc)

                # Execute the restore command
                if file_type == "globals":
                    result = driver.restore_globals(
                        docker_runner,
                        image,
                        version,
                        config.host,
                        config.port,
                        config.user,
                        config.password,
                        sql_data,
                        config.timeout,
                    )
                elif file_type == "table":
                    result = driver.restore_table(
                        docker_runner,
                        image,
                        version,
                        config.host,
                        config.port,
                        config.user,
                        config.password,
                        database or "",
                        sql_data,
                        config.timeout,
                    )
                else:
                    # schema or full database
                    result = driver.restore_schema(
                        docker_runner,
                        image,
                        version,
                        config.host,
                        config.port,
                        config.user,
                        config.password,
                        database or "",
                        sql_data,
                        config.timeout,
                    )

                duration = time.monotonic() - start_time

                if result.returncode == -1:
                    error_msg = f"Restore timed out after {config.timeout}s"
                    logger.error(
                        "Restore of %s timed out after %ds.", filename, config.timeout
                    )
                    restore_log.add_file(
                        {
                            "filename": filename,
                            "type": file_type,
                            **({"database": database} if database else {}),
                            "status": "timeout",
                            "duration_seconds": round(duration, 1),
                            "checksum_verified": True,
                            "error": error_msg,
                        }
                    )
                    failed += 1
                    exit_code = 2
                    break  # Stop on first failure

                if result.returncode != 0:
                    error_msg = result.stderr.strip()
                    logger.error("Restore of %s failed: %s", filename, error_msg)
                    restore_log.add_file(
                        {
                            "filename": filename,
                            "type": file_type,
                            **({"database": database} if database else {}),
                            "status": "failed",
                            "duration_seconds": round(duration, 1),
                            "checksum_verified": True,
                            "error": error_msg,
                        }
                    )
                    failed += 1
                    exit_code = 2
                    break  # Stop on first failure

                # Success
                restore_log.add_file(
                    {
                        "filename": filename,
                        "type": file_type,
                        **({"database": database} if database else {}),
                        **(
                            {"schema": file_entry.get("schema")}
                            if file_entry.get("schema")
                            else {}
                        ),
                        "status": "success",
                        "duration_seconds": round(duration, 1),
                        "checksum_verified": True,
                    }
                )
                succeeded += 1
                logger.info("Restored %s (%.1fs)", filename, duration)

            except Exception as exc:
                duration = time.monotonic() - start_time
                error_msg = str(exc)
                logger.error("Restore of %s failed: %s", filename, error_msg)
                restore_log.add_file(
                    {
                        "filename": filename,
                        "type": file_type,
                        **({"database": database} if database else {}),
                        "status": "failed",
                        "duration_seconds": round(duration, 1),
                        "checksum_verified": False,
                        "error": error_msg,
                    }
                )
                failed += 1
                exit_code = 2
                break  # Stop on first failure

        # ── Verification fingerprint ──────────────────────────────────
        if config.verify and exit_code == 0:
            backup_verification = manifest.get("verification")
            if not backup_verification:
                logger.warning(
                    "Verification requested but backup manifest has no verification data. Skipping."
                )
            else:
                logger.info("Running verification fingerprint on target database...")
                target_fingerprint = driver.verify_fingerprint(
                    docker_runner,
                    image,
                    version,
                    config.host,
                    config.port,
                    config.user,
                    config.password,
                    manifest.get("databases", []),
                    config.timeout,
                )
                # Compare each check
                backup_checks = backup_verification.get("checks", {})
                any_failed = False
                for check_name in sorted(
                    set(list(backup_checks.keys()) + list(target_fingerprint.keys()))
                    - {"combined"}
                ):
                    backup_hash = backup_checks.get(check_name, "")
                    target_hash = target_fingerprint.get(check_name, "")
                    if backup_hash == target_hash:
                        logger.info("Verification check '%s': PASS", check_name)
                    else:
                        logger.warning(
                            "Verification check '%s': FAIL (backup=%s, target=%s)",
                            check_name,
                            backup_hash,
                            target_hash,
                        )
                        any_failed = True

                # Compare combined hash
                backup_combined = backup_verification.get("combined", "")
                target_combined = target_fingerprint.get("combined", "")
                if backup_combined == target_combined:
                    logger.info("Verification combined hash: PASS")
                else:
                    logger.warning(
                        "Verification combined hash: FAIL (backup=%s, target=%s)",
                        backup_combined,
                        target_combined,
                    )
                    any_failed = True

                if any_failed:
                    logger.warning(
                        "Some verification checks failed. This is informational only."
                    )
                else:
                    logger.info("All verification checks passed.")

        # ── Finalize ──────────────────────────────────────────────────
        total_duration = time.monotonic() - all_start

        if exit_code == 0:
            final_status = "success"
        elif succeeded > 0:
            final_status = "partial"
        else:
            final_status = "failed"

        restore_log.finalize(
            status=final_status,
            total_files=succeeded + failed,
            succeeded=succeeded,
            failed=failed,
            total_duration_seconds=total_duration,
        )

        if exit_code == 0:
            logger.info(
                "Restore completed successfully. %d file(s) restored.", succeeded
            )
        else:
            logger.warning(
                "Restore %s. %d succeeded, %d failed.",
                "partially completed" if succeeded > 0 else "failed",
                succeeded,
                failed,
            )

        return exit_code

    # ── Helpers ───────────────────────────────────────────────────────

    def _order_files(self, config: RestoreConfig, all_files: list[dict]) -> list[dict]:
        """Order files for restore: globals first, then databases/schemas in manifest order."""
        files_to_restore = _get_files_to_restore(config, all_files)

        # Separate globals and non-globals
        globals_files = [f for f in files_to_restore if f.get("type") == "globals"]
        other_files = [f for f in files_to_restore if f.get("type") != "globals"]

        # Globals first, then the rest in manifest order
        ordered: list[dict] = []
        if config.globals_included:
            ordered.extend(globals_files)
        ordered.extend(other_files)

        return ordered

    def _read_file(self, file_path: Path, encrypted: bool) -> bytes:
        """Read a backup file, decrypting and decompressing as needed.

        Determines the pipeline from the file extension:
        .sql.gz.enc -> decrypt -> decompress
        .sql.gz -> decompress
        .sql.enc -> decrypt
        .sql -> raw
        """
        import tempfile

        name = file_path.name
        data: bytes

        if name.endswith(".enc"):
            # Decrypt first
            with tempfile.NamedTemporaryFile(delete=False, suffix=".decrypted") as tmp:
                tmp_path = Path(tmp.name)
            try:
                decrypt_file(file_path, tmp_path)
                decrypted_data = tmp_path.read_bytes()
            finally:
                tmp_path.unlink(missing_ok=True)

            # Check if also compressed
            stripped = name[:-4]  # remove .enc
            if stripped.endswith(".gz"):
                data = gzip.decompress(decrypted_data)
            else:
                data = decrypted_data
        elif name.endswith(".gz"):
            with gzip.open(file_path, "rb") as f:
                data = f.read()
        else:
            data = file_path.read_bytes()

        return data
