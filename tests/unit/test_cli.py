"""Tests for CLI argument parsing and env-var fallbacks."""

import pytest

from db_backup_orchestrator.cli import parse_args
from db_backup_orchestrator.config import BackupConfig, RestoreConfig


# ---------------------------------------------------------------------------
# Backup subcommand — required args
# ---------------------------------------------------------------------------

BACKUP_REQUIRED = [
    "backup",
    "--host",
    "db.example.com",
    "--user",
    "admin",
    "--password",
    "secret",
    "--driver",
    "postgres",
    "--version",
    "16",
    "--connection",
    "prod-pg",
    "--full",
]

RESTORE_REQUIRED = [
    "restore",
    "--from",
    "/backups/prod-pg/2026-03-18.001",
    "--host",
    "db.example.com",
    "--user",
    "admin",
    "--password",
    "secret",
    "--full",
]


class TestBackupSubcommand:
    """Test backup subcommand with all required args."""

    def test_backup_full_mode(self):
        cfg = parse_args(BACKUP_REQUIRED)
        assert isinstance(cfg, BackupConfig)
        assert cfg.host == "db.example.com"
        assert cfg.user == "admin"
        assert cfg.password == "secret"
        assert cfg.driver == "postgres"
        assert cfg.version == "16"
        assert cfg.connection == "prod-pg"
        assert cfg.full is True
        assert cfg.databases is None
        assert cfg.tables is None
        assert cfg.globals_only is False

    def test_backup_databases_mode(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "mysql",
            "--version",
            "8.0",
            "--connection",
            "prod-mysql",
            "--databases",
            "app_store",
            "analytics",
        ]
        cfg = parse_args(args)
        assert isinstance(cfg, BackupConfig)
        assert cfg.databases == ["app_store", "analytics"]
        assert cfg.full is False

    def test_backup_tables_mode(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--tables",
            "app_store.public.users",
        ]
        cfg = parse_args(args)
        assert isinstance(cfg, BackupConfig)
        assert cfg.tables == ["app_store.public.users"]

    def test_backup_globals_only_mode(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--globals-only",
        ]
        cfg = parse_args(args)
        assert isinstance(cfg, BackupConfig)
        assert cfg.globals_only is True

    def test_backup_all_optional_flags(self):
        args = BACKUP_REQUIRED + [
            "--schemas",
            "inventory",
            "customers",
            "--output-dir",
            "/data/backups",
            "--no-compress",
            "--encrypt",
            "--encrypt-key",
            "my-secret-key",
            "--parallel",
            "4",
            "--timeout",
            "600",
            "--retries",
            "5",
            "--retry-delay",
            "60",
            "--retain-successful",
            "10",
            "--retain-partial",
            "3",
            "--dry-run",
            "--verbose",
            "--docker-network",
            "my-net",
        ]
        cfg = parse_args(args)
        assert isinstance(cfg, BackupConfig)
        assert cfg.schemas == ["inventory", "customers"]
        assert cfg.output_dir == "/data/backups"
        assert cfg.no_compress is True
        assert cfg.encrypt is True
        assert cfg.encrypt_key == "my-secret-key"
        assert cfg.parallel == 4
        assert cfg.timeout == 600
        assert cfg.retries == 5
        assert cfg.retry_delay == 60
        assert cfg.retain_successful == 10
        assert cfg.retain_partial == 3
        assert cfg.dry_run is True
        assert cfg.verbose is True
        assert cfg.docker_network == "my-net"


class TestRestoreSubcommand:
    """Test restore subcommand with all required args."""

    def test_restore_full_mode(self):
        cfg = parse_args(RESTORE_REQUIRED)
        assert isinstance(cfg, RestoreConfig)
        assert cfg.from_path == "/backups/prod-pg/2026-03-18.001"
        assert cfg.host == "db.example.com"
        assert cfg.user == "admin"
        assert cfg.password == "secret"
        assert cfg.full is True

    def test_restore_drop_databases_flag(self):
        args = RESTORE_REQUIRED + ["--drop-databases"]
        cfg = parse_args(args)
        assert isinstance(cfg, RestoreConfig)
        assert cfg.drop_databases is True

    def test_restore_drop_users_flag(self):
        args = RESTORE_REQUIRED + ["--drop-users"]
        cfg = parse_args(args)
        assert isinstance(cfg, RestoreConfig)
        assert cfg.drop_users is True

    def test_restore_databases_mode(self):
        args = [
            "restore",
            "--from",
            "/backups/prod-pg/2026-03-18.001",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--databases",
            "app_store",
        ]
        cfg = parse_args(args)
        assert isinstance(cfg, RestoreConfig)
        assert cfg.databases == ["app_store"]

    def test_restore_version_override(self):
        args = RESTORE_REQUIRED + ["--version-override", "15"]
        cfg = parse_args(args)
        assert isinstance(cfg, RestoreConfig)
        assert cfg.version_override == "15"
        assert cfg.effective_version == "15"


