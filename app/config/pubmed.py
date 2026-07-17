"""
pubmed.py

PubMed configuration.

Purpose
-------
This module defines the runtime configuration required for interacting
with the PubMed (NCBI Entrez) API.

Configuration values are loaded automatically from environment variables
defined in the project's `.env` file.

The rest of the application should access configuration through domain
concepts (e.g. ``email`` or ``api_key``) rather than environment variable
names.

Example
-------
>>> from app.config.settings import settings
>>>
>>> settings.pubmed.email
>>> settings.pubmed.api_key
>>> settings.pubmed.max_results

Environment Variables
---------------------
PUBMED_EMAIL
PUBMED_API_KEY
PUBMED_BASE_URL
PUBMED_TOOL_NAME
PUBMED_TIMEOUT
PUBMED_MAX_RESULTS

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PubMedSettings(BaseSettings):
    """
    Runtime configuration for PubMed integration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    email: str = Field(
        alias="PUBMED_EMAIL",
    )

    api_key: str = Field(
        default="",
        alias="PUBMED_API_KEY",
        repr=False,
    )

    base_url: str = Field(
        default="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        alias="PUBMED_BASE_URL",
    )

    tool_name: str = Field(
        default="BioResearchAI",
        alias="PUBMED_TOOL_NAME",
    )

    timeout: int = Field(
        default=30,
        alias="PUBMED_TIMEOUT",
    )

    max_results: int = Field(
        default=20,
        alias="PUBMED_MAX_RESULTS",
    )


pubmed_settings = PubMedSettings()