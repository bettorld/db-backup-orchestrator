"""MySQL driver implementation."""

import hashlib
import shlex
from pathlib import Path
from typing import Optional

from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult
from db_backup_orchestrator.drivers.base import BaseDriver
from db_backup_orchestrator.utils.logging import get_logger


class MySQLDriver(BaseDriver):
    """MySQL-specific dump and restore commands.

    Uses mysqldump, mysql, mysqladmin via Docker containers.
    Credentials are passed via the MYSQL_PWD environment variable.
    """

    @property
    def engine(self) -> str:
        return "mysql"

    @property
    def image(self) -> str:
        return "mysql"

    @property
    def password_env_var(self) -> str:
        return "MYSQL_PWD"

    def _env(self, password: str) -> dict[str, str]:
        return {"MYSQL_PWD": password}

    @property
    def _dump_binary(self) -> str:
        """Name of the dump binary. Overridden by MariaDB driver."""
        return "mysqldump"

    @property
    def _client_binary(self) -> str:
        """Name of the client binary. Overridden by MariaDB driver."""
        return "mysql"

    @property
    def _admin_binary(self) -> str:
        """Name of the admin binary. Overridden by MariaDB driver."""
        return "mysqladmin"

    # ── System databases to exclude ───────────────────────────────────

    SYSTEM_DATABASES = frozenset(
        {
            "mysql",
            "information_schema",
            "performance_schema",
            "sys",
        }
    )

    SYSTEM_USERS = frozenset(
        {
            "mysql.sys",
            "mysql.session",
            "mysql.infoschema",
            "root",
            "debian-sys-maint",
        }
    )

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
                self._admin_binary,
                "ping",
                "-h",
                host,
                "-P",
                str(port),
                f"--connect-timeout={timeout}",
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
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
                "-e",
                "SELECT 1;",
            ],
            env=self._env(password),
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
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');"
        )
        result = docker_runner.run(
            image=image,
            version=version,
            command=[
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
                "-N",
                "-e",
                query,
            ],
            env=self._env(password),
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
        """MySQL: database = schema, so this returns None (not applicable)."""
        return None

    # ── Dump ──────────────────────────────────────────────────────────

    def _create_user_concat_sql(self) -> str:
        """SQL CONCAT expression to generate CREATE USER with password hash.

        MySQL 8.x: CREATE USER ... IDENTIFIED WITH 'plugin' AS 0xHEX;
        Override in MariaDB for different syntax.
        """
        return (
            "CONCAT("
            "'CREATE USER IF NOT EXISTS \\'', user, '\\'@\\'', host, '\\'',"
            "CASE WHEN authentication_string != '' AND plugin != '' "
            "THEN CONCAT(' IDENTIFIED WITH \\'', plugin, '\\' AS 0x', HEX(authentication_string)) "
            "ELSE '' END,"
            "';'"
            ")"
        )

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
        """Dump users and grants.

        Two-step process: extract CREATE USER statements, then SHOW GRANTS.
        Combined into a single shell command piped through bash.
        """
        excluded = ", ".join(f"'{u}'" for u in self.SYSTEM_USERS)
        client = shlex.quote(self._client_binary)
        q_host = shlex.quote(host)
        q_port = shlex.quote(str(port))
        q_user = shlex.quote(user)
        script = (
            f"# Get list of users to dump\n"
            f"USERS=$({client} -h {q_host} -P {q_port} -u {q_user} -N -B -e "
            f"\"SELECT DISTINCT CONCAT(user, '@', host) "
            f'FROM mysql.user WHERE user NOT IN ({excluded});" 2>/dev/null)\n'
            f"\n"
            f'if [ -z "$USERS" ]; then\n'
            f'    echo "-- No users to dump"\n'
            f"    exit 0\n"
            f"fi\n"
            f"\n"
            f"# For each user: CREATE USER with password + SHOW GRANTS\n"
            f'echo "$USERS" | while read userhost; do\n'
            f'    u=$(echo "$userhost" | cut -d@ -f1)\n'
            f'    h=$(echo "$userhost" | cut -d@ -f2)\n'
            f"\n"
            f"    # CREATE USER with auth plugin and password hash\n"
            f"    # Generated server-side via SQL to avoid shell escaping issues\n"
            f"    {client} -h {q_host} -P {q_port} -u {q_user} -N -B -e "
            f'"SELECT {self._create_user_concat_sql()} FROM mysql.user '
            f"WHERE user='${{u}}' AND host='${{h}}';\" 2>/dev/null\n"
            f"\n"
            f"    # GRANT statements\n"
            f"    {client} -h {q_host} -P {q_port} -u {q_user} -N -B -e "
            f"\"SHOW GRANTS FOR '${{u}}'@'${{h}}';\" 2>/dev/null | sed 's/$/;/'\n"
            f"    echo ''\n"
            f"done"
        )
        cmd = ["bash", "-c", script]
        if output_path:
            return docker_runner.run_to_file(
                image=image, version=version, command=cmd,
                output_path=output_path, env=self._env(password),
                timeout=timeout,
            )
        return docker_runner.run(
            image=image, version=version, command=cmd,
            env=self._env(password), timeout=timeout,
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
        """Dump a full database. The schema parameter is ignored for MySQL."""
        cmd = [
            self._dump_binary,
            "-h", host, "-P", str(port), "-u", user,
            "--single-transaction", "--routines", "--triggers", "--events",
            "--databases", database,
        ]
        if output_path:
            return docker_runner.run_to_file(
                image=image, version=version, command=cmd,
                output_path=output_path, env=self._env(password),
                timeout=timeout,
            )
        return docker_runner.run(
            image=image, version=version, command=cmd,
            env=self._env(password), timeout=timeout,
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
        """Dump a specific table. The schema parameter is ignored for MySQL."""
        cmd = [
            self._dump_binary,
            "-h", host, "-P", str(port), "-u", user,
            "--single-transaction", database, table,
        ]
        if output_path:
            return docker_runner.run_to_file(
                image=image, version=version, command=cmd,
                output_path=output_path, env=self._env(password),
                timeout=timeout,
            )
        return docker_runner.run(
            image=image, version=version, command=cmd,
            env=self._env(password), timeout=timeout,
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
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
            ],
            env=self._env(password),
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
        """Restore a database from SQL data.

        Connects WITHOUT specifying a database because mysqldump --databases
        output includes CREATE DATABASE and USE statements in the SQL itself.
        Specifying the database here would fail if it doesn't exist yet.
        """
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
            ],
            env=self._env(password),
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
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
                "-e",
                f"CREATE DATABASE IF NOT EXISTS `{database}`;",
            ],
            env=self._env(password),
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
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
                "-e",
                f"DROP DATABASE IF EXISTS `{database}`;",
            ],
            env=self._env(password),
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
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
                "-N",
                "-e",
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = '"
                + database.replace("'", "''").replace("\\", "\\\\")
                + "';",
            ],
            env=self._env(password),
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
        """List non-system users as 'user@host' strings."""
        logger = get_logger()
        excluded = ", ".join(f"'{u}'" for u in self.SYSTEM_USERS)
        query = (
            f"SELECT CONCAT(user, '@', host) FROM mysql.user "
            f"WHERE user NOT IN ({excluded});"
        )
        result = docker_runner.run(
            image=image,
            version=version,
            command=[
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
                "-N",
                "-B",
                "-e",
                query,
            ],
            env=self._env(password),
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error("Failed to list users: %s", result.stderr.strip())
            return []
        users = [
            line.strip() for line in result.stdout.strip().splitlines() if line.strip()
        ]
        logger.debug("Non-system users: %s", users)
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
        """Drop a single user. user_to_drop is 'username@hostname'."""
        parts = user_to_drop.split("@", 1)
        uname = parts[0]
        uhost = parts[1] if len(parts) > 1 else "%"
        return docker_runner.run(
            image=image,
            version=version,
            command=[
                self._client_binary,
                "-h",
                host,
                "-P",
                str(port),
                "-u",
                user,
                "-e",
                f"DROP USER IF EXISTS '{uname}'@'{uhost}';",
            ],
            env=self._env(password),
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
        """Run verification queries against MySQL and return sha256 hashes."""
        logger = get_logger()
        sys_dbs = "('mysql', 'information_schema', 'performance_schema', 'sys')"
        queries = {
            "databases": (
                "SELECT schema_name FROM information_schema.schemata "
                f"WHERE schema_name NOT IN {sys_dbs} ORDER BY schema_name"
            ),
            "tables": (
                "SELECT table_schema, table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                f"WHERE table_schema NOT IN {sys_dbs} "
                "ORDER BY table_schema, table_name, column_name"
            ),
            "indexes": (
                "SELECT table_schema, table_name, index_name, column_name, non_unique "
                "FROM information_schema.statistics "
                f"WHERE table_schema NOT IN {sys_dbs} "
                "ORDER BY table_schema, table_name, index_name, seq_in_index"
            ),
            "foreign_keys": (
                "SELECT constraint_schema, table_name, constraint_name, "
                "referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE referenced_table_name IS NOT NULL "
                f"AND constraint_schema NOT IN {sys_dbs} "
                "ORDER BY constraint_schema, table_name, constraint_name"
            ),
            "views": (
                "SELECT table_schema, table_name "
                "FROM information_schema.views "
                f"WHERE table_schema NOT IN {sys_dbs} "
                "ORDER BY table_schema, table_name"
            ),
            "routines": (
                "SELECT routine_schema, routine_name, routine_type "
                "FROM information_schema.routines "
                f"WHERE routine_schema NOT IN {sys_dbs} "
                "ORDER BY routine_schema, routine_name"
            ),
            "triggers": (
                "SELECT trigger_schema, trigger_name, event_object_table, "
                "action_timing, event_manipulation "
                "FROM information_schema.triggers "
                f"WHERE trigger_schema NOT IN {sys_dbs} "
                "ORDER BY trigger_schema, trigger_name"
            ),
            "events": (
                "SELECT event_schema, event_name, status "
                "FROM information_schema.events "
                f"WHERE event_schema NOT IN {sys_dbs} "
                "ORDER BY event_schema, event_name"
            ),
            "users": (
                "SELECT user, host FROM mysql.user "
                "WHERE user NOT IN ('mysql.sys', 'mysql.session', 'mysql.infoschema', "
                "'root', 'debian-sys-maint') ORDER BY user, host"
            ),
            "collations": (
                "SELECT table_schema, table_name, table_collation "
                "FROM information_schema.tables "
                f"WHERE table_schema NOT IN {sys_dbs} "
                "ORDER BY table_schema, table_name"
            ),
        }

        fingerprint: dict[str, str] = {}
        for check_name, query in queries.items():
            result = docker_runner.run(
                image=image,
                version=version,
                command=[
                    self._client_binary,
                    "-h",
                    host,
                    "-P",
                    str(port),
                    "-u",
                    user,
                    "-N",
                    "-B",
                    "-e",
                    query,
                ],
                env=self._env(password),
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
