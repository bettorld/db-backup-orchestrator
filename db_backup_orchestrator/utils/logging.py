"""Structured logging to stderr with credential redaction."""

import logging
import re
import sys
from typing import Optional


_REDACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(PGPASSWORD=)[^\s]+"),
    re.compile(r"(MYSQL_PWD=)[^\s]+"),
    re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(-p\s*)[^\s]+"),
    re.compile(r"(BACKUP_ENCRYPT_KEY=)[^\s]+"),
    re.compile(r"(BACKUP_PASSWORD=)[^\s]+"),
    re.compile(r"(DB_PASSWORD=)[^\s]+"),
    re.compile(r"(-pass\s+(?:env:|pass:))[^\s]+"),
]


def redact(message: str) -> str:
    """Remove credentials from a log message."""
    result = message
    for pattern in _REDACT_PATTERNS:
        result = pattern.sub(r"\1***REDACTED***", result)
    return result


class _RedactingFormatter(logging.Formatter):
    """Formatter that scrubs credentials from all output."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact(original)


_logger: Optional[logging.Logger] = None


def setup_logger(verbose: bool = False) -> logging.Logger:
    """Configure and return the application logger.

    All output goes to stderr so stdout is clean for piping.
    Format: [TIMESTAMP] [LEVEL] message
    """
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("db_backup_orchestrator")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)

    formatter = _RedactingFormatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Return the existing logger or create a default one."""
    global _logger
    if _logger is None:
        return setup_logger(verbose=False)
    return _logger
