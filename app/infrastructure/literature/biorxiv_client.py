"""
biorxiv_client.py

bioRxiv / medRxiv ``LiteratureSearcher`` implementation.

bioRxiv has no keyword search — it's a chronological dump
plus DOI lookup. See the research report at
``/home/grf/workspace/literature_apis_research.md`` for
live-verified endpoint shapes.

Why we implement it anyway
----------------------------
The Advanced Search modal exposes bioRxiv as a source. When
the user picks bioRxiv AND provides a date window, the
client returns whatever preprints were posted in that
window. For keyword search, the orchestrator's
``MultiSourceSearcher`` falls back to Europe PMC's
``SRC:BIORXIV`` filter and uses bioRxiv's DOI endpoint to
enrich each hit with the preprint's canonical record.

What we expose
--------------
- ``search_with_filters``: when the filter has ``since_year``
  AND ``until_year`` (date window), fetch the window and
  return those preprints. Without a date window, return
  ``[]`` — the orchestrator routes keyword-only queries to
  Europe PMC instead.
- ``fetch_by_doi(server, doi)``: the canonical single-DOI
  lookup. Used by the orchestrator to enrich Europe PMC
  ``SRC:BIORXIV`` hits.
- ``get_by_id``: just calls ``fetch_by_doi``.

Caveats
-------
- The date-window endpoint caps at 100 records per cursor
  page. We iterate cursor up to ``max_results``.
- Authors are a single ``"; "``-separated string — we split
  and hope for the best.
- Field names are ``preprint_*`` everywhere.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.enums.search_source import SearchSource
from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.interfaces.literature_searcher import (
    LiteratureSearcher,
)
from app.domain.value_objects.search_filters import SearchFilters
from app.domain.value_objects.search_result import SearchResult
from app.infrastructure.pubmed.abstract_normalizer import normalize_abstract

logger = logging.getLogger(__name__)


BIORXIV_BASE_URL = "https://api.biorxiv.org"
"""Base URL for the bioRxiv / medRxiv API.

