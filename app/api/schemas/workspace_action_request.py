"""
workspace_action_request.py

API request schema for invoking an FSM action on a Research Workspace.

The legacy shape (just ``query``) is preserved for the basic
search endpoint. The full multi-source shape is exposed as
``AdvancedSearchFilters`` — the Advanced Search modal in the
UI fills this in and posts it.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Document-type filter values — must match
# :class:`SearchDocumentType` enum strings in
# ``app/domain/value_objects/search_filters.py``.
DocTypeLiteral = Literal[
    "journal-article",
    "review",
    "preprint",
    "dataset",
    "conference-paper",
    "book-chapter",
    "thesis",
]

# Sort-by filter values — must match ``SortBy`` enum strings.
SortByLiteral = Literal["relevance", "newest_first"]

# Source filter values — must match ``SearchSource`` enum
# strings. Empty list / None means "use the orchestrator's
# default source set".
SourceLiteral = Literal[
    "pubmed", "openalex", "europe_pmc", "biorxiv"
]


class AdvancedSearchFilters(BaseModel):
    """Full filter bundle for the Advanced Search modal.

    Mirrors :class:`SearchFilters` in the domain layer but
    uses Pydantic-friendly types (strings instead of enums,
    no tuple for document_types — use a list of literals
    instead).

    Every field is optional. The orchestrator's defaults
    (``max_results=20``, ``sort_by="relevance"``,
    ``include_abstracts=True``, etc.) apply when a field is
    omitted.

    Notes
    -----
    The frontend builds this object from the Advanced Search
    modal's form values. The backend converts it to a domain
    :class:`SearchFilters` instance before invoking the
    orchestrator.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    since_year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description=(
            "Inclusive lower bound on publication year. "
            "``null`` means no lower bound."
        ),
        examples=[2020],
    )
    until_year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description=(
            "Inclusive upper bound on publication year. "
            "``null`` means no upper bound."
        ),
        examples=[2024],
    )
    max_results: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "Maximum number of results to return. The global "
            "ceiling is 200 — the orchestrator caps OpenAlex "
            "queries at that and the other providers return "
            "less per page."
        ),
        examples=[20],
    )
    sort_by: SortByLiteral = Field(
        default="relevance",
        description=(
            "Result ordering. ``newest_first`` sorts by "
            "publication date descending."
        ),
        examples=["relevance", "newest_first"],
    )
    include_abstracts: bool = Field(
        default=True,
        description=(
            "Hint to providers that strip abstracts by "
            "default (Europe PMC ``lite`` resultType). "
            "Always ``True`` unless the user opts out for "
            "speed."
        ),
    )
    open_access_only: bool = Field(
        default=False,
        description=(
            "Only return papers with a public PDF. Maps to "
            "OpenAlex ``open_access.is_oa:true`` and Europe "
            "PMC ``OPEN_ACCESS:Y``."
        ),
    )
    document_types: list[DocTypeLiteral] = Field(
        default_factory=list,
        description=(
            "Optional document-type filter. Each entry is a "
            "string from the ``DocTypeLiteral`` enum. Providers "
            "silently drop types they don't support."
        ),
        examples=[["journal-article", "review"]],
    )
    sources: list[SourceLiteral] = Field(
        default_factory=list,
        description=(
            "Optional restricted source set. Empty list / "
            "omitted means 'use every registered source' "
            "(PubMed + OpenAlex + Europe PMC by default). The "
            "user picks specific sources from the Advanced "
            "Search modal's source picker."
        ),
        examples=[["pubmed", "openalex"]],
    )


class WorkspaceActionRequest(BaseModel):
    """Request body for ``POST /workspaces/{id}/actions/{action}``.

    Two shapes:

    - **Legacy / simple search**: just ``query``. Used by the
      "Search PubMed" button — keeps backward compatibility
      with the original endpoint contract.
    - **Advanced search**: full ``AdvancedSearchFilters``
      block. The endpoint accepts either shape; if both are
      provided, the ``filters`` block wins (with a warning
      logged at the route layer).

    Attributes
    ----------
    query : str | None
        Optional override of the question. Only used by the
        ``search`` action. If ``filters.query`` is also given
        (via ``AdvancedSearchFilters``), ``filters.query``
        wins.
    filters : AdvancedSearchFilters | None
        Full multi-source filter bundle. When supplied, the
        orchestrator's ``search_with_filters`` entry point
        is invoked.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    query: str | None = Field(
        default=None,
        description=(
            "Optional override of the question. Used by the "
            "search action to re-run with a different query."
        ),
        examples=[
            "GLP-1 receptor agonists and Alzheimer's",
        ],
    )
    filters: AdvancedSearchFilters | None = Field(
        default=None,
        description=(
            "Advanced Search filter bundle. When supplied, "
            "the search action uses "
            "``WorkspaceOrchestrator.search_with_filters`` "
            "instead of the legacy ``search`` method."
        ),
    )
