"""AES-256-CBC encryption/decryption via openssl subprocess."""

import os
import subprocess
from pathlib import Path

from db_backup_orchestrator.utils.logging import get_logger


def encrypt_file(input_path: Path, output_path: Path) -> None:
    """Encrypt a file using AES-256-CBC with PBKDF2.

    The key is read from the BACKUP_ENCRYPT_KEY environment variable.
    It is passed to openssl via ``-pass env:BACKUP_ENCRYPT_KEY`` so it
    never appears on the command line or in logs.

    Raises:
        RuntimeError: If encryption fails or BACKUP_ENCRYPT_KEY is not set.
    """
    logger = get_logger()
    key = os.environ.get("BACKUP_ENCRYPT_KEY")
    if not key:
        raise RuntimeError("BACKUP_ENCRYPT_KEY environment variable is not set")

    cmd = [
        "openssl",
        "enc",
        "-aes-256-cbc",
        "-pbkdf2",
        "-salt",
        "-in",
        str(input_path),
        "-out",
        str(output_path),
        "-pass",
        "env:BACKUP_ENCRYPT_KEY",
    ]
    logger.debug("Encrypting %s -> %s", input_path, output_path)

    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=300,
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Encryption failed for {input_path}: {stderr_text}")


def decrypt_file(input_path: Path, output_path: Path) -> None:
    """Decrypt a file encrypted with AES-256-CBC + PBKDF2.

    The key is read from the BACKUP_ENCRYPT_KEY environment variable.

    Raises:
        RuntimeError: If decryption fails or BACKUP_ENCRYPT_KEY is not set.
    """
    logger = get_logger()
    key = os.environ.get("BACKUP_ENCRYPT_KEY")
    if not key:
        raise RuntimeError("BACKUP_ENCRYPT_KEY environment variable is not set")

    cmd = [
        "openssl",
        "enc",
        "-d",
        "-aes-256-cbc",
        "-pbkdf2",
        "-in",
        str(input_path),
        "-out",
        str(output_path),
        "-pass",
        "env:BACKUP_ENCRYPT_KEY",
    ]
    logger.debug("Decrypting %s -> %s", input_path, output_path)

    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=300,
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Decryption failed for {input_path}: {stderr_text}")
