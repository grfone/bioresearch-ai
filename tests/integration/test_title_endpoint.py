"""
Integration tests for the ``POST /workspaces/{id}/papers/from-title``
endpoint.

These tests stub the orchestrator so the HTTP layer is fully
validated without PubMed or persistence. They exercise:

- The endpoint is reachable and registered.
- A title-only request adds a paper and returns 200 with the
  updated workspace.
- An optional ``first_author`` / ``journal`` / ``year`` is
  passed through to the orchestrator.
- An empty / whitespace-only title returns 422 (Pydantic
  validator on ``FindByTitleRequest``).
- An unknown workspace id returns 404 from the underlying
  lookup. (The orchestrator's ``_add_papers_bulk`` raises
  ``ValueError`` from the in-memory repo; the route returns 500
  here because the endpoint doesn't translate that, which is
  consistent with how the bulk endpoint behaves.)
- An FSM-illegal state (e.g. transient state) returns 409 with
  the legal-alternatives body — same contract as
  ``POST /papers/bulk``.
- An empty PubMed result from the orchestrator returns 422 with
  the ``title_no_confident_match`` error body.

The fixture pattern mirrors ``tests/integration/test_api_fsm.py``:
the same ``StubOrchestrator`` / ``StubAssistant`` pair is used,
extended with the new method.
"""

from __future__ import annotations

from typing import Any, Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared in-memory state
# ---------------------------------------------------------------------------


