"""Tests for PostgresDriver command generation (mock docker_runner)."""

from unittest.mock import MagicMock

import pytest

from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.postgres import PostgresDriver


@pytest.fixture
def driver():
    return PostgresDriver()


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
    """Test list_databases builds correct psql command."""

    def test_list_databases_command(self, driver, mock_runner):
        driver.list_databases(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            30,
        )

        mock_runner.run.assert_called_once()
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "psql" in command
        assert "-h" in command
        assert "db.example.com" in command
        assert "-p" in command
        assert "5432" in command
        assert "-U" in command
        assert "admin" in command
        assert "-t" in command  # tuples only
        assert "-A" in command  # unaligned
        assert "-c" in command

        # Check env has PGPASSWORD
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["PGPASSWORD"] == "secret"

    def test_list_databases_returns_parsed_output(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(
            stdout="app_store\nanalytics\n",
            stderr="",
            returncode=0,
        )
        databases = driver.list_databases(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            30,
        )
        assert databases == ["app_store", "analytics"]

    def test_list_databases_empty_on_failure(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(
            stdout="",
            stderr="connection refused",
            returncode=1,
        )
        databases = driver.list_databases(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            30,
        )
        assert databases == []


class TestDumpGlobals:
    """Test dump_globals builds correct pg_dumpall command."""

    def test_dump_globals_command(self, driver, mock_runner):
        driver.dump_globals(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "pg_dumpall" in command
        assert "-h" in command
        assert "db.example.com" in command
        assert "-p" in command
        assert "5432" in command
        assert "-U" in command
        assert "admin" in command
        assert "--globals-only" in command
        assert "--no-tablespaces" in command

        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["PGPASSWORD"] == "secret"


class TestDumpSchema:
    """Test dump_schema builds correct pg_dump -n command."""

    def test_dump_schema_with_schema_filter(self, driver, mock_runner):
        driver.dump_schema(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            "app_store",
            "inventory",
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "pg_dump" in command
        assert "-h" in command
        assert "db.example.com" in command
        assert "-d" in command
        assert "app_store" in command
        assert "-n" in command
        assert "inventory" in command
        assert "--no-tablespaces" in command

    def test_dump_schema_without_schema_filter(self, driver, mock_runner):
        driver.dump_schema(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            "app_store",
            None,
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "pg_dump" in command
        assert "-d" in command
        assert "app_store" in command
        assert "-n" not in command  # No schema filter


class TestDumpTable:
    """Test dump_table builds correct pg_dump -t command."""

    def test_dump_table_with_schema(self, driver, mock_runner):
        driver.dump_table(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            "app_store",
            "inventory",
            "products",
            300,
        )

        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")

        assert "pg_dump" in command
        assert "-t" in command
        assert "inventory.products" in command


class TestPGPasswordEnv:
    """Test PGPASSWORD is passed as env var."""

    def test_check_reachable_no_password(self, driver, mock_runner):
        driver.check_reachable(mock_runner, "postgres", "16", "host", 5432, 30)
        call_kwargs = mock_runner.run.call_args
        # check_reachable uses pg_isready which does not need auth
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "pg_isready" in command

    def test_check_connection_uses_pgpassword(self, driver, mock_runner):
        driver.check_connection(
            mock_runner,
            "postgres",
            "16",
            "host",
            5432,
            "admin",
            "secret",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert "PGPASSWORD" in env
        assert env["PGPASSWORD"] == "secret"


class TestListSchemas:
    """Test list_schemas builds correct query."""

    def test_list_schemas_returns_list(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(
            stdout="public\ninventory\ncustomers\n",
            stderr="",
            returncode=0,
        )
        schemas = driver.list_schemas(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            "app_store",
            30,
        )
        assert schemas == ["public", "inventory", "customers"]

    def test_list_schemas_excludes_system(self, driver, mock_runner):
        """The query itself filters system schemas."""
        driver.list_schemas(
            mock_runner,
            "postgres",
            "16",
            "db.example.com",
            5432,
            "admin",
            "secret",
            "app_store",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        # Find the -c argument to check the query
        c_idx = command.index("-c")
        query = command[c_idx + 1]
        assert "pg_catalog" in query
        assert "information_schema" in query


class TestRestoreCommands:
    """Test restore command generation."""

    def test_restore_globals(self, driver, mock_runner):
        driver.restore_globals(
            mock_runner,
            "postgres",
            "16",
            "host",
            5432,
            "admin",
            "secret",
            b"CREATE ROLE testuser;",
            300,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "psql" in command
        assert "-d" in command
        assert "postgres" in command
        stdin = call_kwargs.kwargs.get("stdin_data") or call_kwargs[1].get("stdin_data")
        assert stdin == b"CREATE ROLE testuser;"

    def test_restore_schema(self, driver, mock_runner):
        driver.restore_schema(
            mock_runner,
            "postgres",
            "16",
            "host",
            5432,
            "admin",
            "secret",
            "app_store",
            b"CREATE TABLE products;",
            300,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "psql" in command
        assert "-d" in command
        assert "app_store" in command


class TestDatabaseManagement:
    """Test create/drop/check database commands."""

    def test_create_database(self, driver, mock_runner):
        driver.create_database(
            mock_runner,
            "postgres",
            "16",
            "host",
            5432,
            "admin",
            "secret",
            "new_db",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        assert "psql" in command
        c_idx = command.index("-c")
        assert "CREATE DATABASE" in command[c_idx + 1]
        assert "new_db" in command[c_idx + 1]

    def test_drop_database(self, driver, mock_runner):
        driver.drop_database(
            mock_runner,
            "postgres",
            "16",
            "host",
            5432,
            "admin",
            "secret",
            "old_db",
            30,
        )
        call_kwargs = mock_runner.run.call_args
        command = call_kwargs.kwargs.get("command") or call_kwargs[1].get("command")
        c_idx = command.index("-c")
        assert "DROP DATABASE" in command[c_idx + 1]

    def test_check_database_exists_true(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)
        assert (
            driver.check_database_exists(
                mock_runner,
                "postgres",
                "16",
                "host",
                5432,
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
                "postgres",
                "16",
                "host",
                5432,
                "admin",
                "secret",
                "nonexistent",
                30,
            )
            is False
        )

    def test_drop_database(self, driver, mock_runner):
        driver.drop_database(
            mock_runner, "postgres", "16", "host", 5432, "admin", "secret", "testdb", 30,
        )
        cmd = mock_runner.run.call_args[1]["command"]
        assert "DROP DATABASE" in " ".join(cmd)
        assert "testdb" in " ".join(cmd)

    def test_list_users(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(
            stdout="app_readonly\nreporting\n", stderr="", returncode=0
        )
        users = driver.list_users(
            mock_runner, "postgres", "16", "host", 5432, "admin", "secret", 30,
        )
        assert users == ["app_readonly", "reporting"]

    def test_list_users_empty(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(stdout="", stderr="", returncode=0)
        users = driver.list_users(
            mock_runner, "postgres", "16", "host", 5432, "admin", "secret", 30,
        )
        assert users == []

    def test_list_users_failure(self, driver, mock_runner):
        mock_runner.run.return_value = DockerResult(stdout="", stderr="error", returncode=1)
        users = driver.list_users(
            mock_runner, "postgres", "16", "host", 5432, "admin", "secret", 30,
        )
        assert users == []

    def test_drop_user(self, driver, mock_runner):
        driver.drop_user(
            mock_runner, "postgres", "16", "host", 5432, "admin", "secret", "app_readonly", 30,
        )
        cmd = mock_runner.run.call_args[1]["command"]
        assert "DROP ROLE" in " ".join(cmd)
        assert "app_readonly" in " ".join(cmd)

    def test_check_database_exists_escapes_quotes(self, driver, mock_runner):
        """SQL injection: single quotes in DB name are escaped."""
        mock_runner.run.return_value = DockerResult(stdout="1", stderr="", returncode=0)
        driver.check_database_exists(
            mock_runner, "postgres", "16", "host", 5432, "admin", "secret",
            "db'injection", 30,
        )
        cmd = mock_runner.run.call_args[1]["command"]
        sql = cmd[-1]
        assert "db''injection" in sql
        assert "db'injection" not in sql
