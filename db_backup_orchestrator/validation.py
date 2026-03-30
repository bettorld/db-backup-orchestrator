"""Backup (B1-B7) and Restore (R1-R12) validation pipelines.

Each step logs [INFO] [BN] or [INFO] [RN] on success.
On failure, logs [ERROR] and calls sys.exit(1).
"""

import json
import os
import sys
from pathlib import Path

from db_backup_orchestrator.config import (
    BackupConfig,
    RestoreConfig,
    DRIVER_REGISTRY,
)
from db_backup_orchestrator.docker_runner import DockerRunner
from db_backup_orchestrator.drivers.base import BaseDriver
from db_backup_orchestrator.utils.checksum import sha256_file
from db_backup_orchestrator.utils.logging import get_logger


# ═══════════════════════════════════════════════════════════════════════
# BACKUP VALIDATION  (B1-B7)
# ═══════════════════════════════════════════════════════════════════════


def validate_backup(
    config: BackupConfig,
    docker_runner: DockerRunner,
    driver: BaseDriver,
) -> None:
    """Run the full B1-B7 validation pipeline. Exits on first failure."""
    _b1_required_args(config)
    _b2_driver_registry(config)
    _b3_docker_socket(docker_runner)
    _b4_image_exists(docker_runner, config)
    _b5_host_reachable(docker_runner, config, driver)
    _b6_db_health(docker_runner, config, driver)
    _b7_output_dir(config)

    logger = get_logger()
    logger.info("Validation complete — starting backup.")


def _b1_required_args(config: BackupConfig) -> None:
    logger = get_logger()

    # Required fields
    if not config.host:
        logger.error(
            "Fatal: Missing required argument '--host'. Provide via CLI or BACKUP_HOST env var."
        )
        sys.exit(1)
    if not config.user:
        logger.error(
            "Fatal: Missing required argument '--user'. Provide via CLI or DB_USER env var."
        )
        sys.exit(1)
    if not config.password:
        logger.error(
            "Fatal: Missing required argument '--password'. Provide via CLI or DB_PASSWORD env var."
        )
        sys.exit(1)
    if not config.driver:
        logger.error(
            "Fatal: Missing required argument '--driver'. Provide via CLI or BACKUP_DRIVER env var."
        )
        sys.exit(1)
    if not config.version:
        logger.error(
            "Fatal: Missing required argument '--version'. Provide via CLI or BACKUP_VERSION env var."
        )
        sys.exit(1)
    if not config.connection:
        logger.error(
            "Fatal: Missing required argument '--connection'. Provide via CLI or BACKUP_CONNECTION env var."
        )
        sys.exit(1)

    # Exactly one mode
    modes_set = sum(
        [
            config.full,
            config.databases_only,
            bool(config.databases),
            bool(config.tables),
            config.globals_only,
        ]
    )
    if modes_set == 0:
        logger.error(
            "Fatal: Exactly one mode required (--full, --databases-only, --databases, --tables, --globals-only). Got none."
        )
        sys.exit(1)
    if modes_set > 1:
        logger.error("Fatal: Exactly one mode required. Got multiple.")
        sys.exit(1)

    # --schemas filter constraints
    if config.schemas:
        if config.tables or config.globals_only:
            logger.error(
                "Fatal: --schemas filter is only allowed with --full or --databases modes."
            )
            sys.exit(1)
        if config.driver in ("mysql", "mariadb"):
            logger.warning(
                "--schemas is not applicable for driver '%s' (database = schema). Ignoring.",
                config.driver,
            )
            config.schemas = None

    # --tables format
    if config.tables:
        for t in config.tables:
            parts = t.split(".")
            if config.driver == "postgres" and len(parts) != 3:
                logger.error(
                    "Fatal: '--tables' values must be in 'db.schema.table' format for postgres. Got: '%s'",
                    t,
                )
                sys.exit(1)
            if config.driver in ("mysql", "mariadb") and len(parts) != 2:
                logger.error(
                    "Fatal: '--tables' values must be in 'db.table' format for %s. Got: '%s'",
                    config.driver,
                    t,
                )
                sys.exit(1)

    # Numeric validation
    for name, value in [
        ("--port", config.port),
        ("--timeout", config.timeout),
        ("--retries", config.retries),
        ("--retry-delay", config.retry_delay),
        ("--connect-timeout", config.connect_timeout),
        ("--retain-successful", config.retain_successful),
        ("--retain-partial", config.retain_partial),
    ]:
        if value is not None and value < 0:
            logger.error(
                "Fatal: %s must be a non-negative integer. Got: %d", name, value
            )
            sys.exit(1)

    if config.parallel is not None and config.parallel < 1:
        logger.error(
            "Fatal: --parallel must be at least 1. Got: %d", config.parallel
        )
        sys.exit(1)

    # Output dir must be absolute
    if not os.path.isabs(config.output_dir):
        logger.error(
            "Fatal: --output-dir must be an absolute path. Got: '%s'", config.output_dir
        )
        sys.exit(1)

    # Encryption
    if config.encrypt and not config.encrypt_key:
        logger.error(
            "Fatal: --encrypt requires --encrypt-key or BACKUP_ENCRYPT_KEY env var."
        )
        sys.exit(1)
    if config.encrypt_key and not config.encrypt:
        logger.warning("--encrypt-key provided without --encrypt. Ignoring.")

    logger.info("[B1] Arguments validated.")


