"""Tests for MariaDBDriver binary selection based on version and driver factory."""

from unittest.mock import MagicMock

import pytest

from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.mariadb import MariaDBDriver


class TestDriverFactory:
    """Test get_driver factory function."""

    def test_get_postgres(self):
        from db_backup_orchestrator.drivers import get_driver

        driver = get_driver("postgres")
        assert driver.engine == "postgres"

    def test_get_mysql(self):
        from db_backup_orchestrator.drivers import get_driver

        driver = get_driver("mysql")
        assert driver.engine == "mysql"

    def test_get_mariadb_with_version(self):
        from db_backup_orchestrator.drivers import get_driver

        driver = get_driver("mariadb", version="10.11")
        assert driver.engine == "mariadb"

    def test_get_unknown_raises(self):
        from db_backup_orchestrator.drivers import get_driver

        with pytest.raises(ValueError, match="Unknown driver"):
            get_driver("mssql")


@pytest.fixture
def mock_runner():
    mock = MagicMock(spec=DockerRunner)
    mock.run.return_value = DockerResult(
        stdout="app_store\nanalytics\n",
        stderr="",
        returncode=0,
    )
    return mock


class TestNewBinaries:
    """Test that MariaDB >= 10.5 uses mariadb-dump, mariadb, mariadb-admin."""

    def test_version_10_11_uses_new_binaries(self):
        driver = MariaDBDriver(version="10.11")
        assert driver._dump_binary == "mariadb-dump"
        assert driver._client_binary == "mariadb"
        assert driver._admin_binary == "mariadb-admin"

    def test_version_10_5_uses_new_binaries(self):
        driver = MariaDBDriver(version="10.5")
        assert driver._dump_binary == "mariadb-dump"
        assert driver._client_binary == "mariadb"
        assert driver._admin_binary == "mariadb-admin"

    def test_version_11_0_uses_new_binaries(self):
        driver = MariaDBDriver(version="11.0")
        assert driver._dump_binary == "mariadb-dump"
        assert driver._client_binary == "mariadb"
        assert driver._admin_binary == "mariadb-admin"

    def test_version_11_4_2_uses_new_binaries(self):
        driver = MariaDBDriver(version="11.4.2")
        assert driver._dump_binary == "mariadb-dump"
        assert driver._client_binary == "mariadb"
        assert driver._admin_binary == "mariadb-admin"


class TestOldBinaries:
    """Test that MariaDB < 10.5 uses mysqldump, mysql, mysqladmin."""

    def test_version_10_4_uses_old_binaries(self):
        driver = MariaDBDriver(version="10.4")
        assert driver._dump_binary == "mysqldump"
        assert driver._client_binary == "mysql"
        assert driver._admin_binary == "mysqladmin"

    def test_version_10_3_uses_old_binaries(self):
        driver = MariaDBDriver(version="10.3")
        assert driver._dump_binary == "mysqldump"
        assert driver._client_binary == "mysql"
        assert driver._admin_binary == "mysqladmin"

    def test_version_10_0_uses_old_binaries(self):
        driver = MariaDBDriver(version="10.0")
        assert driver._dump_binary == "mysqldump"
        assert driver._client_binary == "mysql"
        assert driver._admin_binary == "mysqladmin"

    def test_version_5_5_uses_old_binaries(self):
        driver = MariaDBDriver(version="5.5")
        assert driver._dump_binary == "mysqldump"
        assert driver._client_binary == "mysql"
        assert driver._admin_binary == "mysqladmin"


class TestEdgeCases:
    """Test edge cases for version parsing."""

    def test_empty_version_defaults_to_new(self):
        driver = MariaDBDriver(version="")
        assert driver._dump_binary == "mariadb-dump"

    def test_no_version_defaults_to_new(self):
        driver = MariaDBDriver()
        assert driver._dump_binary == "mariadb-dump"

    def test_invalid_version_defaults_to_new(self):
        driver = MariaDBDriver(version="latest")
        assert driver._dump_binary == "mariadb-dump"

    def test_single_digit_version(self):
        driver = MariaDBDriver(version="11")
        assert driver._use_new_binaries is True

    def test_version_exactly_10(self):
        driver = MariaDBDriver(version="10")
        assert driver._use_new_binaries is False  # 10.0 < 10.5


class TestDumpCommands:
    """Test that dump commands use the correct binary."""

    def test_dump_schema_new_binary(self, mock_runner):
        driver = MariaDBDriver(version="10.11")
        driver.dump_schema(
            mock_runner,
            "mariadb",
            "10.11",
            "host",
            3306,
            "admin",
            "secret",
            "testdb",
            None,
            300,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "mariadb-dump" in command

    def test_dump_schema_old_binary(self, mock_runner):
        driver = MariaDBDriver(version="10.3")
        driver.dump_schema(
            mock_runner,
            "mariadb",
            "10.3",
            "host",
            3306,
            "admin",
            "secret",
            "testdb",
            None,
            300,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "mysqldump" in command

    def test_check_reachable_new_binary(self, mock_runner):
        driver = MariaDBDriver(version="10.11")
        driver.check_reachable(mock_runner, "mariadb", "10.11", "host", 3306, 30)
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "mariadb-admin" in command

    def test_check_reachable_old_binary(self, mock_runner):
        driver = MariaDBDriver(version="10.3")
        driver.check_reachable(mock_runner, "mariadb", "10.3", "host", 3306, 30)
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "mysqladmin" in command

    def test_check_connection_new_binary(self, mock_runner):
        driver = MariaDBDriver(version="10.11")
        driver.check_connection(
            mock_runner,
            "mariadb",
            "10.11",
            "host",
            3306,
            "admin",
            "secret",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        # The first element of the command should be the client binary "mariadb"
        assert command[0] == "mariadb"


class TestMariaDBProperties:
    """Test MariaDB driver properties."""

    def test_engine_name(self):
        driver = MariaDBDriver()
        assert driver.engine == "mariadb"

    def test_image_name(self):
        driver = MariaDBDriver()
        assert driver.image == "mariadb"

    def test_inherits_mysql_system_databases(self):
        driver = MariaDBDriver()
        assert "mysql" in driver.SYSTEM_DATABASES
        assert "information_schema" in driver.SYSTEM_DATABASES

    def test_list_schemas_returns_none(self, mock_runner):
        """MariaDB inherits MySQL's list_schemas which returns None."""
        driver = MariaDBDriver(version="10.11")
        result = driver.list_schemas(
            mock_runner,
            "mariadb",
            "10.11",
            "host",
            3306,
            "admin",
            "secret",
            "testdb",
            30,
        )
        assert result is None
