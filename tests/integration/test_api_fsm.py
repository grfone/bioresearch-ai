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

        def publish(self, wid: UUID) -> ResearchSession:
            """Stub PUBLISH: render a minimal valid PDF and
            advance REPORTED -> PUBLISHING -> COMPLETED.

            Mirrors the real orchestrator's flow so the FSM
            gates and the audit-trail transitions show up the
            same way in tests as they do in production. The
            bytes are a minimal valid PDF so the
            ``PublishedReport`` validator accepts them.
            """
            session = _get(wid)
            session.transition_to(
                WorkspaceAction.PUBLISH, reason="PDF export in flight"
            )
            # Minimal valid PDF -- 4 objects (catalog,
            # pages, page, no font/content). Starts with
            # ``%PDF-1.4`` so PublishedReport.__post_init__
            # accepts it.
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
            from app.domain.entities.published_report import (
                PublishedReport,
            )
            session.set_published_report(
                PublishedReport.create(
                    pdf_bytes=pdf_bytes,
                    workspace_id=str(wid),
                )
            )
            session.force_state(
                WorkspaceState.COMPLETED,
                reason="PDF published",
            )
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
    assert "/workspaces/{workspace_id}/actions/publish" in paths
    assert "/workspaces/{workspace_id}/actions/retry" in paths
    assert "/workspaces/{workspace_id}/transitions" in paths
    assert "/workspaces/{workspace_id}/evidence-comparison" in paths
    # The PDF download companion to PUBLISH -- distinct
    # route, GET method, registered alongside the action
    # surface. Without this assertion, a future refactor
    # could silently drop the download endpoint.
    assert (
        "/workspaces/{workspace_id}/published-report.pdf" in paths
    )


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
    """The FSM guard rejects illegal actions with 409 + allowed list.

    Historically this test pinned the ``REPORT`` action from
    ``PAPERS_RETRIEVED`` as illegal. That gate has been
    intentionally removed (see ADR-008): the orchestrator now
    auto-summarises when ``summary is None`` so the user can
    get a report in one click. We now use a different
    ``(state, action)`` pair that is still illegal -- the
    ``COMPLETE`` action from ``PAPERS_RETRIEVED``.
    """
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))
    # Session is in PAPERS_RETRIEVED -- COMPLETE is illegal
    # (a workspace can only be completed after the report has
    # been generated).
    response = client.post(f"/workspaces/{wid}/actions/complete")
    assert response.status_code == 409
    body = response.json()
    detail = body["detail"]
    assert detail["error"] == "illegal_workspace_action"
    assert detail["current_state"] == "PAPERS_RETRIEVED"
    assert detail["action"] == "complete"
    # The list of allowed actions should NOT include ``complete``
    # for a workspace in PAPERS_RETRIEVED.
    assert "complete" not in detail["allowed_actions"]


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



# ---------------------------------------------------------------------------
# PUBLISH action + GET /published-report.pdf
# ---------------------------------------------------------------------------
#
# These tests cover the four-layer FSM audit for PUBLISH (see ADR-009):
#   1. Positive -- POST /actions/publish from REPORTED returns 200 with
#      state=COMPLETED and published_report_available=True.
#   2. Negative -- POST /actions/publish from PAPERS_RETRIEVED returns
#      409 with the FSM error envelope and ``publish`` absent from
#      allowed_actions.
#   3. Wire-format -- GET /published-report.pdf returns 200 with
#      Content-Type: application/pdf and valid PDF bytes.
#   4. Wire-format -- GET /published-report.pdf before PUBLISH returns
#      404 with a clear error message.
#
# These are the contract guarantees the React frontend relies on for
# the "Publish as PDF" button (data-action="publish-pdf") and the
# "Download PDF" link it reveals after a successful publish.


def _advance_to_reported(app_with_stubs) -> str:
    """Advance the fixture workspace from PAPERS_RETRIEVED to
    REPORTED so PUBLISH is legal.

    The fixture workspace starts in PAPERS_RETRIEVED; we run the
    SUMMARIZE + REPORT actions in sequence to get it to REPORTED.
    Returns the workspace id (str).
    """
    app, _, workspaces = app_with_stubs
    client = TestClient(app)
    wid = next(iter(workspaces))
    r1 = client.post(f"/workspaces/{wid}/actions/summarize")
    assert r1.status_code == 200
    r2 = client.post(f"/workspaces/{wid}/actions/report")
    assert r2.status_code == 200
    assert r2.json()["state"] == "REPORTED"
    return wid


