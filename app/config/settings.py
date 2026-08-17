"""
settings.py

Global application configuration.

Purpose
-------
This module exposes the global configuration object used throughout
BioResearch AI.

Rather than reading environment variables directly, application code
should import the singleton ``settings`` instance defined here. This
ensures that every configuration value is loaded exactly once and
provides a stable, domain-oriented API for the rest of the system.

The configuration itself is divided into independent domains
(e.g. LLM, PubMed, database, logging). This module simply aggregates
those domains into a single object.

Example
-------
    from app.config.settings import settings

    settings.llm.provider
    'openai'

    settings.pubmed.email
    'my_email@example.com'

    settings.database.url
    'sqlite:///bioresearch.db'

Architecture
------------
                    settings
                        │
        ┌───────────────┼───────────────┐
        │               │               │
      llm           pubmed         database
        │               │               │
        └───────────────┼───────────────┘
                        │
                     logging

Notes
-----
This module intentionally contains no business logic.

Its sole responsibility is to expose the application's runtime
configuration through a single importable object.

New configuration domains should be added here without affecting the
existing API.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.config.database import database_settings
from app.config.literature import literature_settings
from app.config.llm import llm_settings
from app.config.logging import logging_settings
from app.config.pubmed import pubmed_settings


class Settings:
    """
    Aggregates every runtime configuration domain.

    The Settings object provides a single entry point for accessing
    configuration across the application while keeping each domain
    logically independent.

    Attributes
    ----------
    llm
        Large Language Model configuration.

    pubmed
        The PubMed integration configuration.

    database
        The database configuration.

    logging
        The logging configuration.
    """

    def __init__(self) -> None:
        """
        Initialize the application configuration.

        Each configuration domain is instantiated once using its
        corresponding Pydantic Settings class. The resulting objects are
        reused throughout the application's lifetime.
        """

        self.llm = llm_settings
        self.pubmed = pubmed_settings
        self.database = database_settings
        self.logging = logging_settings
        self.literature = literature_settings


# ---------------------------------------------------------------------
# Global configuration singleton
# ---------------------------------------------------------------------
#
# This singleton should be imported wherever configuration is required.
# Application code should never instantiate Settings directly.
#
# Example
# -------
#
# from app.config.settings import settings
#
# provider = settings.llm.provider
# email = settings.pubmed.email
#
settings = Settings()