def _make_state() -> tuple[Any, Any, dict[UUID, Any]]:
    """Build a fresh in-memory workspace + stub orchestrator +
    stub assistant that all share one state dict.
    """
    from app.core.enums.workspace_state import (
        WorkspaceAction,
        WorkspaceState,
    )
    from app.domain.entities.paper import Paper
    from app.domain.entities.research_question import ResearchQuestion
    from app.domain.entities.research_session import ResearchSession

    # Two workspaces: one in CREATED (where the title-flow is
    # most likely to be exercised) and one in PAPERS_RETRIEVED
    # (so we can verify the route doesn't accidentally regress
    # later states).
    fresh = ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?"),
        state=WorkspaceState.CREATED,
    )
    populated = ResearchSession(
        question=ResearchQuestion(question="CRISPR review"),
        state=WorkspaceState.PAPERS_RETRIEVED,
    )
    paper = Paper(title="Pre-existing.", pmid="000")
    populated.add_papers([paper])
    workspaces: dict[UUID, ResearchSession] = {
        fresh.id: fresh,
        populated.id: populated,
    }

    def _get(wid: UUID) -> ResearchSession:
        if wid not in workspaces:
            raise ValueError(f"workspace {wid} not found")
        return workspaces[wid]

    class StubOrchestrator:
        """Stub that simulates title-driven paper recovery.

        The orchestrator's real implementation calls the
        literature searcher and scores the candidates. The
        stub instead routes by the title string so each test
        can predict which paper ends up in the workspace.
        """

        def __init__(self) -> None:
            # Track calls so tests can assert what the
            # orchestrator was actually asked to do.
            self.title_calls: list[dict[str, Any]] = []
            self.next_match: Paper | None = None
            self.next_return_none = False

        def get_workspace(self, wid: UUID) -> ResearchSession:
            return _get(wid)

        def allowed_actions(self, wid: UUID) -> list[Any]:
            return _get(wid).allowed_actions()

        def search(self, wid: UUID, query=None) -> ResearchSession:
            session = _get(wid)
            session.transition_to(WorkspaceAction.SEARCH)
            session.force_state(
                WorkspaceState.PAPERS_RETRIEVED,
                reason="stub-search",
            )
            return session

        def summarize(self, wid: UUID) -> ResearchSession:
            session = _get(wid)
            session.transition_to(WorkspaceAction.SUMMARIZE)
            session.force_state(
                WorkspaceState.SUMMARIZED,
                reason="stub-summarize",
            )
            return session

        def compare(self, wid: UUID) -> ResearchSession:
            session = _get(wid)
            session.transition_to(WorkspaceAction.COMPARE)
            session.force_state(
                WorkspaceState.COMPARED,
                reason="stub-compare",
            )
            return session

        def report(self, wid: UUID) -> ResearchSession:
            session = _get(wid)
            session.transition_to(WorkspaceAction.REPORT)
            session.force_state(
                WorkspaceState.REPORTED,
                reason="stub-report",
            )
            return session

        def complete(self, wid: UUID) -> ResearchSession:
            session = _get(wid)
            session.transition_to(WorkspaceAction.COMPLETE)
            return session

        def retry(self, wid: UUID) -> ResearchSession:
            session = _get(wid)
            session.transition_to(WorkspaceAction.RETRY)
            return session

        def add_paper(self, wid: UUID, paper: Paper) -> ResearchSession:
            session = _get(wid)
            if WorkspaceAction.ADD_PAPER not in session.allowed_actions():
                from app.core.exceptions import IllegalWorkspaceActionError
                raise IllegalWorkspaceActionError(
                    current_state=session.state.value,
                    action=WorkspaceAction.ADD_PAPER.value,
                    allowed=[a.value for a in session.allowed_actions()],
                )
            session.add_papers([paper])
            workspaces[wid] = session
            return session

        def add_papers_bulk(
            self, wid: UUID, papers: list[Paper]
        ) -> ResearchSession:
            session = _get(wid)
            if WorkspaceAction.ADD_PAPER not in session.allowed_actions():
                from app.core.exceptions import IllegalWorkspaceActionError
                raise IllegalWorkspaceActionError(
                    current_state=session.state.value,
                    action=WorkspaceAction.ADD_PAPER.value,
                    allowed=[a.value for a in session.allowed_actions()],
                )
            if papers:
                session.add_papers(papers)
            workspaces[wid] = session
            return session

        def resolve_and_add_by_title(
            self,
            workspace_id: UUID,
            title: str,
            first_author: str | None = None,
            journal: str | None = None,
            year: int | None = None,
        ) -> tuple[ResearchSession, Paper | None]:
            self.title_calls.append(
                {
                    "workspace_id": workspace_id,
                    "title": title,
                    "first_author": first_author,
                    "journal": journal,
                    "year": year,
                }
            )
            if self.next_return_none:
                return _get(workspace_id), None
            if self.next_match is None:
                # Default: synthesise a paper from the title so
                # tests get a deterministic pass-through.
                matched = Paper(
                    title=title,
                    authors=[],
                    journal=None,
                    year=year,
                    abstract="",
                    doi=None,
                    pmid="999",
                    keywords=[],
                    url=None,
                )
            else:
                matched = self.next_match
            session = self.add_papers_bulk(workspace_id, [matched])
            return session, matched

        def remove_paper(self, wid: UUID, paper_id: str) -> ResearchSession:
            session = _get(wid)
            if WorkspaceAction.REMOVE_PAPER not in session.allowed_actions():
                from app.core.exceptions import IllegalWorkspaceActionError
                raise IllegalWorkspaceActionError(
                    current_state=session.state.value,
                    action=WorkspaceAction.REMOVE_PAPER.value,
                    allowed=[a.value for a in session.allowed_actions()],
                )
            session.papers = [
                p for p in session.papers
                if p.pmid != paper_id and p.doi != paper_id
            ]
            workspaces[wid] = session
            return session

    class StubAssistant:
        def get_workspace(self, wid: UUID) -> ResearchSession:
            return _get(wid)

        def create_workspace(self, question: str) -> ResearchSession:
            from app.domain.entities.research_question import (
                ResearchQuestion,
            )
            new = ResearchSession(question=ResearchQuestion(question=question))
            workspaces[new.id] = new
            return new

        def update_workspace(self, session: ResearchSession) -> ResearchSession:
            workspaces[session.id] = session
            return session

    return StubOrchestrator(), StubAssistant(), workspaces


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    """Set env vars before any ``app.*`` import.

    The Settings classes load at module import time so the
    variables must be present in the environment before the
    FastAPI app is built. ``autouse`` guarantees this for every
    test in the module.
    """
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("PUBMED_EMAIL", "test@example.com")
    monkeypatch.setenv("PUBMED_EMAIL", "test@example.com")
    monkeypatch.setenv("PUBMED_API_KEY", "")
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./bioresearch.db")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[
    tuple[TestClient, Any, dict[UUID, Any]], None, None
]:
    """Build a FastAPI test client with the stub orchestrator.

    Returns a 3-tuple so tests can grab the client, inspect
    orchestrator calls, and peek at the in-memory workspace
    store.
    """
    orchestrator, assistant, workspaces = _make_state()

    import main as main_module
    from app.api.routes import (
        report as report_route,
        search as search_route,
        workspace_actions,
    )
    from app.config import container

    overrides = {
        container.get_workspace_orchestrator: lambda: orchestrator,
        container.get_research_assistant: lambda: assistant,
        workspace_actions.get_workspace_orchestrator: lambda: orchestrator,
        report_route.get_orchestrator: lambda: orchestrator,
        search_route.get_research_assistant: lambda: assistant,
    }
    for dep, override in overrides.items():
        main_module.app.dependency_overrides[dep] = override

    monkeypatch.setattr(
        container.Container, "build",
        classmethod(lambda cls: assistant),
    )

    # Clear overrides after the test so they don't leak
    # across modules that share ``main_module.app``.
    yield TestClient(main_module.app), orchestrator, workspaces

    main_module.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_endpoint_is_registered(client) -> None:
    """The route exists in the FastAPI app's URL table."""
    test_client, _, _ = client
    paths = {
        r.path for r in test_client.app.routes
        if hasattr(r, "path")
    }
    assert "/workspaces/{workspace_id}/papers/from-title" in paths


