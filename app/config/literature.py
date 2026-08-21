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
    # LLM-based extraction fallback for the AbstractEnricher.
    # When the deterministic regex path returns None or a
    # short string AND the HTML page was reachable (HTTP
    # 200), the resolver falls back to the LLM. The LLM
    # contract is verbatim extraction or NONE -- never
    # invented content. Opt-in because every miss costs
    # 1-3k tokens.
    llm_abstract_extraction_enabled: bool = Field(
        default=False,
        alias="LLM_ABSTRACT_EXTRACTION_ENABLED",
    )

    # ---- Abstract-enricher cache backend ----
    #
    # The cache lives between the deterministic regex path
    # and the LLM fallback path; it stores the resolved
    # abstract (or None for "this DOI has no abstract")
    # keyed by the normalized DOI. Two backends are
    # supported:
    #
    #   - ``memory`` (default): in-process LRU. Each uvicorn
    #     worker has its own cache. Fine for single-worker
    #     deployments and tests.
    #
    #   - ``redis``: shared LRU backed by a Redis instance.
    #     All workers in the cluster see the same cache.
    #     Required for multi-worker deployments where you
    #     don't want the same DOI to be re-fetched (and
    #     re-paid for in LLM API costs) on each worker.
    #     See ``docs/multi-worker-cache-investigation.md``.
    #
    # On a misconfigured Redis (wrong host, unreachable
    # server), the first ``get`` call raises
    # ``redis.exceptions.ConnectionError``. This is the
    # right behavior -- silent fallback to the in-memory
    # impl would re-introduce the fragmentation bug. The
    # error surfaces in the API response and the logs;
    # operators fix the Redis config.
    cache_backend: str = Field(
        default="memory",
        alias="CACHE_BACKEND",
    )
    # Maximum number of entries the cache will hold. ``0``
    # disables the cache entirely (every lookup is a miss
    # and no INCR/INCRBY happens). With the in-memory
    # backend, this caps the OrderedDict size; with the
    # Redis backend, the sorted set is trimmed to this
    # size by evicting the LRU.
    cache_size: int = Field(
        default=256,
        alias="CACHE_SIZE",
    )
    # Maximum PDF upload size in bytes. The original
    # hardcoded 10 MB cap was too small for legitimate
    # research papers (a 21 MB file is a perfectly normal
    # thesis chapter or annotated review). The default is
    # now 200 MB to accommodate large annotated reviews
    # and book chapters; operators can lower it via the
    # ``PDF_UPLOAD_MAX_BYTES`` env var if they need a
    # tighter cap. We don't allow unlimited uploads
    # because a malicious user could trivially OOM the
    # container with a 10 GB file -- the upper bound is
    # hard-coded at 200 MB (``_PDF_UPLOAD_MAX_BYTES_HARD_CAP``
    # in the route) so an unfortunate env var cannot
    # bypass the cap.
    pdf_upload_max_bytes: int = Field(
        default=200 * 1024 * 1024,  # 200 MB
        alias="PDF_UPLOAD_MAX_BYTES",
    )

    # Maximum PDF upload size in bytes. The original
    # hardcoded 10 MB cap was too small for legitimate
    # research papers (a 21 MB file is a perfectly normal
    # thesis chapter or annotated review). The default is
    # now 200 MB to accommodate large annotated reviews
    # and book chapters; operators can lower it via the
    # ``PDF_UPLOAD_MAX_BYTES`` env var if they need a
    # tighter cap. We don't allow unlimited uploads
    # because a malicious user could trivially OOM the
    # container with a 10 GB file -- the upper bound is
    # hard-coded at 200 MB (``_PDF_UPLOAD_MAX_BYTES_HARD_CAP``
    # in the route) so an unfortunate env var cannot
    # bypass the cap.
    pdf_upload_max_bytes: int = Field(
        default=200 * 1024 * 1024,  # 200 MB
        alias="PDF_UPLOAD_MAX_BYTES",
    )
    # Only used when ``CACHE_BACKEND=redis``. Format:
    # ``redis://host:port/db``. If empty when
    # ``CACHE_BACKEND=redis``, ``make_cache`` raises
    # ``ValueError`` at startup.
    redis_url: str = Field(
        default="",
        alias="REDIS_URL",
    )
    # Only used when ``CACHE_BACKEND=redis``. The key
    # namespace. All keys created by the cache are prefixed
    # with this string. If you change this prefix, the
    # existing cache (under the old prefix) becomes
    # invisible -- not deleted, just orphaned. Pick a
    # prefix specific to the bioresearch-ai app so it
    # doesn't collide with other apps sharing the same
    # Redis instance.
    redis_key_prefix: str = Field(
        default="bioresearch:abstract:",
        alias="REDIS_KEY_PREFIX",
    )


literature_settings = LiteratureSettings()
