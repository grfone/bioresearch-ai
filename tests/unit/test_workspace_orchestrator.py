"""
Unit tests for the WorkspaceOrchestrator.

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
from app.application.use_cases.compare_evidence import CompareEvidenceUseCase
from app.application.use_cases.generate_report import GenerateReportUseCase
from app.application.use_cases.search_literature import SearchLiteratureUseCase
from app.application.use_cases.summarize_papers import SummarizePapersUseCase
from app.core.enums.workspace_state import (
    WorkspaceAction,
    WorkspaceState,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary
from app.domain.interfaces.comparison_generator import ComparisonGenerator
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.interfaces.literature_searcher import LiteratureSearcher
from app.domain.interfaces.report_generator import ReportGenerator
from app.domain.interfaces.workspace_repository import WorkspaceRepository
from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class InMemoryRepository(WorkspaceRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, ResearchSession] = {}

    def create(self, workspace: ResearchSession) -> ResearchSession:
        if workspace.id in self._store:
            raise ValueError(f"Workspace '{workspace.id}' already exists.")
        self._store[workspace.id] = workspace
        return workspace

    def get(self, workspace_id: UUID) -> ResearchSession:
        if workspace_id not in self._store:
            raise ValueError(f"Workspace '{workspace_id}' not found.")
        return self._store[workspace_id]

    def update(self, workspace: ResearchSession) -> ResearchSession:
        if workspace.id not in self._store:
            raise ValueError(f"Workspace '{workspace.id}' not found.")
        self._store[workspace.id] = workspace
        return workspace

    def delete(self, workspace_id: UUID) -> None:
        self._store.pop(workspace_id, None)

    def exists(self, workspace_id: UUID) -> bool:
        return workspace_id in self._store

    def list_workspaces(self) -> list[ResearchSession]:
        return list(self._store.values())

    def workspace_state_counts(self) -> dict[str, int]:
        """Test stub -- counts workspaces per state, zero-filling."""
        from app.core.enums.workspace_state import WorkspaceState
        counts = {state.value: 0 for state in WorkspaceState}
        for session in self._store.values():
            counts[session.state.value] += 1
        return counts


class StubPubMed(LiteratureSearcher):
    """Stub that returns a fixed paper list for any search."""

    def __init__(self, papers: list[Paper]) -> None:
        self.papers = papers
        self.call_count = 0

    def search(self, question: ResearchQuestion) -> list[Paper]:
        self.call_count += 1
        return list(self.papers)

    def get_by_id(self, paper_id: str) -> Paper | None:
        for p in self.papers:
            if p.pmid == paper_id or p.doi == paper_id:
                return p
        return None


class StubLLM(LLMProvider):
    """Stub LLM that returns a fixed response."""

    def __init__(self, content: str = "stub") -> None:
        self.calls = 0
        self._content = content

    def generate(self, prompt: Prompt) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content=self._content,
            model="stub",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            finish_reason="stop",
        )


class StubReportGenerator(ReportGenerator):
    """Track which papers are passed to the report step."""

    def __init__(self, papers_seen: list[Paper]) -> None:
        self.papers_seen = papers_seen

    def generate(
        self,
        question: ResearchQuestion,
        summary: Summary,
    ) -> ResearchReport:
        self.papers_seen.append(Summary)
        return ResearchReport(
            summary=summary,
            citations=[],
            limitations=[],
            future_work=[],
            metadata={"model": "stub"},
        )


class StubComparisonGenerator(ComparisonGenerator):
    """Stub that returns a deterministic comparison."""

    def generate(
        self,
        question: ResearchQuestion,
        papers: list[Paper],
    ) -> EvidenceComparison:
        return EvidenceComparison(
            consensus=[
                Finding(claim="x", paper_ids=[f"pmid:{p.pmid}"])
                for p in papers if p.pmid
            ],
            used_paper_ids=[p.pmid for p in papers if p.pmid],
            research_gaps=["gap1"],
            future_directions=["future1"],
        )


# Lazy import to avoid circulars
from app.domain.entities.finding import Finding


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _paper(pmid: str) -> Paper:
    return Paper(title=f"Paper {pmid}", pmid=pmid, abstract="abs")


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
        report_generator=StubReportGenerator([]),
        comparison_generator=StubComparisonGenerator(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_workspace_is_in_created_state() -> None:
    repo = InMemoryRepository()
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator([]),
        comparison_generator=StubComparisonGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?")
    )
    repo.create(ws)
    loaded = orch.get_workspace(ws.id)
    assert loaded.state is WorkspaceState.CREATED


def test_search_advances_to_papers_retrieved(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
    stub_papers: list[Paper],
) -> None:
    ws = ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?")
    )
    repo.create(ws)

    result = orchestrator.search(ws.id)
    assert result.state is WorkspaceState.PAPERS_RETRIEVED
    assert len(result.papers) == 2


def test_summarize_advances_to_summarized(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.PAPERS_RETRIEVED,
    )
    ws.add_papers([_paper("111")])
    repo.create(ws)

    result = orchestrator.summarize(ws.id)
    assert result.state is WorkspaceState.SUMMARIZED
    assert result.summary is not None


def test_summarize_raises_when_no_papers(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(question=ResearchQuestion(question="x"))
    repo.create(ws)
    with pytest.raises(IllegalWorkspaceActionError):
        orchestrator.summarize(ws.id)


def test_compare_advances_to_compared(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.SUMMARIZED,
    )
    ws.add_papers([_paper("111"), _paper("222")])
    repo.create(ws)

    result = orchestrator.compare(ws.id)
    assert result.state is WorkspaceState.COMPARED
    assert result.evidence_comparison is not None
    assert result.evidence_comparison.research_gaps == ["gap1"]


def test_compare_rejects_fabricated_citations(
    repo: InMemoryRepository,
) -> None:
    """The validator must reject a comparison that cites papers not
    in the workspace."""
    from app.domain.entities.evidence_comparison import EvidenceComparison
    from app.domain.entities.finding import Finding
    from app.domain.entities.paper import Paper

    class BadComparisonGenerator(ComparisonGenerator):
        def generate(self, question, papers):
            return EvidenceComparison(
                consensus=[Finding(claim="x", paper_ids=["pmid:99999"])],
                used_paper_ids=["99999"],
            )

    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator([]),
        comparison_generator=BadComparisonGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.SUMMARIZED,
    )
    ws.add_papers([_paper("111")])
    repo.create(ws)

    with pytest.raises(Exception):
        orch.compare(ws.id)

    # Workspace should be in ERROR state after the failure.
    failed = repo.get(ws.id)
    assert failed.state is WorkspaceState.ERROR


def test_report_uses_workspace_papers_not_research(
    repo: InMemoryRepository,
) -> None:
    """Regression: the report must use the workspace's papers, not
    re-search PubMed. This is the bug the FSM refactor fixes."""
    pubmed = StubPubMed([_paper("99999")])
    papers_seen: list = []
    report_gen = _RecordingReportGenerator(papers_seen)
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=pubmed,
        llm_provider=StubLLM(),
        report_generator=report_gen,
        comparison_generator=StubComparisonGenerator(),
    )
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.SUMMARIZED,
    )
    workspace_papers = [_paper("111"), _paper("222")]
    ws.add_papers(workspace_papers)
    repo.create(ws)

    # Force a summary (the stub LLM doesn't matter here).
    ws2 = repo.get(ws.id)
    ws2.set_summary(Summary(text="stub", papers_used=workspace_papers))
    repo.update(ws2)

    orch.report(ws.id)

    # PubMed must NOT have been called.
    assert pubmed.call_count == 0
    # The report generator must have received the workspace's papers.
    assert papers_seen == ["111", "222"]


def test_report_raises_when_no_summary(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.PAPERS_RETRIEVED,
    )
    ws.add_papers([_paper("111")])
    repo.create(ws)
    with pytest.raises(IllegalWorkspaceActionError):
        orchestrator.report(ws.id)


def test_complete_advances_to_completed(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.REPORTED,
    )
    repo.create(ws)
    result = orchestrator.complete(ws.id)
    assert result.state is WorkspaceState.COMPLETED


def test_retry_returns_to_creatable(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.ERROR,
        last_error="network",
    )
    repo.create(ws)
    result = orchestrator.retry(ws.id)
    assert result.state is WorkspaceState.CREATED
    assert result.last_error is None


def test_allowed_actions_reflects_state(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(question=ResearchQuestion(question="x"))
    repo.create(ws)
    actions = orchestrator.allowed_actions(ws.id)
    assert WorkspaceAction.SEARCH in actions
    assert WorkspaceAction.REPORT not in actions


def test_remove_paper_persists(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.PAPERS_RETRIEVED,
    )
    ws.add_papers([_paper("111"), _paper("222")])
    repo.create(ws)

    result = orchestrator.remove_paper(ws.id, "111")
    assert len(result.papers) == 1
    assert result.papers[0].pmid == "222"


# ---------------------------------------------------------------------------
# Internal test helper
# ---------------------------------------------------------------------------


class _RecordingReportGenerator(ReportGenerator):
    """Captures the PMIDs of the papers that were passed in."""

    def __init__(self, papers_seen: list) -> None:
        self._papers_seen = papers_seen

    def generate(
        self,
        question: ResearchQuestion,
        summary: Summary,
    ) -> ResearchReport:
        self._papers_seen.extend(summary.papers_used and [p.pmid for p in summary.papers_used] or [])
        return ResearchReport(
            summary=summary,
            citations=[],
            limitations=[],
            future_work=[],
            metadata={"model": "stub"},
        )
