"""Tests for SHA-256 checksum utility."""

import hashlib

import pytest

from db_backup_orchestrator.utils.checksum import sha256_file


class TestSha256File:
    """Test sha256_file against known hashes."""

    def test_known_content(self, tmp_path):
        """Hash of known content matches hashlib directly."""
        content = b"hello world\n"
        path = tmp_path / "test.txt"
        path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(path) == expected

    def test_empty_file(self, tmp_path):
        """Hash of an empty file is the SHA-256 of empty bytes."""
        path = tmp_path / "empty.txt"
        path.write_bytes(b"")

        expected = hashlib.sha256(b"").hexdigest()
        assert sha256_file(path) == expected

    def test_large_file(self, tmp_path):
        """Hash of a file larger than the 64KB chunk size."""
        # 256KB of data — forces multiple chunk reads
        content = b"A" * (256 * 1024)
        path = tmp_path / "large.bin"
        path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(path) == expected

    def test_binary_content(self, tmp_path):
        """Hash works on binary (non-UTF-8) content."""
        content = bytes(range(256)) * 100
        path = tmp_path / "binary.bin"
        path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(path) == expected

    def test_nonexistent_file(self, tmp_path):
        """Raises FileNotFoundError for a missing file."""
        path = tmp_path / "missing.txt"
        with pytest.raises(FileNotFoundError):
            sha256_file(path)
