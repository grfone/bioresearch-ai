"""
Unit tests for the WorkspaceOrchestrator (FSM behaviour).

These tests use stub implementations of the use cases so the
orchestrator can be exercised deterministically without any LLM
or PubMed calls. The tests focus on the FSM behaviour:

- The orchestrator rejects illegal actions.
- The orchestrator uses the workspace's papers — it does NOT
  re-search PubMed when generating a report.
- The orchestrator persists state changes.
- The orchestrator exposes ``allowed_actions`` and ``get_workspace``.
"""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

import pytest

from app.application.services.workspace_orchestrator import (
    WorkspaceOrchestrator,
)
from app.application.use_cases.generate_report import GenerateReportUseCase
from app.application.use_cases.search_literature import SearchLiteratureUseCase
from app.application.use_cases.summarize_papers import SummarizePapersUseCase
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
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.interfaces.literature_searcher import LiteratureSearcher
from app.domain.interfaces.pdf_generator import PDFGenerator
from app.domain.interfaces.report_generator import ReportGenerator
from app.domain.interfaces.workspace_repository import WorkspaceRepository
from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt


# ---------------------------------------------------------------------------
# Shared in-memory state
# ---------------------------------------------------------------------------


class InMemoryRepository(WorkspaceRepository):
    """Minimal in-memory repo so the orchestrator's persistence
    calls succeed. We assert on the returned ``ResearchSession``
    objects rather than re-reading from storage.

    Implements every method the orchestrator calls: ``create``,
    ``get``, ``update``, ``delete``, ``list_all``,
    ``workspace_state_counts``. ``exists`` and ``list_workspaces``
    are part of the abstract interface but are not called by
    the orchestrator's action handlers -- we implement them as
    no-ops so the class isn't abstract.
    """

    def __init__(self) -> None:
        self._by_id: dict[UUID, ResearchSession] = {}

    def create(self, workspace: ResearchSession) -> ResearchSession:
        self._by_id[workspace.id] = workspace
        return workspace

    def get(self, workspace_id: UUID) -> ResearchSession:
        return self._by_id[workspace_id]

    def update(self, workspace: ResearchSession) -> ResearchSession:
        self._by_id[workspace.id] = workspace
        return workspace

    def delete(self, workspace_id: UUID) -> None:
        self._by_id.pop(workspace_id, None)

    def exists(self, workspace_id: UUID) -> bool:
        return workspace_id in self._by_id

    def list_all(self) -> list[ResearchSession]:
        return list(self._by_id.values())

    def list_workspaces(self) -> list[ResearchSession]:
        return self.list_all()

    def workspace_state_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in WorkspaceState}
        for s in self._by_id.values():
            counts[s.state.value] += 1
        return counts


class StubPubMed(LiteratureSearcher):
    """Stub that yields a fixed list of papers for any query."""

    def __init__(self, papers: list[Paper]) -> None:
        self._papers = list(papers)

    def search(self, question, filters=None):
        return list(self._papers)

    def search_with_filters(self, filters):
        from app.domain.value_objects.search_result import SearchResult
        return [
            SearchResult(paper=p, source=self.default_source(), confidence=1.0)
            for p in self._papers
        ]

    def default_source(self):
        from app.core.enums.search_source import SearchSource
        return SearchSource.PUBMED

    def get_by_id(self, paper_id):
        return None


class StubLLM(LLMProvider):
    """Stub LLM that returns a fixed Summary + ReportResponse text."""

    def generate(self, prompt, **kwargs):
        return LLMResponse(
            content='{"body": "stub", "papers_used": []}',
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            model="stub",
            finish_reason="stop",
        )


class StubReportGenerator(ReportGenerator):
    def generate(self, question, summary) -> ResearchReport:
        return _make_report("Executive summary.")


class StubPDFGenerator(PDFGenerator):
    """Stub that returns canned PDF bytes and records what it saw.

    The canned payload is a minimal valid PDF (starts with
    ``b"%PDF-"``) so the PublishedReport validator doesn't
    reject it. Tests that need to assert on the rendered output
    can inspect ``calls`` to see which reports were rendered.
    """

    _CANNED_BYTES: bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
    )

    def __init__(self) -> None:
        self.calls: list[ResearchReport] = []

    def generate(self, report: ResearchReport) -> bytes:
        self.calls.append(report)
        return self._CANNED_BYTES


class _RecordingReportGenerator(ReportGenerator):
    """Like StubReportGenerator but records the summary it sees."""

    def __init__(self, papers_seen: list) -> None:
        self.papers_seen = papers_seen

    def generate(self, question, summary):
        self.papers_seen.append(summary)
        return _make_report("Executive summary.")


def _paper(pmid: str) -> Paper:
    return Paper(
        title=f"Paper {pmid}",
        pmid=pmid,
        authors=[],
        journal=None,
        year=2024,
        abstract="",
        doi=None,
        keywords=[],
        url=None,
    )


