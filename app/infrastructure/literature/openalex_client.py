"""
openalex_client.py

OpenAlex ``LiteratureSearcher`` implementation.

OpenAlex is the broadest open scholarly database (~200M works).
API: https://api.openalex.org/works — see the research report
at ``/home/grf/workspace/literature_apis_research.md`` for the
live-verified endpoint shape and gotchas.

Why OpenAlex
------------
- Free tier: 100k credits/day, ~10 req/s. ``mailto=`` query
  param unlocks the polite pool (faster + higher limit).
- Title + abstract + concepts + keywords + open-access
  flag + DOI + PMID all in one record.
- 200M works — best coverage outside PubMed for biomedical
  (and many other disciplines).

Why we re-implement rather than wrap the PubMed provider
-------------------------------------------------------
PubMed's E-Utils API has its own quirks (ESearch/EFetch two-step
flow, PubMed-specific XML/JSON). OpenAlex is JSON-native with a
single GET per query and a positional-token inverted-index for
abstracts (we reconstruct it in ``_reconstruct_abstract``). Mixing
the two code paths behind one client would obscure both.

Limitations we encode here
--------------------------
- Year filter uses ``publication_year:YYYY`` (single year) or
  ``publication_year:YYYY-YYYY`` (range).
- ``sort_by=NEWEST_FIRST`` uses
  ``sort=publication_date:desc``. Relevance is the OpenAlex
  default (no ``sort=`` param needed).
- Hard ceiling of 200 results per page, 10,000 across
  pages. The ``max_results`` cap in :class:`SearchFilters` is
  200 globally so we cap the per-page request to that and
  let the orchestrator decide whether to paginate.
- We always request the ``select=`` field-list so the
  response is ~10x smaller than the default ``*`` shape.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.enums.search_source import SearchSource
from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.interfaces.literature_searcher import (
    LiteratureSearcher,
)
from app.domain.value_objects.search_filters import (
    SearchDocumentType,
    SearchFilters,
    SortBy,
)
from app.domain.value_objects.search_result import SearchResult
from app.infrastructure.pubmed.abstract_normalizer import normalize_abstract

logger = logging.getLogger(__name__)


OPENALEX_BASE_URL = "https://api.openalex.org/works"
"""Base URL for the OpenAlex Works endpoint."""


class OpenAlexSearcher(LiteratureSearcher):
    """OpenAlex-backed :class:`LiteratureSearcher`.

    Configure with an optional ``mailto`` for the polite pool.
    No key required.
    """

    def __init__(
        self,
        *,
        mailto: str | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._mailto = mailto
        # If the caller passed an httpx.Client we reuse it;
        # otherwise we own the lifecycle and close it on
        # ``close()``.
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    # ----------------------------------------------------------------
    # LiteratureSearcher interface
    # ----------------------------------------------------------------

    def default_source(self) -> SearchSource:  # type: ignore[override]
        return SearchSource.OPENALEX

    def search(self, question) -> list[Paper]:
        # Legacy single-source entry point. Delegates to
        # search_with_filters so the two paths share logic.
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        from app.domain.value_objects.search_filters import (
            SearchFilters,
        )

        filters = SearchFilters(query=question.question)
        results = self.search_with_filters(filters)
        return [r.paper for r in results]

    def get_by_id(self, paper_id: str) -> Paper | None:
        """Fetch a single paper by DOI or OpenAlex ID.

        ``paper_id`` is the raw DOI string (without the
        ``https://doi.org/`` prefix) or the OpenAlex ID
        (``W4376614794``). Returns ``None`` if not found.
        """
        # OpenAlex accepts DOIs as ``doi:10.…`` (their
        # canonical form) and OpenAlex IDs as
        # ``openalex:W…``. We try DOI first (more useful
        # for our use cases) and fall back to OpenAlex ID.
        if paper_id.startswith("W") or paper_id.startswith("openalex:"):
            openalex_id = paper_id.removeprefix("openalex:")
            url = f"{OPENALEX_BASE_URL}/{openalex_id}"
        else:
            url = f"{OPENALEX_BASE_URL}/doi:{paper_id}"
        params = {"select": _SELECT_FIELDS}
        try:
            response = self._client.get(
                url,
                params=params,  # type: ignore[arg-type]
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "OpenAlex get_by_id(%s) failed: %s", paper_id, exc
            )
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.warning(
                "OpenAlex get_by_id(%s) returned %d",
                paper_id,
                response.status_code,
            )
            return None
        data = response.json()
        try:
            paper = _record_to_paper(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "OpenAlex record decode failed for %s: %s",
                paper_id,
                exc,
            )
            return None
        return paper

    def search_with_filters(
        self, filters: SearchFilters
    ) -> list[SearchResult]:
        params = _build_query_params(filters, mailto=self._mailto)
        try:
            response = self._client.get(
                OPENALEX_BASE_URL,
                params=params,  # type: ignore[arg-type]
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "OpenAlex search failed for %r: %s", filters.query, exc
            )
            return []
        if response.status_code != 200:
            logger.warning(
                "OpenAlex search returned %d for %r",
                response.status_code,
                filters.query,
            )
            return []
        try:
            payload = response.json()
            results = payload.get("results", []) or []
        except json.JSONDecodeError:
            logger.warning(
                "OpenAlex returned non-JSON for %r", filters.query
            )
            return []

        out: list[SearchResult] = []
        for record in results[: filters.max_results]:
            try:
                paper = _record_to_paper(record)
                confidence = _confidence_from_record(record)
                out.append(
                    SearchResult(
                        paper=paper,
                        source=SearchSource.OPENALEX,
                        confidence=confidence,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                # One bad record shouldn't poison the whole
                # search; log and skip.
                logger.warning(
                    "OpenAlex record decode failed: %s", exc
                )
                continue
        return out

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OpenAlexSearcher":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# ----------------------------------------------------------------
# Module-level constants and helpers
# ----------------------------------------------------------------


# Slim field list to keep responses small. Each field is
# documented in the research report at /home/grf/workspace/
# literature_apis_research.md.
_SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "publication_year",
        "publication_date",
        "authorships",
        "primary_location",
        "best_oa_location",
        "abstract_inverted_index",
        "concepts",
        "keywords",
        "ids",
        "open_access",
        "language",
    ]
)


def _build_query_params(
    filters: SearchFilters, *, mailto: str | None
) -> list[tuple[str, str]]:
    """Build the OpenAlex query-string parameter list.

    Returned as a list of (key, value) tuples (NOT a dict)
    because httpx's ``params`` accepts both but list-of-tuples
    preserves duplicate keys (``filter=…`` can appear
    multiple times for OR semantics).
    """
    # Strip wildcards (``?``, ``*``) from the query so
    # OpenAlex's stemmed search doesn't reject it as a
    # wildcard-pattern request.
    cleaned_query = re.sub(r"[?*]", " ", filters.query).strip()
    out: list[tuple[str, str]] = [
        ("search", cleaned_query),
        ("per_page", str(filters.max_results)),
        ("select", _SELECT_FIELDS),
    ]
    # OpenAlex's stemmed-search (``search=``) interprets
    # ``?`` and ``*`` as wildcard characters and 400s unless
    # we set ``search.exact=true``. Research questions often
    # end with ``?`` ("What is the amyloid cascade
    # hypothesis?"), so we strip wildcards from the query
    # before passing it to OpenAlex. The resulting search is
    # still stemmed, just without literal wildcard
    # characters. This is a regression for the user's
    # bioRxiv workspace question, which silently returned
    # zero results because of this.
    # Year filter: single year or range.
    if filters.since_year is not None and filters.until_year is not None:
        if filters.since_year == filters.until_year:
            out.append(
                ("filter", f"publication_year:{filters.since_year}")
            )
        else:
            out.append(
                (
                    "filter",
                    f"publication_year:{filters.since_year}-{filters.until_year}",
                )
            )
    elif filters.since_year is not None:
        out.append(
            ("filter", f"publication_year:{filters.since_year}-")
        )
    elif filters.until_year is not None:
        out.append(("filter", f"publication_year:-{filters.until_year}"))

    # Sort.
    if filters.sort_by == SortBy.NEWEST_FIRST:
        out.append(("sort", "publication_date:desc"))
    # RELEVANCE is the default; no ``sort=`` param needed.

    # Open-access only.
    if filters.open_access_only:
        out.append(("filter", "open_access.is_oa:true"))

    # Document types — OpenAlex supports a few
    # ``type:`` filters. Map each :class:`SearchDocumentType`
    # to its OpenAlex ``type`` value.
    type_filters = []
    for doc_type in filters.document_types:
        openalex_type = _DOC_TYPE_MAP.get(doc_type)
        if openalex_type:
            type_filters.append(openalex_type)
    if type_filters:
        # OpenAlex type values: article, book-chapter,
        # dataset, dissertation, preprint, review, etc.
        # We send each as its own ``filter`` so they're OR'd.
        out.append(("filter", f"type:{'|'.join(type_filters)}"))

    # Polite-pool mailto.
    if mailto:
        out.append(("mailto", mailto))
    return out


_DOC_TYPE_MAP = {
    SearchDocumentType.JOURNAL_ARTICLE: "article",
    SearchDocumentType.REVIEW: "review",
    SearchDocumentType.PREPRINT: "preprint",
    SearchDocumentType.DATASET: "dataset",
    SearchDocumentType.BOOK_CHAPTER: "book-chapter",
    SearchDocumentType.CONFERENCE_PAPER: None,
    # OpenAlex doesn't distinguish conference papers as a
    # top-level type; they'd come through as "article". We
    # silently skip the filter.
    SearchDocumentType.THESIS: "dissertation",
}


def _record_to_paper(record: dict[str, Any]) -> Paper:
    """Map one OpenAlex record to a domain ``Paper``.

    Raises ``KeyError`` / ``ValueError`` if the record is
    structurally broken (the caller catches and skips).
    """
    title = record.get("title") or ""
    if not title:
        raise ValueError("OpenAlex record has no title.")

    # DOI: OpenAlex returns the URL form. Strip the prefix
    # so the rest of the app stores bare DOIs.
    raw_doi = record.get("doi") or ""
    doi = _strip_doi_url(raw_doi)

    # PMID: similar — strip the URL prefix.
    pmid = _extract_pmid(record.get("ids") or {})

    # Year.
    year = record.get("publication_year")
    try:
        year_int = int(year) if year is not None else None
    except (TypeError, ValueError):
        year_int = None

    # Journal: prefer primary_location.source; fall back to
    # best_oa_location.source; fall back to None.
    journal = _extract_journal(record)

    # Authors: from ``authorships[*].author.display_name``.
    authors = _extract_authors(record.get("authorships") or [])

    # Abstract: reconstruct from the inverted index.
    abstract = normalize_abstract(
        _reconstruct_abstract(record.get("abstract_inverted_index"))
    )

    # Keywords: prefer ``keywords[*].display_name`` (top N).
    keywords = _extract_keywords(record.get("keywords") or [])

    # URL: prefer primary_location.landing_page_url; fall
    # back to best_oa_location or the OpenAlex canonical URL.
    url = _extract_url(record)

    return Paper(
        title=title,
        authors=authors,
        journal=journal,
        year=year_int,
        abstract=abstract,
        doi=doi,
        pmid=pmid,
        keywords=keywords,
        url=url,
    )


def _strip_doi_url(raw_doi: str) -> str | None:
    """Strip the ``https://doi.org/`` prefix from a DOI."""
    if not raw_doi:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/"):
        if raw_doi.startswith(prefix):
            return raw_doi[len(prefix):]
    return raw_doi


def _extract_pmid(ids: dict[str, Any]) -> str | None:
    """Pull PMID out of OpenAlex ``ids.pmid`` (URL form)."""
    raw = ids.get("pmid") if isinstance(ids, dict) else None
    if not raw:
        return None
    for prefix in (
        "https://pubmed.ncbi.nlm.nih.gov/",
        "http://pubmed.ncbi.nlm.nih.gov/",
    ):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def _extract_journal(record: dict[str, Any]) -> Journal | None:
    """Return the journal venue from primary_location or
    best_oa_location, whichever is populated."""
    for key in ("primary_location", "best_oa_location"):
        location = record.get(key)
        if not isinstance(location, dict):
            continue
        source = location.get("source")
        if not isinstance(source, dict):
            continue
        name = source.get("display_name")
        if not name:
            continue
        # ISSN: prefer ``issn_l`` (the linking ISSN), fall
        # back to the first entry in ``issn``.
        issn = source.get("issn_l") or ""
        if not issn and source.get("issn"):
            issn = source["issn"][0] if source["issn"] else ""
        publisher = source.get("host_organization_name") or None
        return Journal(
            name=name,
            issn=issn or None,
            publisher=publisher,
        )
    return None


def _extract_authors(
    authorships: list[dict[str, Any]],
) -> list[Author]:
    """Pull ``display_name`` out of each authorship record."""
    authors: list[Author] = []
    for entry in authorships:
        if not isinstance(entry, dict):
            continue
        author_obj = entry.get("author") or {}
        if not isinstance(author_obj, dict):
            continue
        full_name = author_obj.get("display_name")
        if not full_name:
            raw = entry.get("raw_author_name")
            full_name = raw or None
        if not full_name:
            continue
        # OpenAlex gives us ``display_name`` (e.g. "Kasper P
        # Kepp") — we don't get given/family separation
        # reliably, so we keep full_name and split on the
        # last whitespace for first/last (matches our
        # existing Author.full_name invariant).
        parts = full_name.rsplit(" ", 1)
        if len(parts) == 2:
            first, last = parts
        else:
            first, last = full_name, ""
        # Affiliation: take the first institution's name.
        affiliation = None
        institutions = entry.get("institutions") or []
        if institutions and isinstance(institutions[0], dict):
            affiliation = institutions[0].get("display_name")
        authors.append(
            Author(
                first_name=first,
                last_name=last,
                affiliation=affiliation,
            )
        )
    return authors


def _extract_keywords(
    keywords: list[dict[str, Any]],
) -> list[str]:
    """Take the top 8 keywords by score."""
    sorted_kw = sorted(
        keywords,
        key=lambda k: k.get("score", 0.0) if isinstance(k, dict) else 0.0,
        reverse=True,
    )
    out: list[str] = []
    for entry in sorted_kw[:8]:
        if isinstance(entry, dict) and entry.get("display_name"):
            out.append(str(entry["display_name"]))
    return out


def _extract_url(record: dict[str, Any]) -> str | None:
    """Return the best landing-page URL we can find."""
    for key in ("primary_location", "best_oa_location"):
        location = record.get(key)
        if isinstance(location, dict) and location.get("landing_page_url"):
            return str(location["landing_page_url"])
    return record.get("id")


def _confidence_from_record(record: dict[str, Any]) -> float:
    """OpenAlex doesn't expose a relevance score in the
    response payload, so we approximate from cited_by_count
    + open-access status. The orchestrator uses this only
    to break ties across sources, so a flat 0.5 is fine
    when no signal is present.
    """
    cited = record.get("cited_by_count") or 0
    # Heuristic: 0.4 baseline, +0.3 if highly cited (>100),
    # +0.2 if open access. Clamped to [0.0, 1.0].
    score = 0.4
    try:
        cited_n = int(cited)
    except (TypeError, ValueError):
        cited_n = 0
    if cited_n > 100:
        score += 0.3
    elif cited_n > 10:
        score += 0.1
    oa = record.get("open_access") or {}
    if isinstance(oa, dict) and oa.get("is_oa"):
        score += 0.2
    return max(0.0, min(1.0, score))


def _reconstruct_abstract(
    inverted_index: dict[str, list[int]] | None,
) -> str:
    """Reconstruct OpenAlex's positional-token abstract.

    OpenAlex returns the abstract as a mapping of
    ``{word: [position, position, …]}``. We sort by position
    and join with spaces. Placeholder tokens like ``<i>``
    appear as standalone entries.

    Empty / missing ``abstract_inverted_index`` → ``""``
    (not an error — many works don't have abstracts).
    """
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        if not isinstance(idxs, list):
            continue
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda pair: pair[0])
    return " ".join(word for _, word in positions)