def test_title_only_request_adds_a_paper(client) -> None:
    test_client, orchestrator, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "CREATED"
    )

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={"title": "A paper title"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "PAPERS_RETRIEVED"
    pmids = [p["pmid"] for p in body["papers"]]
    assert "999" in pmids

    # The orchestrator was called with the title and no hints.
    assert len(orchestrator.title_calls) == 1
    call = orchestrator.title_calls[0]
    assert call["title"] == "A paper title"
    assert call["first_author"] is None
    assert call["journal"] is None
    assert call["year"] is None


def test_disambiguation_hints_pass_through(client) -> None:
    """The endpoint forwards author / journal / year to the
    orchestrator so the orchestrator's scoring can use them.
    """
    test_client, orchestrator, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "CREATED"
    )

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={
            "title": "amyloid cascade",
            "first_author": "Smith",
            "journal": "Nature",
            "year": 2025,
        },
    )

    assert response.status_code == 200, response.text
    assert len(orchestrator.title_calls) == 1
    call = orchestrator.title_calls[0]
    assert call["first_author"] == "Smith"
    assert call["journal"] == "Nature"
    assert call["year"] == 2025


def test_empty_title_returns_422(client) -> None:
    """Pydantic enforces ``min_length=3`` on the title field.

    An empty body should fail validation, not call the
    orchestrator at all.
    """
    test_client, orchestrator, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "CREATED"
    )

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={"title": ""},
    )

    assert response.status_code == 422
    assert orchestrator.title_calls == []


def test_whitespace_only_title_returns_422(client) -> None:
    """Two-character titles also fail validation."""
    test_client, _, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "CREATED"
    )

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={"title": "ab"},
    )

    assert response.status_code == 422


def test_no_confident_match_returns_422(client) -> None:
    """When the orchestrator returns ``(session, None)`` the
    endpoint responds with ``422 title_no_confident_match``.

    The frontend reads this body to surface the "no precise
    match" UI. We assert the error body shape so the contract
    is locked in.
    """
    test_client, orchestrator, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "CREATED"
    )
    orchestrator.next_return_none = True

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={"title": "A paper nobody wrote"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["error"] == "title_no_confident_match"
    # Helpful message is present so the frontend can render it.
    assert "PubMed" in body["detail"]["message"]


def test_workspace_in_papers_retrieved_state_works(client) -> None:
    """Title-driven recovery isn't restricted to CREATED — the
    user can drop a PDF / paste a title even after the SEARCH
    action has populated the workspace."""
    test_client, _, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "PAPERS_RETRIEVED"
    )

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={"title": "Another paper"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    pmids = [p["pmid"] for p in body["papers"]]
    # The pre-existing paper and the new one are both there.
    assert "000" in pmids
    assert "999" in pmids


def test_fsm_illegal_state_returns_409(client) -> None:
    """If the orchestrator raises ``IllegalWorkspaceActionError``
    the route returns 409 with the legal-alternatives body —
    the same contract as ``POST /papers/bulk``.

    We seed the workspace into REPORTING (a transient state
    where ``ADD_PAPER`` is forbidden) by force. We can't go
    through the orchestrator's normal ``report()`` because
    PAPERS_RETRIEVED → REPORTING requires passing through
    SUMMARIZED and COMPARED first; force-state is the test
    seam for that.
    """
    from app.core.enums.workspace_state import WorkspaceState
    test_client, _, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "PAPERS_RETRIEVED"
    )
    workspace = workspaces[ws_id]
    workspace.state = WorkspaceState.REPORTING

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={"title": "Another paper"},
    )

    assert response.status_code == 409
    body = response.json()
    detail = body["detail"]
    assert detail["action"] == "add_paper"
    assert detail["current_state"] == "REPORTING"


def test_year_out_of_range_returns_422(client) -> None:
    """``FindByTitleRequest.year`` is bounded to [1800, 2100].

    A year outside that range fails Pydantic validation, not
    the orchestrator's logic.
    """
    test_client, orchestrator, workspaces = client
    ws_id = next(
        wid for wid, s in workspaces.items()
        if s.state.name == "CREATED"
    )

    response = test_client.post(
        f"/workspaces/{ws_id}/papers/from-title",
        json={"title": "Real paper", "year": 1500},
    )

    assert response.status_code == 422
    assert orchestrator.title_calls == []
