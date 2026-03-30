"""Validation helper functions for integration tests."""

import gzip
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Optional


def assert_file_is_gzipped(path: Path) -> None:
    """Verify file has gzip magic bytes (1f 8b)."""
    with open(path, "rb") as f:
        magic = f.read(2)
    assert magic == b"\x1f\x8b", (
        f"Expected gzip magic bytes (1f 8b) at start of {path.name}, got {magic.hex()}"
    )
    # Also verify it can be fully decompressed
    with gzip.open(path, "rb") as f:
        _ = f.read()


def assert_file_is_encrypted(path: Path) -> None:
    """Verify file is not readable as plain text or gzip."""
    data = path.read_bytes()
    # Should not start with gzip magic
    assert data[:2] != b"\x1f\x8b", (
        f"File {path.name} starts with gzip magic but should be encrypted"
    )
    # Should not look like SQL text
    try:
        text = data[:200].decode("utf-8")
        sql_markers = ["CREATE", "INSERT", "DROP", "SELECT", "ALTER", "--"]
        for marker in sql_markers:
            assert marker not in text.upper(), (
                f"File {path.name} contains SQL marker '{marker}' — not encrypted"
            )
    except UnicodeDecodeError:
        pass  # Binary content = good, likely encrypted


def assert_file_decrypts(path: Path, key: str) -> None:
    """Decrypt file with key and verify it produces valid output."""
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".decrypted") as tmp:
        tmp_path = Path(tmp.name)

    try:
        import os

        env = {**os.environ, "BACKUP_ENCRYPT_KEY": key}
        result = subprocess.run(
            [
                "openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-pbkdf2",
                "-in",
                str(path),
                "-out",
                str(tmp_path),
                "-pass",
                "env:BACKUP_ENCRYPT_KEY",
            ],
            capture_output=True,
            timeout=30,
            env=env,
        )
        assert result.returncode == 0, (
            f"Decryption of {path.name} failed: "
            f"{result.stderr.decode(errors='replace')}"
        )
        decrypted = tmp_path.read_bytes()
        assert len(decrypted) > 0, f"Decrypted {path.name} is empty"
    finally:
        tmp_path.unlink(missing_ok=True)


def assert_manifest_valid(
    path: Path,
    expected_status: str,
    expected_files: Optional[list[str]] = None,
) -> dict:
    """Load manifest.json, check status, file list, checksums."""
    assert path.exists(), f"Manifest not found at {path}"

    data = json.loads(path.read_text())

    # Required top-level fields
    for field in (
        "version",
        "status",
        "driver",
        "driver_version",
        "mode",
        "globals_included",
        "files",
    ):
        assert field in data, f"Manifest missing required field: {field}"

    assert data["status"] == expected_status, (
        f"Expected manifest status '{expected_status}', got '{data['status']}'"
    )

    if expected_files is not None:
        actual_filenames = sorted([f["filename"] for f in data["files"]])
        expected_sorted = sorted(expected_files)
        assert actual_filenames == expected_sorted, (
            f"File list mismatch.\n"
            f"  Expected: {expected_sorted}\n"
            f"  Actual:   {actual_filenames}"
        )

    # Verify checksums for successful files
    backup_dir = path.parent
    for file_entry in data["files"]:
        if file_entry.get("status") != "success":
            continue
        checksum = file_entry.get("checksum_sha256")
        if not checksum:
            continue
        file_path = backup_dir / file_entry["filename"]
        assert file_path.exists(), f"File {file_entry['filename']} missing from disk"
        actual_checksum = _sha256(file_path)
        assert actual_checksum == checksum, (
            f"Checksum mismatch for {file_entry['filename']}: "
            f"manifest={checksum}, actual={actual_checksum}"
        )

    return data


def assert_sql_contains(path: Path, expected_strings: list[str]) -> None:
    """Decompress/decrypt if needed, verify SQL contains expected content."""
    name = path.name

    if name.endswith(".enc"):
        raise ValueError(
            "Cannot verify SQL content of encrypted file without key. "
            "Use assert_file_decrypts first, then check the decrypted output."
        )

    if name.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            content = f.read().decode("utf-8", errors="replace")
    else:
        content = path.read_text(errors="replace")

    for expected in expected_strings:
        assert expected in content, (
            f"Expected string '{expected}' not found in {path.name}"
        )


def assert_checksum_matches(path: Path, expected_sha256: str) -> None:
    """Verify file SHA-256 matches the expected value."""
    actual = _sha256(path)
    assert actual == expected_sha256, (
        f"Checksum mismatch for {path.name}: expected={expected_sha256}, actual={actual}"
    )


def wait_for_healthy(container_name: str, timeout: int = 30) -> bool:
    """Poll docker inspect until container is healthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Health.Status}}",
                    container_name,
                ],
                capture_output=True,
                timeout=5,
            )
            status = result.stdout.decode().strip()
            if status == "healthy":
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(1)
    return False


def _mariadb_use_new_binary(version: str) -> bool:
    """Check if MariaDB version uses mariadb binary (10.5+)."""
    try:
        parts = version.split(".")
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        return major > 10 or (major == 10 and minor >= 5)
    except (ValueError, IndexError):
        return True


def query_mysql(
    instance,
    query: str,
    timeout: int = 30,
    *,
    docker_network: str | None = None,
) -> str:
    """Run a SQL query against MySQL/MariaDB and return stdout.

    Uses the instance's driver/version to pick the right Docker image
    and connects via the configured network (bridge on Docker Desktop,
    host on native Linux).
    """
    from tests.integration.conftest import DOCKER_NETWORK

    network = docker_network or DOCKER_NETWORK
    if instance.driver == "mariadb":
        image = f"mariadb:{instance.version}"
    else:
        image = f"mysql:{instance.version}"

    cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--network",
        network,
        "-e",
        f"MYSQL_PWD={instance.password}",
        image,
        "mariadb"
        if instance.driver == "mariadb" and _mariadb_use_new_binary(instance.version)
        else "mysql",
        "-h",
        instance.host,
        "-P",
        str(instance.port),
        "-u",
        "root",
        "-N",
        "-B",
        "-e",
        query,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return result.stdout.decode("utf-8", errors="replace").strip()


def query_postgres(
    instance,
    query: str,
    timeout: int = 30,
    *,
    database: str = "postgres",
    docker_network: str | None = None,
) -> str:
    """Run a SQL query against PostgreSQL and return stdout.

    Uses the instance's version to pick the right Docker image
    and connects via the configured network.
    """
    from tests.integration.conftest import DOCKER_NETWORK

    network = docker_network or DOCKER_NETWORK
    image = f"postgres:{instance.version}"

    cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--network",
        network,
        "-e",
        f"PGPASSWORD={instance.password}",
        image,
        "psql",
        "-h",
        instance.host,
        "-p",
        str(instance.port),
        "-U",
        instance.user,
        "-d",
        database,
        "-t",
        "-A",
        "-c",
        query,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return result.stdout.decode("utf-8", errors="replace").strip()


def _sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
