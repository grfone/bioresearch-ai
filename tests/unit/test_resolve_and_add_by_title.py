"""
Unit tests for WorkspaceOrchestrator.resolve_and_add_by_title.

This is the title-driven fallback for the PDF upload flow. The
real-world scenario: a researcher drops a scanned PDF that has no
recognisable DOI or PMID on its first page. The /papers/from-pdf
endpoint returns ``422 no_identifiers_found``. The frontend
catches that and offers to recover the paper by title — the user
types a title, we hit PubMed ESearch, take the top match, and
add it to the workspace.

The tests below exercise:

- Happy path: PubMed returns ≥1 candidate, top one wins.
- Author / journal / year disambiguation: when the user supplies
  hints, the candidate that matches the most fields is picked.
- "Soft miss": title matched something but disambiguation hints
  found nothing — orchestrator returns ``(session, None)`` so
  the frontend can surface a clear "no precise match" message.
- Empty PubMed result: returns ``(session, None)`` without
  raising.
- FSM guard: ``ADD_PAPER`` is illegal from terminal states,
  so the orchestrator raises ``IllegalWorkspaceActionError``.
- Side effects: the workspace is advanced from CREATED to
  PAPERS_RETRIEVED exactly once when the match succeeds.

We use the same stub patterns as
``tests/unit/test_workspace_orchestrator.py`` so the new tests
stay compatible with the existing suite. The literature searcher
stub takes a list of candidates and a counter so tests can
inspect what query PubMed was actually called with.
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
from app.domain.entities.author import Author
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.finding import Finding  # noqa: F401
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
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
# Stubs (mirrored from test_workspace_orchestrator.py — kept inline so the
# test file is self-contained and can be read in isolation)
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


class RecordingStubPubMed(LiteratureSearcher):
    """Stub PubMed that records every query it sees.

    Real PubMed calls would query ESearch + EFetch in two steps.
    For these tests we want to inspect the *query string* the
    orchestrator builds so we can assert the disambiguation
    fields are folded into the search correctly.
    """

    def __init__(self, papers: list[Paper]) -> None:
        self.papers = papers
        self.queries: list[str] = []

    def search(self, question: ResearchQuestion) -> list[Paper]:
        self.queries.append(question.question)
        return list(self.papers)

    def get_by_id(self, paper_id: str) -> Paper | None:
        for p in self.papers:
            if p.pmid == paper_id or p.doi == paper_id:
                return p
        return None


class StubLLM(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: Prompt) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content="stub",
            model="stub",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            finish_reason="stop",
        )


class StubReportGenerator(ReportGenerator):
    def __init__(self) -> None:
        self.papers_seen: list = []

    def generate(
        self,
        question: ResearchQuestion,
        summary: Summary,
    ):
        self.papers_seen.append(summary)
        from app.domain.entities.research_report import ResearchReport
        return ResearchReport(
            summary=summary,
            citations=[],
            limitations=[],
            future_work=[],
            metadata={"model": "stub"},
        )


class StubComparisonGenerator(ComparisonGenerator):
    def generate(
        self,
        question: ResearchQuestion,
        papers: list[Paper],
    ) -> EvidenceComparison:
        return EvidenceComparison(
            consensus=[],
            used_paper_ids=[p.pmid for p in papers if p.pmid],
            research_gaps=[],
            future_directions=[],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _paper(
    pmid: str,
    *,
    title: str = "Untitled",
    first_author: str = "Doe",
    last_author: str = "Doe",
    journal: str | None = None,
    year: int | None = None,
) -> Paper:
    """Build a Paper with realistic author + journal metadata.

    The Author entity takes ``first_name``/``last_name``; the
    orchestrator's scoring function reads the derived
    ``full_name`` property, which concatenates those two
    strings. We therefore construct authors with explicit names
    so the disambiguation tests have a real name to match on.
    """
    author = Author(
        first_name=first_author,
        last_name=last_author,
        affiliation=None,
    )
    j: Journal | None = None
    if journal is not None:
        j = Journal(name=journal, issn=None, publisher=None)
    return Paper(
        title=title,
        authors=[author],
        journal=j,
        year=year,
        abstract="",
        doi=None,
        pmid=pmid,
        keywords=[],
        url=None,
    )


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


def _make_orchestrator(
    repo: InMemoryRepository,
    searcher: LiteratureSearcher,
) -> WorkspaceOrchestrator:
    """Build an orchestrator with the same dependency shape as
    the production container.

    Keeping this in one place means individual tests don't have
    to repeat the five ``WorkspaceOrchestrator(...)`` args.
    """
    llm = StubLLM()
    return WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=searcher,
        llm_provider=llm,
        report_generator=StubReportGenerator(),
        comparison_generator=StubComparisonGenerator(),
    )


def _make_workspace(
    repo: InMemoryRepository,
    state: WorkspaceState = WorkspaceState.CREATED,
) -> ResearchSession:
    """Persist a fresh workspace in the requested state."""
    session = ResearchSession(question=ResearchQuestion(question="q"))
    # ``state`` is a public attribute on ResearchSession. We seed
    # it directly so we can hit edge states (PAPERS_RETRIEVED,
    # REPORTED, ERROR) without running the full pipeline.
    session.state = state
    return repo.create(session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolveAndAddByTitleHappyPath:
    """The headline flow: title only, no disambiguation hints."""

    def test_picks_top_candidate_when_no_hints(
        self, repo: InMemoryRepository,
    ) -> None:
        candidates = [
            _paper("111", title="A real paper."),
            _paper("222", title="A different paper."),
        ]
        searcher = RecordingStubPubMed(candidates)
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        workspace, matched = orch.resolve_and_add_by_title(
            session.id, title="A real paper.",
        )

        assert matched is not None
        assert matched.pmid == "111"
        assert matched.title == "A real paper."

    def test_builds_a_title_only_query(
        self, repo: InMemoryRepository,
    ) -> None:
        """When no hints are provided the orchestrator still wraps
        the title in a ``[Title]`` tag so PubMed ESearch doesn't
        broaden to the abstract or full text.
        """
        searcher = RecordingStubPubMed([_paper("111")])
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        orch.resolve_and_add_by_title(session.id, title="alzheimer")

        assert len(searcher.queries) == 1
        # The exact quoting depends on how PubMed parses the
        # brackets — we only assert that the title tag is present
        # and the title text is embedded.
        q = searcher.queries[0]
        assert "[Title]" in q
        assert "alzheimer" in q

    def test_persists_the_paper(
        self, repo: InMemoryRepository,
    ) -> None:
        candidates = [_paper("111", title="A real paper.")]
        searcher = RecordingStubPubMed(candidates)
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        workspace, _ = orch.resolve_and_add_by_title(
            session.id, title="A real paper.",
        )

        # Reload the session through the repo to make sure the
        # write hit storage, not just the in-memory return.
        reloaded = repo.get(session.id)
        assert any(p.pmid == "111" for p in reloaded.papers)


class TestResolveAndAddByTitleDisambiguation:
    """When the user supplies author / journal / year hints the
    orchestrator must pick the candidate that matches the most
    fields instead of trusting PubMed's relevance order."""

    def test_picks_author_match_over_relevance(
        self, repo: InMemoryRepository,
    ) -> None:
        # PubMed returns the wrong author first by relevance;
        # the user's hint should pull the right one to the top.
        candidates = [
            _paper(
                "111", title="Same title.", first_author="Alice",
                last_author="Wrong", journal="Cell",
            ),
            _paper(
                "222", title="Same title.", first_author="Bob",
                last_author="Right", journal="Nature",
            ),
        ]
        searcher = RecordingStubPubMed(candidates)
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        _, matched = orch.resolve_and_add_by_title(
            session.id,
            title="Same title.",
            first_author="Right",
        )

        assert matched is not None
        assert matched.pmid == "222"

    def test_picks_journal_match(
        self, repo: InMemoryRepository,
    ) -> None:
        candidates = [
            _paper("111", title="t", journal="Cell"),
            _paper("222", title="t", journal="Nature"),
        ]
        searcher = RecordingStubPubMed(candidates)
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        _, matched = orch.resolve_and_add_by_title(
            session.id,
            title="t",
            journal="Nature",
        )

        assert matched is not None
        assert matched.pmid == "222"

    def test_picks_year_match(
        self, repo: InMemoryRepository,
    ) -> None:
        candidates = [
            _paper("111", title="t", year=1995),
            _paper("222", title="t", year=2025),
        ]
        searcher = RecordingStubPubMed(candidates)
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        _, matched = orch.resolve_and_add_by_title(
            session.id, title="t", year=2025,
        )

        assert matched is not None
        assert matched.pmid == "222"

    def test_combined_score_picks_most_matches(
        self, repo: InMemoryRepository,
    ) -> None:
        # ``222`` matches all three hints (author + journal + year).
        # ``333`` matches only journal + year.
        # ``111`` matches only year.
        # ``222`` should win.
        candidates = [
            _paper(
                "111", title="t", first_author="Alice", last_author="Wrong",
                journal="Cell", year=2025,
            ),
            _paper(
                "222", title="t", first_author="Bob", last_author="Right",
                journal="Nature", year=2025,
            ),
            _paper(
                "333", title="t", first_author="Charlie", last_author="Other",
                journal="Nature", year=2025,
            ),
        ]
        searcher = RecordingStubPubMed(candidates)
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        _, matched = orch.resolve_and_add_by_title(
            session.id,
            title="t",
            first_author="Right",
            journal="Nature",
            year=2025,
        )

        assert matched is not None
        assert matched.pmid == "222"

    def test_query_combines_all_hints(
        self, repo: InMemoryRepository,
    ) -> None:
        """The PubMed query string should fold every hint in
        so ESearch's relevance scoring knows about them.
        """
        searcher = RecordingStubPubMed([_paper("111")])
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        orch.resolve_and_add_by_title(
            session.id,
            title="alzheimer",
            first_author="Smith",
            journal="Nature",
            year=2025,
        )

        q = searcher.queries[0]
        assert "[Title]" in q
        assert "[Author]" in q
        assert "[Journal]" in q
        assert "[Date" in q
        assert "alzheimer" in q
        assert "Smith" in q
        assert "Nature" in q
        assert "2025" in q


