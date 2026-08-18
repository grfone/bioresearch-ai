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

        def get(self, url, *args, **kwargs):
            # Accept any combination of kwargs (``headers=``,
            # ``params=``, ``timeout=``, ...) so the same
            # fake works for both the CrossRef call and the
            # new OpenAlex fallback.
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


# ---------------------------------------------------------------------------
# OpenAlex fallback tests
# ---------------------------------------------------------------------------


def test_openalex_fallback_fills_abstract_when_crossref_is_empty(monkeypatch):
    """When CrossRef returns a paper with no abstract, the
    resolver falls back to OpenAlex. The book-chapter case
    the user reported (10.1007/978-3-031-64636-2_17) is
    exactly this pattern -- CrossRef has thin metadata for
    non-journal types.
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(pubmed_provider=provider)

    # CrossRef returns a paper with no abstract.
    crossref_payload = {
        "message": {
            "title": ["Training Deep Learning Neural Networks"],
            "author": [{"given": "Anna", "family": "Jensen"}],
            "published-print": {"date-parts": [[2024]]},
            "abstract": "",
        }
    }
    # OpenAlex returns an inverted-index abstract.
    openalex_payload = {
        "abstract_inverted_index": {
            "We": [1, 9],
            "describe": [2],
            "deep": [3],
            "learning": [4],
            "models": [5],
            "for": [6],
            "predicting": [7],
            "CCS": [8],
        }
    }

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "crossref" in url:
            resp.json.return_value = crossref_payload
        elif "openalex" in url:
            resp.json.return_value = openalex_payload
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    result = resolver.resolve_one("10.1007/978-3-031-64636-2_17")

    assert result.failure is None
    assert result.paper is not None
    # The title came from CrossRef.
    assert result.paper.paper.title == "Training Deep Learning Neural Networks"
    # The abstract came from OpenAlex (reconstructed).
    assert "deep" in result.paper.paper.abstract
    assert "learning" in result.paper.paper.abstract


def test_openalex_fallback_skipped_when_crossref_has_abstract(monkeypatch):
    """If CrossRef already has an abstract, the resolver
    does NOT call OpenAlex. The fallback is a no-op when
    the primary source is good.
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(pubmed_provider=provider)

    crossref_payload = {
        "message": {
            "title": ["A well-abstracted paper."],
            "author": [],
            "published-print": {"date-parts": [[2024]]},
            "abstract": "<jats:p>This is a real abstract.</jats:p>",
        }
    }

    crossref_calls = [0]
    openalex_calls = [0]

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            crossref_calls[0] += 1
            resp.status_code = 200
            resp.json.return_value = crossref_payload
        elif "openalex" in url:
            openalex_calls[0] += 1
            resp.status_code = 200
            resp.json.return_value = {"abstract_inverted_index": {}}
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    result = resolver.resolve_one("10.1234/with-abstract")
    assert result.paper is not None
    assert "real abstract" in result.paper.paper.abstract
    assert crossref_calls[0] == 1
    assert openalex_calls[0] == 0


def test_openalex_fallback_returns_none_on_network_error(monkeypatch):
    """If OpenAlex fails (network error, 404, malformed JSON),
    the fallback returns None and the resolver keeps the
    CrossRef paper (with empty abstract).
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(pubmed_provider=provider)

    crossref_payload = {
        "message": {
            "title": ["Thin record."],
            "author": [],
            "abstract": "",
        }
    }

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            resp.status_code = 200
            resp.json.return_value = crossref_payload
        elif "openalex" in url:
            # 503 -- OpenAlex is unreachable. The fallback
            # swallows this; the CrossRef paper (with empty
            # abstract) is returned.
            resp.status_code = 503
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    result = resolver.resolve_one("10.1234/thin")
    assert result.failure is None
    assert result.paper is not None
    # Abstract stays empty -- OpenAlex fallback failed silently.
    assert result.paper.paper.abstract == ""


def test_openalex_fallback_handles_empty_inverted_index(monkeypatch):
    """OpenAlex returns the record but with no abstract. The
    resolver keeps the CrossRef paper as-is (no error).
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(pubmed_provider=provider)

    crossref_payload = {
        "message": {
            "title": ["Thin record."],
            "author": [],
            "abstract": "",
        }
    }
    openalex_payload = {
        # No abstract_inverted_index at all.
        "id": "https://openalex.org/W123",
    }

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            resp.status_code = 200
            resp.json.return_value = crossref_payload
        elif "openalex" in url:
            resp.status_code = 200
            resp.json.return_value = openalex_payload
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    result = resolver.resolve_one("10.1234/no-abstract")
    assert result.failure is None
    assert result.paper is not None
    assert result.paper.paper.abstract == ""