def _b2_driver_registry(config: BackupConfig) -> None:
    logger = get_logger()
    if config.driver not in DRIVER_REGISTRY:
        supported = ", ".join(DRIVER_REGISTRY.keys())
        logger.error(
            "Fatal: Unknown driver '%s'. Supported drivers: %s.",
            config.driver,
            supported,
        )
        sys.exit(1)

    # Auto-fill port from driver default if not provided
    if config.port == 0:
        config.port = int(DRIVER_REGISTRY[config.driver]["default_port"])  # type: ignore[arg-type]

    logger.info("[B2] Driver '%s' is supported.", config.driver)


def _b3_docker_socket(docker_runner: DockerRunner) -> None:
    logger = get_logger()
    if not docker_runner.check_docker():
        logger.error(
            "Fatal: Docker is not available. Ensure /var/run/docker.sock is mounted and Docker daemon is running."
        )
        sys.exit(1)
    logger.info("[B3] Docker daemon is available.")


def _b4_image_exists(docker_runner: DockerRunner, config: BackupConfig) -> None:
    logger = get_logger()
    tag = f"{config.image}:{config.version}"
    if not docker_runner.ensure_image(config.image, config.version):
        logger.error(
            "Fatal: Docker image '%s' not found. Verify --driver '%s' and --version '%s' are correct.",
            tag,
            config.driver,
            config.version,
        )
        sys.exit(1)
    logger.info("[B4] Image %s ready.", tag)


def _b5_host_reachable(
    docker_runner: DockerRunner, config: BackupConfig, driver: BaseDriver
) -> None:
    logger = get_logger()
    result = driver.check_reachable(
        docker_runner,
        config.image,
        config.version,
        config.host,
        config.port,
        config.connect_timeout,
    )
    if result.returncode != 0:
        logger.error(
            "Fatal: Host %s:%d is not reachable. Connection timed out after %ds.",
            config.host,
            config.port,
            config.connect_timeout,
        )
        sys.exit(1)
    logger.info("[B5] Host %s:%d is reachable.", config.host, config.port)


def _b6_db_health(
    docker_runner: DockerRunner, config: BackupConfig, driver: BaseDriver
) -> None:
    logger = get_logger()
    result = driver.check_connection(
        docker_runner,
        config.image,
        config.version,
        config.host,
        config.port,
        config.user,
        config.password,
        config.connect_timeout,
    )
    if result.returncode != 0:
        stderr_lower = result.stderr.lower()
        if (
            "authentication" in stderr_lower
            or "password" in stderr_lower
            or "denied" in stderr_lower
        ):
            logger.error(
                "Fatal: Authentication failed on %s:%d. Check DB_USER/DB_PASSWORD.",
                config.host,
                config.port,
            )
        elif "timeout" in stderr_lower or result.returncode == -1:
            logger.error(
                "Fatal: DB health check timed out after %ds. Server may be overloaded or in recovery.",
                config.connect_timeout,
            )
        else:
            logger.error(
                "Fatal: DB health check failed on %s:%d. %s",
                config.host,
                config.port,
                result.stderr.strip(),
            )
        sys.exit(1)
    logger.info(
        "[B6] DB connection verified: %s:%d — SELECT 1 OK.", config.host, config.port
    )


def _b7_output_dir(config: BackupConfig) -> None:
    logger = get_logger()
    base = Path(config.output_dir)
    if not base.exists():
        logger.error("Fatal: Output directory '%s' does not exist.", config.output_dir)
        sys.exit(1)
    if not os.access(base, os.W_OK):
        logger.error(
            "Fatal: Output directory '%s' is not writable. Check volume mount permissions.",
            config.output_dir,
        )
        sys.exit(1)
    logger.info("[B7] Output directory %s is writable.", config.output_dir)


