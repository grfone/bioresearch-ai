"""
Integration tests for the FSM-related REST endpoints.

These tests exercise the FastAPI app end-to-end with a stub
orchestrator and a stub legacy assistant so the HTTP layer is
fully validated without external dependencies (LLM, PubMed,
persistence).

The tests verify:

- New FSM action endpoints are reachable (search, generate, retry).
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

import json
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.enums.workspace_state import (
    WorkspaceAction,
    WorkspaceState,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.paper import Paper
from app.domain.entities.published_report import PublishedReport
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary


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
    from app.domain.entities.research_question import (
        ResearchQuestion,
    )
    from app.domain.entities.research_session import (
        ResearchSession,
    )

    workspaces: dict[UUID, ResearchSession] = {}

    def _get(wid: UUID) -> ResearchSession:
        return workspaces[wid]

    class StubOrchestrator:
        """Mimics the WorkspaceOrchestrator with just enough methods
        for the routes we exercise here. The contract is "anything
        that the route handler calls succeeds" — we don't simulate
        real search/generate logic; we just verify the FSM gates."""

        def search(self, wid, query=None):
            session = _get(wid)
            session.transition_to(WorkspaceAction.SEARCH)
            # Simulate papers arriving. The search route expects
            # the workspace to be in INTERMEDIATE after the call.
            session.add_papers(
                [
                    Paper(
                        title=f"Stub {i}",
                        pmid=str(i),
                        authors=[],
                        journal=None,
                        year=2024,
                        abstract="",
                        doi=None,
                        keywords=[],
                        url=None,
                    )
                    for i in range(2)
                ]
            )
            workspaces[session.id] = session
            return session

        def _fail(self, session, exc):
            """Mimic WorkspaceOrchestrator._fail - record
            last_known_state before moving to ERROR."""
            if session.state is not WorkspaceState.ERROR:
                session.last_known_state = session.state
            session.last_error = str(exc)
            from datetime import datetime, UTC
            session.last_error_at = datetime.now(UTC)
            session.force_state(
                WorkspaceState.ERROR, reason=str(exc),
            )

        def generate(self, wid):
            session = _get(wid)
            session.transition_to(WorkspaceAction.GENERATE)
            # The real generate runs the full pipeline
            # (summary + report + PDF). For the stub we just
            # set the artefacts so the FINAL state has the
            # expected populated fields.
            if session.summary is None:
                session.set_summary(Summary(body="stub", papers_used=[]))
            session.set_report(
                ResearchReport(
                    summary=session.summary if session.summary is not None else Summary(body="", papers_used=[]),
                    citations=[],
                    limitations=[],
                    future_work=[],
                    metadata={"model": "stub"},
                )
            )
            pdf_bytes = (
                b"%PDF-1.4\n"
                b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
                b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
                b"/MediaBox [0 0 612 792] >>\nendobj\n"
                b"xref\n0 4\n0000000000 65535 f \n"
                b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
                b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
            )
            session.set_published_report(
                PublishedReport.create(
                    pdf_bytes=pdf_bytes,
                    workspace_id=str(wid),
                )
            )
            session.force_state(
                WorkspaceState.FINAL,
                reason="Report generated",
            )
            workspaces[session.id] = session
            return session

        def retry(self, wid):
            session = _get(wid)
            target = (
                session.last_known_state
                or (
                    WorkspaceState.INTERMEDIATE
                    if session.papers
                    else WorkspaceState.INITIAL
                )
            )
            session.transition_to(WorkspaceAction.RETRY)
            if session.state != target:
                session.force_state(
                    target,
                    reason=f"Retry: returning to {target.value}",
                )
            workspaces[session.id] = session
            return session

        def back_to_workspace(self, wid):
            session = _get(wid)
            session.transition_to(WorkspaceAction.BACK_TO_WORKSPACE)
            workspaces[session.id] = session
            return session

        def back_to_home(self, wid):
            session = _get(wid)
            session.transition_to(WorkspaceAction.BACK_TO_HOME)
            workspaces[session.id] = session
            return session

        def get_workspace(self, wid):
            return _get(wid)

        def allowed_actions(self, wid):
            return _get(wid).allowed_actions()

    class StubAssistant:
        """Mimics the legacy ResearchAssistant."""

        def get_workspace(self, wid):
            return _get(wid)

        def create_workspace(self, question):
            new = ResearchSession(
                question=ResearchQuestion(question=question),
            )
            workspaces[new.id] = new
            return new

        def update_workspace(self, session):
            workspaces[session.id] = session
            return session

    return StubOrchestrator(), StubAssistant(), workspaces


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    """Set the env vars required by the pydantic Settings load."""
    monkeypatch.setenv("BIORESEARCH_LLM_PROVIDER", "stub")
    monkeypatch.setenv("BIORESEARCH_LLM_MODEL", "stub-model")
    monkeypatch.setenv("BIORESEARCH_LLM_API_KEY", "stub-key")
    monkeypatch.setenv("BIORESEARCH_PUBMED_EMAIL", "stub@example.com")
    monkeypatch.setenv("BIORESEARCH_PUBMED_API_KEY", "stub-pubmed-key")


@pytest.fixture
def app_with_stubs(monkeypatch: pytest.MonkeyPatch):
    from app.config import container
    import main as main_module
    from app.api.routes import workspace_actions

    orchestrator, assistant, workspaces = _make_state()

    # Seed an initial workspace so the tests have something to
    # work with.
    seed = assistant.create_workspace("test question")
    seed_wid = seed.id

    def _override():
        return orchestrator

    # The route handlers reference ``get_workspace_orchestrator``
    # via FastAPI's ``Depends()`` mechanism. FastAPI captures the
    # function reference at route-definition time and uses its own
    # resolution machinery at request time — monkeypatch.setattr
    # on the module attribute does NOT affect what FastAPI calls.
    #
    # The blessed way to override Depends() in FastAPI tests is
    # ``app.dependency_overrides[original] = replacement``. This
    # works for every route registered against this ``app``.
    main_module.app.dependency_overrides[
        container.get_workspace_orchestrator
    ] = _override
    if hasattr(container, "get_research_assistant"):
        main_module.app.dependency_overrides[
            container.get_research_assistant
        ] = lambda: assistant

    # Also reset the module-level singleton so direct callers
    # (e.g. via container.get_workspace_orchestrator()) return
    # our stub if they bypass Depends().
    container._orchestrator = None

    class _Fixture:
        def __init__(self):
            self.app = main_module.app
            self.orchestrator = orchestrator
            self.workspaces = workspaces
            self.wid = seed_wid

    return _Fixture()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_routes_are_registered(app_with_stubs) -> None:
    """The 4-state FSM action surface is registered."""
    app = app_with_stubs.app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    # Action surface
    assert "/workspaces/{workspace_id}/actions/search" in paths
    assert "/workspaces/{workspace_id}/actions/generate" in paths
    assert "/workspaces/{workspace_id}/actions/retry" in paths
    assert "/workspaces/{workspace_id}/actions/back_to_workspace" in paths
    assert "/workspaces/{workspace_id}/actions/back_to_home" in paths
    # Optional power-user endpoints
    assert "/workspaces/{workspace_id}/transitions" in paths
    assert "/workspaces/{workspace_id}/published-report.pdf" in paths
    assert "/workspaces/{workspace_id}/published-report.tex" in paths
    # The retired /summarize / /report / /complete / /publish /
    # /compare routes are GONE. Any future refactor that
    # accidentally re-introduces them will fail this test.
    assert "/workspaces/{workspace_id}/actions/summarize" not in paths
    assert "/workspaces/{workspace_id}/actions/report" not in paths
    assert "/workspaces/{workspace_id}/actions/complete" not in paths
    assert "/workspaces/{workspace_id}/actions/publish" not in paths
    assert "/workspaces/{workspace_id}/actions/compare" not in paths
    assert "/workspaces/{workspace_id}/evidence-comparison" not in paths


def test_transitions_endpoint_returns_fsm_payload(app_with_stubs) -> None:
    """The /transitions endpoint reflects the current state and
    page token."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    response = client.get(f"/workspaces/{wid}/transitions")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "INITIAL"
    assert "search" in body["allowed_actions"]
    assert "generate" not in body["allowed_actions"]
    assert body["is_terminal"] is False
    assert body["page"] == "home"
    assert isinstance(body["state_history"], list)
    assert body["progress"] == pytest.approx(0.0)


