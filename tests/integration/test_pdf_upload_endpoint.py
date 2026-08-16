"""
test_pdf_upload_endpoint.py

Integration tests for ``POST /workspaces/{id}/papers/from-pdf``.

Two paths are exercised:

1. ``test_pdf_upload_with_resolvable_doi`` — the PDF contains a
   DOI that CrossRef has on file. The route resolves the DOI,
   the resolved paper is added.

2. ``test_pdf_upload_with_unresolvable_doi_falls_back_to_pdf_text``
   — the PDF contains a DOI that returns 404. The route must
   fall back to structured PDF text extraction and add the
   paper anyway (this is the user's regression: they uploaded
   a bioRxiv preprint whose DOI had ``doi:`` glued to the
   suffix and was rejected by CrossRef with a 404).

3. ``test_pdf_upload_with_no_doi_at_all_falls_back_to_pdf_text``
   — the PDF has no DOI but has a recognisable title. The
   structured extractor builds a Paper and the route adds it.

4. ``test_pdf_upload_with_nothing_to_extract_returns_422`` —
   the PDF is blank or has only a title-less body. The route
   returns 422.
"""

from __future__ import annotations

import io
from typing import Any, Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures: monkeypatch the resolver so we don't hit CrossRef for real.
# ---------------------------------------------------------------------------


def _pdf_with_text(text: str) -> bytes:
    """Hand-rolled one-page PDF, same shape as test_pdf_extractor.py."""
    text = text.replace("(", r"\(").replace(")", r"\)")
    stream = b"BT /F1 12 Tf 50 700 Td (" + text.encode() + b") Tj ET"
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
        b"0000000009 00000 n \n0000000058 00000 n \n"
        b"0000000115 00000 n \n0000000218 00000 n \n"
        b"0000000310 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n374\n%%EOF\n"
    )


class _StubPaper:
    """Minimal Paper stub for the resolver."""

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class _StubSuccess:
    """Resolver success result."""

    is_success = True
    failure = None

    def __init__(self, identifier: str, paper: Any) -> None:
        self.identifier = identifier
        self.paper = type("Result", (), {"paper": paper})()


class _StubFailure:
    """Resolver failure result."""

    is_success = False
    paper = None

    def __init__(self, identifier: str, reason: str) -> None:
        self.failure = type("Failure", (), {"identifier": identifier, "reason": reason})()