def test_openalex_fallback_reconstructs_inverted_index():
    """The inverted-index reconstruction joins tokens in
    their original order. Tested with a tiny example to
    make the math explicit.
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(pubmed_provider=provider)
    abstract = resolver._fetch_openalex_abstract.__wrapped__ if hasattr(
        resolver._fetch_openalex_abstract, "__wrapped__"
    ) else resolver._fetch_openalex_abstract

    # Inject a fake response by calling the method directly
    # with a payload via monkeypatched httpx.
    from unittest.mock import MagicMock, patch

    fake_data = {
        "abstract_inverted_index": {
            "Hello": [1, 5],
            "world": [2, 7],
            "from": [3],
            "OpenAlex": [4, 6],
        }
    }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = fake_data
            return resp

    with patch(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    ):
        result = resolver._fetch_openalex_abstract("10.1234/x")

    # Reconstructed: each position 1-7 is filled with the
    # word at that position in the inverted index. Position
    # 4 is "OpenAlex", position 5 is "Hello" (Hello's second
    # occurrence), position 6 is "OpenAlex" (its second),
    # position 7 is "world" (its second).
    assert result == "Hello world from OpenAlex Hello OpenAlex world"


# ---------------------------------------------------------------------------
# AbstractEnricher fallback (HTML meta-tag scraping)
# ---------------------------------------------------------------------------


def test_abstract_enricher_fills_abstract_when_crossref_and_openalex_are_empty(
    monkeypatch,
):
    """When both CrossRef and OpenAlex return no abstract,
    the resolver falls back to the HTML enricher. The
    enricher is injected via the constructor.
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.abstract_enricher import (
        AbstractEnricher,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "crossref" in url:
            # CrossRef returns a paper with no abstract.
            resp.json.return_value = {
                "message": {
                    "title": ["Thin record."],
                    "author": [],
                    "abstract": "",
                }
            }
        elif "openalex" in url:
            # OpenAlex also has no abstract.
            resp.json.return_value = {"abstract_inverted_index": None}
        else:
            resp.json.return_value = None
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    # The HTML enricher itself is mocked to return an
    # abstract. We don't actually run the HTML scraping
    # here -- that's covered by the AbstractEnricher unit
    # tests. This test only verifies the resolver's
    # plumbing of the enricher.
    class FakeEnricher:
        def __init__(self, abstract):
            self._abstract = abstract

        def fetch(self, doi):
            return self._abstract

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    enricher = FakeEnricher(
        "This abstract was scraped from the publisher's HTML page."
    )
    resolver = IdentifierResolver(
        pubmed_provider=provider,
        abstract_enricher=enricher,
    )

    result = resolver.resolve_one("10.1234/html-fallback")
    assert result.failure is None
    assert result.paper is not None
    assert (
        "This abstract was scraped"
        in result.paper.paper.abstract
    )


def test_abstract_enricher_skipped_when_crossref_has_abstract(
    monkeypatch,
):
    """If CrossRef already has an abstract, the enricher is
    NOT called -- the fallback chain stops at the first
    source that has data.
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    enricher_calls = []

    class TrackingEnricher:
        def fetch(self, doi):
            enricher_calls.append(doi)
            return "SHOULD NOT BE USED"

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            resp.status_code = 200
            resp.json.return_value = {
                "message": {
                    "title": ["Has abstract."],
                    "author": [],
                    "abstract": "<jats:p>Real abstract from CrossRef.</jats:p>",
                }
            }
        elif "openalex" in url:
            resp.status_code = 200
            resp.json.return_value = {"abstract_inverted_index": None}
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(
        pubmed_provider=provider,
        abstract_enricher=TrackingEnricher(),
    )

    result = resolver.resolve_one("10.1038/has-abstract")
    assert result.failure is None
    assert "Real abstract from CrossRef" in result.paper.paper.abstract
    # Enricher was never called because CrossRef already
    # had the abstract.
    assert enricher_calls == []


def test_abstract_enricher_returns_none_when_html_has_no_abstract(
    monkeypatch,
):
    """The enricher returning None (e.g. Datadome block, no
    meta tag found) is handled silently -- the paper just
    has no abstract."""
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            resp.status_code = 200
            resp.json.return_value = {
                "message": {
                    "title": ["Thin record."],
                    "author": [],
                    "abstract": "",
                }
            }
        elif "openalex" in url:
            resp.status_code = 200
            resp.json.return_value = {"abstract_inverted_index": None}
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    class ReturningNoneEnricher:
        def fetch(self, doi):
            return None

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(
        pubmed_provider=provider,
        abstract_enricher=ReturningNoneEnricher(),
    )

    result = resolver.resolve_one("10.1007/978-3-031-64636-2_17")
    assert result.failure is None
    assert result.paper is not None
    # Abstract stays empty when enricher returns None.
    assert result.paper.paper.abstract == ""


def test_abstract_enricher_is_optional(monkeypatch):
    """The resolver works fine without an enricher -- it's
    backward-compatible. Pre-existing callers that don't
    pass an enricher still get the CrossRef + OpenAlex
    fallback chain."""
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from unittest.mock import MagicMock

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            resp.status_code = 200
            resp.json.return_value = {
                "message": {
                    "title": ["Thin record."],
                    "author": [],
                    "abstract": "",
                }
            }
        elif "openalex" in url:
            resp.status_code = 200
            resp.json.return_value = {"abstract_inverted_index": None}
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    # No enricher passed.
    resolver = IdentifierResolver(pubmed_provider=provider)

    result = resolver.resolve_one("10.1234/no-enricher")
    assert result.failure is None
    assert result.paper is not None
    # The resolver still works; the abstract is just empty.
    assert result.paper.paper.abstract == ""
    # Internal state: enricher is None.
    assert resolver._abstract_enricher is None


# ---------------------------------------------------------------------------
# LLM extractor fallback integration
# ---------------------------------------------------------------------------


def test_llm_extractor_fires_only_when_deterministic_extraction_fails(
    monkeypatch,
):
    """The LLM extractor is the third fallback in the chain:
    CrossRef -> OpenAlex -> HTML meta-tag scrape -> LLM.
    The LLM must only fire when the deterministic path
    produced nothing usable (None or short).
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.llm_extractor import (
        LLMExtractor,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from app.domain.interfaces.llm_provider import LLMProvider
    from app.domain.models.llm_response import LLMResponse
    from app.domain.models.prompt import Prompt
    from unittest.mock import MagicMock

    class TrackingLLMProvider(LLMProvider):
        """Records whether the LLM was called."""

        def __init__(self, content: str) -> None:
            self._content = content
            self.calls = 0

        def generate(self, prompt: Prompt) -> LLMResponse:
            self.calls += 1
            return LLMResponse(
                content=self._content,
                model="fake",
                prompt_tokens=100,
                completion_tokens=len(self._content),
                total_tokens=100 + len(self._content),
                finish_reason="stop",
            )

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            # CrossRef returns empty abstract.
            resp.status_code = 200
            resp.json.return_value = {
                "message": {
                    "title": ["Thin record."],
                    "author": [],
                    "abstract": "",
                }
            }
        elif "openalex" in url:
            # OpenAlex also empty.
            resp.status_code = 200
            resp.json.return_value = {"abstract_inverted_index": None}
        elif "doi.org" in url:
            # The HTML page is reachable but has NO abstract
            # meta tag (the LLM will see the page text and
            # return NONE).
            resp.status_code = 200
            resp.text = (
                "<html><body>"
                "<h1>Table of Contents</h1>"
                "<ul><li>Chapter 1</li></ul>"
                "</body></html>"
            )
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    llm = TrackingLLMProvider("NONE")  # LLM correctly says NONE
    llm_extractor = LLMExtractor(llm_provider=llm)

    # The LLMExtractor lives INSIDE the AbstractEnricher
    # (the latter has the HTTP client + LRU cache; the
    # former is the optional LLM fallback). The resolver
    # only knows about the outer AbstractEnricher.
    from app.infrastructure.pubmed.abstract_enricher import (
        AbstractEnricher,
    )
    enricher = AbstractEnricher(
        client=FakeClient(),  # type: ignore[abstract]
        llm_extractor=llm_extractor,
    )

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(
        pubmed_provider=provider,
        abstract_enricher=enricher,
    )

    result = resolver.resolve_one("10.1234/thin")
    # The paper was resolved successfully but with no
    # abstract -- the LLM correctly refused to invent one.
    assert result.failure is None
    assert result.paper is not None
    assert result.paper.paper.abstract == ""
    # The LLM was called because the deterministic path
    # returned nothing.
    assert llm.calls == 1


def test_llm_extractor_NOT_called_when_deterministic_succeeds(monkeypatch):
    """If the deterministic regex path already produced a
    usable abstract, the LLM is NOT called -- we don't
    want to waste tokens on cases the regex already
    handled.
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.llm_extractor import (
        LLMExtractor,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from app.domain.interfaces.llm_provider import LLMProvider
    from app.domain.models.llm_response import LLMResponse
    from app.domain.models.prompt import Prompt
    from unittest.mock import MagicMock

    class TrackingLLMProvider(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt: Prompt) -> LLMResponse:
            self.calls += 1
            return LLMResponse(
                content="SHOULD NOT BE USED",
                model="fake",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                finish_reason="stop",
            )

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            # CrossRef HAS an abstract -- deterministic path
            # will succeed; LLM should NOT be called.
            resp.status_code = 200
            resp.json.return_value = {
                "message": {
                    "title": ["Has abstract."],
                    "author": [],
                    "abstract": (
                        "<jats:p>This is a real abstract from "
                        "CrossRef, returned verbatim by the LLM "
                        "if it were called.</jats:p>"
                    ),
                }
            }
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    llm = TrackingLLMProvider()
    llm_extractor = LLMExtractor(llm_provider=llm)
    from app.infrastructure.pubmed.abstract_enricher import (
        AbstractEnricher,
    )
    enricher = AbstractEnricher(
        client=FakeClient(),  # type: ignore[abstract]
        llm_extractor=llm_extractor,
    )

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(
        pubmed_provider=provider,
        abstract_enricher=enricher,
    )

    result = resolver.resolve_one("10.1234/has-abstract")
    assert "real abstract from CrossRef" in result.paper.paper.abstract
    # LLM was NEVER called because CrossRef already had it.
    assert llm.calls == 0


def test_llm_extractor_NOT_called_when_html_unreachable(monkeypatch):
    """The LLM must not be called when we couldn't even
    fetch the HTML page (e.g. anti-bot block). The LLM
    has no web access of its own -- it only sees what
    we put in the prompt -- so calling it with no
    page text would be useless.
    """
    from app.infrastructure.pubmed.identifier_resolver import (
        IdentifierResolver,
    )
    from app.infrastructure.pubmed.llm_extractor import (
        LLMExtractor,
    )
    from app.infrastructure.pubmed.provider import PubMedProvider
    from app.infrastructure.pubmed.client import PubMedClient
    from app.domain.interfaces.llm_provider import LLMProvider
    from app.domain.models.llm_response import LLMResponse
    from app.domain.models.prompt import Prompt
    from unittest.mock import MagicMock

    class TrackingLLMProvider(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt: Prompt) -> LLMResponse:
            self.calls += 1
            return LLMResponse(
                content="SHOULD NOT BE CALLED",
                model="fake",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                finish_reason="stop",
            )

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if "crossref" in url:
            resp.status_code = 200
            resp.json.return_value = {
                "message": {
                    "title": ["Thin record."],
                    "author": [],
                    "abstract": "",
                }
            }
        elif "doi.org" in url:
            # 503 -- the page is unreachable.
            resp.status_code = 503
            resp.text = ""
        else:
            resp.status_code = 404
        return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, *args, **kwargs):
            return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(
        "app.infrastructure.pubmed.identifier_resolver.httpx.Client",
        FakeClient,
    )

    llm = TrackingLLMProvider()
    llm_extractor = LLMExtractor(llm_provider=llm)
    from app.infrastructure.pubmed.abstract_enricher import (
        AbstractEnricher,
    )
    enricher = AbstractEnricher(
        client=FakeClient(),  # type: ignore[abstract]
        llm_extractor=llm_extractor,
    )

    provider = PubMedProvider(
        client=PubMedClient(email="test@example.com", api_key="")
    )
    resolver = IdentifierResolver(
        pubmed_provider=provider,
        abstract_enricher=enricher,
    )

    result = resolver.resolve_one("10.1234/blocked")
    assert result.failure is None
    assert result.paper.paper.abstract == ""
    # LLM was NOT called because we couldn't fetch the
    # HTML page (503). No point calling the LLM with no
    # content to extract from.
    assert llm.calls == 0
