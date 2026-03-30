"""SHA-256 file hashing utility."""

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file.

    Reads the file in 64KB chunks to handle large files without
    loading them entirely into memory.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