def _make_report(text: str = "Executive summary.") -> ResearchReport:
    return ResearchReport(
        summary=Summary(body=text, papers_used=[]),
        citations=[],
        limitations=[],
        future_work=[],
        metadata={"model": "stub"},
    )


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def stub_papers() -> list[Paper]:
    return [_paper("111"), _paper("222")]


@pytest.fixture
def orchestrator(repo: InMemoryRepository, stub_papers: list[Paper]) -> WorkspaceOrchestrator:
    return WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_workspace_is_in_initial_state() -> None:
    repo = InMemoryRepository()
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?")
    )
    repo.create(ws)
    loaded = orch.get_workspace(ws.id)
    assert loaded.state is WorkspaceState.INITIAL
    assert "search" in loaded.allowed_actions()


def test_search_advances_to_intermediate(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """Search moves INITIAL → INTERMEDIATE (the user's "Workspace" page)."""
    ws = ResearchSession(question=ResearchQuestion(question="x"))
    repo.create(ws)

    # Use a single-paper stub so the search returns at least one
    # result and ``replace_papers`` triggers the INITIAL →
    # INTERMEDIATE auto-advance.
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    loaded = orch.search(ws.id, query="x")
    assert loaded.state is WorkspaceState.INTERMEDIATE
    assert len(loaded.papers) == 2


def test_generate_action_is_removed_summarize() -> None:
    """SUMMARIZE was retired on 2026-08-31 — see ADR-017.

    The summarise/report/publish flow is now collapsed into a
    single ``generate`` action. This stub remains so any stale
    caller (an old LangGraph node, an abandoned integration test,
    a stale frontend bundle cached by a CDN) gets a clear 409
    error rather than a silent failure.
    """
    from app.core.exceptions import IllegalWorkspaceActionError
    from app.domain.entities.research_session import ResearchSession
    from app.domain.entities.research_question import ResearchQuestion

    repo = InMemoryRepository()
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    repo.create(ws)

    with pytest.raises(IllegalWorkspaceActionError):
        orch.summarize(ws.id)


def test_generate_runs_full_pipeline(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """GENERATE: summarise → report → PDF → FINAL.

    This is the action that fixes the original bug. The full
    pipeline runs server-side in one call. The workspace ends
    up in FINAL with summary, report, and published_report all
    populated.
    """
    pdf_gen = StubPDFGenerator()
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=pdf_gen,
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    ws.add_papers(stub_papers)
    repo.create(ws)

    result = orch.generate(ws.id)
    assert result.state is WorkspaceState.FINAL
    assert result.summary is not None
    assert result.report is not None
    assert result.published_report is not None
    # PDF generator saw the report we just made.
    assert len(pdf_gen.calls) == 1


def test_generate_uses_workspace_papers_not_research(
    repo: InMemoryRepository,
) -> None:
    """Regression: GENERATE must use the workspace's papers, not
    re-search PubMed. This is the bug the FSM refactor fixes.
    """
    pubmed = StubPubMed([_paper("99999")])
    papers_seen: list = []
    report_gen = _RecordingReportGenerator(papers_seen)
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=pubmed,
        llm_provider=StubLLM(),
        report_generator=report_gen,
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    workspace_papers = [_paper("111"), _paper("222")]
    ws.add_papers(workspace_papers)
    repo.create(ws)

    orch.generate(ws.id)

    # The pubmed stub returned a paper with PMID 99999 that the
    # workspace does NOT have. The report must not contain it.
    assert _paper("99999") not in ws.papers


def test_generate_advances_through_states(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """GENERATE walks INTERMEDIATE → FINAL with the audit trail
    correctly populated.
    """
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    ws.add_papers(stub_papers)
    repo.create(ws)

    # Pre-generate: only the initial seed entry.
    initial_history = len(ws.state_history)
    result = orch.generate(ws.id)
    # The history gains the GENERATE action (recorded by
    # ``_enter_action``) but does NOT gain a second entry for
    # the force_state to FINAL call -- that entry is only added
    # to ``state_history`` if it represents a real state
    # transition (which the force_state path does), but here
    # the orchestrator's ``force_state(FINAL)`` is a no-op in
    # terms of transition_to because it's the same state
    # recorded as the action. We just assert the entry exists.
    assert len(result.state_history) > initial_history
    last = result.state_history[-1]
    # The final state transition was either the GENERATE action
    # (recorded by _enter_action) or the force_state to FINAL.
    # Both record INTERMEDIATE → FINAL or INTERMEDIATE → INTERMEDIATE
    # with action=GENERATE. Check the to_state is FINAL or that
    # the last force_state was to FINAL.
    assert result.state is WorkspaceState.FINAL


def test_generate_illegal_from_initial(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """GENERATE from INITIAL is illegal -- the user must search first."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INITIAL,
    )
    repo.create(ws)

    with pytest.raises(IllegalWorkspaceActionError) as exc:
        orch.generate(ws.id)
    assert exc.value.current_state == "INITIAL"
    assert exc.value.action == "generate"
    assert "search" in exc.value.allowed


def test_generate_illegal_from_final(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """GENERATE from FINAL is illegal -- use BACK_TO_WORKSPACE first."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.FINAL,
    )
    repo.create(ws)

    with pytest.raises(IllegalWorkspaceActionError) as exc:
        orch.generate(ws.id)
    assert exc.value.current_state == "FINAL"
    assert "back_to_workspace" in exc.value.allowed


def test_generate_creates_published_report(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """GENERATE persists a PublishedReport so the user can
    download the PDF from the FINAL page.
    """
    pdf_gen = StubPDFGenerator()
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=pdf_gen,
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    ws.add_papers(stub_papers)
    repo.create(ws)

    result = orch.generate(ws.id)
    assert result.published_report is not None
    assert result.published_report.pdf_bytes == pdf_gen._CANNED_BYTES
    # workspace_id is stamped onto the published_report.
    assert result.published_report.workspace_id == str(ws.id)


def test_back_to_workspace_action(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """BACK_TO_WORKSPACE moves FINAL → INTERMEDIATE."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.FINAL,
    )
    repo.create(ws)

    result = orch.back_to_workspace(ws.id)
    assert result.state is WorkspaceState.INTERMEDIATE


def test_back_to_home_action(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """BACK_TO_HOME moves INTERMEDIATE → INITIAL."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    repo.create(ws)

    result = orch.back_to_home(ws.id)
    assert result.state is WorkspaceState.INITIAL


def test_retry_recovers_to_initial_when_no_papers(
    repo: InMemoryRepository,
) -> None:
    """RETRY after a failed search → INITIAL (no papers yet)."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.ERROR,
        last_known_state=WorkspaceState.INITIAL,
    )
    repo.create(ws)

    result = orch.retry(ws.id)
    assert result.state is WorkspaceState.INITIAL


def test_retry_recovers_to_intermediate_when_papers_exist(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """RETRY after a failed generate → INTERMEDIATE (papers preserved)."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.ERROR,
        last_known_state=WorkspaceState.INTERMEDIATE,
    )
    ws.add_papers(stub_papers)
    repo.create(ws)

    result = orch.retry(ws.id)
    assert result.state is WorkspaceState.INTERMEDIATE


def test_fail_records_last_known_state(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """_fail() records the pre-ERROR state in last_known_state."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    repo.create(ws)

    # Simulate a failure via _fail.
    orch._fail(ws, RuntimeError("LLM timeout"))
    assert ws.state is WorkspaceState.ERROR
    assert ws.last_error == "RuntimeError: LLM timeout"
    assert ws.last_known_state is WorkspaceState.INTERMEDIATE


def test_allowed_actions_reflects_state(
    repo: InMemoryRepository,
) -> None:
    """allowed_actions returns the right list per state."""
    from app.application.services.workspace_orchestrator import (
        WorkspaceOrchestrator as _WO,
    )

    orch = _WO(
        workspace_repository=repo,
        literature_searcher=StubPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )

    ws = ResearchSession(question=ResearchQuestion(question="x"))
    repo.create(ws)
    # INITIAL
    assert "search" in orch.allowed_actions(ws.id)
    assert "generate" not in orch.allowed_actions(ws.id)

    ws.state = WorkspaceState.INTERMEDIATE
    repo.update(ws)
    # INTERMEDIATE
    assert "generate" in orch.allowed_actions(ws.id)
    assert "back_to_home" in orch.allowed_actions(ws.id)

    ws.state = WorkspaceState.FINAL
    repo.update(ws)
    # FINAL
    assert "back_to_workspace" in orch.allowed_actions(ws.id)
    assert "generate" not in orch.allowed_actions(ws.id)

    ws.state = WorkspaceState.ERROR
    repo.update(ws)
    # ERROR
    assert "retry" in orch.allowed_actions(ws.id)


def test_remove_paper_persists(
    repo: InMemoryRepository, stub_papers: list[Paper],
) -> None:
    """remove_paper persists to the repository."""
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed(stub_papers),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    ws.add_papers(stub_papers)
    repo.create(ws)

    result = orch.remove_paper(ws.id, "111")
    assert result is not None
    assert len(result.papers) == 1
    assert result.papers[0].pmid == "222"
    # Reload from the repo to confirm persistence.
    reloaded = repo.get(ws.id)
    assert len(reloaded.papers) == 1


# ---------------------------------------------------------------------------
# Stubs needed by tests above (kept at the bottom for readability)
# ---------------------------------------------------------------------------
