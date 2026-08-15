"""
Tests for the manual paper upload and removal routes.

A previous version of the FSM had the ``ADD_PAPER`` and
``REMOVE_PAPER`` actions in the state machine but never exposed
them over HTTP. The frontend had no way to upload a paper that
wasn't in PubMed, so workspaces at ``CREATED`` state were stuck
with no usable inputs unless the user accepted the SEARCH action.

These tests guard the new endpoints at
``POST /workspaces/{id}/papers`` and
``DELETE /workspaces/{id}/papers/{paper_id}`` so the regression
can't return.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTES_PY = REPO_ROOT / "app" / "api" / "routes" / "workspace_actions.py"
SCHEMA_PY = REPO_ROOT / "app" / "api" / "schemas" / "paper_request.py"


# ---------------------------------------------------------------------------
# Source-level: the routes must exist
# ---------------------------------------------------------------------------


def test_add_paper_route_registered() -> None:
    """``workspace_actions.py`` must declare a ``POST`` route at
    ``/{workspace_id}/papers``."""
    text = ROUTES_PY.read_text()
    assert "@router.post(" in text and "/{workspace_id}/papers" in text, (
        "POST /workspaces/{id}/papers must be registered for "
        "manual paper upload"
    )
    assert "def add_paper" in text, (
        "the add_paper route handler must exist"
    )


def test_remove_paper_route_registered() -> None:
    """``workspace_actions.py`` must declare a ``DELETE`` route at
    ``/{workspace_id}/papers/{paper_id}``."""
    text = ROUTES_PY.read_text()
    assert "@router.delete(" in text, (
        "a DELETE route must be registered"
    )
    assert "/{workspace_id}/papers/{paper_id}" in text, (
        "DELETE /workspaces/{id}/papers/{paper_id} must be "
        "registered for paper removal"
    )
    assert "def remove_paper" in text, (
        "the remove_paper route handler must exist"
    )


def test_paper_request_schema_exists() -> None:
    """The ``PaperRequest`` schema must exist so the frontend can
    submit papers via HTTP."""
    text = SCHEMA_PY.read_text()
    assert "class PaperRequest(BaseModel)" in text, (
        "PaperRequest schema must exist for manual uploads"
    )
    # Required fields.
    assert "title:" in text, "PaperRequest must require a title"
    # Optional fields.
    for field in ["authors:", "journal:", "year:", "abstract:", "doi:", "pmid:", "keywords:", "url:"]:
        assert field in text, f"PaperRequest must expose optional field {field!r}"


# ---------------------------------------------------------------------------
# Schema-level: the PaperRequest validates correctly
# ---------------------------------------------------------------------------


def test_paper_request_accepts_minimal_payload() -> None:
    """A paper with just a title must be valid — the user can
    flesh out the rest later."""
    sys.path.insert(0, str(REPO_ROOT))
    from app.api.schemas.paper_request import PaperRequest

    paper = PaperRequest(title="A 2025 update on Alzheimer's biomarkers.")
    assert paper.title == "A 2025 update on Alzheimer's biomarkers."
    assert paper.authors == []
    assert paper.abstract == ""
    assert paper.doi is None
    assert paper.pmid is None


def test_paper_request_rejects_empty_title() -> None:
    """A paper without a title must fail validation. The title is
    the minimum required field; rejecting empty titles prevents
    junk papers from polluting the workspace."""
    from pydantic import ValidationError

    sys.path.insert(0, str(REPO_ROOT))
    from app.api.schemas.paper_request import PaperRequest

    with pytest.raises(ValidationError) as exc_info:
        PaperRequest(title="")
    assert "title" in str(exc_info.value).lower()


def test_paper_request_accepts_full_payload() -> None:
    """A paper with every field set must validate cleanly."""
    sys.path.insert(0, str(REPO_ROOT))
    from app.api.schemas.paper_request import (
        AuthorRequest,
        JournalRequest,
        PaperRequest,
    )

    paper = PaperRequest(
        title="Amyloid-β clearance mechanisms.",
        authors=[
            AuthorRequest(
                full_name="Maria Garcia",
                given_name="Maria",
                family_name="Garcia",
            ),
        ],
        journal=JournalRequest(
            name="Nature Neuroscience",
            issn="1097-6256",
            publisher="Nature Publishing Group",
        ),
        year=2025,
        abstract="We review the major pathways involved in Aβ clearance...",
        doi="10.1038/s41593-025-00001-1",
        pmid="40000001",
        keywords=["Alzheimer", "amyloid", "clearance"],
        url="https://example.org/papers/123",
    )
    assert paper.title == "Amyloid-β clearance mechanisms."
    assert len(paper.authors) == 1
    assert paper.authors[0].full_name == "Maria Garcia"
    assert paper.journal is not None
    assert paper.journal.name == "Nature Neuroscience"
    assert paper.year == 2025
    assert paper.pmid == "40000001"


# ---------------------------------------------------------------------------
# Helper function: _paper_request_to_domain
# ---------------------------------------------------------------------------


def test_paper_request_to_domain_converts_full_name_to_first_and_last() -> None:
    """``_paper_request_to_domain`` must split ``full_name`` into
    ``first_name`` / ``last_name`` so the domain ``Author`` is
    constructed correctly. A previous version tried to pass
    ``Author(full_name=...)`` which raised TypeError because the
    domain entity is keyed on first_name / last_name (full_name is
    a derived property).
    """
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.api.routes.workspace_actions import _paper_request_to_domain
    from app.api.schemas.paper_request import (
        AuthorRequest,
        PaperRequest,
    )

    paper = PaperRequest(
        title="A test paper.",
        authors=[
            AuthorRequest(full_name="Maria Del Carmen Garcia"),
        ],
    )
    domain = _paper_request_to_domain(paper)
    assert len(domain.authors) == 1
    author = domain.authors[0]
    # The split happens on the last whitespace boundary so
    # "Maria Del Carmen Garcia" becomes first="Maria Del Carmen",
    # last="Garcia".
    assert author.last_name == "Garcia", (
        f"expected last_name='Garcia', got {author.last_name!r}"
    )
    assert author.first_name.startswith("Maria"), (
        f"expected first_name to start with 'Maria', got "
        f"{author.first_name!r}"
    )


def test_paper_request_to_domain_uses_explicit_names_when_provided() -> None:
    """When the user supplies explicit given_name and family_name,
    those win over full_name."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.api.routes.workspace_actions import _paper_request_to_domain
    from app.api.schemas.paper_request import (
        AuthorRequest,
        PaperRequest,
    )

    paper = PaperRequest(
        title="A test paper.",
        authors=[
            AuthorRequest(
                full_name="Ignored Full Name",
                given_name="Jane",
                family_name="Doe",
            ),
        ],
    )
    domain = _paper_request_to_domain(paper)
    author = domain.authors[0]
    assert author.first_name == "Jane"
    assert author.last_name == "Doe"


def test_paper_request_to_domain_handles_missing_optional_fields() -> None:
    """When ``full_name`` is provided but ``given_name`` and
    ``family_name`` are empty, the helper must split on the last
    whitespace boundary and produce a non-empty first/last name.

    The schema rejects truly empty strings (min_length=1), so the
    helper can safely assume the supplied ``full_name`` has at
    least one non-whitespace character. Whitespace-only is a
    separate edge case that's caught at the schema layer.
    """
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.api.routes.workspace_actions import _paper_request_to_domain
    from app.api.schemas.paper_request import (
        AuthorRequest,
        PaperRequest,
    )

    paper = PaperRequest(
        title="A test paper.",
        authors=[AuthorRequest(full_name="SingleName")],  # no spaces
    )
    domain = _paper_request_to_domain(paper)
    assert len(domain.authors) == 1
    author = domain.authors[0]
    # "SingleName" rsplit at the last space returns just one
    # element, so we fall back to last_name="".
    assert author.first_name == "SingleName"
    assert author.last_name == ""
