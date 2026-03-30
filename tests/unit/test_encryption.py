"""Tests for encryption round-trip."""

from unittest.mock import patch, MagicMock

import pytest

from db_backup_orchestrator.utils.encryption import encrypt_file, decrypt_file


@pytest.fixture
def sample_sql_file(tmp_path):
    """Create a sample SQL file for testing."""
    sql_content = b"CREATE TABLE users (id INT PRIMARY KEY, name TEXT);\nINSERT INTO users VALUES (1, 'Alice');\n"
    path = tmp_path / "sample.sql"
    path.write_bytes(sql_content)
    return path


class TestEncryptDecryptRoundTrip:
    """Test encrypt then decrypt produces original content."""

    def test_encrypt_then_decrypt_roundtrip(
        self, tmp_path, sample_sql_file, monkeypatch
    ):
        """Encrypt a file, then decrypt it, and verify the content matches the original."""
        monkeypatch.setenv("BACKUP_ENCRYPT_KEY", "test-encryption-key-2026")

        original_content = sample_sql_file.read_bytes()
        encrypted_path = tmp_path / "sample.sql.enc"
        decrypted_path = tmp_path / "sample_decrypted.sql"

        encrypt_file(sample_sql_file, encrypted_path)

        # Encrypted file should exist and differ from original
        assert encrypted_path.exists()
        encrypted_content = encrypted_path.read_bytes()
        assert encrypted_content != original_content
        assert len(encrypted_content) > 0

        decrypt_file(encrypted_path, decrypted_path)

        # Decrypted content should match original
        assert decrypted_path.exists()
        decrypted_content = decrypted_path.read_bytes()
        assert decrypted_content == original_content

    def test_encrypt_large_file_roundtrip(self, tmp_path, monkeypatch):
        """Test encryption round-trip with a larger file."""
        monkeypatch.setenv("BACKUP_ENCRYPT_KEY", "large-file-key-2026")

        # Create a 100KB file
        large_content = b"INSERT INTO events VALUES " + b"(1, 'test', NOW());\n" * 5000
        input_path = tmp_path / "large.sql"
        input_path.write_bytes(large_content)

        encrypted_path = tmp_path / "large.sql.enc"
        decrypted_path = tmp_path / "large_decrypted.sql"

        encrypt_file(input_path, encrypted_path)
        decrypt_file(encrypted_path, decrypted_path)

        assert decrypted_path.read_bytes() == large_content


class TestEncryptionMissingKey:
    """Test that missing key env var raises error."""

    def test_encrypt_missing_key_raises(self, tmp_path, sample_sql_file, monkeypatch):
        monkeypatch.delenv("BACKUP_ENCRYPT_KEY", raising=False)
        encrypted_path = tmp_path / "sample.sql.enc"

        with pytest.raises(RuntimeError, match="BACKUP_ENCRYPT_KEY"):
            encrypt_file(sample_sql_file, encrypted_path)

    def test_decrypt_missing_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BACKUP_ENCRYPT_KEY", raising=False)
        # Create a dummy encrypted file
        encrypted_path = tmp_path / "dummy.enc"
        encrypted_path.write_bytes(b"encrypted content")
        decrypted_path = tmp_path / "dummy.sql"

        with pytest.raises(RuntimeError, match="BACKUP_ENCRYPT_KEY"):
            decrypt_file(encrypted_path, decrypted_path)


class TestEncryptionFailure:
    """Test that encryption/decryption failures are reported."""

    @patch("db_backup_orchestrator.utils.encryption.subprocess.run")
    def test_encrypt_failure_raises(
        self, mock_run, tmp_path, sample_sql_file, monkeypatch
    ):
        monkeypatch.setenv("BACKUP_ENCRYPT_KEY", "test-key")
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr=b"openssl error: bad encrypt",
        )
        encrypted_path = tmp_path / "sample.sql.enc"

        with pytest.raises(RuntimeError, match="Encryption failed"):
            encrypt_file(sample_sql_file, encrypted_path)

    @patch("db_backup_orchestrator.utils.encryption.subprocess.run")
    def test_decrypt_failure_raises(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_ENCRYPT_KEY", "wrong-key")
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr=b"bad decrypt",
        )
        encrypted_path = tmp_path / "sample.enc"
        encrypted_path.write_bytes(b"garbage")
        decrypted_path = tmp_path / "sample.sql"

        with pytest.raises(RuntimeError, match="Decryption failed"):
            decrypt_file(encrypted_path, decrypted_path)
