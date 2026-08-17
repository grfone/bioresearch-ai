"""
search_filters.py

Search-filter dataclass shared across all literature providers.

Why a dataclass (not a method-per-provider signature)?
----------------------------------------------------
- The orchestrator can build the filters once, then dispatch
  to multiple providers with the same intent.
- The Advanced Search modal in the UI serialises to/from
  this shape directly.
- New filters (e.g. ``language``, ``is_oa_only``) are added
  in one place and propagate to every client.

Filter semantics
----------------
- ``query``: free-text research question. Provider-specific
  query DSL is hidden by the orchestrator; clients translate.
- ``since_year`` / ``until_year``: optional inclusive year
  bounds. ``None`` means "no bound".
- ``max_results``: 1-200 depending on provider (OpenAlex
  caps at 200; Europe PMC at 25 in our safe mode).
- ``sort_by``: ``RELEVANCE`` (default) or ``NEWEST_FIRST``.
  Europe PMC's ``sort`` param is broken, so the
  EuropePMCClient implements "newest first" by combining
  with ``since_year`` and reverse-sorting client-side.
- ``include_abstracts``: hint to providers that omit
  abstracts by default (e.g. Europe PMC ``lite``). We
  always want them when they're available, so this is a
  default ``True`` and clients can opt out for speed.
- ``open_access_only``: optional boolean — only return
  papers with a public PDF. Europe PMC has ``HAS_ABSTRACT:Y``
  + OA flag; OpenAlex has ``open_access.is_oa``.
- ``document_types``: optional list of
  ``SearchDocumentType`` values (journal-article, preprint,
  review, dataset, etc.). Provider-specific mapping.

Provider support matrix
------------------------
| filter           | PubMed | OpenAlex | Europe PMC | bioRxiv |
|------------------|--------|----------|------------|---------|
| query            |   ✓    |    ✓     |     ✓      |    ✗    |
| since_year       |   ✓    |    ✓     |   (in q)   |  (date) |
| max_results      |   ✓    |    ✓     |     ✓      |    ✓    |
| sort relevance   |   ✓    |    ✓     |   (default)|    ✗    |
| sort newest      |   ✓    |    ✓     |  (workaround)|  (cursor) |
| include_abstracts|  ✓     |    ✓     |   resultType |   ✓    |
| open_access_only |   ✓    |    ✓     |     ✓      |    ✓    |
| document_types   |   ✓    |    ✓     |     ✓      |    ✗    |

bioRxiv's blank cells are because it has no keyword search
or relevance sort — it's a chronological dump. The
``MultiSourceSearcher`` skips bioRxiv when ``query`` is set
without a date window, OR fans out via Europe PMC
``SRC:BIORXIV`` and then enriches with bioRxiv details.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SortBy(str, Enum):
    """How to order results.

    RELEVANCE — provider default (most providers rank by
    full-text relevance). NEWEST_FIRST — most recent
    publication first.
    """

    RELEVANCE = "relevance"
    NEWEST_FIRST = "newest_first"


class SearchDocumentType(str, Enum):
    """Coarse document type filter.

    Not every provider supports every value — clients
    silently drop unsupported values from their query.
    """

    JOURNAL_ARTICLE = "journal-article"
    REVIEW = "review"
    PREPRINT = "preprint"
    DATASET = "dataset"
    CONFERENCE_PAPER = "conference-paper"
    BOOK_CHAPTER = "book-chapter"
    THESIS = "thesis"


@dataclass(frozen=True)
class SearchFilters:
    """Filter bundle passed to each provider's search call.

    ``query`` is required; everything else is optional with
    sensible defaults. Frozen so a single filter bundle can
    be passed to multiple providers without mutation.
    """

    query: str
    since_year: int | None = None
    until_year: int | None = None
    max_results: int = 20
    sort_by: SortBy = SortBy.RELEVANCE
    include_abstracts: bool = True
    open_access_only: bool = False
    document_types: tuple[SearchDocumentType, ...] = ()

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("SearchFilters.query cannot be empty.")
        if self.max_results < 1:
            raise ValueError("max_results must be >= 1.")
        if self.max_results > 200:
            # OpenAlex caps at 200; we cap globally to one
            # number so providers don't disagree on the
            # contract.
            raise ValueError("max_results must be <= 200.")
        if (
            self.since_year is not None
            and self.until_year is not None
            and self.since_year > self.until_year
        ):
            raise ValueError(
                f"since_year ({self.since_year}) cannot be "
                f"after until_year ({self.until_year})."
            )

    def with_defaults(self, **overrides: object) -> "SearchFilters":
        """Return a copy with the given fields overridden.

        Useful for tests: ``SearchFilters("foo").with_defaults(
        max_results=5)``.
        """
        import dataclasses

        return dataclasses.replace(self, **overrides)


DEFAULT_MAX_RESULTS = 20
"""The orchestrator's default page size — matches PubMed's
default for compatibility with the existing UI.
"""