class TestEnvVarFallbacks:
    """Test that environment variables are used as fallbacks."""

    def test_db_user_env_fallback(self, monkeypatch):
        monkeypatch.setenv("DB_USER", "env_user")
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
        ]
        cfg = parse_args(args)
        assert cfg.user == "env_user"

    def test_db_password_env_fallback(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "env_pass")
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
        ]
        cfg = parse_args(args)
        assert cfg.password == "env_pass"

    def test_backup_host_env_fallback(self, monkeypatch):
        monkeypatch.setenv("BACKUP_HOST", "env-host.example.com")
        args = [
            "backup",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
        ]
        cfg = parse_args(args)
        assert cfg.host == "env-host.example.com"

    def test_backup_driver_env_fallback(self, monkeypatch):
        monkeypatch.setenv("BACKUP_DRIVER", "mysql")
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--version",
            "8.0",
            "--connection",
            "prod-mysql",
            "--full",
        ]
        cfg = parse_args(args)
        assert cfg.driver == "mysql"

    def test_backup_encrypt_key_env_fallback(self, monkeypatch):
        monkeypatch.setenv("BACKUP_ENCRYPT_KEY", "env-key-123")
        args = BACKUP_REQUIRED + ["--encrypt"]
        cfg = parse_args(args)
        assert cfg.encrypt_key == "env-key-123"

    def test_backup_output_dir_env_fallback(self, monkeypatch):
        monkeypatch.setenv("BACKUP_OUTPUT_DIR", "/mnt/backups")
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
        ]
        cfg = parse_args(args)
        assert cfg.output_dir == "/mnt/backups"

    def test_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DB_USER", "env_user")
        cfg = parse_args(BACKUP_REQUIRED)
        assert cfg.user == "admin"  # CLI wins over env


class TestMutuallyExclusiveModes:
    """Test that --full, --databases, --tables, --globals-only are mutually exclusive."""

    def test_full_and_databases_conflict(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
            "--databases",
            "app_store",
        ]
        with pytest.raises(SystemExit):
            parse_args(args)

    def test_full_and_tables_conflict(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
            "--tables",
            "app_store.public.users",
        ]
        with pytest.raises(SystemExit):
            parse_args(args)

    def test_full_and_globals_only_conflict(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
            "--globals-only",
        ]
        with pytest.raises(SystemExit):
            parse_args(args)

    def test_databases_and_tables_conflict(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--databases",
            "app_store",
            "--tables",
            "app_store.public.users",
        ]
        with pytest.raises(SystemExit):
            parse_args(args)


class TestSchemasFilterConstraints:
    """Test --schemas is only valid with --full or --databases."""

    def test_schemas_with_full_allowed(self):
        args = BACKUP_REQUIRED + ["--schemas", "inventory"]
        cfg = parse_args(args)
        assert cfg.schemas == ["inventory"]

    def test_schemas_with_databases_allowed(self):
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--databases",
            "app_store",
            "--schemas",
            "inventory",
        ]
        cfg = parse_args(args)
        assert cfg.schemas == ["inventory"]


class TestEncryptRequiresKey:
    """Test that --encrypt requires --encrypt-key (validated later in B1, but parsed here)."""

    def test_encrypt_without_key_parses(self):
        """CLI parsing succeeds; validation catches this later in B1."""
        args = BACKUP_REQUIRED + ["--encrypt"]
        cfg = parse_args(args)
        assert cfg.encrypt is True
        assert cfg.encrypt_key is None

    def test_encrypt_with_key(self):
        args = BACKUP_REQUIRED + ["--encrypt", "--encrypt-key", "my-key"]
        cfg = parse_args(args)
        assert cfg.encrypt is True
        assert cfg.encrypt_key == "my-key"


class TestMissingRequiredArgs:
    """Test that missing required args cause SystemExit."""

    def test_no_subcommand(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_backup_no_args(self):
        """Backup with no arguments still parses, but produces empty fields."""
        cfg = parse_args(["backup", "--full"])
        assert isinstance(cfg, BackupConfig)
        assert cfg.host == ""

    def test_restore_no_args(self):
        """Restore with no arguments still parses, but produces empty fields."""
        cfg = parse_args(["restore", "--full"])
        assert isinstance(cfg, RestoreConfig)
        assert cfg.from_path == ""


class TestDefaultValues:
    """Test that default values are correctly set."""

    def test_backup_defaults(self):
        cfg = parse_args(BACKUP_REQUIRED)
        assert isinstance(cfg, BackupConfig)
        assert cfg.port == 0  # filled later by B2
        assert cfg.timeout == 1800
        assert cfg.retries == 3
        assert cfg.retry_delay == 300
        assert cfg.retain_successful == 30
        assert cfg.retain_partial == 5
        assert cfg.connect_timeout == 30
        assert cfg.parallel == 1
        assert cfg.output_dir == "/backups"
        assert cfg.no_compress is False
        assert cfg.encrypt is False
        assert cfg.dry_run is False
        assert cfg.verbose is False
        assert cfg.docker_network == "host"

    def test_restore_defaults(self):
        cfg = parse_args(RESTORE_REQUIRED)
        assert isinstance(cfg, RestoreConfig)
        assert cfg.port == 0
        assert cfg.timeout == 7200
        assert cfg.connect_timeout == 30
        assert cfg.drop_databases is False
        assert cfg.drop_users is False
        assert cfg.version_override is None
        assert cfg.dry_run is False
        assert cfg.verbose is False
        assert cfg.docker_network == "host"

    def test_backup_port_from_env(self, monkeypatch):
        monkeypatch.setenv("BACKUP_PORT", "15432")
        cfg = parse_args(BACKUP_REQUIRED)
        assert cfg.port == 15432

    def test_backup_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("BACKUP_TIMEOUT", "600")
        args = [
            "backup",
            "--host",
            "db.example.com",
            "--user",
            "admin",
            "--password",
            "secret",
            "--driver",
            "postgres",
            "--version",
            "16",
            "--connection",
            "prod-pg",
            "--full",
        ]
        cfg = parse_args(args)
        assert cfg.timeout == 600
