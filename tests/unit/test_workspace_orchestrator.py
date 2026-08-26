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
from app.domain.interfaces.pdf_generator import PDFGenerator
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


class StubPDFGenerator(PDFGenerator):
    """Stub that returns canned PDF bytes and records what it saw.

    The canned payload is a minimal valid PDF (starts with
    ``b"%PDF-"``) so the PublishedReport validator doesn't
    reject it. Tests that need to assert on the rendered output
    can inspect ``calls`` to see which reports were rendered.
    """

    # Hand-rolled minimal valid PDF (single page, empty content
    # stream). Just enough for ``PublishedReport.__post_init__``
    # to accept it. We deliberately keep this byte literal in
    # source rather than constructing at runtime -- if the magic
    # header ever changes, the test breaks loudly here, not in
    # production.
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


# Lazy import to avoid circulars
from app.domain.entities.finding import Finding


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _paper(pmid: str) -> Paper:
    return Paper(title=f"Paper {pmid}", pmid=pmid, abstract="abs")


def _make_report(text: str = "Executive summary.") -> ResearchReport:
    """Build a minimal valid ResearchReport for orchestrator tests.

    Used by the PUBLISH tests (positive, audit-trail, structural).
    Returns a report with a single Summary whose ``text`` is
    whatever the test wants to render. Empty citations,
    limitations, and future_work lists -- the PDF generator
    stub is what produces the bytes; the report contents only
    need to satisfy the orchestrator's "report exists" check.
    """
    return ResearchReport(
        summary=Summary(text=text, papers_used=[]),
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
        report_generator=StubReportGenerator([]),
        comparison_generator=StubComparisonGenerator(),
        pdf_generator=StubPDFGenerator(),
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
        pdf_generator=StubPDFGenerator(),
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
        pdf_generator=StubPDFGenerator(),
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
        pdf_generator=StubPDFGenerator(),
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


def test_report_auto_summarises_when_summary_missing(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    """One-click report from PAPERS_RETRIEVED.

    Historically ``WorkspaceOrchestrator.report()`` raised
    ``IllegalWorkspaceActionError`` when ``session.summary is
    None``. Per ADR-008 the orchestrator now auto-summarises
    first so the user can get a report with one click.

    The new contract:

      1. ``report()`` does NOT raise when ``summary is None``.
      2. The orchestrator calls ``summarize()`` first
         (the state machine records the intermediate
         ``SUMMARIZING -> SUMMARIZED`` transitions).
      3. The final state is ``REPORTED``.
      4. The report generator sees a populated summary.
    """
    # Replace the orchestrator's summarise use case with one
    # that uses a stub LLM (the fixture already has
    # ``StubLLM()`` wired in). We construct a fresh
    # ``SummarizePapersUseCase`` here so this test stays
    # self-contained -- no monkeypatching.
    class _MarkerLLM(LLMProvider):
        """Stub LLM whose output lets us prove auto-summarise ran."""

        def generate(self, prompt: Prompt):
            return LLMResponse(
                content="auto-summarise-marker",
                model="stub",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                finish_reason="stop",
            )

    orchestrator._summarize_use_case = SummarizePapersUseCase(_MarkerLLM())

    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.PAPERS_RETRIEVED,
    )
    ws.add_papers([_paper("111")])
    repo.create(ws)

    # Should NOT raise -- the orchestrator auto-summarises
    # transparently and proceeds to the report step.
    result = orchestrator.report(ws.id)

    # Final state should be REPORTED, with summary populated.
    assert result.state is WorkspaceState.REPORTED
    assert result.summary is not None
    # The marker proves the summarise step actually ran.
    assert "auto-summarise-marker" in result.summary.text


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


def test_publish_advances_reported_to_completed_via_publishing(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    """Positive test: PUBLISH from REPORTED advances the FSM to
    COMPLETED and renders a PDF.

    The FSM walk is REPORTED -> PUBLISHING -> COMPLETED, but the
    intermediate PUBLISHING is transient -- only COMPLETED is
    observable in ``session.state`` after the call returns.
    The audit-trail test below pins the PUBLISHING step in
    ``state_history``.
    """
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.REPORTED,
    )
    ws.set_report(
        _make_report(text="This is the executive summary.")
    )
    repo.create(ws)

    result = orchestrator.publish(ws.id)

    # Final state is the terminal COMPLETED.
    assert result.state is WorkspaceState.COMPLETED
    # The PDF was persisted on the session.
    assert result.published_report is not None
    assert result.published_report.pdf_bytes.startswith(b"%PDF-")
    # The stub PDF generator's canned bytes were used.
    assert (
        result.published_report.pdf_bytes
        == StubPDFGenerator._CANNED_BYTES
    )


def test_publish_records_audit_trail_through_publishing_state(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    """Audit-trail test: state_history records the transient
    PUBLISHING step with a reason string.

    Users see "REPORTED -> COMPLETED" in the visible state but
    the FSM actually walked REPORTED -> PUBLISHING -> COMPLETED.
    The state_history JSON column records every transition with
    a ``reason`` distinguishing user-initiated from
    auto-triggered -- so a future maintainer (or a forensic
    audit) can tell that PUBLISHING was a real intermediate step,
    not just a synthetic state for show.
    """
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.REPORTED,
    )
    ws.set_report(_make_report(text="Summary."))
    repo.create(ws)

    orchestrator.publish(ws.id)

    persisted = repo.get(ws.id)
    transitions = persisted.state_history
    # Filter out the synthetic CREATED entry whose ``action``
    # is None (per StateTransition.action: WorkspaceAction | None).
    # Real transitions always carry an action or a ``reason``.
    actions = [
        t.action for t in transitions if t.action is not None
    ]
    # The PUBLISH transition must be in the history. We compare
    # ``.value`` strings since action values are enums.
    action_values = [a.value for a in actions]
    assert WorkspaceAction.PUBLISH.value in action_values, (
        f"PUBLISH transition not found in state_history; got: "
        f"{action_values}"
    )
    # Find the PUBLISHING transition and assert its reason.
    publishing_tx = next(
        t for t in transitions
        if t.action == WorkspaceAction.PUBLISH
    )
    assert publishing_tx.to_state is WorkspaceState.PUBLISHING
    assert publishing_tx.from_state is WorkspaceState.REPORTED
    # The reason string is the contract: changing it requires
    # updating this test and the orchestrator's docstring.
    assert publishing_tx.reason == "PDF export in flight"
    # And the COMPLETED transition (auto-triggered, not user-
    # initiated) -- we use ``force_state`` for this because no
    # WorkspaceAction is associated with it.
    completed_tx = next(
        t for t in transitions if t.to_state == WorkspaceState.COMPLETED
    )
    assert completed_tx.reason == "PDF published"


def test_publish_from_other_states_raises_illegal_action(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    """Negative test: PUBLISH is only legal from REPORTED.

    Picks REPORTED from the four states where the action is
    still illegal under the new contract:
      - CREATED, PAPERS_RETRIEVED, SUMMARIZED, COMPARING.
    Each one should raise IllegalWorkspaceActionError with the
    current state + allowed-actions list so the frontend can
    render a useful "you need to generate a report first"
    message. (COMPLETED is also illegal but the workflow
    typically prevents that path -- we keep the test focused
    on the user-facing "didn't generate a report" failure.)
    """
    illegal_states = [
        WorkspaceState.CREATED,
        WorkspaceState.PAPERS_RETRIEVED,
        WorkspaceState.SUMMARIZED,
        WorkspaceState.COMPARING,
    ]
    for state in illegal_states:
        ws = ResearchSession(
            question=ResearchQuestion(question="x"),
            state=state,
        )
        repo.create(ws)
        with pytest.raises(IllegalWorkspaceActionError) as exc_info:
            orchestrator.publish(ws.id)
        # The error carries enough context for the frontend to
        # tell the user why -- current state + allowed actions.
        # ``allowed`` is a ``list[str]`` (per IllegalWorkspaceActionError
        # signature), so we compare strings, not enum values.
        assert exc_info.value.current_state == state.value
        assert "publish" not in exc_info.value.allowed, (
            f"PUBLISH leaked into allowed_actions for state "
            f"{state.value}; the FSM table is wrong."
        )


def test_publish_persists_pdf_in_repository(
    orchestrator: WorkspaceOrchestrator,
    repo: InMemoryRepository,
) -> None:
    """Structural pin: the PDF bytes are persisted on the
    session AND survive a refetch through the repository.

    This is the Layer-3-audit test: it pins that
    ``set_published_report`` was called and that the repository
    ``update`` actually wrote the bytes. Without this test, a
    future refactor could accidentally call
    ``session.set_report(report)`` but forget the
    ``set_published_report(published_report)`` call -- the PDF
    would be rendered but the user couldn't download it.

    The test uses the in-memory repository because the SQLite
    repository's ``PublishedReport`` serialization is a separate
    concern (covered by test_published_report_in_serialized).
    """
    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.REPORTED,
    )
    ws.set_report(_make_report(text="Summary."))
    repo.create(ws)

    orchestrator.publish(ws.id)

    # Refetch -- exercises the repo's deserialization path.
    refetched = repo.get(ws.id)
    assert refetched.published_report is not None
    assert refetched.published_report.pdf_bytes == StubPDFGenerator._CANNED_BYTES
    # And the bytes round-trip the magic-header check.
    assert refetched.published_report.pdf_bytes.startswith(b"%PDF-")


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