# ═══════════════════════════════════════════════════════════════════════
# RESTORE VALIDATION  (R1-R12)
# ═══════════════════════════════════════════════════════════════════════


def validate_restore(
    config: RestoreConfig,
    docker_runner: DockerRunner,
) -> dict:
    """Run the full R1-R12 validation pipeline.

    Returns the loaded manifest dict on success.
    Exits on first failure.
    """
    _r1_required_args(config)
    _r2_backup_dir_exists(config)
    manifest = _r3_manifest_valid(config)
    _r4_manifest_status(manifest)
    driver = _r5_driver_compat(config, manifest)
    _r6_requested_items_exist(config, manifest)
    _r7_files_exist(config, manifest)
    _r8_checksums(config, manifest)
    _r9_encryption_key(config, manifest)
    _r10_decryption_test(config, manifest)
    _r11_docker_image(config, docker_runner)
    _r12_target_db(config, docker_runner, driver)

    logger = get_logger()
    logger.info("Validation complete — starting restore.")
    return manifest


def _r1_required_args(config: RestoreConfig) -> None:
    logger = get_logger()
    if not config.from_path:
        logger.error("Fatal: Missing required argument '--from'.")
        sys.exit(1)
    if not config.host:
        logger.error(
            "Fatal: Missing required argument '--host'. Provide via CLI or BACKUP_HOST env var."
        )
        sys.exit(1)
    if not config.user:
        logger.error(
            "Fatal: Missing required argument '--user'. Provide via CLI or DB_USER env var."
        )
        sys.exit(1)
    if not config.password:
        logger.error(
            "Fatal: Missing required argument '--password'. Provide via CLI or DB_PASSWORD env var."
        )
        sys.exit(1)

    modes_set = sum(
        [
            config.full,
            config.databases_only,
            bool(config.databases),
            bool(config.tables),
            config.globals_only,
        ]
    )
    if modes_set == 0:
        logger.error(
            "Fatal: Exactly one restore mode required (--full, --databases-only, --databases, --tables, --globals-only)."
        )
        sys.exit(1)
    if modes_set > 1:
        logger.error("Fatal: Exactly one restore mode required. Got multiple.")
        sys.exit(1)

    logger.info("[R1] Arguments validated.")


def _r2_backup_dir_exists(config: RestoreConfig) -> None:
    logger = get_logger()
    p = Path(config.from_path)
    if not p.exists() or not p.is_dir():
        logger.error("Fatal: Backup directory not found: %s", config.from_path)
        sys.exit(1)
    logger.info("[R2] Backup directory found: %s", config.from_path)


def _r3_manifest_valid(config: RestoreConfig) -> dict:
    logger = get_logger()
    manifest_path = Path(config.from_path) / "manifest.json"
    if not manifest_path.exists():
        logger.error("Fatal: Invalid or missing manifest.json in %s", config.from_path)
        sys.exit(1)
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Fatal: Invalid or missing manifest.json: %s", exc)
        sys.exit(1)

    required_fields = (
        "version",
        "status",
        "driver",
        "driver_version",
        "mode",
        "globals_included",
        "files",
    )
    for field in required_fields:
        if field not in manifest:
            logger.error("Fatal: Manifest is missing required field '%s'.", field)
            sys.exit(1)

    # Populate config from manifest
    config.driver = manifest["driver"]
    config.version = manifest["driver_version"]
    config.connection = manifest.get("connection", "unknown")
    config.manifest_data = manifest

    file_count = len(manifest.get("files", []))
    logger.info(
        "[R3] Manifest loaded: status=%s, %d files, driver=%s:%s",
        manifest["status"],
        file_count,
        manifest["driver"],
        manifest["driver_version"],
    )
    return manifest


def _r4_manifest_status(manifest: dict) -> None:
    logger = get_logger()
    status = manifest.get("status", "unknown")
    if status == "success":
        logger.info("[R4] Backup status: success.")
    elif status == "partial":
        logger.warning("[R4] Backup status: partial — some files may be missing.")
    elif status in ("initialized", "running"):
        logger.error(
            "Fatal: Backup status is '%s' — backup was interrupted, cannot safely restore.",
            status,
        )
        sys.exit(1)
    elif status == "failed":
        logger.error(
            "Fatal: Backup status is 'failed' — no successful dumps to restore."
        )
        sys.exit(1)
    else:
        logger.error("Fatal: Unknown backup status '%s'.", status)
        sys.exit(1)


