"""Wrapper around Docker CLI commands executed via subprocess."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from db_backup_orchestrator.utils.logging import get_logger


@dataclass
class DockerResult:
    """Result from a docker run invocation."""

    stdout: str
    stderr: str
    returncode: int


class DockerRunner:
    """Execute docker commands in ephemeral containers."""

    def __init__(self, network: str = "host", platform: str = "linux/amd64") -> None:
        self.network = network
        self.platform = platform
        self.logger = get_logger()

    def check_docker(self) -> bool:
        """Verify the Docker daemon is reachable (5s timeout).

        Returns True if docker is available, False otherwise.
        """
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def ensure_image(self, image: str, version: str) -> bool:
        """Ensure a Docker image is available locally; pull if missing.

        Phase 1: docker image inspect (local cache check).
        Phase 2: docker pull (60s timeout) if not cached.

        Returns True if image is ready, False on failure.
        """
        tag = f"{image}:{version}"

        # Phase 1 — local cache
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", tag],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                self.logger.info("Image %s found in local cache — skipping pull.", tag)
                return True
        except subprocess.TimeoutExpired:
            pass

        # Phase 2 — pull
        self.logger.info("Image %s not found locally — pulling...", tag)
        try:
            result = subprocess.run(
                ["docker", "pull", "--platform", self.platform, tag],
                capture_output=True,
                timeout=60,
            )
            if result.returncode == 0:
                self.logger.info("Image %s pulled successfully.", tag)
                return True
            else:
                stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
                self.logger.error(
                    "Fatal: Docker image '%s' not found. Verify --driver and --version are correct. %s",
                    tag,
                    stderr_text,
                )
                return False
        except subprocess.TimeoutExpired:
            self.logger.error(
                "Fatal: Docker image pull for '%s' timed out after 60s.", tag
            )
            return False

    def run(
        self,
        image: str,
        version: str,
        command: list[str],
        env: Optional[dict[str, str]] = None,
        timeout: int = 300,
        network: Optional[str] = None,
        volumes: Optional[list[str]] = None,
        stdin_data: Optional[bytes] = None,
    ) -> DockerResult:
        """Run a command in an ephemeral Docker container.

        Args:
            image: Docker image name.
            version: Image tag/version.
            command: The command and arguments to run inside the container.
            env: Environment variables to pass (-e KEY=VALUE).
            timeout: Timeout in seconds for the operation.
            network: Docker network override. Defaults to self.network.
            volumes: Volume mount strings (-v host:container).
            stdin_data: Bytes to pipe to the container's stdin.

        Returns:
            DockerResult with stdout, stderr, and return code.
        """
        tag = f"{image}:{version}"
        net = network or self.network

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--platform",
            self.platform,
            "--network",
            net,
        ]

        if volumes:
            for v in volumes:
                docker_cmd.extend(["-v", v])

        if env:
            for key, value in env.items():
                docker_cmd.extend(["-e", f"{key}={value}"])

        if stdin_data is not None:
            docker_cmd.append("-i")

        docker_cmd.append(tag)
        docker_cmd.extend(command)

        self.logger.debug("Docker run: %s (timeout=%ds)", " ".join(docker_cmd), timeout)

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=timeout,
                input=stdin_data,
            )
            return DockerResult(
                stdout=result.stdout.decode("utf-8", errors="replace"),
                stderr=result.stderr.decode("utf-8", errors="replace"),
                returncode=result.returncode,
            )
        except subprocess.TimeoutExpired:
            self.logger.warning("Docker run timed out after %ds", timeout)
            return DockerResult(
                stdout="",
                stderr=f"Operation timed out after {timeout}s",
                returncode=-1,
            )

    def run_to_file(
        self,
        image: str,
        version: str,
        command: list[str],
        output_path: Path,
        env: Optional[dict[str, str]] = None,
        timeout: int = 1800,
        network: Optional[str] = None,
    ) -> DockerResult:
        """Run a command and stream stdout directly to a file.

        Unlike run(), this never buffers stdout in memory — the Docker
        process writes directly to the file via a pipe. This allows
        dumping databases of any size without OOM.

        Args:
            image: Docker image name.
            version: Image tag/version.
            command: The command and arguments to run inside the container.
            output_path: File path to write stdout to.
            env: Environment variables to pass (-e KEY=VALUE).
            timeout: Timeout in seconds for the operation.
            network: Docker network override. Defaults to self.network.

        Returns:
            DockerResult with empty stdout, stderr, and return code.
        """
        tag = f"{image}:{version}"
        net = network or self.network

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--platform",
            self.platform,
            "--network",
            net,
        ]

        if env:
            for key, value in env.items():
                docker_cmd.extend(["-e", f"{key}={value}"])

        docker_cmd.append(tag)
        docker_cmd.extend(command)

        self.logger.debug(
            "Docker run (streaming to %s): %s (timeout=%ds)",
            output_path,
            " ".join(docker_cmd),
            timeout,
        )

        try:
            with open(output_path, "wb") as stdout_file:
                result = subprocess.run(
                    docker_cmd,
                    stdout=stdout_file,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                )
            return DockerResult(
                stdout="",
                stderr=result.stderr.decode("utf-8", errors="replace"),
                returncode=result.returncode,
            )
        except subprocess.TimeoutExpired:
            self.logger.warning("Docker run timed out after %ds", timeout)
            # Clean up partial file
            output_path.unlink(missing_ok=True)
            return DockerResult(
                stdout="",
                stderr=f"Operation timed out after {timeout}s",
                returncode=-1,
            )
