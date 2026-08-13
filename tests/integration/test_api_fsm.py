"""
Integration tests for the FSM-related REST endpoints.

These tests exercise the FastAPI app end-to-end with a stub
orchestrator and a stub legacy assistant so the HTTP layer is
fully validated without external dependencies (LLM, PubMed,
persistence).

The tests verify:

- New FSM action endpoints are reachable.
- ``allowed_actions`` is reflected in the workspace response.
- Illegal actions return 409 with the legal-alternatives body.
- The legacy ``/reports/generate`` endpoint is wired to the
  orchestrator (the bug fix).
- ``GET /transitions`` returns the FSM status payload.
- The legacy ``GET /workspaces/{id}`` returns the workspace
  with the new FSM fields.

The stubs are injected at the configuration root so every route
that depends on the orchestrator or the research assistant sees
the same shared in-memory state.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared in-memory state
# ---------------------------------------------------------------------------


def _make_state():
    """Build a fresh in-memory workspace + stubs that share it."""
    from app.core.enums.workspace_state import (
        WorkspaceAction,
        WorkspaceState,
    )
    from app.domain.entities.citation import Citation
    from app.domain.entities.paper import Paper
    from app.domain.entities.research_question import ResearchQuestion
    from app.domain.entities.research_report import ResearchReport
    from app.domain.entities.research_session import ResearchSession
    from app.domain.entities.summary import Summary

    workspace = ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?"),
        state=WorkspaceState.PAPERS_RETRIEVED,
    )
    paper = Paper(title="T", pmid="111")
    workspace.add_papers([paper])
    workspace.set_summary(Summary(text="stub", papers_used=[paper]))
    workspaces: dict[UUID, ResearchSession] = {workspace.id: workspace}

    def _get(wid: UUID) -> ResearchSession:
        if wid not in workspaces:
            raise ValueError(f"workspace {wid} not found")
        return workspaces[wid]

    class StubOrchestrator:
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
            report = ResearchReport(
                summary=session.summary,
                citations=[],
            )
            session.set_report(report)
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

    class StubAssistant:
        """Mimics the legacy ResearchAssistant."""

        def get_workspace(self, wid: UUID) -> ResearchSession:
            return _get(wid)

        def create_workspace(self, question: str) -> ResearchSession:
            new = ResearchSession(question=ResearchQuestion(question=question))
            workspaces[new.id] = new
            return new

        def update_workspace(self, session: ResearchSession) -> ResearchSession:
            workspaces[session.id] = session
            return session

    return StubOrchestrator(), StubAssistant(), workspaces


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    """Set the env vars required by the pydantic Settings load.

    The settings classes load their values at module import time so
    the variables must be present in the environment before any
    ``app.*`` import. This is why this fixture is autouse — it
    guarantees the env is set for every test in the module.
    """
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("PUBMED_EMAIL", "test@example.com")
    monkeypatch.setenv("PUBMED_API_KEY", "")
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("API_KEY", "sk-test")
    monkeypatch.setenv("BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./bioresearch.db")


@pytest.fixture
def app_with_stubs(monkeypatch: pytest.MonkeyPatch):
    """Build a FastAPI app with stub orchestrator + assistant."""
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    orchestrator, assistant, workspaces = _make_state()

    import main as main_module

    # FastAPI's ``Depends`` captures the function reference at
    # route-registration time. monkeypatch on the module does not
    # propagate to the dependency tree, so we use the proper
    # FastAPI mechanism: ``app.dependency_overrides``.
    from app.api.routes import (
        report as report_route,
        search as search_route,
        workspace_actions,
    )
    from app.config import container

    overrides = {
        container.get_workspace_orchestrator: lambda: orchestrator,
        container.get_research_assistant: lambda: assistant,
        # Legacy routes declare their own local dependency functions.
        workspace_actions.get_workspace_orchestrator: lambda: orchestrator,
        report_route.get_orchestrator: lambda: orchestrator,
        search_route.get_research_assistant: lambda: assistant,
    }
    for dep, override in overrides.items():
        main_module.app.dependency_overrides[dep] = override

    # The legacy workspace.py route uses a local
    # ``get_research_assistant`` that calls ``Container.build()``,
    # not the module-level function. Patch the classmethod so the
    # stub is also used by that route.
    monkeypatch.setattr(
        container.Container, "build", classmethod(lambda cls: assistant)
    )

    return main_module.app, orchestrator, workspaces


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_routes_are_registered(app_with_stubs) -> None:
    app, _, _ = app_with_stubs
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/workspaces/{workspace_id}/actions/search" in paths
    assert "/workspaces/{workspace_id}/actions/summarize" in paths
    assert "/workspaces/{workspace_id}/actions/compare" in paths
    assert "/workspaces/{workspace_id}/actions/report" in paths
    assert "/workspaces/{workspace_id}/actions/complete" in paths
    assert "/workspaces/{workspace_id}/actions/retry" in paths
    assert "/workspaces/{workspace_id}/transitions" in paths
    assert "/workspaces/{workspace_id}/evidence-comparison" in paths


def test_transitions_endpoint_returns_fsm_payload(app_with_stubs) -> None:
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))
    response = client.get(f"/workspaces/{wid}/transitions")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "PAPERS_RETRIEVED"
    assert "summarize" in body["allowed_actions"]
    assert "search" in body["allowed_actions"]
    assert body["is_terminal"] is False
    assert isinstance(body["state_history"], list)
    assert body["progress"] == pytest.approx(0.2)


def test_summarize_action_advances_state(app_with_stubs) -> None:
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))
    response = client.post(f"/workspaces/{wid}/actions/summarize")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "SUMMARIZED"
    assert "compare" in body["allowed_actions"]
    assert "report" in body["allowed_actions"]


def test_illegal_action_returns_409(app_with_stubs) -> None:
    """The FSM guard rejects illegal actions with 409 + allowed list."""
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))
    # Session is in PAPERS_RETRIEVED — REPORT is illegal.
    response = client.post(f"/workspaces/{wid}/actions/report")
    assert response.status_code == 409
    body = response.json()
    detail = body["detail"]
    assert detail["error"] == "illegal_workspace_action"
    assert detail["current_state"] == "PAPERS_RETRIEVED"
    assert detail["action"] == "report"
    assert "summarize" in detail["allowed_actions"]


def test_compare_action_endpoint_reachable(app_with_stubs) -> None:
    """Run summarize then compare — both should advance the state."""
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))
    r1 = client.post(f"/workspaces/{wid}/actions/summarize")
    assert r1.status_code == 200
    r2 = client.post(f"/workspaces/{wid}/actions/compare")
    assert r2.status_code == 200
    assert r2.json()["state"] == "COMPARED"


def test_workspace_response_exposes_workspace_fsm_fields(app_with_stubs) -> None:
    """The legacy workspace response includes the new FSM fields."""
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))
    response = client.get(f"/workspaces/{wid}")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "PAPERS_RETRIEVED"
    assert "allowed_actions" in body
    assert "progress" in body
    assert "has_evidence_comparison" in body
    assert body["has_evidence_comparison"] is False


def test_legacy_report_generate_is_wired_to_orchestrator(app_with_stubs) -> None:
    """The deprecated /reports/generate delegates to the orchestrator.

    Regression test: the legacy endpoint must use the workspace's
    papers and must not re-search PubMed.
    """
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))

    # Summarize first so REPORT is legal.
    r1 = client.post(f"/workspaces/{wid}/actions/summarize")
    assert r1.status_code == 200

    # Now the deprecated endpoint should work.
    response = client.post(
        "/reports/generate",
        json={"workspace_id": str(wid)},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["workspace_id"] == str(wid)
    assert "summary" in body
    assert isinstance(body["citations"], list)