def _r5_driver_compat(config: RestoreConfig, manifest: dict) -> BaseDriver:
    logger = get_logger()
    manifest_driver = manifest["driver"]
    manifest_version = manifest["driver_version"]

    # If --driver was explicitly passed, it must match
    if config.driver and config.driver != manifest_driver:
        logger.error(
            "Fatal: Cross-driver restore is not supported. Backup driver: %s, requested: %s.",
            manifest_driver,
            config.driver,
        )
        sys.exit(1)

    config.driver = manifest_driver

    # Version compatibility
    effective_version = config.effective_version
    if not effective_version:
        effective_version = manifest_version

    if effective_version != manifest_version:
        if config.version_override:
            logger.warning(
                "Manifest version is %s, but restore will use %s:%s. Proceeding due to --version-override.",
                manifest_version,
                manifest_driver,
                effective_version,
            )
        else:
            logger.error(
                "Fatal: Manifest version is %s, but restore will use %s:%s. Use --version-override to acknowledge.",
                manifest_version,
                manifest_driver,
                effective_version,
            )
            sys.exit(1)

    # Auto-fill port
    if config.port == 0:
        config.port = int(DRIVER_REGISTRY[config.driver]["default_port"])  # type: ignore[arg-type]

    from db_backup_orchestrator.drivers import get_driver

    driver = get_driver(config.driver, version=effective_version)

    logger.info(
        "[R5] Driver compatibility: manifest=%s:%s, target=%s. OK.",
        manifest_driver,
        manifest_version,
        config.driver,
    )
    return driver


def _r6_requested_items_exist(config: RestoreConfig, manifest: dict) -> None:
    logger = get_logger()
    files = manifest.get("files", [])

    if config.full or config.databases_only or config.globals_only:
        logger.info(
            "[R6] Mode is %s — all items from manifest will be restored.", config.mode
        )
        return

    if config.databases:
        available_dbs = set()
        for f in files:
            db = f.get("database")
            if db:
                available_dbs.add(db)
        for db in config.databases:
            if db not in available_dbs:
                logger.error(
                    "Fatal: Database '%s' not found in backup manifest. Available: %s",
                    db,
                    sorted(available_dbs),
                )
                sys.exit(1)
        logger.info("[R6] Requested databases found in manifest: %s.", config.databases)

    if config.tables:
        available_files = set()
        for f in files:
            available_files.add(f.get("filename", ""))
        for table_spec in config.tables:
            # Build expected filename patterns
            found = False
            for f in files:
                fname = f.get("filename", "")
                if table_spec in fname or _table_spec_matches(
                    table_spec, f, config.driver or ""
                ):
                    found = True
                    break
            if not found:
                all_tables = [f["filename"] for f in files if f.get("type") == "table"]
                logger.error(
                    "Fatal: Table '%s' not found in backup manifest. Available: %s",
                    table_spec,
                    all_tables,
                )
                sys.exit(1)
        logger.info("[R6] Requested tables found in manifest: %s.", config.tables)


def _table_spec_matches(spec: str, file_entry: dict, driver: str) -> bool:
    """Check if a table spec (db.schema.table or db.table) matches a manifest file entry."""
    if file_entry.get("type") != "table":
        return False
    parts = spec.split(".")
    if driver == "postgres" and len(parts) == 3:
        db, schema, table = parts
        return (
            file_entry.get("database") == db
            and file_entry.get("schema") == schema
            and table in file_entry.get("filename", "")
        )
    elif len(parts) == 2:
        db, table = parts
        return file_entry.get("database") == db and table in file_entry.get(
            "filename", ""
        )
    return False


def _r7_files_exist(config: RestoreConfig, manifest: dict) -> None:
    logger = get_logger()
    files = manifest.get("files", [])
    backup_dir = Path(config.from_path)

    files_to_check = _get_files_to_restore(config, files)
    for f in files_to_check:
        filename = f.get("filename", "")
        if f.get("status") == "failed":
            continue
        filepath = backup_dir / filename
        if not filepath.exists():
            logger.error(
                "Fatal: File '%s' listed in manifest but missing from disk.", filename
            )
            sys.exit(1)

    logger.info("[R7] All %d backup files present on disk.", len(files_to_check))


def _r8_checksums(config: RestoreConfig, manifest: dict) -> None:
    logger = get_logger()
    files = manifest.get("files", [])
    backup_dir = Path(config.from_path)

    files_to_check = _get_files_to_restore(config, files)
    for f in files_to_check:
        if f.get("status") == "failed":
            continue
        filename = f.get("filename", "")
        expected_checksum = f.get("checksum_sha256")
        if not expected_checksum:
            continue
        filepath = backup_dir / filename
        actual = sha256_file(filepath)
        if actual != expected_checksum:
            logger.error(
                "Fatal: Checksum mismatch for %s — backup may be corrupted. Expected: %s, Got: %s",
                filename,
                expected_checksum,
                actual,
            )
            sys.exit(1)

    logger.info("[R8] Checksums verified for all %d files.", len(files_to_check))


