"""MariaDB driver implementation — extends MySQL with binary name overrides."""

from db_backup_orchestrator.drivers.mysql import MySQLDriver


class MariaDBDriver(MySQLDriver):
    """MariaDB-specific driver.

    Extends MySQLDriver with different binary names for MariaDB 10.5+
    (mariadb-dump, mariadb, mariadb-admin) while falling back to the
    MySQL-compatible names for older versions.
    """

    def __init__(self, version: str = "") -> None:
        super().__init__()
        self._version = version

    @property
    def engine(self) -> str:
        return "mariadb"

    @property
    def image(self) -> str:
        return "mariadb"

    @property
    def _use_new_binaries(self) -> bool:
        """MariaDB 10.5+ ships mariadb-dump, mariadb, mariadb-admin."""
        if not self._version:
            return True  # Default to new binaries
        try:
            parts = self._version.split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            return (major > 10) or (major == 10 and minor >= 5)
        except (ValueError, IndexError):
            return True

    @property
    def _dump_binary(self) -> str:
        return "mariadb-dump" if self._use_new_binaries else "mysqldump"

    @property
    def _client_binary(self) -> str:
        return "mariadb" if self._use_new_binaries else "mysql"

    @property
    def _admin_binary(self) -> str:
        return "mariadb-admin" if self._use_new_binaries else "mysqladmin"

    def _create_user_concat_sql(self) -> str:
        """MariaDB: CREATE USER ... IDENTIFIED VIA plugin USING 'hash';

        MariaDB uses IDENTIFIED VIA ... USING (not WITH ... AS).
        MariaDB password hashes are hex strings starting with * (no special chars),
        so simple SQL quoting with doubled single quotes works.
        """
        return (
            "CONCAT("
            "'CREATE USER IF NOT EXISTS ''', user, '''@''', host, '''',"
            "CASE WHEN authentication_string != '' AND plugin != '' "
            "THEN CONCAT(' IDENTIFIED VIA ', plugin, ' USING ''', authentication_string, '''') "
            "ELSE '' END,"
            "';'"
            ")"
        )