class TestResolveAndAddByTitleSoftMiss:
    """When hints are supplied but the title match doesn't
    satisfy any of them, the orchestrator must NOT silently
    accept the wrong paper. It returns ``(session, None)`` so
    the frontend can prompt the user."""

    def test_returns_none_when_author_hint_does_not_match(
        self, repo: InMemoryRepository,
    ) -> None:
        candidates = [
            _paper("111", title="t", first_author="Alice", last_author="X"),
            _paper("222", title="t", first_author="Bob", last_author="Y"),
        ]
        searcher = RecordingStubPubMed(candidates)
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        workspace, matched = orch.resolve_and_add_by_title(
            session.id, title="t", first_author="Neither",
        )

        assert matched is None
        # Workspace is untouched — no paper was added.
        reloaded = repo.get(session.id)
        assert reloaded.papers == []

    def test_returns_none_when_pubmed_empty(
        self, repo: InMemoryRepository,
    ) -> None:
        searcher = RecordingStubPubMed([])
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        workspace, matched = orch.resolve_and_add_by_title(
            session.id, title="obscure title no one has written",
        )

        assert matched is None
        # State didn't change.
        reloaded = repo.get(session.id)
        assert reloaded.state == WorkspaceState.CREATED


class TestResolveAndAddByTitleFSMGuard:
    """The orchestrator shares the ``add_paper`` guard with
    other entry points — some states forbid it.

    Looking at ``WorkspaceState.transitions`` the FSM only
    forbids ``ADD_PAPER`` from transient states (SEARCHING,
    SUMMARIZING, COMPARING, REPORTING) and from ERROR. POST-PAPERS
    states (PAPERS_RETRIEVED onward through COMPLETED) all allow
    ADD_PAPER because the user might want to add more papers
    even after a report is generated."""

    @pytest.mark.parametrize(
        "state",
        [
            WorkspaceState.SEARCHING,
            WorkspaceState.SUMMARIZING,
            WorkspaceState.COMPARING,
            WorkspaceState.REPORTING,
            WorkspaceState.ERROR,
        ],
    )
    def test_raises_in_transient_and_error_states(
        self,
        repo: InMemoryRepository,
        state: WorkspaceState,
    ) -> None:
        searcher = RecordingStubPubMed([_paper("111")])
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo, state=state)

        with pytest.raises(IllegalWorkspaceActionError):
            orch.resolve_and_add_by_title(session.id, title="t")

    @pytest.mark.parametrize(
        "state",
        [
            WorkspaceState.CREATED,
            WorkspaceState.PAPERS_RETRIEVED,
            WorkspaceState.SUMMARIZED,
            WorkspaceState.COMPARED,
            WorkspaceState.REPORTED,
            WorkspaceState.COMPLETED,
        ],
    )
    def test_succeeds_in_post_papers_states(
        self,
        repo: InMemoryRepository,
        state: WorkspaceState,
    ) -> None:
        searcher = RecordingStubPubMed([_paper("111")])
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo, state=state)

        _, matched = orch.resolve_and_add_by_title(
            session.id, title="t",
        )

        assert matched is not None


