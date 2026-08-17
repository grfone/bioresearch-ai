"""
europe_pmc_client.py

Europe PMC ``LiteratureSearcher`` implementation.

Europe PMC is the EMBL-EBI aggregator that indexes PubMed +
preprints (bioRxiv, medRxiv, ChemRxiv, etc.) + many open-
access publishers. API: https://www.ebi.ac.uk/europepmc/webservices/rest/search

Why Europe PMC
--------------
- No API key, no rate-limit registration.
- Indexes PubMed AND preprints AND many publishers (over
  40M records as of 2026) — much broader than PubMed
  alone.
- Full-text links + open-access flag + MeSH terms + cross-
  references to PMC and DOI.
- Soft limit ~5-10 req/s; we keep it polite.

Gotchas (verified live in /home/.../literature_apis_research.md):
- ``sort=`` is BROKEN on the ``/search`` endpoint — any
  non-empty value returns only ``{"version": "6.9"}``.
  Workaround for "newest first": filter by
  ``FIRST_PDATE:[YYYY-MM-DD TO *]`` in the query string.
- Default ``resultType=lite`` strips abstract + authorList.
  Always pass ``resultType=core`` for our Paper mapper.
- ``journalInfo.journal`` is a length-1 array.
- Cursor pagination via ``cursorMark=*`` then ``nextCursorMark``.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import json
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
from app.domain.value_objects.search_filters import (
    SearchDocumentType,
    SearchFilters,
    SortBy,
)
from app.domain.value_objects.search_result import SearchResult

logger = logging.getLogger(__name__)


EUROPE_PMC_BASE_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
)


class EuropePMCSearcher(LiteratureSearcher):
    """Europe PMC-backed :class:`LiteratureSearcher`."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    # ----------------------------------------------------------------
    # LiteratureSearcher interface
    # ----------------------------------------------------------------

    def default_source(self) -> SearchSource:  # type: ignore[override]
        return SearchSource.EUROPE_PMC

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
        """Fetch a paper by PMID, DOI, or Europe PMC ID.

        ``paper_id`` formats accepted:
        - PMID (digits only, e.g. ``"1566067"``)
        - DOI (raw, e.g. ``"10.1126/science.1566067"``)
        - Europe PMC internal ID (e.g. ``"EXT_ID:1566067"``
          or numeric strings for non-PubMed sources)
        """
        query = _id_to_query(paper_id)
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": "1",
        }
        try:
            response = self._client.get(
                EUROPE_PMC_BASE_URL,
                params=params,  # type: ignore[arg-type]
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "Europe PMC get_by_id(%s) failed: %s", paper_id, exc
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "Europe PMC get_by_id(%s) returned %d",
                paper_id,
                response.status_code,
            )
            return None
        try:
            payload = response.json()
            results = (
                payload.get("resultList", {}).get("result", []) or []
            )
        except json.JSONDecodeError:
            return None
        if not results:
            return None
        try:
            return _record_to_paper(results[0])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Europe PMC record decode failed: %s", exc
            )
            return None

    def search_with_filters(
        self, filters: SearchFilters
    ) -> list[SearchResult]:
        query = _build_query(filters)
        params: dict[str, str] = {
            "query": query,
            "format": "json",
            "resultType": "core" if filters.include_abstracts else "lite",
            "pageSize": str(min(filters.max_results, 25)),
        }
        # Cursor pagination: send ``*`` for the first page.
        # We only fetch one page here; the orchestrator's
        # ``MultiSourceSearcher`` keeps things simple and
        # caps at ``max_results``.
        if filters.sort_by == SortBy.NEWEST_FIRST and filters.since_year:
            # ``sort=`` is broken on Europe PMC, so we
            # combine with a ``FIRST_PDATE`` filter and
            # reverse-sort the response client-side.
            params["cursorMark"] = "*"
        try:
            response = self._client.get(
                EUROPE_PMC_BASE_URL,
                params=params,  # type: ignore[arg-type]
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "Europe PMC search failed for %r: %s",
                filters.query,
                exc,
            )
            return []
        if response.status_code != 200:
            logger.warning(
                "Europe PMC search returned %d for %r",
                response.status_code,
                filters.query,
            )
            return []
        try:
            payload = response.json()
            results = (
                payload.get("resultList", {}).get("result", []) or []
            )
        except json.JSONDecodeError:
            logger.warning(
                "Europe PMC returned non-JSON for %r", filters.query
            )
            return []

        # Client-side reverse-sort by first_publication_date
        # if ``sort_by=NEWEST_FIRST`` was requested (since the
        # server-side sort is broken).
        if filters.sort_by == SortBy.NEWEST_FIRST and filters.since_year:
            results = _sort_by_date_desc(results)

        out: list[SearchResult] = []
        for record in results[: filters.max_results]:
            try:
                paper = _record_to_paper(record)
                confidence = _confidence_from_record(record)
                out.append(
                    SearchResult(
                        paper=paper,
                        source=SearchSource.EUROPE_PMC,
                        confidence=confidence,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Europe PMC record decode failed: %s", exc
                )
                continue
        return out

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "EuropePMCSearcher":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------


def _id_to_query(paper_id: str) -> str:
    """Translate an identifier into a Europe PMC query.

    PMID: digits only → ``ext_id:PMID``.
    DOI: starts with ``10.`` → ``doi:DOI``.
    Europe PMC internal ID: numeric or ``EXT_ID:...`` →
        ``ext_id:ID``.
    """
    cleaned = paper_id.strip()
    if cleaned.startswith("EXT_ID:"):
        return f"ext_id:{cleaned[len('EXT_ID:'):]}"
    if cleaned.startswith("PMC"):
        return f"pmc:PMC{cleaned[len('PMC'):]}"
    if cleaned.isdigit():
        return f"ext_id:{cleaned}"
    if cleaned.startswith("10."):
        return f"doi:{cleaned}"
    # Fall back to a free-text query.
    return cleaned


def _build_query(filters: SearchFilters) -> str:
    """Build a Europe PMC query DSL string.

    Europe PMC supports rich queries like ``amyloid cascade AND
    (FIRST_PDATE:[2020-01-01 TO 2024-12-31]) AND HAS_ABSTRACT:Y``.
    We assemble the query from the filter bundle.
    """
    parts: list[str] = [filters.query.strip()]
    if filters.since_year or filters.until_year:
        # ``FIRST_PDATE:[YYYY-01-01 TO YYYY-12-31]`` —
        # Europe PMC accepts ``TO *`` for open-ended.
        from_year = filters.since_year or "*"
        from_month_day = "01-01"
        if filters.until_year:
            to_clause = f"{filters.until_year}-12-31"
        else:
            to_clause = "*"
        if from_year == "*":
            range_clause = f"(FIRST_PDATE:[* TO {to_clause}])"
        elif to_clause == "*":
            range_clause = (
                f"(FIRST_PDATE:[{from_year}-{from_month_day} TO *])"
            )
        else:
            range_clause = (
                f"(FIRST_PDATE:[{from_year}-{from_month_day} TO {to_clause}])"
            )
        parts.append(range_clause)
    if filters.include_abstracts:
        parts.append("HAS_ABSTRACT:Y")
    if filters.open_access_only:
        parts.append("OPEN_ACCESS:Y")
    for doc_type in filters.document_types:
        epmc_type = _DOC_TYPE_MAP.get(doc_type)
        if epmc_type:
            parts.append(f"PUB_TYPE:{epmc_type}")
    return " AND ".join(parts)


_DOC_TYPE_MAP = {
    SearchDocumentType.JOURNAL_ARTICLE: "journal-article",
    SearchDocumentType.REVIEW: "review",
    SearchDocumentType.PREPRINT: "preprint",
    SearchDocumentType.DATASET: "dataset",
    SearchDocumentType.CONFERENCE_PAPER: None,
    # Europe PMC has conference abstracts but no top-level
    # PUB_TYPE filter for them; skip.
    SearchDocumentType.BOOK_CHAPTER: None,
    SearchDocumentType.THESIS: "thesis",
}


def _sort_by_date_desc(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort records by ``firstPublicationDate`` descending.

    Records without a date are pushed to the bottom.
    """

    def date_key(rec: dict[str, Any]) -> str:
        return rec.get("firstPublicationDate") or rec.get("pubYear") or ""

    return sorted(
        records,
        key=lambda r: (date_key(r) == "", -ord(date_key(r)[0]) if date_key(r) else 0, date_key(r)),
        reverse=True,
    )


def _record_to_paper(record: dict[str, Any]) -> Paper:
    """Map one Europe PMC record to a domain ``Paper``."""
    title = record.get("title") or ""
    if not title:
        raise ValueError("Europe PMC record has no title.")

    doi = (record.get("doi") or "").strip() or None
    pmid_raw = record.get("pmid")
    pmid: str | None = None
    if pmid_raw and str(pmid_raw).strip():
        pmid = str(pmid_raw).strip()

    # Year — Europe PMC sometimes gives an int (yearOfPublication)
    # and sometimes a string (pubYear).
    year = None
    journal_info = record.get("journalInfo") or {}
    if isinstance(journal_info.get("yearOfPublication"), int):
        year = journal_info["yearOfPublication"]
    elif record.get("pubYear"):
        try:
            year = int(str(record["pubYear"])[:4])
        except (TypeError, ValueError):
            year = None

    journal = _extract_journal(journal_info)

    authors = _extract_authors(record.get("authorList") or {})

    # Abstract: only present when ``resultType=core``.
    abstract = (record.get("abstractText") or "").strip()

    keywords = _extract_keywords(record)

    url = _extract_url(record)

    return Paper(
        title=title,
        authors=authors,
        journal=journal,
        year=year,
        abstract=abstract,
        doi=doi,
        pmid=pmid,
        keywords=keywords,
        url=url,
    )


def _extract_journal(journal_info: dict[str, Any]) -> Journal | None:
    """Pull the journal name out of ``journalInfo.journal[0]``."""
    if not isinstance(journal_info, dict):
        return None
    entries = journal_info.get("journal") or []
    if not entries:
        return None
    entry = entries[0] if isinstance(entries, list) else entries
    if not isinstance(entry, dict):
        return None
    name = entry.get("title")
    if not name:
        return None
    issn_obj = entry.get("ISSN") or {}
    issn = (
        issn_obj.get("electronic")
        or issn_obj.get("print")
        or None
    )
    publisher = None  # Europe PMC doesn't surface publisher.
    return Journal(
        name=name,
        issn=issn,
        publisher=publisher,
    )


def _extract_authors(author_list: dict[str, Any]) -> list[Author]:
    authors: list[Author] = []
    if not isinstance(author_list, dict):
        return authors
    entries = author_list.get("author") or []
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Europe PMC gives us first/last explicitly.
        first = (entry.get("firstName") or "").strip()
        last = (entry.get("lastName") or "").strip()
        full = (entry.get("fullName") or "").strip()
        if not first and not last and not full:
            continue
        if not first and not last:
            # last is empty; treat the full name as a
            # single token.
            first, last = full, ""
        elif not last:
            last = full
        affiliation = None
        affil_details = (
            entry.get("authorAffiliationDetailsList") or {}
        )
        if isinstance(affil_details, dict):
            affil_list = affil_details.get("authorAffiliation") or []
            if affil_list and isinstance(affil_list, list):
                first_affil = affil_list[0]
                if isinstance(first_affil, dict):
                    affiliation = first_affil.get("affiliation")
        authors.append(
            Author(
                first_name=first or full,
                last_name=last,
                affiliation=affiliation,
            )
        )
    return authors


def _extract_keywords(record: dict[str, Any]) -> list[str]:
    """Pull ``keywordList.keyword[]`` + MeSH descriptors."""
    out: list[str] = []
    keyword_list = record.get("keywordList") or {}
    if isinstance(keyword_list, dict):
        for kw in keyword_list.get("keyword") or []:
            if kw:
                out.append(str(kw))
    mesh_list = record.get("meshHeadingList") or {}
    if isinstance(mesh_list, dict):
        for mesh in mesh_list.get("meshHeading") or []:
            if isinstance(mesh, dict):
                name = mesh.get("descriptorName")
                if name:
                    out.append(str(name))
    return out


def _extract_url(record: dict[str, Any]) -> str | None:
    """Prefer the OA full-text link; fall back to the DOI URL."""
    full_text = record.get("fullTextUrlList") or {}
    if isinstance(full_text, dict):
        entries = full_text.get("fullTextUrl") or []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("availabilityCode") == "OA":
                    return str(entry.get("url"))
            # No OA — return the first URL anyway.
            if entries and isinstance(entries[0], dict):
                return str(entries[0].get("url"))
    # Fall back to DOI URL.
    doi = record.get("doi")
    if doi:
        return f"https://doi.org/{doi}"
    # Or the PMID URL.
    pmid = record.get("pmid")
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return None


def _confidence_from_record(record: dict[str, Any]) -> float:
    """Approximate relevance from cited_by_count + open access."""
    cited = record.get("citedByCount") or 0
    try:
        cited_n = int(cited)
    except (TypeError, ValueError):
        cited_n = 0
    score = 0.45  # Baseline.
    if cited_n > 100:
        score += 0.25
    elif cited_n > 10:
        score += 0.1
    if record.get("isOpenAccess") == "Y":
        score += 0.2
    return max(0.0, min(1.0, score))
