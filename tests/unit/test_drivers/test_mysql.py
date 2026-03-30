"""Tests for MySQLDriver command generation (mock docker_runner)."""

from unittest.mock import MagicMock

import pytest

from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.mysql import MySQLDriver


@pytest.fixture
def driver():
    return MySQLDriver()


@pytest.fixture
def mock_runner():
    mock = MagicMock(spec=DockerRunner)
    mock.run.return_value = DockerResult(
        stdout="app_store\nanalytics\n",
        stderr="",
        returncode=0,
    )
    return mock


class TestListDatabases:
    """Test list_databases builds correct mysql query."""

    def test_list_databases_command(self, driver, mock_runner):
        driver.list_databases(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            30,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "mysql" in command
        assert "-h" in command
        assert "db.example.com" in command
        assert "-P" in command
        assert "3306" in command
        assert "-u" in command
        assert "admin" in command
        assert "-N" in command  # no column headers
        assert "-e" in command

        # Query should reference information_schema.schemata
        e_idx = command.index("-e")
        query = command[e_idx + 1]
        assert "information_schema.schemata" in query

        # MYSQL_PWD passed as env
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["MYSQL_PWD"] == "secret"

    def test_list_databases_excludes_system(self, driver, mock_runner):
        driver.list_databases(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        e_idx = command.index("-e")
        query = command[e_idx + 1]
        assert "mysql" in query  # excluded
        assert "information_schema" in query
        assert "performance_schema" in query
        assert "sys" in query

    def test_list_databases_returns_parsed_output(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(
            stdout="app_store\nanalytics\n",
            stderr="",
            returncode=0,
        )
        databases = driver.list_databases(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            30,
        )
        assert databases == ["app_store", "analytics"]


class TestDumpGlobals:
    """Test dump_globals extracts users + grants."""

    def test_dump_globals_uses_bash_script(self, driver, mock_runner):
        driver.dump_globals(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        # Should use bash -c with a script
        assert command[0] == "bash"
        assert command[1] == "-c"

        script = command[2]
        # Script should query mysql.user and SHOW GRANTS
        assert "mysql.user" in script
        assert "SHOW GRANTS" in script
        assert "CREATE USER" in script

    def test_dump_globals_excludes_system_users(self, driver, mock_runner):
        driver.dump_globals(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        script = command[2]

        # Should exclude system users
        for sys_user in ["mysql.sys", "mysql.session", "root"]:
            assert sys_user in script


class TestDumpSchema:
    """Test dump_schema uses mysqldump."""

    def test_dump_schema_command(self, driver, mock_runner):
        driver.dump_schema(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            "app_store",
            None,
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "mysqldump" in command
        assert "--single-transaction" in command
        assert "--routines" in command
        assert "--triggers" in command
        assert "--events" in command
        assert "--databases" in command
        assert "app_store" in command


class TestDumpTable:
    """Test dump_table uses mysqldump with database and table."""

    def test_dump_table_command(self, driver, mock_runner):
        driver.dump_table(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            "app_store",
            None,
            "products",
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "mysqldump" in command
        assert "--single-transaction" in command
        assert "app_store" in command
        assert "products" in command


class TestListSchemas:
    """Test list_schemas returns None for MySQL."""

    def test_list_schemas_returns_none(self, driver, mock_runner):
        result = driver.list_schemas(
            mock_runner,
            "mysql",
            "8.0",
            "db.example.com",
            3306,
            "admin",
            "secret",
            "app_store",
            30,
        )
        assert result is None
        # Should not call docker_runner at all
        mock_runner.run.assert_not_called()


class TestMySQLPWDEnv:
    """Test MYSQL_PWD is passed as env var."""

    def test_check_connection_uses_mysql_pwd(self, driver, mock_runner):
        driver.check_connection(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert "MYSQL_PWD" in env
        assert env["MYSQL_PWD"] == "secret"

    def test_dump_schema_uses_mysql_pwd(self, driver, mock_runner):
        driver.dump_schema(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            "testdb",
            None,
            300,
        )
        call_kwargs = mock_runner.run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["MYSQL_PWD"] == "secret"


class TestReachability:
    """Test check_reachable uses mysqladmin ping."""

    def test_check_reachable_command(self, driver, mock_runner):
        driver.check_reachable(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "mysqladmin" in command
        assert "ping" in command
        assert "--connect-timeout=30" in command


class TestRestoreCommands:
    """Test restore command generation."""

    def test_restore_globals(self, driver, mock_runner):
        driver.restore_globals(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            b"CREATE USER testuser;",
            300,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "mysql" in command
        stdin = call_kwargs.kwargs.get("stdin_data") or call_kwargs[1].get("stdin_data")
        assert stdin == b"CREATE USER testuser;"

    def test_restore_schema(self, driver, mock_runner):
        driver.restore_schema(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            "app_store",
            b"CREATE TABLE products;",
            300,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "mysql" in command
        # MySQL restore_schema does NOT specify database — dump SQL has CREATE DATABASE + USE
        assert "app_store" not in command
        assert call_kwargs.kwargs.get("stdin_data") == b"CREATE TABLE products;"


class TestDatabaseManagement:
    """Test create/drop/check database commands."""

    def test_create_database(self, driver, mock_runner):
        driver.create_database(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            "new_db",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        e_idx = command.index("-e")
        assert "CREATE DATABASE" in command[e_idx + 1]
        assert "new_db" in command[e_idx + 1]

    def test_drop_database(self, driver, mock_runner):
        driver.drop_database(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            "old_db",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        e_idx = command.index("-e")
        assert "DROP DATABASE" in command[e_idx + 1]

    def test_check_database_exists_true(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)
        assert (
            driver.check_database_exists(
                mock_runner,
                "mysql",
                "8.0",
                "host",
                3306,
                "admin",
                "secret",
                "app_store",
                30,
            )
            is True
        )

    def test_check_database_exists_false(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(stdout="", stderr="", returncode=0)
        assert (
            driver.check_database_exists(
                mock_runner,
                "mysql",
                "8.0",
                "host",
                3306,
                "admin",
                "secret",
                "nonexistent",
                30,
            )
            is False
        )

    def test_drop_database_contains_db_name(self, driver, mock_runner):
        driver.drop_database(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            "testdb",
            30,
        )
        cmd = mock_runner.run.call_args[1]["command"]
        assert "DROP DATABASE" in " ".join(cmd)
        assert "testdb" in " ".join(cmd)

    def test_list_users(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(
            stdout="app_user@%\nreporting@localhost\n", stderr="", returncode=0
        )
        users = driver.list_users(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            30,
        )
        assert users == ["app_user@%", "reporting@localhost"]

    def test_list_users_failure(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(
            stdout="", stderr="error", returncode=1
        )
        users = driver.list_users(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            30,
        )
        assert users == []

    def test_drop_user(self, driver, mock_runner):
        driver.drop_user(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            "app_user@%",
            30,
        )
        cmd = mock_runner.run.call_args[1]["command"]
        assert "DROP USER" in " ".join(cmd)
        assert "app_user" in " ".join(cmd)

    def test_check_database_exists_escapes_quotes(self, driver, mock_runner):
        """SQL injection: single quotes in DB name are escaped."""
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)
        driver.check_database_exists(
            mock_runner,
            "mysql",
            "8.0",
            "host",
            3306,
            "admin",
            "secret",
            "db'injection",
            30,
        )
        cmd = mock_runner.run.call_args[1]["command"]
        sql = cmd[-1]
        assert "db''injection" in sql
        assert "db'injection" not in sql
