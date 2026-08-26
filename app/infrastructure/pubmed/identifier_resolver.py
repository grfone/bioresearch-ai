"""
identifier_resolver.py

Resolve biomedical paper identifiers (PMID, DOI) into full
``Paper`` domain entities by calling the appropriate upstream API.

Two resolution paths:

- PMID -> PubMed EFetch via Biopython (existing PubMedClient).
- DOI -> CrossRef REST API via httpx (no extra dependency; the
  minimal-requirements already include httpx).

The resolver returns a list of (identifier, Paper | None, error)
tuples so the caller can show per-identifier status chips to the
user (green for resolved, red for not-found, amber for partial).

This module is intentionally a thin adapter — domain logic lives
in the orchestrator, request validation lives in the API schema.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

import httpx

from app.domain.entities.paper import Paper
from app.infrastructure.pubmed.abstract_enricher import (
    AbstractEnricher,
)
from app.infrastructure.pubmed.abstract_normalizer import normalize_abstract
from app.infrastructure.pubmed.mapper import PubMedMapper
from app.infrastructure.pubmed.provider import PubMedProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedPaper:
    """A successfully resolved paper.

    Attributes
    ----------
    identifier : str
        The PMID or DOI that was resolved.

    identifier_type : str
        ``"pmid"`` or ``"doi"``.

    paper : Paper
        The resolved domain entity.

    """

    identifier: str
    identifier_type: str
    paper: Paper


@dataclass(frozen=True)
class FailedResolution:
    """An identifier that could not be resolved.

    Attributes
    ----------
    identifier : str
        The PMID or DOI that was attempted.

    reason : str
        Short human-readable explanation (e.g. "Not found",
        "Network error", "Invalid DOI format").
    """

    identifier: str
    reason: str


@dataclass(frozen=True)
class ResolutionResult:
    """Outcome of resolving a single identifier.

    Exactly one of ``paper`` or ``failure`` is populated. Use
    ``is_success`` to dispatch.
    """

    paper: ResolvedPaper | None = None
    failure: FailedResolution | None = None

    @property
    def is_success(self) -> bool:
        return self.paper is not None


# ---------------------------------------------------------------------------
# Identifier classification
# ---------------------------------------------------------------------------


# PMID: 1-8 digits. Most real PMIDs are 7-8 digits but the NCBI
# technically allows 1-8.
_PMID_RE = re.compile(r"^\d{1,8}$")

# DOI: 10.xxxx/yyyy where the prefix is at least 4 digits and the
# suffix is at least 1 character. Real DOIs are 10.NNNN/anything.
_DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s]+$", re.IGNORECASE)


def classify_identifier(raw: str) -> tuple[str, str] | None:
    """Classify an identifier string as PMID or DOI.

    Parameters
    ----------
    raw : str
        The user-supplied identifier (whitespace is stripped).

    Returns
    -------
    tuple[str, str] | None
        ``("pmid", normalized_pmid)`` or ``("doi", normalized_doi)``
        if recognized, else ``None``.
    """
    cleaned = raw.strip()
    # Strip surrounding whitespace and any common URL prefixes.
    if cleaned.lower().startswith("https://doi.org/"):
        cleaned = cleaned[len("https://doi.org/"):]
    elif cleaned.lower().startswith("http://doi.org/"):
        cleaned = cleaned[len("http://doi.org/"):]
    elif cleaned.lower().startswith("doi:"):
        cleaned = cleaned[len("doi:"):]
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    if _PMID_RE.match(cleaned):
        return ("pmid", cleaned)
    if _DOI_RE.match(cleaned):
        return ("doi", cleaned)
    return None


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class IdentifierResolver:
    """Resolve PMIDs and DOIs to domain ``Paper`` entities.

    The resolver holds a reference to the PubMed client for PMID
    resolution and uses httpx directly for CrossRef. Both code
    paths return ``ResolutionResult`` so the caller can show
    per-identifier feedback to the user.

    The resolver is intentionally tolerant of partial failures:
    one bad identifier in a batch does not abort the others.
    """

    CROSSREF_API = "https://api.crossref.org/works/{doi}"
    CROSSREF_TIMEOUT = 15.0

    def __init__(
        self,
        pubmed_provider: PubMedProvider,
        *,
        abstract_enricher: AbstractEnricher | None = None,
    ) -> None:
        self._pubmed_provider = pubmed_provider
        # AbstractEnricher is optional. When provided, the
        # resolver falls back to HTML meta-tag scraping
        # after the OpenAlex fallback. When None, the
        # resolver stops at OpenAlex (the pre-existing
        # behaviour).
        self._abstract_enricher = abstract_enricher

    def resolve_many(
        self,
        identifiers: list[str],
    ) -> list[ResolutionResult]:
        """Resolve a batch of identifiers.

        Parameters
        ----------
        identifiers : list[str]
            PMIDs and/or DOIs (one per item).

        Returns
        -------
        list[ResolutionResult]
            One result per input identifier, in the same order.
            Unrecognized identifiers produce a ``FailedResolution``
            with reason ``"Unrecognized identifier format"``.
        """
        results: list[ResolutionResult] = []
        for raw in identifiers:
            try:
                results.append(self.resolve_one(raw))
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Unexpected error resolving %r", raw,
                )
                results.append(ResolutionResult(
                    failure=FailedResolution(
                        identifier=raw,
                        reason=f"Resolver error: {exc}",
                    )
                ))
        return results

    def resolve_one(self, raw: str) -> ResolutionResult:
        """Resolve a single identifier."""
        classification = classify_identifier(raw)
        if classification is None:
            return ResolutionResult(
                failure=FailedResolution(
                    identifier=raw,
                    reason="Unrecognized identifier format",
                )
            )
        kind, value = classification
        if kind == "pmid":
            return self._resolve_pmid(value)
        if kind == "doi":
            return self._resolve_doi(value)
        return ResolutionResult(
            failure=FailedResolution(
                identifier=raw,
                reason="Unknown identifier type",
            )
        )

    # ------------------------------------------------------------------
    # Private resolvers
    # ------------------------------------------------------------------

    def _resolve_pmid(self, pmid: str) -> ResolutionResult:
        try:
            paper = self._pubmed_provider.get_by_id(pmid)
        except RuntimeError as exc:
            return ResolutionResult(
                failure=FailedResolution(
                    identifier=pmid,
                    reason=f"PubMed error: {exc}",
                )
            )
        if paper is None:
            return ResolutionResult(
                failure=FailedResolution(
                    identifier=pmid,
                    reason="PubMed returned no record",
                )
            )
        return ResolutionResult(
            paper=ResolvedPaper(
                identifier=pmid,
                identifier_type="pmid",
                paper=paper,
            )
        )

    OPENALEX_DOI_API = "https://api.openalex.org/works/doi:{doi}"
    OPENALEX_TIMEOUT = 15.0

    def _resolve_doi(self, doi: str) -> ResolutionResult:
        url = self.CROSSREF_API.format(doi=doi)
        try:
            with httpx.Client(timeout=self.CROSSREF_TIMEOUT) as client:
                response = client.get(
                    url,
                    headers={
                        "User-Agent": "BioResearchAI/1.0 (mailto:hello@example.org)",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return ResolutionResult(
                failure=FailedResolution(
                    identifier=doi,
                    reason=(
                        f"CrossRef HTTP {exc.response.status_code}"
                    ),
                )
            )
        except httpx.HTTPError as exc:
            return ResolutionResult(
                failure=FailedResolution(
                    identifier=doi,
                    reason=f"Network error: {exc!s}",
                )
            )

        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            return ResolutionResult(
                failure=FailedResolution(
                    identifier=doi,
                    reason=f"Bad CrossRef JSON: {exc}",
                )
            )

        try:
            paper = _crossref_to_paper(doi, data)
        except (KeyError, TypeError, ValueError) as exc:
            return ResolutionResult(
                failure=FailedResolution(
                    identifier=doi,
                    reason=f"CrossRef parse error: {exc}",
                )
            )

        # Fallback: if CrossRef returned a paper with no
        # abstract, try OpenAlex. Book chapters and
        # conference proceedings often have a richer
        # abstract there. We only override the abstract
        # -- the rest of the record (title, authors, year)
        # stays from CrossRef since OpenAlex occasionally
        # has less precise metadata for non-journal types.
        if not paper.abstract or not paper.abstract.strip():
            openalex_abstract = self._fetch_openalex_abstract(doi)
            if openalex_abstract:
                # OpenAlex's inverted-index reconstruction
                # produces plain text (no HTML), but we run
                # the result through ``normalize_abstract``
                # anyway as a forward-compat hedge: if a
                # future OpenAlex response includes stray
                # tags, the stripper catches them before
                # storage.
                paper = replace(
                    paper, abstract=normalize_abstract(openalex_abstract)
                )

        # Third fallback: HTML meta-tag scraping. Open
        # publishers (Nature, PLOS, Frontiers, etc.) ship
        # the abstract in <meta name="description"> or
        # <meta name="citation_abstract">. Gated publishers
        # (Springer, Elsevier) deploy anti-bot that blocks
        # polite clients, so this only catches some of the
        # cases that OpenAlex misses.
        if not paper.abstract or not paper.abstract.strip():
            if self._abstract_enricher is not None:
                html_abstract = self._abstract_enricher.fetch(doi)
                if html_abstract is not None:
                    # ``html_abstract`` is an ExtractionResult
                    # carrying the abstract text AND the
                    # provenance flag (inferred=True if the
                    # LLM produced it). The enricher's
                    # ``_clean_abstract`` runs the stripper
                    # internally, but ``normalize_abstract``
                    # here is belt-and-braces -- a future
                    # enricher that bypasses ``_clean_abstract``
                    # for any reason won't reintroduce the
                    # ``<h4>Introduction</h4>`` leak.
                    paper = replace(
                        paper,
                        abstract=normalize_abstract(html_abstract.abstract),
                        inferred_abstract=html_abstract.inferred,
                    )

        return ResolutionResult(
            paper=ResolvedPaper(
                identifier=doi,
                identifier_type="doi",
                paper=paper,
            )
        )


    # ---------------------------------------------------------------------------
    # OpenAlex fallback (DOI only)
    # ---------------------------------------------------------------------------

    def _fetch_openalex_abstract(self, doi: str) -> str | None:
        """Return OpenAlex's abstract for the given DOI, or
        ``None`` if OpenAlex has no record or no abstract.

        OpenAlex stores abstracts as a positional-token
        inverted index (so they can be searched without
        re-inflating the full text on every query). We
        reconstruct the abstract by sorting tokens by
        their positions. The result is a clean string
        suitable for display in the PaperCard.

        Network errors, malformed responses, and missing
        abstracts are all handled gracefully: this method
        returns ``None`` rather than raising so the
        caller can fall back to "no abstract" without
        breaking the resolution flow.
        """
        url = self.OPENALEX_DOI_API.format(doi=doi)
        try:
            with httpx.Client(timeout=self.OPENALEX_TIMEOUT) as client:
                response = client.get(
                    url,
                    params={"select": "abstract_inverted_index"},
                    headers={
                        "User-Agent": "BioResearchAI/1.0 (mailto:hello@example.org)",
                    },
                )
        except httpx.HTTPError as exc:
            logger.info(
                "OpenAlex fallback failed for DOI %s: %s",
                doi, exc,
            )
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            return None
        inverted = data.get("abstract_inverted_index")
        if not inverted:
            return None
        # Reconstruct: collect (position, word) pairs, sort by
        # position, join. OpenAlex positions are 1-indexed.
        try:
            positions: dict[int, str] = {}
            for word, indices in inverted.items():
                for idx in indices:
                    positions[idx] = word
            if not positions:
                return None
            return " ".join(
                positions[i] for i in range(1, max(positions) + 1)
            )
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# CrossRef -> Paper
# ---------------------------------------------------------------------------


def _crossref_to_paper(doi: str, data: dict[str, Any]) -> Paper:
    """Translate a CrossRef ``/works/{doi}`` JSON payload to a
    domain ``Paper``.

    We do the minimum needed for the lab-bench use case:
    title, authors, journal, year, abstract (if any), DOI, and
    the CrossRef URL. CrossRef records don't have PMIDs, so that
    field stays empty.
    """
    from app.domain.entities.author import Author
    from app.domain.entities.journal import Journal

    message = data.get("message") or {}

    # Title: CrossRef returns a list; the first entry is the
    # canonical title. Strip the trailing period that some
    # publishers add.
    titles = message.get("title") or []
    title = (titles[0] if titles else "").strip()
    if title.endswith("."):
        title = title[:-1]
    if not title:
        raise ValueError("CrossRef record has no title")

    # Authors: list of {given, family, name}.
    authors: list[Author] = []
    for entry in message.get("author") or []:
        given = (entry.get("given") or "").strip()
        family = (entry.get("family") or "").strip()
        name = (entry.get("name") or "").strip()
        first = given or name
        last = family
        if not first and not last and name:
            first = name
            last = ""
        if first or last:
            authors.append(
                Author(
                    first_name=first,
                    last_name=last,
                    affiliation=None,
                )
            )

    # Journal: container-title[0] is usually the journal name.
    journal_name = ""
    container_titles = message.get("container-title") or []
    if container_titles:
        journal_name = container_titles[0]
    journal = (
        Journal(name=journal_name, issn=None, publisher=None)
        if journal_name
        else None
    )

    # Year: published-print or published-online date-parts[0][0].
    year: int | None = None
    for date_field in ("published-print", "published-online", "created"):
        date_obj = message.get(date_field) or {}
        raw_parts = date_obj.get("date-parts") or [[None]]
        if not raw_parts or not raw_parts[0]:
            continue
        first_year = raw_parts[0][0]
        if first_year is None:
            continue
        try:
            year = int(first_year)
            break
        except (TypeError, ValueError):
            continue

    # Abstract: CrossRef often has a JATS abstract. Strip HTML.
    abstract_raw = message.get("abstract") or ""
    abstract = _strip_jats(abstract_raw)

    url = message.get("URL") or f"https://doi.org/{doi}"

    return Paper(
        title=title,
        authors=authors,
        journal=journal,
        year=year,
        abstract=abstract,
        doi=doi,
        pmid=None,
        keywords=[],
        url=url,
    )


def _strip_jats(html: str) -> str:
    """Best-effort strip of JATS/XML tags from a CrossRef abstract."""
    if not html:
        return ""
    # Replace common block tags with whitespace boundaries.
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse runs of whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text
