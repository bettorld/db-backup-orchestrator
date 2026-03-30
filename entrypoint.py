#!/usr/bin/env python3
"""DB Backup Orchestrator — CLI entry point.

Parses the subcommand (backup or restore) and routes to the
appropriate orchestrator.

Exit codes:
    0 — success
    1 — fatal error (bad args, infra failure, etc.)
    2 — partial failure (some operations failed after retries)
"""

import signal
import sys
import traceback

from db_backup_orchestrator.cli import parse_args
from db_backup_orchestrator.config import BackupConfig, RestoreConfig
from db_backup_orchestrator.docker_runner import DockerRunner
from db_backup_orchestrator.drivers import get_driver
from db_backup_orchestrator.orchestrator import BackupOrchestrator
from db_backup_orchestrator.restorer import Restorer
from db_backup_orchestrator.utils.logging import setup_logger


def main() -> int:
    """Parse args, route to backup or restore, return exit code."""
    try:
        config = parse_args()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    # Set up logging after parsing (so we know --verbose)
    logger = setup_logger(verbose=config.verbose)

    try:
        if isinstance(config, BackupConfig):
            return _run_backup(config)
        elif isinstance(config, RestoreConfig):
            return _run_restore(config)
        else:
            logger.error("Fatal: Unknown config type.")
            return 1
    except SystemExit as exc:
        # Validation failures call sys.exit(1) — catch and return the code
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        logger.error("Fatal: Unhandled exception: %s", exc)
        if config.verbose:
            traceback.print_exc(file=sys.stderr)
        return 1


def _run_backup(config: BackupConfig) -> int:
    """Instantiate driver and docker runner, then run the backup orchestrator."""
    docker_runner = DockerRunner(network=config.docker_network, platform=config.docker_platform)

    driver = get_driver(config.driver, version=config.version)

    orchestrator = BackupOrchestrator()
    return orchestrator.run(config, driver, docker_runner)


def _run_restore(config: RestoreConfig) -> int:
    """Instantiate docker runner and run the restorer."""
    docker_runner = DockerRunner(network=config.docker_network, platform=config.docker_platform)

    restorer = Restorer()
    return restorer.run(config, docker_runner)


def _handle_signal(sig: int, _frame: object) -> None:
    """Handle termination signals gracefully."""
    sys.exit(128 + sig)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    sys.exit(main())
