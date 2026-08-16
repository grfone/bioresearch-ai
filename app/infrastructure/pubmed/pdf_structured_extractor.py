"""
pdf_structured_extractor.py

Extract a structured ``Paper`` from PDF text when external
lookup fails.

The :class:`IdentifierResolver` is the primary path: the PDF
yields a DOI, CrossRef returns full metadata, we add the paper
to the workspace. When the resolver fails (paper not in any of
the metadata APIs, the network is down, the DOI is malformed,
etc.) we still want the paper in the workspace — the user
uploaded it for a reason, and the PDF text often contains
enough information for the LLM stages to produce a useful
summary.

This module is the "structured extraction" fallback. It reads
the first page of a PDF and parses out:

  - Title (the longest line near the top of the page, before
    the author block).
  - Authors (a comma-separated list between the title and the
    affiliations block; we use the affiliations pattern —
    digits followed by a degree/superscript symbol — as a
    sentinel).
  - Year (parsed from the bioRxiv "this version posted
    <Month> <Day>, <Year>" boilerplate or from the copyright
    line "© <Year> ...").
  - DOI (cleaned via the same logic as
    :func:`extract_identifiers_from_pdf`).
  - Abstract (text between the literal "Abstract" header and
    the next section break — typically "1 Introduction" or
    "Introduction").
  - Keywords (after the literal "Keywords:" line; comma-
    separated).

Heuristics, not ML — these patterns are tight enough to be
deterministic, but they may fail on unusual layouts. We
return ``None`` for any field we can't extract confidently,
so the caller knows what it has and what it doesn't.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.entities.author import Author
from app.domain.entities.paper import Paper
from app.infrastructure.pubmed.pdf_extractor import (
    extract_identifiers_from_pdf,
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Heuristics
# -------------------------------------------------------------------


# bioRxiv's footer boilerplate: "this version posted April 2, 2026"
# The user-facing line is "posted <Month> <Day>, <Year>"; we capture
# the year.
_BIORXIV_POSTED_RE = re.compile(
    r"posted\s+\w+\s+\d{1,2},\s+(\d{4})",
    re.IGNORECASE,
)

# Copyright line: "© 2026 Elsevier ..." or "(c) 2026 ..."
_COPYRIGHT_YEAR_RE = re.compile(
    r"[©\u00a9]\s*(\d{4})|\b(?:copyright|\(c\))\s+(\d{4})",
    re.IGNORECASE,
)

# Section break sentinel — after "Abstract", the next heading is
# usually "1 Introduction" / "Introduction" / "1. Introduction".
_AFTER_ABSTRACT_SECTION_RE = re.compile(
    r"^\s*\d{0,2}\.?\s*(?:Introduction|Methods?|Materials\s+and\s+Methods|Results?|Background)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Affiliation marker — digits then a degree symbol or
# superscript digit, like "Travi1,2" or "Cecchi3#". This
# signals "this is the end of the author list".
_AFFILIATION_MARKER_RE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹\d][,¹²³⁴⁵⁶⁷⁸⁹\d*#†‡§¶]+")

# Email in author block — researchers list corresponding
# author email immediately after the affiliations.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


# -------------------------------------------------------------------
# Result type
# -------------------------------------------------------------------


@dataclass(frozen=True)
class StructuredPdfPaper:
    """Outcome of structured extraction from a PDF.

    The ``paper`` is always present (we wouldn't be here if
    the PDF had no title), but individual fields may be
    ``None`` or empty — the caller decides what to do with
    thin metadata (the workspace marks it with the partial-
    metadata asterisk + warning banner).
    """

    paper: Paper
    pdf_text: str
    pages_scanned: int


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------


def extract_paper_from_pdf(
    fileobj: BinaryIO,
    max_pages: int = 1,
) -> StructuredPdfPaper | None:
    """Extract a structured ``Paper`` from a PDF.

    Returns ``None`` if the PDF can't be read or contains no
    identifiable content. Raises ``RuntimeError`` for parse
    errors so the route can surface a 422.
    """
    try:
        reader = PdfReader(fileobj)
    except PdfReadError as exc:
        raise RuntimeError(
            f"Could not read the PDF: {exc}. The file may be corrupted, "
            "password-protected, or not actually a PDF."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not open the PDF: {exc}") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            raise RuntimeError(
                "The PDF is password-protected. Remove the password "
                "and re-upload the file."
            )

    pages_to_scan = min(max_pages, len(reader.pages))
    text_parts: list[str] = []
    for i in range(pages_to_scan):
        page = reader.pages[i]
        try:
            text_parts.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("pypdf failed to extract page %d: %s", i, exc)
    pdf_text = "\n".join(text_parts)

    paper = _parse_paper_from_text(pdf_text)
    if paper is None:
        return None
    return StructuredPdfPaper(
        paper=paper,
        pdf_text=pdf_text,
        pages_scanned=pages_to_scan,
    )


# -------------------------------------------------------------------
# Parsing helpers
# -------------------------------------------------------------------


def _parse_paper_from_text(pdf_text: str) -> Paper | None:
    """Heuristically parse the first-page text into a Paper."""
    # Normalise line endings — pypdf sometimes returns \r\n.
    text = pdf_text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of blank lines into a single blank line.
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = text.split("\n")

    # 1. DOI — re-use the existing extractor (already handles the
    # bioRxiv boilerplate ``doi:`` glued to the suffix).
    doi = _extract_first_doi(text)

    # 2. Title — first non-empty line that isn't an author
    # marker. Heuristic: take the first 1-3 lines that look
    # like a title (long, no affiliations markers, no "@").
    title = _extract_title(lines)

    # 3. Authors — line(s) immediately after the title, before
    # the first affiliation.
    authors = _extract_authors(lines)

    # 4. Year — bioRxiv footer or copyright line.
    year = _extract_year(text)

    # 5. Abstract — between "Abstract" header and the next
    # section break.
    abstract = _extract_abstract(text)

    # 6. Keywords — after the literal "Keywords:" line.
    keywords = _extract_keywords(text)

    if not title:
        return None

    return Paper(
        title=title,
        authors=authors,
        journal=None,  # Unknown from PDF text alone.
        year=year,
        abstract=abstract,
        doi=doi,
        pmid=None,  # We don't try to extract PMID here.
        keywords=keywords,
        url=f"https://doi.org/{doi}" if doi else None,
    )


def _extract_first_doi(text: str) -> str | None:
    """Pull the first cleaned DOI from the text using the same
    regex + strip logic as the identifier extractor, but
    applied directly to the text (no PDF re-parsing).
    """
    from app.infrastructure.pubmed.pdf_extractor import (
        _DOI_RE,
        _clean_doi_candidate,
    )

    for match in _DOI_RE.finditer(text):
        candidate = _clean_doi_candidate(match.group(0))
        if candidate and candidate.lower().startswith("10."):
            return candidate
    return None


def _extract_title(lines: list[str]) -> str | None:
    """First 1-3 lines near the top that look like a title.

    Heuristic: the title is the first contiguous block of lines
    that don't contain an affiliation marker, an email, or a
    section header. We cap at 3 lines because titles occasionally
    wrap (e.g. "Alzheimer's Disease Brain Phenotypes are\n
    Age-dependent").
    """
    title_lines: list[str] = []
    for raw in lines[:30]:
        line = raw.strip()
        if not line:
            if title_lines:
                break
            continue
        # Stop at the first line that looks like authors,
        # affiliations, keywords, or section header.
        if (
            _AFFILIATION_MARKER_RE.search(line)
            or _EMAIL_RE.search(line)
            or line.lower().startswith("keyword")
            or line.lower().startswith("abstract")
            or line.lower().startswith("introduction")
            or re.match(r"^\d+\.?\s+\w", line)
        ):
            break
        title_lines.append(line)
        if len(title_lines) >= 3:
            break
    if not title_lines:
        return None
    title = " ".join(title_lines).strip()
    if len(title) < 8:
        return None
    return title


def _extract_authors(lines: list[str]) -> list[Author]:
    """Parse the author block from the lines immediately
    following the title.

    Heuristic: the author block ends at the first line that
    contains an institution keyword ("University",
    "Department", "Institute", "Laboratory", "Faculty") or
    an email or a footnote marker. We split the joined
    author line on commas, peel off the affiliation digit
    suffixes ("Travi1,2,, Anushree Mehta3" → "Travi" /
    "Anushree Mehta"), and treat each comma-separated chunk
    as one author (or split on spaces for comma-only
    separation).
    """
    in_authors = False
    author_chunks: list[str] = []
    for raw in lines[:40]:
        line = raw.strip()
        if not line:
            if in_authors:
                # End of author block.
                break
            continue
        if _INSTITUTION_KEYWORDS_RE.search(line):
            # We've hit the affiliations block.
            break
        if _EMAIL_RE.search(line):
            break
        if _AFFILIATION_MARKER_RE.search(line):
            in_authors = True
            author_chunks.append(line)
            continue
        if in_authors:
            # Continuation of the author block (some PDFs wrap).
            author_chunks.append(line)

    if not author_chunks:
        return []

    # Strip affiliation markers ("1,2", "3#", "¹,²") so we can
    # split on the next commas/spaces cleanly.
    cleaned = _strip_affiliation_markers(" ".join(author_chunks))
    # Split on commas first; fall back to spaces if no commas.
    raw_names = [n.strip() for n in cleaned.split(",") if n.strip()]
    if len(raw_names) < 2:
        # No commas — try splitting on spaces but keep paired
        # given/family names (e.g. "Fermin Travi").
        tokens = cleaned.split()
        raw_names = []
        for i in range(0, len(tokens) - 1, 2):
            raw_names.append(f"{tokens[i]} {tokens[i + 1]}")
        if len(tokens) % 2 == 1:
            raw_names.append(tokens[-1])

    authors: list[Author] = []
    for raw in raw_names:
        if not raw:
            continue
        # Split into first/last name — last token is the surname.
        tokens = raw.split()
        if len(tokens) == 1:
            authors.append(
                Author(first_name=tokens[0], last_name="", affiliation=None)
            )
        else:
            authors.append(
                Author(
                    first_name=" ".join(tokens[:-1]),
                    last_name=tokens[-1],
                    affiliation=None,
                )
            )
    return authors


_INSTITUTION_KEYWORDS_RE = re.compile(
    r"\b(?:University|Department|Institute|Laboratory|Faculty|College|Hospital|Center|Centre|School)\b",
    re.IGNORECASE,
)


def _strip_affiliation_markers(text: str) -> str:
    """Remove affiliation marker suffixes like ``1,2`` or ``3#``
    from a string of author names.
    """
    # Drop digits that are glued to the end of a name token,
    # or appear as comma-separated footnoted digits.
    text = re.sub(r"(?<=[A-Za-z])[\d¹²³⁴⁵⁶⁷⁸⁹]+(?=[,\s]|$)", "", text)
    text = re.sub(r"\d{1,2}#", "", text)
    text = re.sub(r"[\d¹²³⁴⁵⁶⁷⁸⁹]{1,3}", "", text)
    # Collapse repeated commas/whitespace.
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,")


def _extract_year(text: str) -> int | None:
    """Year from bioRxiv boilerplate or copyright line."""
    for pattern in (_BIORXIV_POSTED_RE, _COPYRIGHT_YEAR_RE):
        match = pattern.search(text)
        if match:
            year_str = next((g for g in match.groups() if g), None)
            if year_str:
                try:
                    return int(year_str)
                except ValueError:
                    pass
    return None


def _extract_abstract(text: str) -> str:
    """Extract the abstract section, between the literal
    "Abstract" header and the next section break.
    """
    # Find the abstract header.
    abstract_match = re.search(
        r"^abstract\s*[:.]?\s*$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not abstract_match:
        return ""
    body_start = abstract_match.end()
    # Find the next section break.
    rest = text[body_start:]
    end_match = _AFTER_ABSTRACT_SECTION_RE.search(rest)
    if end_match:
        body = rest[: end_match.start()]
    else:
        body = rest
    # Clean: collapse whitespace, drop the literal "Abstract."
    # repeated header, drop leading numbers like "1".
    body = re.sub(r"\s+", " ", body).strip()
    return body


def _extract_keywords(text: str) -> list[str]:
    """Comma-separated keywords after the literal ``Keywords:``
    line.
    """
    match = re.search(
        r"^\s*keywords?\s*[:\-]\s*(.+)$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return []
    raw = match.group(1)
    # Take only the first line (keywords are usually on one line).
    raw = raw.split("\n", 1)[0]
    # Split on commas / semicolons.
    parts = re.split(r"[,;]\s*", raw)
    return [p.strip() for p in parts if p.strip()]