"""
Tests for the PDF identifier extractor.

The extractor is the front-end of the drag-and-drop PDF
workflow. It reads the first page of a PDF with pypdf and
sweeps DOI/PMID patterns so the user can drop a paper onto
the workspace without typing the identifier by hand.

These tests use hand-crafted PDFs (raw PDF byte streams) so the
extractor is exercised end-to-end without depending on a real
PDF in the repo. The mechanism is small enough that hand-crafted
PDFs are easier to read than a fixture file.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers — build minimal valid PDFs with custom text content
# ---------------------------------------------------------------------------


def _pdf_with_text(text: str) -> bytes:
    """Return a minimal PDF whose first page contains ``text``.

    Hand-rolled PDF 1.4 with a single page, a Helvetica font, and
    the text drawn via the standard ``BT … ET`` text block. The
    cross-reference table is intentionally minimal (notice the
    fixed offsets). pypdf accepts this without complaint
    (warnings about "wrong pointing object" are expected but
    don't affect extraction).
    """
    text = text.replace("(", r"\(").replace(")", r"\)")
    stream = (
        b"BT /F1 12 Tf 50 700 Td (" + text.encode() + b") Tj ET"
    )
    n = len(stream)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(n).encode() + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000109 00000 n \n"
        b"0000000202 00000 n \n"
        b"0000000366 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n434\n%%EOF\n"
    )


def _pdf_encrypted() -> bytes:
    """A PDF with an empty-owner-password encryption marker.

    Constructed just enough to trigger the encrypted branch in
    the extractor. pypdf refuses to extract text from this
    without a password, so we expect RuntimeError.
    """
    return (
        b"%PDF-1.4\n"
        b"%dummy encrypted-but-not-really bytes\n"
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_extract_doi_and_pmid_from_pdf() -> None:
    """A PDF with both DOI and PMID on the first page returns both."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text(
        "Amyloid clearance. DOI: 10.1038/nature12373. PMID: 40000001."
    )
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert result.identifiers == ["10.1038/nature12373", "40000001"]
    assert result.pages_scanned == 1
    assert "Amyloid clearance" in result.pdf_text


def test_extract_doi_only() -> None:
    """A PDF with only a DOI returns the DOI alone."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text("A paper. doi: 10.1038/s41586-021-03819-2.")
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert result.identifiers == ["10.1038/s41586-021-03819-2"]


def test_extract_pmid_only() -> None:
    """A PDF with only a PMID returns the PMID alone."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text("Methods. PubMed: 12345678.")
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert result.identifiers == ["12345678"]


def test_extract_deduplicates_across_pages() -> None:
    """If the same identifier appears twice (e.g. once on the
    first page, once in the bibliography) we return only one
    copy. Duplicates are confusing when the user sees the
    resolver report them."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text(
        "DOI: 10.1038/nature12373 here. "
        "DOI: 10.1038/nature12373 again."
    )
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert result.identifiers == ["10.1038/nature12373"]


def test_extract_strips_trailing_punctuation() -> None:
    """DOIs occasionally render with trailing commas or
    parentheses. The extractor must strip those so the resolver
    gets a clean identifier."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text(
        "See DOI: 10.1038/nature12373, and Figure 1 (ref 1)."
    )
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    # Trailing comma and ")" are stripped, but the leading "10."
    # is preserved.
    assert "10.1038/nature12373" in result.identifiers
    assert all("10.1038/nature12373" in ident for ident in result.identifiers)


def test_extract_strips_trailing_doi_keyword() -> None:
    """bioRxiv preprint boilerplate often renders the DOI on the
    same line as the next ``doi:`` literal with no whitespace
    between them — ``https://doi.org/10.64898/...doi: bioRxiv``.

    The greedy DOI regex captures everything up to the next
    whitespace, including the literal ``doi`` and ``:``. The
    extractor must peel those off before lookup, otherwise
    CrossRef returns 404 for a DOI that exists.

    This is the exact regression the user hit with their PDF.
    """
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text(
        "bioRxiv preprint doi: https://doi.org/10.64898/2026.03.31.715296doi: "
        "bioRxiv preprint"
    )
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    # The trailing ``doi:`` and any trailing colons are stripped.
    assert "10.64898/2026.03.31.715296" in result.identifiers
    # No candidate ends with the literal "doi" word.
    assert all(not ident.lower().endswith("doi") for ident in result.identifiers)
    assert all(not ident.lower().endswith("doi:") for ident in result.identifiers)
    # No candidate contains ``doi:`` glued to the DOI suffix.
    assert all("715296doi" not in ident for ident in result.identifiers)


def test_extract_strips_trailing_https_keyword() -> None:
    """Same as the doi-keyword case but with ``https:`` glued to
    the DOI suffix."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text("10.1038/nature12373https: see https://example.com")
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert "10.1038/nature12373" in result.identifiers
    assert all(not ident.lower().endswith("https:") for ident in result.identifiers)
    assert all("12373https" not in ident for ident in result.identifiers)


def test_extract_strips_repeated_trailing_keyword() -> None:
    """Defensive: if the PDF renders ``doi:doi:doi`` after the
    DOI (never observed in practice but cheap to handle), the
    extractor peels all of them off."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text("10.1038/nature12373doi:doi:doi:")
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert "10.1038/nature12373" in result.identifiers


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_extract_no_identifiers_returns_empty() -> None:
    """A PDF without any DOI/PMID returns an empty list with
    the text preserved so the caller can return a helpful
    diagnostic to the user."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text("This paper has no identifier at all.")
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert result.identifiers == []
    assert "no identifier" in result.pdf_text


def test_extract_corrupted_pdf_raises() -> None:
    """A PDF that pypdf can't open raises RuntimeError with a
    user-friendly message."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    with pytest.raises(RuntimeError, match="Could not read the PDF"):
        extract_identifiers_from_pdf(io.BytesIO(b"not a pdf at all"))


def test_extract_preserves_extracted_text_in_result() -> None:
    """The result carries the extracted text so the caller can
    surface it to the user when the heuristic finds nothing —
    helps debug scanned PDFs."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    body = (
        "Long-form abstract. We tested 200 participants over "
        "two years and found interesting results."
    )
    pdf = _pdf_with_text(body)
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert "200 participants" in result.pdf_text
    assert result.identifiers == []


def test_extract_handles_uppercase_doi() -> None:
    """DOIs are case-insensitive in the prefix but the conventions
    say lowercase. The extractor must still find ``10.1038/...``
    regardless."""
    from app.infrastructure.pubmed.pdf_extractor import (
        extract_identifiers_from_pdf,
    )

    pdf = _pdf_with_text("doi: 10.1038/NATURE12373.")
    result = extract_identifiers_from_pdf(io.BytesIO(pdf))

    assert "10.1038/NATURE12373" in result.identifiers
