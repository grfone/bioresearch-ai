"""
database.py

Database configuration.

Purpose
-------
This module defines the runtime configuration required for the
application's persistence layer.

Although BioResearch AI does not currently require persistent storage,
introducing a dedicated configuration module establishes a consistent
architecture for future database integrations.

The configuration is automatically loaded from environment variables,
while exposing domain-oriented attribute names to the rest of the
application.

Example
-------
>>> from app.config.settings import settings
>>>
>>> settings.database.url
'sqlite:///bioresearch.db'
>>>
>>> settings.database.echo
False

Environment Variables
---------------------
DATABASE_URL
DATABASE_ECHO
DATABASE_POOL_SIZE
DATABASE_POOL_TIMEOUT

Future Extensions
-----------------
As the project evolves, additional configuration options may be added
without affecting the rest of the application, including:

- PostgreSQL credentials
- SQLite tuning
- Connection pooling
- Vector databases
- Redis
- ChromaDB
- Milvus
- Pinecone

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """
    Runtime configuration for the persistence layer.

    Attributes
    ----------
    url
        Database connection URL.

    echo
        Enable SQL statement logging.

    pool_size
        Maximum number of pooled database connections.

    pool_timeout
        Maximum time (seconds) to wait for an available connection.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    url: str = Field(
        default="sqlite:///bioresearch.db",
        alias="DATABASE_URL",
    )

    echo: bool = Field(
        default=False,
        alias="DATABASE_ECHO",
    )

    pool_size: int = Field(
        default=5,
        alias="DATABASE_POOL_SIZE",
    )

    pool_timeout: int = Field(
        default=30,
        alias="DATABASE_POOL_TIMEOUT",
    )


database_settings = DatabaseSettings()