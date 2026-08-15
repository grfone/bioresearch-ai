r"""
pdf_extractor.py

Extract DOI / PMID identifiers from a PDF file the user uploaded.

The extraction is intentionally lightweight — no ML deps, no
Grok, no SciBERT. We read the first page of the PDF with
``pypdf`` (pure-Python, ~3 MB) and sweep the text with two
regular expressions:

- DOI:  ``10\.\d{4,9}/[^\s]+`` (the canonical DOI prefix)
- PMID: ``PMID[:\s]*\d{1,8}`` (the standard PubMed citation form)

Each match is normalised and passed through the same
:class:`IdentifierResolver` we use for the bulk-paste workflow,
so the user gets the same green/amber/red feedback whether
they pasted a PMID, a DOI, or a PDF.

Why not do full text extraction?
--------------------------------
The actual paper text (introduction, methods, etc.) is irrelevant
for cataloging purposes — we only need the identifier so we can
fetch the metadata from PubMed / CrossRef. The first page
contains the DOI in the citation block and the PMID on the
publisher's landing page. That's enough.

Why not use a heavy PDF parser?
-------------------------------
We deliberately avoid ``pdfplumber``, ``PyMuPDF``, and similar
because they add 30-50 MB to the image and pull in C extensions
that don't build on every platform. ``pypdf`` is a pure-Python
read-only parser that handles the 99% case (text-based PDFs from
BioMed Central, Nature, PubMed Central, etc.) and is 30x smaller.
Scanned PDFs are out of scope for now — we surface a clear
"no DOI/PMID found" error so the user can fall back to the
PMID/DOI tab.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identifier patterns
# ---------------------------------------------------------------------------


# DOI: 10.NNNN/yyyy…  (case-insensitive; the PDF may render
# "10.1038/" with different spacing or breaks).
_DOI_RE = re.compile(
    r"10\.\d{4,9}/[^\s\"'<>]+",
    re.IGNORECASE,
)

# PMID: appears in the citation block as "PMID: 12345678" or
# "pmid 12345678" or "PubMed: 12345678". We accept any of those.
_PMID_RE = re.compile(
    r"(?:pmid|pubmed)[:\s]*(\d{1,8})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PdfExtractionResult:
    """Outcome of extracting identifiers from a PDF.

    Attributes
    ----------
    identifiers : list[str]
        DOIs and PMIDs found in the first page of the PDF, in
        the order they appeared. Duplicates are removed while
        preserving the first occurrence.

    pdf_text : str
        The first-page text we extracted. Returned so the route
        can include it in the response (helpful for debugging
        when the user uploads a scanned PDF and the heuristic
        finds nothing).

    pages_scanned : int
        How many pages we read. For now we only read the first
        page, but the parameter is there for future use (e.g.
        scan a few pages when the DOI is missing from page 1).
    """

    identifiers: list[str]
    pdf_text: str
    pages_scanned: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_identifiers_from_pdf(
    fileobj: BinaryIO,
    max_pages: int = 1,
) -> PdfExtractionResult:
    """Extract DOI / PMID identifiers from a PDF.

    Parameters
    ----------
    fileobj : BinaryIO
        File-like object opened in binary mode. Reads the PDF
        from the current position; the caller is responsible for
        rewinding if needed.

    max_pages : int, default=1
        How many pages to scan. Defaults to 1 because DOIs and
        PMIDs are almost always on the first page. Bumping this
        helps when the user uploads a multi-page document where
        the citation block is on page 2.

    Returns
    -------
    PdfExtractionResult
        The list of found identifiers, the text that was scanned,
        and the page count for transparency.

    Raises
    ------
    RuntimeError
        If the PDF can't be opened (corrupted file, encryption,
        not a PDF at all). The error message is intended to be
        friendly enough to surface to the user.
    """
    try:
        reader = PdfReader(fileobj)
    except PdfReadError as exc:
        raise RuntimeError(
            f"Could not read the PDF: {exc}. The file may be corrupted, "
            "password-protected, or not actually a PDF."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Could not open the PDF: {exc}"
        ) from exc

    if reader.is_encrypted:
        # Try the empty password (the standard "owner" lockdown).
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
            page_text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("pypdf failed to extract page %d: %s", i, exc)
            page_text = ""
        text_parts.append(page_text)

    pdf_text = "\n".join(text_parts)

    # Find identifiers in the combined text. We strip every
    # candidate by removing trailing punctuation that PDFs
    # commonly attach (periods, commas, brackets) so the resolver
    # doesn't trip on a stray comma.
    identifiers: list[str] = []
    seen: set[str] = set()

    for match in _DOI_RE.finditer(pdf_text):
        candidate = match.group(0).rstrip(".,;)")
        if candidate.lower().endswith(")"):
            candidate = candidate[:-1]
        if candidate not in seen:
            seen.add(candidate)
            identifiers.append(candidate)

    for match in _PMID_RE.finditer(pdf_text):
        candidate = match.group(1)
        if candidate not in seen:
            seen.add(candidate)
            identifiers.append(candidate)

    return PdfExtractionResult(
        identifiers=identifiers,
        pdf_text=pdf_text,
        pages_scanned=pages_to_scan,
    )
