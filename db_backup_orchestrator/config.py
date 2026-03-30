"""Configuration dataclasses and driver registry."""

from dataclasses import dataclass, field
from typing import Optional


DRIVER_REGISTRY: dict[str, dict[str, object]] = {
    "postgres": {"image": "postgres", "default_port": 5432},
    "mysql": {"image": "mysql", "default_port": 3306},
    "mariadb": {"image": "mariadb", "default_port": 3306},
}


@dataclass
class BackupConfig:
    """All configuration for a backup operation."""

    # Shared / required
    host: str
    port: int
    user: str
    password: str
    driver: str
    version: str
    connection: str

    # Mode — exactly one is True / non-empty
    full: bool = False
    databases: Optional[list[str]] = None
    tables: Optional[list[str]] = None
    globals_only: bool = False

    # Optional flags
    databases_only: bool = False
    schemas: Optional[list[str]] = None

    # Optional arguments
    output_dir: str = "/backups"
    no_compress: bool = False
    encrypt: bool = False
    encrypt_key: Optional[str] = None
    parallel: int = 1
    timeout: int = 1800
    retries: int = 3
    retry_delay: int = 300
    retain_successful: int = 30
    retain_partial: int = 5
    connect_timeout: int = 30

    # Verification
    verify: bool = False

    # Misc
    dry_run: bool = False
    verbose: bool = False
    docker_network: str = "host"
    docker_platform: str = "linux/amd64"
    result_file: Optional[str] = None

    @property
    def image(self) -> str:
        return str(DRIVER_REGISTRY[self.driver]["image"])

    @property
    def mode(self) -> str:
        if self.full:
            return "full"
        if self.databases_only:
            return "databases-only"
        if self.databases:
            return "databases"
        if self.tables:
            return "tables"
        if self.globals_only:
            return "globals-only"
        return "unknown"

    @property
    def globals_included(self) -> bool:
        return self.full or self.globals_only

    @property
    def compress(self) -> bool:
        return not self.no_compress


@dataclass
class RestoreConfig:
    """All configuration for a restore operation."""

    # Required
    from_path: str
    host: str
    user: str
    password: str
    port: int = 0  # filled from manifest or default

    # Mode — exactly one is True / non-empty
    full: bool = False
    databases: Optional[list[str]] = None
    tables: Optional[list[str]] = None
    globals_only: bool = False

    # Optional flags
    databases_only: bool = False
    drop_databases: bool = False
    drop_users: bool = False
    version_override: Optional[str] = None

    # Optional arguments
    timeout: int = 7200
    connect_timeout: int = 30
    encrypt_key: Optional[str] = None

    # Verification
    verify: bool = False

    # Misc
    dry_run: bool = False
    verbose: bool = False
    docker_network: str = "host"
    docker_platform: str = "linux/amd64"

    # Populated from manifest during validation
    driver: Optional[str] = None
    version: Optional[str] = None
    connection: Optional[str] = None
    manifest_data: Optional[dict] = field(default=None, repr=False)

    @property
    def mode(self) -> str:
        if self.full:
            return "full"
        if self.databases_only:
            return "databases-only"
        if self.databases:
            return "databases"
        if self.tables:
            return "tables"
        if self.globals_only:
            return "globals-only"
        return "unknown"

    @property
    def globals_included(self) -> bool:
        return self.full or self.globals_only

    @property
    def effective_version(self) -> str:
        """The DB version to use: override takes precedence over manifest."""
        if self.version_override:
            return self.version_override
        return self.version or ""

    @property
    def image(self) -> str:
        if self.driver and self.driver in DRIVER_REGISTRY:
            return str(DRIVER_REGISTRY[self.driver]["image"])
        return ""