Two servers share this host: ``biorxiv`` and ``medrxiv``.
"""


class BiorxivSearcher(LiteratureSearcher):
    """bioRxiv / medRxiv-backed :class:`LiteratureSearcher`."""

    def __init__(
        self,
        *,
        server: str = "biorxiv",
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if server not in ("biorxiv", "medrxiv"):
            raise ValueError(
                f"server must be 'biorxiv' or 'medrxiv', got {server!r}"
            )
        self._server = server
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    # ----------------------------------------------------------------
    # LiteratureSearcher interface
    # ----------------------------------------------------------------

    def default_source(self) -> SearchSource:  # type: ignore[override]
        return SearchSource.BIORXIV

    def search(self, question) -> list[Paper]:
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
        """Fetch by DOI (e.g. ``10.1101/2022.09.11.507474``)."""
        return self.fetch_by_doi(self._server, paper_id)

    def search_with_filters(
        self, filters: SearchFilters
    ) -> list[SearchResult]:
        # bioRxiv only supports date-window queries. If
        # neither bound is supplied we have nothing to do.
        if filters.since_year is None and filters.until_year is None:
            return []
        # Otherwise pull the full window and return up to
        # ``max_results`` records.
        from_year = filters.since_year or 2013  # bioRxiv launched 2013
        to_year = filters.until_year or _current_year()
        records = self.fetch_by_date_range(from_year, to_year)
        out: list[SearchResult] = []
        for record in records[: filters.max_results]:
            try:
                paper = _record_to_paper(record)
                out.append(
                    SearchResult(
                        paper=paper,
                        source=SearchSource.BIORXIV,
                        confidence=0.5,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "bioRxiv record decode failed: %s", exc
                )
                continue
        return out

    # ----------------------------------------------------------------
    # bioRxiv-specific methods
    # ----------------------------------------------------------------

    def fetch_by_doi(self, server: str, doi: str) -> Paper | None:
        """Fetch a single preprint by DOI."""
        # The endpoint is
        # ``api.biorxiv.org/details/{server}/{doi}``.
        # Returns 200 + empty collection if DOI is not on
        # this server; 404 for malformed.
        url = f"{BIORXIV_BASE_URL}/details/{server}/{doi}"
        try:
            response = self._client.get(url, timeout=30.0)
        except httpx.HTTPError as exc:
            logger.warning(
                "bioRxiv details(%s) failed: %s", doi, exc
            )
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            return None
        records = payload.get("collection") or []
        if not records:
            return None
        try:
            return _record_to_paper(records[0])
        except Exception:  # noqa: BLE001
            return None

    def fetch_by_date_range(
        self, from_year: int, to_year: int
    ) -> list[dict[str, Any]]:
        """Pull all preprints in the date window.

        bioRxiv's date-window endpoint caps at 100 records
        per cursor page. We iterate the cursor until we've
        consumed the full window or hit ``max_results``.
        """
        if to_year < from_year:
            return []
        from_date = f"{from_year}-01-01"
        to_date = f"{to_year}-12-31"
        url = (
            f"{BIORXIV_BASE_URL}/pubs/{self._server}/"
            f"{from_date}/{to_date}"
        )
        records: list[dict[str, Any]] = []
        cursor = 0
        while True:
            page_url = f"{url}/{cursor}/json"
            try:
                response = self._client.get(
                    page_url, timeout=60.0
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "bioRxiv date-range fetch failed at cursor %d: %s",
                    cursor,
                    exc,
                )
                break
            if response.status_code != 200:
                break
            try:
                payload = response.json()
            except Exception:  # noqa: BLE001
                break
            page = payload.get("collection") or []
            if not page:
                break
            records.extend(page)
            messages = payload.get("messages") or []
            if messages:
                first_msg = messages[0]
                if isinstance(first_msg, dict):
                    total_str = first_msg.get("total")
                    count = first_msg.get("count", 0)
                    try:
                        total = int(total_str) if total_str else 0
                    except (TypeError, ValueError):
                        total = 0
                    # If we've consumed the total, we're done.
                    if total and len(records) >= total:
                        break
                    # If we got fewer than the page cap, no
                    # more pages exist.
                    if count < 100:
                        break
            cursor += 1
        return records

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "BiorxivSearcher":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------


def _current_year() -> int:
    """Return the current calendar year."""
    import datetime

    return datetime.datetime.now().year


def _record_to_paper(record: dict[str, Any]) -> Paper:
    """Map one bioRxiv record to a domain ``Paper``."""
    title = (record.get("preprint_title") or "").strip()
    if not title:
        raise ValueError("bioRxiv record has no title.")

    doi = (record.get("preprint_doi") or "").strip() or None

    year = None
    preprint_date = record.get("preprint_date") or ""
    if preprint_date:
        try:
            year = int(preprint_date[:4])
        except (TypeError, ValueError):
            year = None

    # Journal: bioRxiv preprints may later be published in
    # a journal. ``published_journal`` is the canonical name
    # of that journal, or ``None`` for unpublished preprints.
    journal_name = (record.get("published_journal") or "").strip()
    journal = None
    if journal_name:
        journal = Journal(
            name=journal_name,
            issn=None,
            publisher=None,
        )

    authors = _parse_authors(record.get("preprint_authors") or "")

    abstract = normalize_abstract(
        (record.get("preprint_abstract") or "").strip()
    )

    keywords: list[str] = []
    category = (record.get("preprint_category") or "").strip()
    if category:
        keywords.append(category)

    url: str | None = None
    if doi:
        url = f"https://doi.org/{doi}"

    return Paper(
        title=title,
        authors=authors,
        journal=journal,
        year=year,
        abstract=abstract,
        doi=doi,
        pmid=None,  # bioRxiv never has a PMID.
        keywords=keywords,
        url=url,
    )


def _parse_authors(raw_authors: str) -> list[Author]:
    """Split a ``"; "``-separated author string into Authors.

    The format is inconsistent across bioRxiv records:
    - ``"Last, F.; Last, F."`` (initials after comma)
    - ``"First Last; First Last"`` (space-separated)

    We split on ``"; "``, then on either ``" "`` or ``", "`` to
    decide which format each entry uses. If a name has only
    one token we treat it as the surname with no given name.
    """
    if not raw_authors:
        return []
    out: list[Author] = []
    for entry in raw_authors.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "," in entry:
            # ``"Last, F."`` or ``"Last, First"`` — surname
            # first.
            parts = [p.strip() for p in entry.split(",", 1)]
            if len(parts) == 2:
                last, first = parts
            else:
                first, last = "", parts[0]
        else:
            # ``"First Last"`` — surname last.
            tokens = entry.split()
            if len(tokens) >= 2:
                first = " ".join(tokens[:-1])
                last = tokens[-1]
            else:
                first, last = "", tokens[0]
        out.append(
            Author(
                first_name=first,
                last_name=last,
                affiliation=None,
            )
        )
    return out
