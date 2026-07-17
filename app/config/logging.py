"""
logging.py

Logging configuration for BioResearch AI.

Purpose
-------
This module defines the runtime configuration for the application's
logging system.

Rather than exposing environment variable names throughout the codebase,
this module provides a clean, domain-oriented interface that can be
consumed by the rest of the application.

The configuration is automatically loaded from environment variables
using Pydantic Settings.

Example
-------
>>> from app.config.settings import settings
>>>
>>> settings.logging.level
'INFO'
>>>
>>> settings.logging.to_file
False

Environment Variables
---------------------
LOG_LEVEL
LOG_FORMAT
LOG_TO_FILE
LOG_FILE

Future Extensions
-----------------
As BioResearch AI evolves, this configuration may include:

- JSON logging
- Structured logging
- Log rotation
- Multiple handlers
- Remote logging
- OpenTelemetry integration
- Distributed tracing

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    """
    Runtime configuration for the application's logging system.

    Attributes
    ----------
    level
        Minimum logging level.

    format
        Format string applied to every log record.

    to_file
        Whether log messages should also be written to a file.

    file
        Destination log file when file logging is enabled.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    level: str = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )

    format: str = Field(
        default="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        alias="LOG_FORMAT",
    )

    to_file: bool = Field(
        default=False,
        alias="LOG_TO_FILE",
    )

    file: str = Field(
        default="logs/bioresearch-ai.log",
        alias="LOG_FILE",
    )


logging_settings = LoggingSettings()