class _StubResolver:
    """Resolver that yields whatever the test wants."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results

    def resolve_many(self, identifiers: list[str]) -> list[Any]:
        return self._results


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """Override the resolver and orchestrator dependencies so the
    route runs against our stubs."""
    from app.api.routes import workspace_actions
    from app.config import container
    import main as main_module

    # Build a fake orchestrator that captures the bulk add.
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add_papers_bulk(
            self, workspace_id: UUID, papers: list[Any]
        ) -> Any:
            print(f"[TEST] FakeOrchestrator.add_papers_bulk called! papers={[p.title for p in papers]}")
            self.added.extend(papers)
            # Return a fake workspace with a known state.
            from app.domain.entities.research_session import (
                ResearchSession,
            )
            from app.domain.entities.research_question import (
                ResearchQuestion,
            )
            from app.core.enums.workspace_state import WorkspaceState

            session = ResearchSession(
                question=ResearchQuestion(
                    question="test question"
                ),
                state=WorkspaceState.PAPERS_RETRIEVED,
            )
            session.add_papers(papers)
            session.id = workspace_id
            return session

    # Fake assistant so the POST /workspaces endpoint doesn't
    # hit the real DB.
    class FakeAssistant:
        def create_workspace(self, question: str) -> Any:
            from app.domain.entities.research_session import (
                ResearchSession,
            )
            from app.domain.entities.research_question import (
                ResearchQuestion,
            )
            from app.core.enums.workspace_state import WorkspaceState

            session = ResearchSession(
                question=ResearchQuestion(question=question),
                state=WorkspaceState.CREATED,
            )
            return session

    # Resolver defaults to "no identifiers found" — tests
    # override by calling ``monkeypatch.setattr`` on the
    # container's resolver provider.
    fake_orchestrator = FakeOrchestrator()
    fake_assistant = FakeAssistant()
    overrides = {
        container.get_workspace_orchestrator: lambda: fake_orchestrator,
        container.get_research_assistant: lambda: fake_assistant,
        workspace_actions.get_workspace_orchestrator: lambda: fake_orchestrator,
    }
    for dep, override in overrides.items():
        main_module.app.dependency_overrides[dep] = override

    print(f"[TEST] dependency_overrides keys: {list(main_module.app.dependency_overrides.keys())}")
    print(f"[TEST] get_workspace_orchestrator in overrides: {container.get_workspace_orchestrator in main_module.app.dependency_overrides}")

    with TestClient(main_module.app) as c:
        yield c


def _set_resolver(monkeypatch: pytest.MonkeyPatch, results: list[Any]) -> None:
    """Replace the resolver for the next request."""
    from app.api.routes import workspace_actions
    from app.config import container
    import main as main_module

    resolver = _StubResolver(results)
    monkeypatch.setattr(container, "get_identifier_resolver", lambda: resolver)
    monkeypatch.setattr(workspace_actions, "get_identifier_resolver", lambda: resolver)
    main_module.app.dependency_overrides[
        container.get_identifier_resolver
    ] = lambda: resolver
    main_module.app.dependency_overrides[
        workspace_actions.get_identifier_resolver
    ] = lambda: resolver


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pdf_upload_with_resolvable_doi(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF with a DOI that CrossRef has returns the resolved
    paper — full metadata is preserved.
    """
    from app.domain.entities.author import Author
    from app.domain.entities.journal import Journal
    from app.domain.entities.paper import Paper

    pdf_text = (
        "Alzheimer's Disease: a Review\n"
        "Jane Doe\n"
        "Department of Neurology\n"
        "Abstract\n"
        "Lorem ipsum.\n"
        "DOI: 10.1038/nature12373\n"
    )
    pdf_bytes = _pdf_with_text(pdf_text)
    resolved = Paper(
        title="Alzheimer's Disease: a Review",
        authors=[Author(first_name="Jane", last_name="Doe", affiliation=None)],
        journal=Journal(name="Nature", issn=None, publisher=None),
        year=2024,
        abstract="Full abstract from CrossRef.",
        doi="10.1038/nature12373",
        pmid=None,
        keywords=["Alzheimer"],
        url="https://doi.org/10.1038/nature12373",
    )
    _set_resolver(
        monkeypatch,
        [_StubSuccess(identifier="10.1038/nature12373", paper=resolved)],
    )

    # Create a workspace.
    workspace_id = _create_workspace(client)
    response = client.post(
        f"/workspaces/{workspace_id}/papers/from-pdf",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "PAPERS_RETRIEVED"
    papers = body["papers"]
    assert len(papers) == 1
    assert papers[0]["title"] == "Alzheimer's Disease: a Review"
    assert papers[0]["doi"] == "10.1038/nature12373"
    # Resolved (not fallback) — journal and abstract are full.
    assert papers[0]["abstract"] == "Full abstract from CrossRef."


def test_pdf_upload_with_unresolvable_doi_falls_back_to_pdf_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's regression: bioRxiv preprints render the DOI
    with ``doi:`` glued to the suffix and CrossRef returns 404.

    The PDF still has the title, authors, year, abstract, and
    keywords — the structured extractor recovers them and the
    paper is added to the workspace.
    """
    pdf_text = (
        "Alzheimer's Disease Brain Phenotypes are Age-dependent\n"
        "Fermin Travi1, Anushree Mehta2\n"
        "Department of X\n"
        "Keywords: Alzheimer's, deep learning\n"
        "Abstract\n"
        "A widespread view of neurodegenerative disorders.\n"
        "1 Introduction\n"
        "Body text.\n"
        "bioRxiv preprint doi: https://doi.org/10.64898/2026.03.31.715296doi: "
        "this version posted April 2, 2026.\n"
    )
    pdf_bytes = _pdf_with_text(pdf_text)
    _set_resolver(
        monkeypatch,
        [_StubFailure(
            identifier="10.64898/2026.03.31.715296doi:",
            reason="CrossRef HTTP 404",
        )],
    )

    workspace_id = _create_workspace(client)
    response = client.post(
        f"/workspaces/{workspace_id}/papers/from-pdf",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "PAPERS_RETRIEVED"
    papers = body["papers"]
    assert len(papers) == 1
    # The structured extractor picked up the title.
    assert "Alzheimer" in papers[0]["title"]
    assert papers[0]["year"] == 2026
    # The cleaned DOI is in the response (no trailing ``doi:``).
    assert papers[0]["doi"] == "10.64898/2026.03.31.715296"


def test_pdf_upload_with_no_doi_falls_back_to_pdf_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF with no DOI at all (but a recognisable title) is
    added from the PDF text. The structured extractor fills
    in what it can; missing fields are empty / null.
    """
    pdf_text = (
        "Some Title Here\n"
        "Jane Doe\n"
        "Department of X\n"
        "Abstract\n"
        "Lorem ipsum.\n"
    )
    pdf_bytes = _pdf_with_text(pdf_text)
    _set_resolver(monkeypatch, [])

    workspace_id = _create_workspace(client)
    response = client.post(
        f"/workspaces/{workspace_id}/papers/from-pdf",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    papers = body["papers"]
    assert len(papers) == 1
    assert "Some Title Here" in papers[0]["title"]


def test_pdf_upload_with_nothing_to_extract_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank PDF returns 422 (no DOI AND no title to
    extract)."""
    pdf_bytes = _pdf_with_text("   ")  # whitespace-only
    _set_resolver(monkeypatch, [])

    workspace_id = _create_workspace(client)
    response = client.post(
        f"/workspaces/{workspace_id}/papers/from-pdf",
        files={"file": ("blank.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 422
    body = response.json()
    # The ``no_identifiers_found`` error is the canonical
    # response for "PDF had nothing".
    assert body["detail"]["error"] in (
        "no_identifiers_found",
        "all_identifiers_failed",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_workspace(client: TestClient) -> str:
    """Create a workspace through the API.

    The fake assistant doesn't set ``session.id`` (UUIDs are
    normally generated by the real DB), so we fabricate one
    here. The route returns whatever id it generated, which is
    what the orchestrator will see.
    """
    import uuid

    response = client.post(
        "/workspaces",
        json={"question": "test question"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body.get("workspace_id") or str(uuid.uuid4())