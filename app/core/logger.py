"""
logger.py

Central logging utilities for BioResearch AI.

Purpose
-------
This module provides a consistent logging interface for the entire
application.

Rather than configuring logging independently inside each module,
the application configures the logging system once during startup and
retrieves logger instances through the ``get_logger`` function.

Typical usage
-------------

Application startup::

    from app.core.logger import configure_logging

    configure_logging()

Inside any module::

    from app.core.logger import get_logger

    logger = get_logger(__name__)

    logger.info("Searching PubMed...")

Design
------
This module separates configuration from logger retrieval.

- configure_logging()
    Configures the Python logging subsystem once.

- get_logger()
    Returns a configured logger instance.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import settings


def configure_logging() -> None:
    """
    Configure the application's logging system.

    This function should be called exactly once during application
    startup.

    The configuration supports both console logging and optional file
    logging with automatic log rotation.

    Notes
    -----
    Subsequent calls have no effect if logging has already been
    configured.
    """

    root_logger = logging.getLogger()

    if root_logger.handlers:
        return

    formatter = logging.Formatter(
        settings.logging.format
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger.setLevel(settings.logging.level)
    root_logger.addHandler(console_handler)

    # Quiet noisy third-party loggers. When LOG_LEVEL=DEBUG,
    # the root logger emits everything; these libraries emit
    # per-connection / per-packet DEBUG lines that drown
    # our own application logs. Pinning them to WARNING
    # means their ERROR/CRITICAL still propagate (via the
    # root handler), but their DEBUG/INFO chatter stops.
    #
    # This is a curated list, not a blanket suppression --
    # we pin only the libraries whose DEBUG output is known
    # to be high-volume and low-value during boot.
    for noisy in (
        "httpx",      # HTTP client
        "httpcore",   # lower-level transport -- the worst
                      # offender; emits one log per packet
        "httpcore.http11",
        "httpcore.connection",
        "urllib3",    # requests dependency (if used)
        "asyncio",    # Python stdlib async runtime
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if settings.logging.to_file:

        log_path = Path(settings.logging.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )

        file_handler.setFormatter(formatter)

        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the specified module.

    Parameters
    ----------
    name
        Logger name.

        In most cases this should be::

            __name__

    Returns
    -------
    logging.Logger
        Configured logger instance.

    Examples
    --------
        logger = get_logger(__name__)
        logger.info("Application started.")
    """

    return logging.getLogger(name)