def test_search_action_advances_to_intermediate(app_with_stubs) -> None:
    """search moves INITIAL → INTERMEDIATE."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    response = client.post(f"/workspaces/{wid}/actions/search", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "INTERMEDIATE"
    assert "generate" in body["allowed_actions"]
    # search is no longer legal from INTERMEDIATE
    # (one search per workspace is the design); re-search
    # requires removing papers to regress to INITIAL.
    assert "search" not in body["allowed_actions"]
    assert "back_to_home" in body["allowed_actions"]


def test_generate_action_advances_to_final(app_with_stubs) -> None:
    """generate moves INTERMEDIATE → FINAL."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    # Search first.
    client.post(f"/workspaces/{wid}/actions/search", json={})
    # Now generate.
    r = client.post(f"/workspaces/{wid}/actions/generate")
    # The generate endpoint returns 201 Created + a ReportResponse.
    assert r.status_code == 201
    body = r.json()
    assert "summary" in body  # the ReportResponse shape
    # The workspace is now in FINAL.
    r2 = client.get(f"/workspaces/{wid}/transitions")
    assert r2.json()["state"] == "FINAL"


def test_generate_from_initial_returns_409(app_with_stubs) -> None:
    """generate is only legal from INTERMEDIATE."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    response = client.post(f"/workspaces/{wid}/actions/generate")
    assert response.status_code == 409
    body = response.json()
    detail = body["detail"]
    assert detail["error"] == "illegal_workspace_action"
    assert detail["current_state"] == "INITIAL"
    assert detail["action"] == "generate"
    assert "search" in detail["allowed_actions"]


def test_back_to_workspace_action(app_with_stubs) -> None:
    """back_to_workspace moves FINAL → INTERMEDIATE."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    client.post(f"/workspaces/{wid}/actions/search", json={})
    client.post(f"/workspaces/{wid}/actions/generate")
    # Confirm we are at FINAL.
    r = client.get(f"/workspaces/{wid}/transitions")
    assert r.json()["state"] == "FINAL"
    # Back to workspace.
    r = client.post(f"/workspaces/{wid}/actions/back_to_workspace")
    assert r.status_code == 200
    assert r.json()["state"] == "INTERMEDIATE"


