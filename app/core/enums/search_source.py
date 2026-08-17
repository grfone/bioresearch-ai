"""
search_source.py

Enumeration of literature-search sources wired into the
``LiteratureSearcher`` interface. Each value maps to one
concrete infrastructure client under
``app/infrastructure/literature/``.

The orchestrator can fan out to multiple sources, dedupe
across them, and rank by relevance. The user picks the
sources via the Advanced Search modal in the UI.

Why an enum (not free-form strings)?
-----------------------------------
- Frontend TypeScript mirrors this enum
  (``frontend/src/models/literature.ts``).
- The orchestrator's
  ``MultiSourceSearcher`` uses ``set[SearchSource]`` to
  decide which concrete providers to call.
- New sources are added by extending this enum + writing
  a client + a unit test.

Notes on each source
--------------------
- ``PUBMED``: the original E-Utils-backed searcher (NCBI).
  Free, requires a registered email address.
- ``OPENALEX``: 200M+ works, free tier 100k credits/day.
  Polite pool unlocked by ``mailto=`` query param.
- ``EUROPE_PMC``: indexes PubMed + preprints + many
  publishers. No key. ``sort`` is broken on this endpoint
  — filter by date instead.
- ``BIORXIV``: preprint server, no keyword search
  (chronological dump + DOI lookup). For topic queries
  the orchestrator queries Europe PMC with
  ``SRC:BIORXIV`` filter, then enriches via this provider.
"""

from __future__ import annotations

from enum import Enum


class SearchSource(str, Enum):
    """Concrete literature source identifiers.

    The values are stable strings — they're what gets sent
    over the API (``?source=pubmed``) and persisted in
    workspace state, so don't rename without a migration.
    """

    PUBMED = "pubmed"
    OPENALEX = "openalex"
    EUROPE_PMC = "europe_pmc"
    BIORXIV = "biorxiv"

    @classmethod
    def from_string(cls, raw: str) -> "SearchSource":
        """Parse a source string. Falls back to ``PUBMED``."""
        try:
            return cls(raw.lower().strip())
        except ValueError:
            return cls.PUBMED

    @property
    def display_label(self) -> str:
        """Human-friendly label for the UI."""
        return {
            SearchSource.PUBMED: "PubMed",
            SearchSource.OPENALEX: "OpenAlex",
            SearchSource.EUROPE_PMC: "Europe PMC",
            SearchSource.BIORXIV: "bioRxiv",
        }[self]


def default_sources() -> list[SearchSource]:
    """Default source set when the user hasn't picked one.

    PubMed is the medical canon; OpenAlex is the broadest
    coverage. Europe PMC and bioRxiv are opt-in because
    they overlap heavily with PubMed and OpenAlex.
    """
    return [SearchSource.PUBMED, SearchSource.OPENALEX]
