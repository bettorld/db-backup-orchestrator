"""Abstract base driver defining the interface for all DB drivers."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult


class BaseDriver(ABC):
    """Abstract base class for database drivers.

    Each driver knows how to construct Docker commands for its specific
    database engine. The DockerRunner actually executes them.
    """

    @property
    @abstractmethod
    def engine(self) -> str:
        """Engine name (postgres, mysql, mariadb)."""
        ...

    @property
    @abstractmethod
    def image(self) -> str:
        """Docker image name."""
        ...

    @property
    @abstractmethod
    def password_env_var(self) -> str:
        """Environment variable name for the password inside the container."""
        ...

    @abstractmethod
    def check_reachable(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        timeout: int,
    ) -> DockerResult:
        """B5: Check host+port reachability at the network level."""
        ...

    @abstractmethod
    def check_connection(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        timeout: int,
    ) -> DockerResult:
        """B6: Authenticate and run SELECT 1."""
        ...

    @abstractmethod
    def list_databases(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        timeout: int,
    ) -> list[str]:
        """Auto-discover all user databases on the server."""
        ...

    @abstractmethod
    def list_schemas(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        timeout: int,
    ) -> Optional[list[str]]:
        """List schemas within a database. Returns None if not applicable."""
        ...

    @abstractmethod
    def dump_globals(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        timeout: int,
        output_path: Optional[Path] = None,
    ) -> DockerResult:
        """Dump roles, users, permissions (globals).

        If output_path is provided, stdout is streamed directly to the file.
        """
        ...

    @abstractmethod
    def dump_schema(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        schema: Optional[str],
        timeout: int,
        output_path: Optional[Path] = None,
    ) -> DockerResult:
        """Dump a schema (PG) or full database (MySQL/MariaDB).

        If output_path is provided, stdout is streamed directly to the file.
        """
        ...

    @abstractmethod
    def dump_table(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        schema: Optional[str],
        table: str,
        timeout: int,
        output_path: Optional[Path] = None,
    ) -> DockerResult:
        """Dump a specific table.

        If output_path is provided, stdout is streamed directly to the file.
        """
        ...

    @abstractmethod
    def restore_globals(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        sql_data: bytes,
        timeout: int,
    ) -> DockerResult:
        """Restore globals (roles/users/permissions) from SQL data."""
        ...

    @abstractmethod
    def restore_schema(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        sql_data: bytes,
        timeout: int,
    ) -> DockerResult:
        """Restore a schema/database from SQL data."""
        ...

    @abstractmethod
    def restore_table(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        sql_data: bytes,
        timeout: int,
    ) -> DockerResult:
        """Restore a specific table from SQL data."""
        ...

    @abstractmethod
    def create_database(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        timeout: int,
    ) -> DockerResult:
        """Create a database if it does not exist."""
        ...

    @abstractmethod
    def drop_database(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        timeout: int,
    ) -> DockerResult:
        """Drop a database."""
        ...

    @abstractmethod
    def check_database_exists(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        timeout: int,
    ) -> bool:
        """Check whether a database exists on the target server."""
        ...

    @abstractmethod
    def list_users(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        timeout: int,
    ) -> list[str]:
        """List non-system users as 'user@host' strings (MySQL/MariaDB) or role names (Postgres)."""
        ...

    @abstractmethod
    def drop_user(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        user_to_drop: str,
        timeout: int,
    ) -> DockerResult:
        """Drop a single user."""
        ...

    @abstractmethod
    def verify_fingerprint(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        user: str,
        password: str,
        databases: list[str],
        timeout: int,
    ) -> dict[str, str]:
        """Run verification queries and return dict of check_name -> sha256 hash."""
        ...
