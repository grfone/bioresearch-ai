"""
Live end-to-end verification of the LangGraph workspace FSM.

This is NOT a unit test. It drives the real FastAPI application
against a real SQLite database, through the real
``WorkspaceOrchestrator``, and through the real LangGraph workspace
FSM, and asserts the externally visible contract:

* the four serialized workspace states and their values;
* the legal-action list per state;
* the HTTP 409 envelope for an illegal action (field-for-field);
* the full search -> generate -> report pipeline;
* the retry semantics after a real failure.

Run it from the repository root:

    PYTHONPATH=. .venv/bin/python scripts/verify_langgraph_fsm.py

Exit code 0 means every check passed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("PUBMED_EMAIL", "bioresearch-ai-verify@example.com")
os.environ.setdefault("OPENAI_API_KEY", "sk-verify-only")
os.environ.setdefault("DEFAULT_LLM_PROVIDER", "openai")
os.environ.setdefault("DEFAULT_LLM_MODEL", "gpt-4.1-mini")
os.environ["CACHE_BACKEND"] = "memory"

from fastapi.testclient import TestClient  # noqa: E402

from app.application.services.workspace_orchestrator import (  # noqa: E402
    WorkspaceOrchestrator,
)
from app.core.enums.workspace_state import (  # noqa: E402
    WorkspaceAction,
    WorkspaceState,
)
from app.domain.entities.paper import Paper  # noqa: E402
from app.domain.entities.research_question import ResearchQuestion  # noqa: E402
from app.domain.entities.research_report import ResearchReport  # noqa: E402
from app.domain.entities.research_session import ResearchSession  # noqa: E402
from app.domain.entities.summary import Summary  # noqa: E402
from app.domain.interfaces.llm_provider import LLMProvider  # noqa: E402
from app.domain.interfaces.literature_searcher import LiteratureSearcher  # noqa: E402
from app.domain.interfaces.pdf_generator import PDFGenerator  # noqa: E402
from app.domain.interfaces.report_generator import ReportGenerator  # noqa: E402
from app.domain.models.llm_response import LLMResponse  # noqa: E402
from app.infrastructure.storage.sqlite_workspace_repository import (  # noqa: E402
    SqliteWorkspaceRepository,
)


FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Record a check's outcome."""
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


def equal(label: str, actual: object, expected: object) -> None:
    """Check that two values are equal."""
    check(label, actual == expected, f"(got {actual!r}, expected {expected!r})")


# ---------------------------------------------------------------------------
# Stubs — the pipeline is exercised end to end, only the external
# providers (PubMed / LLM / PDF) are stubbed.
# ---------------------------------------------------------------------------


def _paper(pmid: str) -> Paper:
    return Paper(
        title=f"Paper {pmid}",
        pmid=pmid,
        authors=[],
        journal=None,
        year=2024,
        abstract="An abstract about GLP-1.",
        doi=None,
        keywords=[],
        url=None,
    )


class StubPubMed(LiteratureSearcher):
    def __init__(self, papers: list[Paper]) -> None:
        self._papers = list(papers)

    def search(self, question, filters=None):
        return list(self._papers)

    def search_with_filters(self, filters):
        from app.core.enums.search_source import SearchSource
        from app.domain.value_objects.search_result import SearchResult

        return [
            SearchResult(paper=p, source=SearchSource.PUBMED, confidence=1.0)
            for p in self._papers
        ]

    def default_source(self):
        from app.core.enums.search_source import SearchSource

        return SearchSource.PUBMED

    def get_by_id(self, paper_id):
        return None


class StubLLM(LLMProvider):
    def generate(self, prompt, **kwargs):
        return LLMResponse(
            content='{"body": "stub summary", "papers_used": []}',
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            model="stub",
            finish_reason="stop",
        )


class StubReportGenerator(ReportGenerator):
    def generate(self, question, summary) -> ResearchReport:
        return ResearchReport(
            summary=Summary(body="Executive summary.", papers_used=[]),
            citations=[],
            limitations=[],
            future_work=[],
            metadata={"model": "stub"},
        )


class StubPDFGenerator(PDFGenerator):
    """Returns a minimal but structurally valid PDF.

    ``PublishedReport`` validates the payload size (minimum 200
    bytes), so the stub must return a real, if tiny, PDF.
    """

    _CANNED = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
    )

    def generate(self, report: ResearchReport) -> bytes:
        return self._CANNED


class FailingPubMed(StubPubMed):
    def search(self, question, filters=None):
        raise RuntimeError("pubmed is down")

    def search_with_filters(self, filters):
        raise RuntimeError("pubmed is down")