def _fixture_workspace_id(app_with_stubs) -> str:
    """Return the id of the fixture workspace, without
    spinning up a fresh state dict.

    Each test gets a fresh ``app_with_stubs`` fixture that
    creates a new in-memory workspaces dict. The orchestrator
    stub's ``_get`` closure refers to that specific dict, so
    the test MUST read the id from the same fixture, not from
    a fresh ``_make_state()`` call (which would yield a
    different dict the orchestrator doesn't know about).
    """
    _, _, workspaces = app_with_stubs
    return str(next(iter(workspaces)))


def test_publish_action_from_reported_advances_to_completed(
    app_with_stubs,
) -> None:
    """Positive: PUBLISH from REPORTED returns 200 + state=COMPLETED.

    The action surface is a single POST -- the same FSM-aware
    pattern as /actions/search, /actions/report, etc. The
    response is the post-publish workspace with
    ``published_report_available=True`` so the frontend can
    reveal the Download PDF link on the very next render.
    """
    app, _, _ = app_with_stubs
    client = TestClient(app)
    wid = _advance_to_reported(app_with_stubs)

    response = client.post(f"/workspaces/{wid}/actions/publish")
    assert response.status_code == 200, (
        f"PUBLISH should be 200 from REPORTED, got "
        f"{response.status_code}: {response.text}"
    )
    body = response.json()
    # Final state is terminal COMPLETED.
    assert body["state"] == "COMPLETED"
    # The published-report flag flips so the frontend can
    # render the Download PDF link without a follow-up fetch.
    assert body["published_report_available"] is True
    # The action is no longer allowed once the workspace is
    # COMPLETED (terminal state -- nothing left to do).
    assert "publish" not in body["allowed_actions"]


def test_publish_action_from_papers_retrieved_returns_409(
    app_with_stubs,
) -> None:
    """Negative: PUBLISH from PAPERS_RETRIEVED returns 409.

    The action is FSM-gated -- the legal starting state is
    REPORTED. Any other state triggers the standard FSM
    error envelope (the same shape used for every other
    illegal action -- see ``test_illegal_action_returns_409``
    above). The frontend uses ``current_state`` and
    ``allowed_actions`` to render a useful error message.
    """
    app, _, _ = app_with_stubs
    client = TestClient(app)
    wid = _fixture_workspace_id(app_with_stubs)

    response = client.post(f"/workspaces/{wid}/actions/publish")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "illegal_workspace_action"
    assert detail["current_state"] == "PAPERS_RETRIEVED"
    assert detail["action"] == "publish"
    # The workspace hasn't reached REPORTED yet, so PUBLISH
    # is not in the allowed list.
    assert "publish" not in detail["allowed_actions"]


def test_published_report_pdf_endpoint_returns_pdf_after_publish(
    app_with_stubs,
) -> None:
    """Wire-format: GET /published-report.pdf returns 200 with
    Content-Type: application/pdf + valid bytes.

    This is the download companion to PUBLISH. The bytes
    served MUST start with the PDF magic header -- the test
    asserts on that prefix as a structural pin (the same
    invariant the PublishedReport entity enforces on
    incoming bytes). Without the magic-header check a
    corrupted render could be served silently.
    """
    app, _, _ = app_with_stubs
    client = TestClient(app)
    wid = _advance_to_reported(app_with_stubs)

    # Publish first -- sets published_report on the session.
    publish = client.post(f"/workspaces/{wid}/actions/publish")
    assert publish.status_code == 200

    response = client.get(f"/workspaces/{wid}/published-report.pdf")
    assert response.status_code == 200
    # Content-Type is the standard PDF MIME -- browsers
    # treat this as a downloadable PDF (combined with the
    # Content-Disposition: attachment header we set).
    assert response.headers["content-type"] == "application/pdf"
    # The magic header is the structural pin: a corrupted
    # render fails the assertion loudly here rather than
    # confusing the browser.
    assert response.content.startswith(b"%PDF-")
    # Content-Disposition: attachment makes the browser
    # save the file rather than navigate away.
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert ".pdf" in disposition


def test_published_report_pdf_endpoint_returns_404_before_publish(
    app_with_stubs,
) -> None:
    """Wire-format: GET /published-report.pdf before PUBLISH
    returns 404 with an actionable error message.

    The error message tells the user which action to run
    first -- so a frontend bug that surfaces this 404 still
    gives the user a useful next step.
    """
    app, _, _ = app_with_stubs
    client = TestClient(app)
    wid = _fixture_workspace_id(app_with_stubs)

    response = client.get(f"/workspaces/{wid}/published-report.pdf")
    assert response.status_code == 404
    # The detail message tells the user which action to run
    # first. The frontend's catch-all 404 handler will show
    # this verbatim.
    assert "publish" in response.text.lower()
