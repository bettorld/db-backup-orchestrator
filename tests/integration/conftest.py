"""
Parametrized integration test fixtures.

Spawns database containers directly via Docker (not docker-compose) so each
version can be tested independently. Tests are parametrized over DB versions.

Usage:
    pytest tests/integration/ -v                    # all versions
    pytest tests/integration/ -k "postgres"         # postgres only
    pytest tests/integration/ -k "mysql_5_7"        # mysql 5.7 only
"""

import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SEED_DIR = FIXTURES_DIR / "seed"


# Detect Docker Desktop (macOS/Windows) vs native Linux Docker.
# Docker Desktop doesn't support --network host, so containers must use
# host.docker.internal and the bridge network.
# Inside a container on Docker Desktop, platform.system() returns "Linux"
# but host.docker.internal still resolves — we use that as the detection.
def _is_docker_desktop() -> bool:
    if platform.system() in ("Darwin", "Windows"):
        return True
    import socket

    try:
        socket.getaddrinfo("host.docker.internal", None)
        return True
    except socket.gaierror:
        return False


IS_DOCKER_DESKTOP = _is_docker_desktop()
DOCKER_HOST_FROM_CONTAINER = (
    "host.docker.internal" if IS_DOCKER_DESKTOP else "127.0.0.1"
)
DOCKER_NETWORK = "bridge" if IS_DOCKER_DESKTOP else "host"

# ─── Version matrix ───────────────────────────────────────────────────────────
# Add or remove versions here — tests automatically run for each.

POSTGRES_VERSIONS = ["14", "15", "16", "17"]
MYSQL_VERSIONS = ["8.0", "8.4"]
MARIADB_VERSIONS = ["10.6", "10.11", "11.4"]


@dataclass
class DBInstance:
    """Running database container instance."""

    driver: str
    version: str
    host: str
    port: int
    user: str
    password: str
    container_name: str
    seed_driver: str  # which seed dir to use (postgres, mysql, mariadb)


# ─── Container management ─────────────────────────────────────────────────────


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _image_name(driver: str, version: str) -> str:
    """Map driver + version to Docker image."""
    if driver == "postgres":
        return f"postgres:{version}"
    elif driver == "mysql":
        return f"mysql:{version}"
    elif driver == "mariadb":
        return f"mariadb:{version}"
    raise ValueError(f"Unknown driver: {driver}")


def _container_port(driver: str) -> int:
    """Internal container port for the driver."""
    return 5432 if driver == "postgres" else 3306


def _start_container(driver: str, version: str, seed_driver: str) -> DBInstance:
    """Start a database container with seed data, return DBInstance."""
    port = _find_free_port()
    container_port = _container_port(driver)
    container_name = f"dbo-test-{driver}-{version.replace('.', '')}-{port}"
    image = _image_name(driver, version)
    user = "testuser"
    password = "testpass"

    # Build docker run command (no volume mount — use docker cp for seed files
    # so it works both locally and inside a test container)
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "-p",
        f"127.0.0.1:{port}:{container_port}",
    ]

    # Engine-specific env vars
    if driver == "postgres":
        cmd.extend(
            [
                "-e",
                f"POSTGRES_USER={user}",
                "-e",
                f"POSTGRES_PASSWORD={password}",
            ]
        )
    else:
        # MySQL and MariaDB
        cmd.extend(
            [
                "-e",
                f"MYSQL_ROOT_PASSWORD={password}",
                "-e",
                f"MYSQL_USER={user}",
                "-e",
                f"MYSQL_PASSWORD={password}",
            ]
        )

    cmd.append(image)

    # Pull image if not present (silent)
    subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    subprocess.run(
        ["docker", "pull", image],
        capture_output=True,
        timeout=120,
    )

    # Start container
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        # Skip instead of crash — image may not be available for this platform
        pytest.skip(f"Could not start {container_name}: {stderr.strip()}")

    return DBInstance(
        driver=driver,
        version=version,
        host=DOCKER_HOST_FROM_CONTAINER,
        port=port,
        user=user,
        password=password,
        container_name=container_name,
        seed_driver=seed_driver,
    )


def _wait_for_ready(instance: DBInstance, timeout: int = 90) -> bool:
    """Wait until the database is accepting connections.

    Uses 'docker exec' on the running container to check readiness,
    avoiding --network host which doesn't work on macOS Docker Desktop.
    """
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            if instance.driver == "postgres":
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        instance.container_name,
                        "pg_isready",
                        "-U",
                        instance.user,
                    ],
                    capture_output=True,
                    timeout=10,
                )
            else:
                # MariaDB 10.5+ ships mariadb-admin; older versions use mysqladmin
                admin_binary = "mysqladmin"
                if instance.driver == "mariadb":
                    try:
                        parts = instance.version.split(".")
                        major = int(parts[0])
                        minor = int(parts[1]) if len(parts) > 1 else 0
                        if major > 10 or (major == 10 and minor >= 5):
                            admin_binary = "mariadb-admin"
                    except (ValueError, IndexError):
                        admin_binary = "mariadb-admin"

                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        instance.container_name,
                        admin_binary,
                        "ping",
                        "-u",
                        instance.user,
                        f"-p{instance.password}",
                    ],
                    capture_output=True,
                    timeout=10,
                )

            if result.returncode == 0:
                # Extra wait for init scripts to complete
                time.sleep(5)
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(2)

    return False


