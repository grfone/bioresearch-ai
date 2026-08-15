"""
Tests for the identifier resolver.

The resolver is the bridge that lets the user paste a PMID or
DOI and have the system pull full metadata automatically. It is
intentionally tolerant: one bad identifier in a batch does not
abort the others. Each entry produces either a ResolvedPaper or
a FailedResolution so the frontend can show per-identifier
status chips.

These tests cover the unit-level pieces (classifier, batch
dispatcher, CrossRef -> Paper conversion) without hitting the
real PubMed/CrossRef APIs. Integration with the live APIs is
exercised by curl in the live verification step.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Insert the project root onto sys.path so the resolver module
# can be imported without installing the package.
sys.path.insert(0, str(REPO_ROOT))


def _make_resolver() -> tuple:
    """Build an IdentifierResolver with a stubbed PubMed provider.

    Returns ``(resolver, mock_provider)``. The mock provider's
    ``get_by_id`` returns a minimal ``Paper`` shaped like the
    domain entity so the resolver can hand it back.
    """
    from app.domain.entities.author import Author
    from app.domain.entities.journal import Journal
    from app.domain.entities.paper import Paper
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )

    def fake_get_by_id(pmid: str):
        # Simulate PubMed returning the paper for known IDs and
        # None for unknown ones.
        if pmid == "40000001":
            return Paper(
                title="Amyloid clearance in Alzheimer's disease.",
                authors=[
                    Author(first_name="Maria", last_name="Garcia"),
                ],
                journal=Journal(name="Nature Neuroscience"),
                year=2025,
                abstract="Review of amyloid clearance pathways.",
                doi="10.1038/s41593-025-00001-1",
                pmid="40000001",
                keywords=["Alzheimer"],
                url=None,
            )
        return None

    mock_provider = MagicMock()
    mock_provider.get_by_id.side_effect = fake_get_by_id
    return IdentifierResolver(pubmed_provider=mock_provider), mock_provider


# ---------------------------------------------------------------------------
# Identifier classification
# ---------------------------------------------------------------------------


def test_classify_identifier_recognises_pmid() -> None:
    from app.infrastructure.pubmed.identifier_resolver import (
        classify_identifier,
    )
    assert classify_identifier("40000001") == ("pmid", "40000001")
    assert classify_identifier("  12345  ") == ("pmid", "12345")


def test_classify_identifier_recognises_doi_with_prefix() -> None:
    from app.infrastructure.pubmed.identifier_resolver import (
        classify_identifier,
    )
    assert classify_identifier("10.1038/s41593-025-00001-1") == (
        "doi", "10.1038/s41593-025-00001-1"
    )


def test_classify_identifier_strips_doi_url_prefix() -> None:
    from app.infrastructure.pubmed.identifier_resolver import (
        classify_identifier,
    )
    assert classify_identifier(
        "https://doi.org/10.1038/s41593-025-00001-1",
    ) == ("doi", "10.1038/s41593-025-00001-1")
    assert classify_identifier(
        "doi:10.1038/s41593-025-00001-1",
    ) == ("doi", "10.1038/s41593-025-00001-1")


def test_classify_identifier_rejects_garbage() -> None:
    from app.infrastructure.pubmed.identifier_resolver import (
        classify_identifier,
    )
    assert classify_identifier("not-an-id") is None
    assert classify_identifier("") is None
    assert classify_identifier("   ") is None


# ---------------------------------------------------------------------------
# Resolver batch dispatch
# ---------------------------------------------------------------------------


def test_resolve_many_mixed_pmid_and_doi() -> None:
    """A batch of mixed PMID/DOI inputs returns one entry per
    input, with success/failure flags set correctly."""
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )

    # Stub out CrossRef via httpx patching: instead of going
    # over the network we just intercept the resolve_doi path
    # and return a failure for DOI in this unit test (DOI
    # resolution is exercised live).
    resolver, mock_provider = _make_resolver()

    # Monkey-patch the CrossRef httpx call to return a known
    # CrossRef-shaped payload for one DOI and fail for another.
    import httpx

    doi = "10.1038/s41593-025-00001-1"
    crossref_payload = {
        "message": {
            "title": ["Amyloid clearance"],
            "author": [{"given": "Maria", "family": "Garcia"}],
            "container-title": ["Nature Neuroscience"],
            "published-print": {"date-parts": [[2025]]},
            "DOI": doi,
            "URL": f"https://doi.org/{doi}",
        }
    }

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return crossref_payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, headers=None):
            return FakeResponse()

    # Swap httpx.Client with our fake so resolve_doi doesn't hit
    # the network.
    original_client = httpx.Client
    httpx.Client = FakeClient  # type: ignore[assignment]
    try:
        results = resolver.resolve_many([
            "40000001",  # known PMID
            "10.1038/s41593-025-00001-1",  # known DOI
            "99999999",  # unknown PMID
            "not-an-id",  # garbage
        ])
    finally:
        httpx.Client = original_client  # type: ignore[assignment]

    assert len(results) == 4
    assert results[0].is_success  # known PMID
    assert results[1].is_success  # known DOI
    assert not results[2].is_success  # unknown PMID
    assert not results[3].is_success  # garbage
    assert mock_provider.get_by_id.call_count == 2  # two PMIDs attempted


def test_resolve_one_continues_after_failure() -> None:
    """A failing PMID in the middle of a batch does not stop the
    later identifiers."""
    resolver, _ = _make_resolver()
    results = resolver.resolve_many([
        "40000001",   # ok
        "11111111",   # not found in PubMed
        "40000002",   # not in our mock (returns None) — should fail
    ])
    assert len(results) == 3
    assert results[0].is_success
    assert not results[1].is_success
    assert not results[2].is_success
    assert results[1].failure is not None
    assert "PubMed" in results[1].failure.reason


# ---------------------------------------------------------------------------
# CrossRef payload -> Paper
# ---------------------------------------------------------------------------


def test_crossref_payload_minimal_required_fields() -> None:
    """A CrossRef payload must have at least a title. Anything
    missing the title raises ValueError."""
    from app.infrastructure.pubmed.identifier_resolver import (
        _crossref_to_paper,
    )

    with pytest.raises(ValueError, match="no title"):
        _crossref_to_paper(
            "10.1038/empty",
            {"message": {"title": []}},
        )


def test_crossref_payload_happy_path() -> None:
    """A fully populated CrossRef payload becomes a Paper with
    every field populated."""
    from app.infrastructure.pubmed.identifier_resolver import (
        _crossref_to_paper,
    )

    paper = _crossref_to_paper(
        "10.1038/s41593-025-00001-1",
        {
            "message": {
                "title": ["Amyloid clearance."],
                "author": [
                    {"given": "Maria Del Carmen", "family": "Garcia"},
                    {"given": "John", "family": "Smith"},
                ],
                "container-title": ["Nature Neuroscience"],
                "published-print": {"date-parts": [[2025, 3, 14]]},
                "DOI": "10.1038/s41593-025-00001-1",
                "URL": "https://doi.org/10.1038/s41593-025-00001-1",
                "abstract": (
                    "<jats:p>We review <jats:bold>amyloid</jats:bold> "
                    "clearance pathways.</jats:p>"
                ),
            }
        },
    )
    assert paper.title == "Amyloid clearance"
    assert len(paper.authors) == 2
    assert paper.authors[0].first_name == "Maria Del Carmen"
    assert paper.authors[0].last_name == "Garcia"
    assert paper.authors[1].last_name == "Smith"
    assert paper.journal is not None
    assert paper.journal.name == "Nature Neuroscience"
    assert paper.year == 2025
    assert paper.doi == "10.1038/s41593-025-00001-1"
    assert paper.pmid is None
    assert "amyloid" in paper.abstract.lower()
    # The JATS tags should be stripped.
    assert "<jats:" not in paper.abstract


def test_crossref_payload_strips_trailing_period_from_title() -> None:
    """CrossRef titles often end with a period. We strip it so
    citations don't double up."""
    from app.infrastructure.pubmed.identifier_resolver import (
        _crossref_to_paper,
    )

    paper = _crossref_to_paper(
        "10.1038/dot",
        {"message": {"title": ["A study of X."]}},
    )
    assert paper.title == "A study of X"


def test_crossref_payload_year_from_multiple_date_fields() -> None:
    """If ``published-print`` is missing, fall back to
    ``published-online`` then ``created``."""
    from app.infrastructure.pubmed.identifier_resolver import (
        _crossref_to_paper,
    )

    paper = _crossref_to_paper(
        "10.1038/online-only",
        {
            "message": {
                "title": ["An online-only paper."],
                "published-online": {"date-parts": [[2024]]},
            }
        },
    )
    assert paper.year == 2024