# ---------------------------------------------------------------------------
# The verification itself
# ---------------------------------------------------------------------------


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="fsm-verify-")
    db_path = Path(tmpdir) / "workspaces.db"

    repository = SqliteWorkspaceRepository(db_path)
    orchestrator = WorkspaceOrchestrator(
        workspace_repository=repository,
        literature_searcher=StubPubMed([_paper("111"), _paper("222")]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )

    # The real application, with only the orchestrator swapped for
    # our stub-backed one. Every route, every schema and every
    # error envelope is the production code.
    from app.config import container
    import main as main_module

    app = main_module.app
    app.dependency_overrides[
        container.get_workspace_orchestrator
    ] = lambda: orchestrator
    client = TestClient(app)

    print("\n=== 1. The serialized state values are unchanged ===")
    equal(
        "WorkspaceState.INITIAL serialises to 'INITIAL'",
        WorkspaceState.INITIAL.value,
        "INITIAL",
    )
    equal(
        "WorkspaceState.INTERMEDIATE serialises to 'INTERMEDIATE'",
        WorkspaceState.INTERMEDIATE.value,
        "INTERMEDIATE",
    )
    equal(
        "WorkspaceState.FINAL serialises to 'FINAL'",
        WorkspaceState.FINAL.value,
        "FINAL",
    )
    equal(
        "WorkspaceState.ERROR serialises to 'ERROR'",
        WorkspaceState.ERROR.value,
        "ERROR",
    )

    print("\n=== 2. The legal-action list per state is unchanged ===")
    session = ResearchSession(question=ResearchQuestion(question="q"))
    repository.create(session)
    equal(
        "INITIAL allows add_paper, remove_paper, search",
        sorted(a.value for a in session.allowed_actions()),
        ["add_paper", "remove_paper", "search"],
    )

    print("\n=== 3. The full search -> generate -> report pipeline ===")
    searched = orchestrator.search(session.id)
    equal("after SEARCH the state is INTERMEDIATE", searched.state.value, "INTERMEDIATE")
    equal("the corpus has 2 papers", len(searched.papers), 2)

    generated = orchestrator.generate(session.id)
    equal("after GENERATE the state is FINAL", generated.state.value, "FINAL")
    check("the summary was produced", generated.summary is not None)
    check("the report was produced", generated.report is not None)
    check("the published report was produced", generated.published_report is not None)

    print("\n=== 4. The HTTP API exposes the same contract ===")
    resp = client.get(f"/workspaces/{session.id}/transitions")
    equal("GET /workspaces/{id}/transitions returns 200", resp.status_code, 200)
    body = resp.json()
    equal("the API reports state FINAL", body["state"], "FINAL")
    equal("the API reports page 'report'", body["page"], "report")
    equal(
        "the API reports the legal actions for FINAL",
        sorted(body["allowed_actions"]),
        ["add_paper", "back_to_workspace", "remove_paper"],
    )
    check("the API reports the audit trail", len(body.get("state_history", [])) > 0)

    print("\n=== 5. An illegal action returns the same 409 envelope ===")
    resp = client.post(f"/workspaces/{session.id}/actions/generate")
    equal("POST an illegal action returns 409", resp.status_code, 409)
    detail = resp.json().get("detail", {})
    equal(
        "the envelope reports the error kind",
        detail.get("error"),
        "illegal_workspace_action",
    )
    equal("the envelope reports current_state", detail.get("current_state"), "FINAL")
    equal("the envelope reports action", detail.get("action"), "generate")
    equal(
        "the envelope reports allowed_actions",
        sorted(detail.get("allowed_actions", [])),
        ["add_paper", "back_to_workspace", "remove_paper"],
    )

    print("\n=== 6. The state is durable across a repository round-trip ===")
    reloaded = repository.get(session.id)
    equal("the reloaded state is FINAL", reloaded.state.value, "FINAL")
    equal(
        "the reloaded audit trail records the search transition",
        [(t.from_state.value, t.to_state.value) for t in reloaded.state_history[-2:]],
        [("INITIAL", "INTERMEDIATE"), ("INTERMEDIATE", "FINAL")],
    )

    print("\n=== 7. A failed search retries to the page the user was on ===")
    failing = WorkspaceOrchestrator(
        workspace_repository=repository,
        literature_searcher=FailingPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    fresh = ResearchSession(question=ResearchQuestion(question="q"))
    repository.create(fresh)
    try:
        failing.search(fresh.id)
        check("the failing search raised", False, "(no exception)")
    except RuntimeError:
        check("the failing search raised", True)

    failed = repository.get(fresh.id)
    equal("the failed workspace is in ERROR", failed.state.value, "ERROR")
    equal(
        "last_known_state is INITIAL (the page the user was on)",
        failed.last_known_state.value if failed.last_known_state else None,
        "INITIAL",
    )
    retried = failing.retry(fresh.id)
    equal("RETRY returns the workspace to INITIAL", retried.state.value, "INITIAL")

    print("\n=== 8. The retry destination depends on the session context ===")
    with_papers = ResearchSession(
        question=ResearchQuestion(question="q"),
        state=WorkspaceState.ERROR,
        last_known_state=WorkspaceState.INTERMEDIATE,
    )
    with_papers.add_papers([_paper("9")])
    repository.create(with_papers)
    equal(
        "RETRY with papers returns to INTERMEDIATE",
        failing.retry(with_papers.id).state.value,
        "INTERMEDIATE",
    )

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s) did not pass:")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED — the LangGraph FSM matches the documented contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
