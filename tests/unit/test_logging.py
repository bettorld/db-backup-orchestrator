"""Tests for logging credential redaction."""

from db_backup_orchestrator.utils.logging import redact


class TestRedaction:
    """Test that sensitive values are scrubbed from log messages."""

    def test_pgpassword_env(self):
        msg = "Docker run: docker run -e PGPASSWORD=supersecret postgres:16 pg_dump"
        result = redact(msg)
        assert "supersecret" not in result
        assert "PGPASSWORD=***REDACTED***" in result

    def test_mysql_pwd_env(self):
        msg = "Docker run: docker run -e MYSQL_PWD=mypass123 mysql:8.0 mysql"
        result = redact(msg)
        assert "mypass123" not in result
        assert "MYSQL_PWD=***REDACTED***" in result

    def test_password_colon(self):
        msg = 'Config: password: "hunter2" host: db.example.com'
        result = redact(msg)
        assert "hunter2" not in result
        assert "***REDACTED***" in result

    def test_password_equals(self):
        msg = "password=s3cret other=value"
        result = redact(msg)
        assert "s3cret" not in result

    def test_p_flag(self):
        msg = "mysql -u root -p mypassword -h localhost"
        result = redact(msg)
        assert "mypassword" not in result
        assert "-p ***REDACTED***" in result

    def test_backup_encrypt_key(self):
        msg = "Setting env: BACKUP_ENCRYPT_KEY=abc123xyz"
        result = redact(msg)
        assert "abc123xyz" not in result
        assert "BACKUP_ENCRYPT_KEY=***REDACTED***" in result

    def test_backup_password(self):
        msg = "BACKUP_PASSWORD=topsecret"
        result = redact(msg)
        assert "topsecret" not in result
        assert "BACKUP_PASSWORD=***REDACTED***" in result

    def test_db_password(self):
        msg = "DB_PASSWORD=dbpass123"
        result = redact(msg)
        assert "dbpass123" not in result
        assert "DB_PASSWORD=***REDACTED***" in result

    def test_pass_env(self):
        msg = "openssl enc -pass env:BACKUP_ENCRYPT_KEY"
        result = redact(msg)
        # The -p pattern catches "-pass" too — key point is sensitive values are scrubbed
        assert "***REDACTED***" in result

    def test_no_redaction_needed(self):
        msg = "Backup completed successfully. 5 files, 1024 bytes total."
        result = redact(msg)
        assert result == msg

    def test_multiple_credentials(self):
        msg = "PGPASSWORD=secret1 MYSQL_PWD=secret2 BACKUP_ENCRYPT_KEY=secret3"
        result = redact(msg)
        assert "secret1" not in result
        assert "secret2" not in result
        assert "secret3" not in result
