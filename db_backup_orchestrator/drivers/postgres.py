"""PostgreSQL driver implementation."""

import hashlib
from pathlib import Path
from typing import Optional

from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.base import BaseDriver
from db_backup_orchestrator.utils.logging import get_logger


class PostgresDriver(BaseDriver):
    """PostgreSQL-specific dump and restore commands.

    Uses pg_dumpall, pg_dump, psql, pg_isready via Docker containers.
    Credentials are passed via the PGPASSWORD environment variable.
    """

    @property
    def engine(self) -> str:
        return "postgres"

    @property
    def image(self) -> str:
        return "postgres"

    @property
    def password_env_var(self) -> str:
        return "PGPASSWORD"

    def _env(self, user: str, password: str) -> dict[str, str]:
        return {"PGPASSWORD": password}

    # ── B5: Reachability ──────────────────────────────────────────────

    def check_reachable(
        self,
        docker_runner: DockerRunner,
        image: str,
        version: str,
        host: str,
        port: int,
        timeout: int,
    ) -> DockerResult:
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                "pg_isready",
                "-h",
                host,
                "-p",
                str(port),
                "-t",
                str(timeout),
            ],
            timeout=timeout + 5,
        )

    # ── B6: Authentication / health ───────────────────────────────────

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
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
                "-c",
                "SELECT 1;",
                "-o",
                "/dev/null",
            ],
            env=self._env(user, password),
            timeout=timeout + 5,
        )

    # ── Discovery ─────────────────────────────────────────────────────

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
        logger = get_logger()
        query = (
            "SELECT datname FROM pg_database "
            "WHERE datistemplate = false AND datname NOT IN ('postgres');"
        )
        result = docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
                "-t",
                "-A",
                "-c",
                query,
            ],
            env=self._env(user, password),
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error("Failed to list databases: %s", result.stderr.strip())
            return []
        databases = [
            line.strip() for line in result.stdout.strip().splitlines() if line.strip()
        ]
        logger.debug("Discovered databases: %s", databases)
        return databases

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
        logger = get_logger()
        query = (
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast');"
        )
        result = docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                database,
                "-t",
                "-A",
                "-c",
                query,
            ],
            env=self._env(user, password),
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error(
                "Failed to list schemas for %s: %s", database, result.stderr.strip()
            )
            return []
        schemas = [
            line.strip() for line in result.stdout.strip().splitlines() if line.strip()
        ]
        logger.debug("Schemas in %s: %s", database, schemas)
        return schemas

    # ── Dump ──────────────────────────────────────────────────────────

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
        cmd = [
            "pg_dumpall",
            "-h", host, "-p", str(port), "-U", user,
            "--globals-only", "--no-tablespaces",
        ]
        if output_path:
            return docker_runner.run_to_file(
                image=image, version=version, command=cmd,
                output_path=output_path, env=self._env(user, password),
                timeout=timeout,
            )
        return docker_runner.run(
            image=image, version=version, command=cmd,
            env=self._env(user, password), timeout=timeout,
        )

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
        cmd = [
            "pg_dump",
            "-h", host, "-p", str(port), "-U", user,
            "-d", database, "--no-tablespaces",
        ]
        if schema:
            cmd.extend(["-n", schema])
        if output_path:
            return docker_runner.run_to_file(
                image=image, version=version, command=cmd,
                output_path=output_path, env=self._env(user, password),
                timeout=timeout,
            )
        return docker_runner.run(
            image=image, version=version, command=cmd,
            env=self._env(user, password), timeout=timeout,
        )

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
        table_ref = f"{schema}.{table}" if schema else table
        cmd = [
            "pg_dump",
            "-h", host, "-p", str(port), "-U", user,
            "-d", database, "-t", table_ref,
        ]
        if output_path:
            return docker_runner.run_to_file(
                image=image, version=version, command=cmd,
                output_path=output_path, env=self._env(user, password),
                timeout=timeout,
            )
        return docker_runner.run(
            image=image, version=version, command=cmd,
            env=self._env(user, password), timeout=timeout,
        )

    # ── Restore ───────────────────────────────────────────────────────

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
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
            ],
            env=self._env(user, password),
            timeout=timeout,
            stdin_data=sql_data,
        )

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
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                database,
            ],
            env=self._env(user, password),
            timeout=timeout,
            stdin_data=sql_data,
        )

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
        # Table restore is same as schema restore — psql reads the SQL
        return self.restore_schema(
            docker_runner,
            image,
            version,
            host,
            port,
            user,
            password,
            database,
            sql_data,
            timeout,
        )

    # ── Database management ───────────────────────────────────────────

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
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
                "-c",
                f'CREATE DATABASE "{database}";',
            ],
            env=self._env(user, password),
            timeout=timeout,
        )

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
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
                "-c",
                f'DROP DATABASE IF EXISTS "{database}";',
            ],
            env=self._env(user, password),
            timeout=timeout,
        )

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
        result = docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
                "-t",
                "-A",
                "-c",
                "SELECT 1 FROM pg_database WHERE datname = '"
                + database.replace("'", "''")
                + "';",
            ],
            env=self._env(user, password),
            timeout=timeout,
        )
        return result.returncode == 0 and result.stdout.strip() == "1"

    # ── User management ────────────────────────────────────────────────

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
        """List non-system roles (excluding pg_* and postgres)."""
        logger = get_logger()
        query = (
            "SELECT rolname FROM pg_roles "
            "WHERE rolname NOT LIKE 'pg_%' AND rolname != 'postgres';"
        )
        result = docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
                "-t",
                "-A",
                "-c",
                query,
            ],
            env=self._env(user, password),
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error("Failed to list users: %s", result.stderr.strip())
            return []
        users = [
            line.strip() for line in result.stdout.strip().splitlines() if line.strip()
        ]
        logger.debug("Non-system roles: %s", users)
        return users

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
        """Drop a single role."""
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                "psql",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                "postgres",
                "-c",
                f'DROP ROLE IF EXISTS "{user_to_drop}";',
            ],
            env=self._env(user, password),
            timeout=timeout,
        )

    # ── Verification fingerprint ─────────────────────────────────────

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
        """Run verification queries against PostgreSQL and return sha256 hashes."""
        logger = get_logger()
        queries = {
            "databases": (
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datname NOT IN ('postgres') "
                "ORDER BY datname"
            ),
            "tables": (
                "SELECT table_schema, table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY table_schema, table_name, column_name"
            ),
            "indexes": (
                "SELECT schemaname, tablename, indexname, indexdef "
                "FROM pg_indexes "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schemaname, tablename, indexname"
            ),
            "foreign_keys": (
                "SELECT conname, conrelid::regclass AS table, confrelid::regclass AS ref_table "
                "FROM pg_constraint WHERE contype = 'f' "
                "ORDER BY conname"
            ),
            "views": (
                "SELECT schemaname, viewname "
                "FROM pg_views "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schemaname, viewname"
            ),
            "routines": (
                "SELECT routine_schema, routine_name, routine_type "
                "FROM information_schema.routines "
                "WHERE routine_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY routine_schema, routine_name"
            ),
            "triggers": (
                "SELECT trigger_schema, trigger_name, event_object_table "
                "FROM information_schema.triggers "
                "WHERE trigger_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY trigger_schema, trigger_name"
            ),
            "users": (
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole "
                "FROM pg_roles WHERE rolname NOT LIKE 'pg_%' "
                "ORDER BY rolname"
            ),
            "collations": (
                "SELECT table_schema, table_name, table_collation "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY table_schema, table_name"
            ),
        }

        fingerprint: dict[str, str] = {}
        for check_name, query in queries.items():
            result = docker_runner.run(
                image=image,
                version=version,
                command=[
                    "psql",
                    "-h",
                    host,
                    "-p",
                    str(port),
                    "-U",
                    user,
                    "-d",
                    "postgres",
                    "-t",
                    "-A",
                    "-c",
                    query,
                ],
                env=self._env(user, password),
                timeout=timeout,
            )
            output = result.stdout if result.returncode == 0 else ""
            hash_val = hashlib.sha256(output.encode()).hexdigest()
            fingerprint[check_name] = f"sha256:{hash_val}"
            logger.debug("Verification check '%s': sha256:%s", check_name, hash_val)

        # Compute combined hash from all individual hashes sorted by key
        combined_input = "".join(fingerprint[k] for k in sorted(fingerprint.keys()))
        combined_hash = hashlib.sha256(combined_input.encode()).hexdigest()
        fingerprint["combined"] = f"sha256:{combined_hash}"

        return fingerprint