def _seed_database(instance: DBInstance) -> None:
    """Copy seed SQL into container and execute it via docker exec.

    This avoids volume mounts (which break when tests run inside a container)
    by using docker cp + docker exec instead.
    """
    seed_path = SEED_DIR / instance.seed_driver
    if not seed_path.exists():
        return

    # Copy all SQL files into the container
    for sql_file in sorted(seed_path.glob("*.sql")):
        subprocess.run(
            [
                "docker",
                "cp",
                str(sql_file),
                f"{instance.container_name}:/tmp/{sql_file.name}",
            ],
            capture_output=True,
            timeout=10,
        )

    # Execute each SQL file in order
    for sql_file in sorted(seed_path.glob("*.sql")):
        if instance.driver == "postgres":
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-e",
                    f"PGPASSWORD={instance.password}",
                    instance.container_name,
                    "psql",
                    "-U",
                    instance.user,
                    "-f",
                    f"/tmp/{sql_file.name}",
                ],
                capture_output=True,
                timeout=30,
            )
        else:
            # MySQL / MariaDB — use mariadb binary for MariaDB 10.5+, mysql otherwise
            client_bin = "mysql"
            if instance.driver == "mariadb":
                try:
                    parts = instance.version.split(".")
                    major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                    if major > 10 or (major == 10 and minor >= 5):
                        client_bin = "mariadb"
                except (ValueError, IndexError):
                    client_bin = "mariadb"
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    instance.container_name,
                    "sh",
                    "-c",
                    f"{client_bin} -u root -p{instance.password} < /tmp/{sql_file.name}",
                ],
                capture_output=True,
                timeout=30,
            )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            print(
                f"WARN: seed {sql_file.name} failed on {instance.container_name}: {stderr[:200]}"
            )


def _stop_container(container_name: str) -> None:
    """Stop and remove a container."""
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        timeout=30,
    )


# ─── Docker availability check ────────────────────────────────────────────────


def _docker_available() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ─── Parametrized fixtures ─────────────────────────────────────────────────────


def _build_db_params():
    """Build the list of (driver, version, seed_driver) tuples for parametrize."""
    params = []
    for v in POSTGRES_VERSIONS:
        params.append(
            pytest.param(
                ("postgres", v, "postgres"),
                id=f"postgres_{v.replace('.', '_')}",
            )
        )
    for v in MYSQL_VERSIONS:
        params.append(
            pytest.param(
                ("mysql", v, "mysql"),
                id=f"mysql_{v.replace('.', '_')}",
            )
        )
    for v in MARIADB_VERSIONS:
        params.append(
            pytest.param(
                ("mariadb", v, "mariadb"),
                id=f"mariadb_{v.replace('.', '_')}",
            )
        )
    return params


DB_PARAMS = _build_db_params()

# Cache of running containers: (driver, version) -> DBInstance
_running_instances: dict[tuple[str, str], DBInstance] = {}


@pytest.fixture(scope="session", autouse=True)
def check_docker():
    """Skip all integration tests if Docker is not available."""
    if not _docker_available():
        pytest.skip("Docker is not available")


@pytest.fixture(scope="session")
def _cleanup_all_containers():
    """Session-scoped cleanup — stop all containers at the end."""
    yield
    for instance in _running_instances.values():
        _stop_container(instance.container_name)
    _running_instances.clear()


def _is_container_running(container_name: str) -> bool:
    """Check if a container is still running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0 and "true" in result.stdout.decode().lower()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _get_or_start_instance(driver: str, version: str, seed_driver: str) -> DBInstance:
    """Get a running instance, starting one if needed (cached per session)."""
    key = (driver, version)

    # Check if cached instance is still alive
    if key in _running_instances:
        instance = _running_instances[key]
        if not _is_container_running(instance.container_name):
            # Container died — remove from cache and restart
            del _running_instances[key]

    if key not in _running_instances:
        instance = _start_container(driver, version, seed_driver)
        if not _wait_for_ready(instance, timeout=90):
            _stop_container(instance.container_name)
            pytest.skip(f"{driver}:{version} did not become ready in time")
        _seed_database(instance)
        time.sleep(2)
        _running_instances[key] = instance
    return _running_instances[key]


@pytest.fixture(params=DB_PARAMS)
def db_instance(request, _cleanup_all_containers) -> DBInstance:
    """
    Parametrized fixture — yields a DBInstance for each (driver, version) combo.

    Tests using this fixture are automatically run for every version in the matrix.
    """
    driver, version, seed_driver = request.param
    return _get_or_start_instance(driver, version, seed_driver)


# ─── Convenience fixtures for single-driver tests ─────────────────────────────


@pytest.fixture(
    params=[pytest.param(v, id=f"pg_{v.replace('.', '_')}") for v in POSTGRES_VERSIONS]
)
def pg_instance(request, _cleanup_all_containers) -> DBInstance:
    """Parametrized PostgreSQL instance across all configured versions."""
    return _get_or_start_instance("postgres", request.param, "postgres")


@pytest.fixture(
    params=[pytest.param(v, id=f"mysql_{v.replace('.', '_')}") for v in MYSQL_VERSIONS]
)
def mysql_instance(request, _cleanup_all_containers) -> DBInstance:
    """Parametrized MySQL instance across all configured versions."""
    return _get_or_start_instance("mysql", request.param, "mysql")


@pytest.fixture(
    params=[
        pytest.param(v, id=f"mariadb_{v.replace('.', '_')}") for v in MARIADB_VERSIONS
    ]
)
def mariadb_instance(request, _cleanup_all_containers) -> DBInstance:
    """Parametrized MariaDB instance across all configured versions."""
    return _get_or_start_instance("mariadb", request.param, "mariadb")


# ─── Output directory ──────────────────────────────────────────────────────────


@pytest.fixture
def backup_output_dir(tmp_path):
    """Provide a temporary directory for backup output."""
    output_dir = tmp_path / "backups"
    output_dir.mkdir()
    return output_dir
