"""Tests for DockerRunner with mocked subprocess."""

import subprocess
from unittest.mock import patch, MagicMock


from db_backup_orchestrator.docker_runner import DockerRunner, DockerResult


class TestCheckDocker:
    """Test check_docker() success/failure."""

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_check_docker_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        runner = DockerRunner()
        assert runner.check_docker() is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["docker", "info"]

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_check_docker_failure_nonzero(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        runner = DockerRunner()
        assert runner.check_docker() is False

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_check_docker_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker info", timeout=5)
        runner = DockerRunner()
        assert runner.check_docker() is False

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_check_docker_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("docker not found")
        runner = DockerRunner()
        assert runner.check_docker() is False


class TestEnsureImage:
    """Test ensure_image() local cache hit / pull success / pull failure."""

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_ensure_image_local_cache_hit(self, mock_run):
        """Image found locally - no pull needed."""
        mock_run.return_value = MagicMock(returncode=0)
        runner = DockerRunner()
        assert runner.ensure_image("postgres", "16") is True
        # Only docker image inspect should have been called
        mock_run.assert_called_once()
        assert "inspect" in mock_run.call_args[0][0]

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_ensure_image_pull_success(self, mock_run):
        """Image not local, pull succeeds."""
        inspect_result = MagicMock(returncode=1)  # not found locally
        pull_result = MagicMock(returncode=0)
        mock_run.side_effect = [inspect_result, pull_result]

        runner = DockerRunner()
        assert runner.ensure_image("postgres", "16") is True
        assert mock_run.call_count == 2

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_ensure_image_pull_failure(self, mock_run):
        """Image not local, pull fails."""
        inspect_result = MagicMock(returncode=1)
        pull_result = MagicMock(returncode=1, stderr=b"not found")
        mock_run.side_effect = [inspect_result, pull_result]

        runner = DockerRunner()
        assert runner.ensure_image("postgres", "99") is False

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_ensure_image_pull_timeout(self, mock_run):
        """Image not local, pull times out."""
        inspect_result = MagicMock(returncode=1)
        mock_run.side_effect = [
            inspect_result,
            subprocess.TimeoutExpired(cmd="docker pull", timeout=60),
        ]

        runner = DockerRunner()
        assert runner.ensure_image("postgres", "16") is False


class TestDockerRun:
    """Test run() with timeout, exit codes, stdout capture."""

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_run_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"SELECT 1\n",
            stderr=b"",
        )
        runner = DockerRunner(network="host")
        result = runner.run(
            image="postgres",
            version="16",
            command=["psql", "-c", "SELECT 1;"],
            env={"PGPASSWORD": "secret"},
            timeout=30,
        )
        assert isinstance(result, DockerResult)
        assert result.returncode == 0
        assert result.stdout == "SELECT 1\n"
        assert result.stderr == ""

        # Verify docker command structure
        call_args = mock_run.call_args[0][0]
        assert call_args[0:3] == ["docker", "run", "--rm"]
        assert "--network" in call_args
        assert "host" in call_args
        assert "postgres:16" in call_args
        assert "-e" in call_args

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_run_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b"",
            stderr=b"connection refused",
        )
        runner = DockerRunner()
        result = runner.run(
            image="postgres",
            version="16",
            command=["psql", "-c", "SELECT 1;"],
            timeout=30,
        )
        assert result.returncode == 1
        assert "connection refused" in result.stderr

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_run_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker run", timeout=300)
        runner = DockerRunner()
        result = runner.run(
            image="postgres",
            version="16",
            command=["pg_dump", "big_db"],
            timeout=300,
        )
        assert result.returncode == -1
        assert "timed out" in result.stderr

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_run_with_volumes(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"ok",
            stderr=b"",
        )
        runner = DockerRunner()
        runner.run(
            image="postgres",
            version="16",
            command=["pg_dump"],
            volumes=["/backups:/backups"],
            timeout=30,
        )
        call_args = mock_run.call_args[0][0]
        assert "-v" in call_args
        assert "/backups:/backups" in call_args

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_run_with_stdin_data(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"",
            stderr=b"",
        )
        runner = DockerRunner()
        sql_data = b"CREATE TABLE test (id INT);"
        runner.run(
            image="postgres",
            version="16",
            command=["psql"],
            stdin_data=sql_data,
            timeout=30,
        )
        call_args = mock_run.call_args[0][0]
        assert "-i" in call_args
        assert mock_run.call_args[1]["input"] == sql_data

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_run_custom_network(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"",
            stderr=b"",
        )
        runner = DockerRunner(network="my-net")
        runner.run(
            image="postgres",
            version="16",
            command=["psql"],
            timeout=30,
        )
        call_args = mock_run.call_args[0][0]
        idx = call_args.index("--network")
        assert call_args[idx + 1] == "my-net"

    @patch("db_backup_orchestrator.docker_runner.subprocess.run")
    def test_run_network_override(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"",
            stderr=b"",
        )
        runner = DockerRunner(network="host")
        runner.run(
            image="postgres",
            version="16",
            command=["psql"],
            network="bridge",
            timeout=30,
        )
        call_args = mock_run.call_args[0][0]
        idx = call_args.index("--network")
        assert call_args[idx + 1] == "bridge"