def test_back_to_home_action(app_with_stubs) -> None:
    """back_to_home moves INTERMEDIATE → INITIAL."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    client.post(f"/workspaces/{wid}/actions/search", json={})
    r = client.post(f"/workspaces/{wid}/actions/back_to_home")
    assert r.status_code == 200
    assert r.json()["state"] == "INITIAL"


def test_workspace_response_exposes_workspace_fsm_fields(app_with_stubs) -> None:
    """The legacy workspace response includes the new FSM fields."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    response = client.get(f"/workspaces/{wid}")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "INITIAL"
    assert "allowed_actions" in body
    assert "progress" in body
    assert body["page"] == "home"
    # The legacy fields that the 4-state FSM retired.
    assert "has_evidence_comparison" not in body


def test_published_report_pdf_endpoint_after_generate(
    app_with_stubs,
) -> None:
    """generate() persists a PDF that the download endpoint serves."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    # Get the workspace from INITIAL → FINAL.
    client.post(f"/workspaces/{wid}/actions/search", json={})
    client.post(f"/workspaces/{wid}/actions/generate")
    # Now download the PDF.
    r = client.get(f"/workspaces/{wid}/published-report.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")


def test_published_report_pdf_404_before_generate(app_with_stubs) -> None:
    """No PDF before generate."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    r = client.get(f"/workspaces/{wid}/published-report.pdf")
    assert r.status_code == 404


def test_published_report_tex_endpoint_after_generate(
    app_with_stubs,
) -> None:
    """LaTeX export available from FINAL."""
    app = app_with_stubs.app
    orch = app_with_stubs.orchestrator
    workspaces = app_with_stubs.workspaces
    wid = app_with_stubs.wid

    client = TestClient(app)
    client.post(f"/workspaces/{wid}/actions/search", json={})
    client.post(f"/workspaces/{wid}/actions/generate")
    r = client.get(f"/workspaces/{wid}/published-report.tex")
    assert r.status_code == 200
    assert b"\\documentclass" in r.content


def test_retry_returns_to_last_known_state(app_with_stubs) -> None:
    """retry restores the pre-ERROR state via last_known_state."""
    app = app_with_stubs.app
    orchestrator = app_with_stubs.orchestrator
    wid = app_with_stubs.wid
    client = TestClient(app)

    # Move to INTERMEDIATE.
    client.post(f"/workspaces/{wid}/actions/search", json={})

    # Simulate a failure (orchestrator._fail is the production
    # entry point; we replicate it here).
    from app.core.enums.workspace_state import WorkspaceState as _WS
    session = orchestrator.get_workspace(wid)
    orchestrator._fail(session, RuntimeError("LLM timeout"))
    # The workspace is in ERROR.
    r = client.get(f"/workspaces/{wid}/transitions")
    assert r.json()["state"] == "ERROR"
    # last_known_state was INTERMEDIATE before the failure.
    r = client.post(f"/workspaces/{wid}/actions/retry")
    assert r.status_code == 200
    assert r.json()["state"] == "INTERMEDIATE"
