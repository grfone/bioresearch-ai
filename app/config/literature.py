"""
literature.py

Runtime configuration for the multi-source literature search
infrastructure (OpenAlex, Europe PMC, bioRxiv).

PubMed is configured separately in :mod:`app.config.pubmed`
because it predates the multi-source work.

Settings
--------
- ``openalex_mailto`` — polite-pool mailto for OpenAlex
  (recommended, speeds up + raises rate limits).
- ``openalex_enabled`` / ``europe_pmc_enabled`` /
  ``biorxiv_enabled`` — per-source toggles. When a source is
  disabled, the orchestrator's
  ``MultiSourceSearcher`` simply omits it.
- ``biorxiv_server`` — ``"biorxiv"`` (default) or
  ``"medrxiv"`` (clinical preprints).
- All sources use the shared ``timeout`` from the PubMed
  settings for consistency.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LiteratureSettings(BaseSettings):
    """Runtime configuration for multi-source literature search."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # OpenAlex: 200M+ works, free tier 100k credits/day.
    # The polite pool (faster + higher limit) is unlocked
    # by setting ``mailto=`` in the query string. We reuse
    # the PubMed email by default since NCBI requires one.
    openalex_mailto: str = Field(
        default="",
        alias="OPENALEX_MAILTO",
    )
    openalex_enabled: bool = Field(
        default=True,
        alias="OPENALEX_ENABLED",
    )

    # Europe PMC: indexes PubMed + preprints + many
    # publishers. No key. ~5-10 req/s soft limit.
    europe_pmc_enabled: bool = Field(
        default=True,
        alias="EUROPE_PMC_ENABLED",
    )

    # bioRxiv / medRxiv: chronological preprint dump. No
    # keyword search — useful only with date-window filters.
    biorxiv_enabled: bool = Field(
        default=False,  # opt-in: overlaps with PubMed / OpenAlex
        alias="BIORXIV_ENABLED",
    )
    biorxiv_server: str = Field(
        default="biorxiv",
        alias="BIORXIV_SERVER",
    )

    # HTML meta-tag fallback for missing abstracts. When
    # enabled, the IdentifierResolver attempts to recover
    # abstracts from the publisher's landing page (Nature,
    # PLOS, Frontiers, etc.) after CrossRef and OpenAlex
    # both fail. Adds ~1-2s latency per DOI lookup so it's
    # off by default; researchers who care about maximal
    # abstract coverage can enable it.
    abstract_enricher_enabled: bool = Field(
        default=False,
        alias="ABSTRACT_ENRICHER_ENABLED",
    )


literature_settings = LiteratureSettings()
