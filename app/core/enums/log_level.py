"""
log_level.py

Enumeration of supported logging levels.

Purpose
-------
This module defines the logging levels recognized by the application.

The values mirror Python's built-in logging module while providing
type safety throughout the project.

Author
------
Guillermo Ramajo Fernández
"""

from enum import StrEnum


class LogLevelEnum(StrEnum):
    """
    Supported logging levels.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"