def _r9_encryption_key(config: RestoreConfig, manifest: dict) -> None:
    logger = get_logger()
    encrypted = manifest.get("encrypt", False)
    if encrypted:
        key = config.encrypt_key or os.environ.get("BACKUP_ENCRYPT_KEY")
        if not key:
            logger.error("Fatal: Backup is encrypted but no --encrypt-key provided.")
            sys.exit(1)
        logger.info("[R9] Backup is encrypted — decryption key provided.")
    else:
        if config.encrypt_key:
            logger.warning(
                "Backup is not encrypted but --encrypt-key was provided. Ignoring."
            )
        logger.info("[R9] Backup is not encrypted — no key needed.")


def _r10_decryption_test(config: RestoreConfig, manifest: dict) -> None:
    logger = get_logger()
    if not manifest.get("encrypt", False):
        logger.info("[R10] Skipped — backup is not encrypted.")
        return

    files = manifest.get("files", [])
    files_to_check = _get_files_to_restore(config, files)
    if not files_to_check:
        logger.info("[R10] Skipped — no files to test.")
        return

    first_file = files_to_check[0]
    filename = first_file.get("filename", "")
    filepath = Path(config.from_path) / filename

    # Try to decrypt the first few bytes
    import subprocess
    import tempfile

    key = config.encrypt_key or os.environ.get("BACKUP_ENCRYPT_KEY", "")
    try:
        with tempfile.NamedTemporaryFile(delete=True) as tmp:
            env = {**os.environ, "BACKUP_ENCRYPT_KEY": key}
            result = subprocess.run(
                [
                    "openssl",
                    "enc",
                    "-d",
                    "-aes-256-cbc",
                    "-pbkdf2",
                    "-in",
                    str(filepath),
                    "-out",
                    tmp.name,
                    "-pass",
                    "env:BACKUP_ENCRYPT_KEY",
                ],
                capture_output=True,
                timeout=10,
                env=env,
            )
            if result.returncode != 0:
                stderr_text = result.stderr.decode(errors="replace").strip()
                logger.error("Fatal: Decryption failed — wrong key? %s", stderr_text)
                sys.exit(1)
    except subprocess.TimeoutExpired:
        logger.error("Fatal: Decryption test timed out after 10s.")
        sys.exit(1)

    logger.info("[R10] Decryption test passed.")


def _r11_docker_image(config: RestoreConfig, docker_runner: DockerRunner) -> None:
    logger = get_logger()
    if not docker_runner.check_docker():
        logger.error("Fatal: Docker is not available.")
        sys.exit(1)

    image = config.image
    version = config.effective_version
    if not docker_runner.ensure_image(image, version):
        logger.error("Fatal: Docker image '%s:%s' not found.", image, version)
        sys.exit(1)

    logger.info("[R11] Docker available, image %s:%s ready.", image, version)


def _r12_target_db(
    config: RestoreConfig, docker_runner: DockerRunner, driver: BaseDriver
) -> None:
    logger = get_logger()
    image = config.image
    version = config.effective_version

    # Reachability
    result = driver.check_reachable(
        docker_runner,
        image,
        version,
        config.host,
        config.port,
        config.connect_timeout,
    )
    if result.returncode != 0:
        logger.error("Fatal: Target DB unreachable: %s:%d.", config.host, config.port)
        sys.exit(1)

    # Auth
    result = driver.check_connection(
        docker_runner,
        image,
        version,
        config.host,
        config.port,
        config.user,
        config.password,
        config.connect_timeout,
    )
    if result.returncode != 0:
        logger.error("Fatal: Auth failed on target %s:%d.", config.host, config.port)
        sys.exit(1)

    logger.info("[R12] Target DB reachable: %s:%d.", config.host, config.port)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _get_files_to_restore(config: RestoreConfig, files: list[dict]) -> list[dict]:
    """Filter manifest files to only those that should be restored based on the restore mode."""
    if config.full or config.databases_only:
        return [f for f in files if f.get("status") != "failed"]

    if config.globals_only:
        return [f for f in files if f.get("type") == "globals"]

    result: list[dict] = []

    if config.databases:
        for f in files:
            if f.get("database") in config.databases and f.get("status") != "failed":
                result.append(f)

    if config.tables:
        for table_spec in config.tables:
            for f in files:
                if _table_spec_matches(table_spec, f, config.driver or ""):
                    if f.get("status") != "failed":
                        result.append(f)

    return result