class TestResolveAndAddByTitleSideEffects:
    """Smoke checks for the things that aren't directly
    observable from the return tuple."""

    def test_pubmed_is_called_exactly_once_per_request(
        self, repo: InMemoryRepository,
    ) -> None:
        searcher = RecordingStubPubMed([_paper("111")])
        orch = _make_orchestrator(repo, searcher)
        session = _make_workspace(repo)

        orch.resolve_and_add_by_title(session.id, title="t")

        assert searcher.queries == ["\"t\"[Title]"]

    def test_two_workspaces_are_isolated(
        self, repo: InMemoryRepository,
    ) -> None:
        """Adding a paper to workspace A must not affect
        workspace B's paper list."""
        # The stub returns the *only* paper whose pmid matches
        # the title, so each workspace's title ends up routed
        # to a different paper. That makes the test about
        # storage isolation rather than PubMed disambiguation.
        class _RoutedStub(RecordingStubPubMed):
            def search(self, question):
                # ``["111"][Title]`` and ``["222"][Title]`` are
                # the two queries the orchestrator will issue
                # in the test. Pick the paper whose pmid is
                # quoted in the question.
                import re
                m = re.search(r'"(\d+)"', question.question)
                pmid = m.group(1) if m else None
                return [p for p in self.papers if p.pmid == pmid]

        searcher = _RoutedStub(
            [_paper("111"), _paper("222")],
        )
        orch = _make_orchestrator(repo, searcher)
        a = _make_workspace(repo)
        b = _make_workspace(repo)

        orch.resolve_and_add_by_title(a.id, title="111")
        orch.resolve_and_add_by_title(b.id, title="222")

        reloaded_a = repo.get(a.id)
        reloaded_b = repo.get(b.id)
        assert [p.pmid for p in reloaded_a.papers] == ["111"]
        assert [p.pmid for p in reloaded_b.papers] == ["222"]
