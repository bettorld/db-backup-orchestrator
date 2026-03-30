"""Driver factory."""

from db_backup_orchestrator.drivers.base import BaseDriver


def get_driver(name: str, version: str = "") -> BaseDriver:
    """Return the appropriate driver instance for the given engine name.

    Args:
        name: Driver name (postgres, mysql, mariadb).
        version: Engine version string, passed to the driver constructor
                 when relevant (e.g. MariaDB uses it to select binaries).

    Raises:
        ValueError: If the driver name is not recognized.
    """
    if name == "postgres":
        from db_backup_orchestrator.drivers.postgres import PostgresDriver

        return PostgresDriver()
    elif name == "mysql":
        from db_backup_orchestrator.drivers.mysql import MySQLDriver

        return MySQLDriver()
    elif name == "mariadb":
        from db_backup_orchestrator.drivers.mariadb import MariaDBDriver

        return MariaDBDriver(version=version)
    else:
        raise ValueError(f"Unknown driver: {name}")
