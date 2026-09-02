"""
Unit tests for ADR-019: ``ResearchSession`` enforces the invariant
that every ``Citation`` (and every entry in
``Summary.papers_used``) is a paper present in
``self.papers``.

The user's hard rule is documented in this ADR:

    "the executive reports can contain only references
    available at INTERMEDIATE, not more (less is possible, but
    definitely not more!)"

These tests pin the structural enforcement at the entity layer
so the rule cannot be silently violated by future code.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import pytest

from app.core.enums.workspace_state import WorkspaceState
from app.core.enums.citation_style import CitationStyleEnum
from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_paper(pmid: str, title: str = "T") -> Paper:
    """Build a real Paper with stable PMID identity.

    The ``_paper_identity`` helper in ``ResearchSession`` uses
    PMID as the primary key, so the PMID alone uniquely identifies
    the paper regardless of ``title`` or ``abstract`` rewrites.
    Tests use that property to construct "logically the same"
    papers that compare as equal under the identity helper.
    """
    return Paper(
        pmid=pmid,
        title=title,
        authors=[Author(first_name="Jane", last_name="Doe")],
        abstract=f"Abstract for {pmid}.",
    )


def _make_session(*papers: Paper, state: WorkspaceState = WorkspaceState.INITIAL) -> ResearchSession:
    """Build a session with the given papers already in INTERMEDIATE."""
    session = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=state,
    )
    if papers:
        session.replace_papers(list(papers))
    return session


def _make_summary(*papers: Paper) -> Summary:
    return Summary(body="", papers_used=list(papers))


def _make_report(*citation_papers: Paper) -> ResearchReport:
    return ResearchReport(
        summary=_make_summary(*citation_papers),
        citations=[
            Citation(paper=p, style=CitationStyleEnum.APA) for p in citation_papers
        ],
        limitations=[],
        future_work=[],
        metadata={},
    )


# ---------------------------------------------------------------------------
# Invariant: set_summary validates
# ---------------------------------------------------------------------------


class TestSetSummaryValidatesPapersUsed:
    """``set_summary`` must validate that every paper in
    ``summary.papers_used`` is in ``self.papers``."""

    def test_set_summary_accepts_papers_within_corpus(self) -> None:
        p1 = _make_paper("111")
        p2 = _make_paper("222")
        session = _make_session(p1, p2)
        # No exception expected.
        session.set_summary(_make_summary(p1, p2))
        assert session.summary is not None

    def test_set_summary_rejects_paper_outside_corpus(self) -> None:
        p1 = _make_paper("111")
        p2 = _make_paper("222")
        session = _make_session(p1, p2)
        outside = _make_paper("333")
        with pytest.raises(ValueError, match="references papers not in workspace.papers"):
            session.set_summary(_make_summary(p1, outside))

    def test_set_summary_error_lists_offending_identifiers(self) -> None:
        """Diagnostics: the error message must name the offending
        papers so an operator can investigate."""
        p1 = _make_paper("111")
        session = _make_session(p1)
        outside = _make_paper("999")
        with pytest.raises(ValueError) as exc_info:
            session.set_summary(_make_summary(outside))
        msg = str(exc_info.value)
        assert "pmid=999" in msg
        assert "workspace.papers.size=1" in msg
        assert "summary.papers_used.size=1" in msg

    def test_set_summary_accepts_empty_papers_used(self) -> None:
        """An empty summary is valid even when the corpus is
        empty -- nothing to validate. (Defensive: a malformed
        LLM might emit an empty bibliography.)"""
        session = _make_session()  # No papers in corpus.
        session.set_summary(_make_summary())  # Empty summary.
        assert session.summary is not None


# ---------------------------------------------------------------------------
# Invariant: set_report validates
# ---------------------------------------------------------------------------


class TestSetReportValidatesCitations:
    """``set_report`` must validate that every citation's paper is
    in ``self.papers``."""

    def test_set_report_accepts_citations_within_corpus(self) -> None:
        p1 = _make_paper("111")
        p2 = _make_paper("222")
        session = _make_session(p1, p2)
        session.set_report(_make_report(p1, p2))
        assert session.report is not None

    def test_set_report_rejects_citation_outside_corpus(self) -> None:
        p1 = _make_paper("111")
        session = _make_session(p1)
        outside = _make_paper("999")
        with pytest.raises(ValueError, match="references papers not in workspace.papers"):
            session.set_report(_make_report(p1, outside))

    def test_set_report_error_message_names_offending_paper(self) -> None:
        p1 = _make_paper("111")
        session = _make_session(p1)
        outside = _make_paper("777")
        with pytest.raises(ValueError) as exc_info:
            session.set_report(_make_report(outside))
        msg = str(exc_info.value)
        assert "report.citations" in msg
        assert "pmid=777" in msg

    def test_set_report_rejected_state_does_not_persist(self) -> None:
        """If ``set_report`` raises, the prior ``self.report`` is
        NOT clobbered. This keeps the user from losing their
        existing report to a buggy future code path that tries
        to overwrite it with an invalid one."""
        p1 = _make_paper("111")
        session = _make_session(p1)
        valid_report = _make_report(p1)
        session.set_report(valid_report)
        assert session.report is valid_report
        # Now try to set an invalid report.
        invalid_paper = _make_paper("999")
        with pytest.raises(ValueError):
            session.set_report(_make_report(invalid_paper))
        # The valid report is still there.
        assert session.report is valid_report


# ---------------------------------------------------------------------------
# Invariant: identity comparison (dedup-aware)
# ---------------------------------------------------------------------------


class TestIdentityComparisonForValidation:
    """The validation uses ``_paper_identity`` (PMID → DOI → URL
    fallback) so two papers with the same PMID compare as equal
    even if the LLM rewrote their ``title`` or ``abstract`` during
    synthesis. This is the same dedup semantics
    :meth:`add_papers` uses."""

    def test_paper_with_same_pmid_but_rewritten_title_is_in_corpus(self) -> None:
        """A summary paper whose title was rewritten by the LLM
        still matches the workspace paper that has the same PMID."""
        workspace_paper = _make_paper("111", title="Original title")
        session = _make_session(workspace_paper)
        summary_paper = _make_paper("111", title="Rewritten title by LLM")
        # No exception — same PMID is the same paper.
        session.set_summary(_make_summary(summary_paper))

    def test_paper_with_different_pmid_is_outside_corpus(self) -> None:
        """Different PMID = different paper, regardless of title."""
        workspace_paper = _make_paper("111", title="Same title")
        session = _make_session(workspace_paper)
        other_paper = _make_paper("222", title="Same title")
        with pytest.raises(ValueError):
            session.set_summary(_make_summary(other_paper))


# ---------------------------------------------------------------------------
# Stale-state invalidation: every paper mutation clears summary/report
# ---------------------------------------------------------------------------


class TestPaperMutationInvalidatesStaleArtefacts:
    """Per ADR-019, every mutation of ``self.papers`` must clear
    ``self.summary`` / ``self.report`` / ``self.published_report``
    so stale artefacts cannot survive a corpus mutation."""

    def test_replace_papers_advances_initial_to_intermediate(self) -> None:
        """``replace_papers`` from INITIAL state advances to
        INTERMEDIATE.

        The 2026-08-31 FSM-fix iteration dropped the explicit
        ``force_state(INTERMEDIATE)`` call from ``replace_papers``;
        the orchestrator's ``search()`` still advanced state
        correctly because ``_enter_action(SEARCH)`` runs first
        (per the FSM table ``INITIAL + SEARCH → INTERMEDIATE``).
        But direct entity callers (tests, future code, anything
        not going through ``_enter_action``) would leave the
        state at INITIAL with papers loaded -- a latent bug
        where ``can('generate')`` would be false even with
        papers present.

        This test pins the fix: ``replace_papers`` itself
        advances state. Direct callers now behave consistently
        with the orchestrator path.
        """
        session = ResearchSession(
            question=ResearchQuestion(question="x"),
            state=WorkspaceState.INITIAL,
        )
        assert session.state is WorkspaceState.INITIAL

        new_paper = _make_paper("111")
        session.replace_papers([new_paper])

        # State advanced to INTERMEDIATE because the corpus is
        # non-empty. Without this fix the state would have
        # stayed at INITIAL -- the latent bug.
        assert session.state is WorkspaceState.INTERMEDIATE
        assert session.papers == [new_paper]

    def test_remove_paper_clears_summary(self) -> None:
        p1 = _make_paper("111")
        p2 = _make_paper("222")
        p3 = _make_paper("333")
        session = _make_session(p1, p2, p3)
        session.set_summary(_make_summary(p1, p2, p3))
        assert session.summary is not None
        session.remove_paper("111")
        assert session.summary is None

    def test_remove_paper_clears_report(self) -> None:
        p1 = _make_paper("111")
        p2 = _make_paper("222")
        session = _make_session(p1, p2)
        session.set_report(_make_report(p1, p2))
        assert session.report is not None
        session.remove_paper("111")
        assert session.report is None

    def test_replace_papers_clears_summary(self) -> None:
        """A new search returns papers A, B, C. The workspace
        now has A, B, C but ``summary.papers_used`` might still
        reference the previous search's papers D, E, F.
        ``replace_papers`` must clear the stale summary."""
        old_paper = _make_paper("OLD")
        session = _make_session(old_paper)
        session.set_summary(_make_summary(old_paper))
        new_paper = _make_paper("NEW")
        session.replace_papers([new_paper])
        assert session.summary is None

    def test_replace_papers_clears_report(self) -> None:
        old_paper = _make_paper("OLD")
        session = _make_session(old_paper)
        session.set_report(_make_report(old_paper))
        new_paper = _make_paper("NEW")
        session.replace_papers([new_paper])
        assert session.report is None

    def test_add_papers_clears_summary(self) -> None:
        """Adding papers doesn't change the existing summary's
        correctness (the existing summary still describes the
        old subset), but it does mean the summary is now
        INCOMPLETE (it doesn't cover the new paper). The
        ``_mutate_papers`` helper clears the summary so the
        next generate() rebuilds it from the full corpus."""
        p1 = _make_paper("111")
        session = _make_session(p1)
        session.set_summary(_make_summary(p1))
        p2 = _make_paper("222")
        session.add_papers([p2])
        # Summary is cleared; next generate() rebuilds it.
        assert session.summary is None

    def test_replacement_summary_with_stale_papers_is_rejected(self) -> None:
        """Even if a buggy caller tries to re-attach a stale
        summary, the validation rejects it."""
        p1 = _make_paper("111")
        p2 = _make_paper("222")
        session = _make_session(p1, p2)
        session.set_summary(_make_summary(p1, p2))
        session.remove_paper("111")
        # Now session.papers is just [p2]. Try to re-attach the
        # old summary that referenced p1 (which is no longer in
        # the corpus).
        stale_summary = _make_summary(p1, p2)
        with pytest.raises(ValueError, match="references papers not in workspace.papers"):
            session.set_summary(stale_summary)


# ---------------------------------------------------------------------------
# Regression: the user's exact scenario from the bug report
# ---------------------------------------------------------------------------


class TestUserScenarioRegression:
    """Regression test for the user's report:

        "after removing some papers in my INTERMEDIATE state,
        then when generating the executive report the number
        of citations were higher than the articles available
        in INTERMEDIATE"

    After this ADR, the invariant is structural. Even if the
    orchestrator regressed and tried to use a stale summary,
    the entity would refuse to persist the violating state.
    """

    def test_remove_then_generate_citations_within_corpus(self) -> None:
        """The exact scenario: 10 papers -> generate -> remove 3
        papers -> generate again. The second report's citations
        must be a subset of the (now 7) remaining papers."""
        # This test exercises the orchestrator path indirectly:
        # we don't call generate() because that requires the
        # full orchestrator + stubs, but we do verify that the
        # underlying invariant the orchestrator relies on
        # (citations ⊆ workspace.papers) holds at every step.
        initial_papers = [_make_paper(f"{i:05d}") for i in range(10)]
        session = _make_session(*initial_papers)
        assert len(session.papers) == 10

        # Simulate a first generate: summary + report.
        session.set_summary(_make_summary(*initial_papers))
        session.set_report(_make_report(*initial_papers))
        assert session.report is not None
        assert len(session.report.citations) == 10

        # User removes 3 papers. ``_make_paper`` always sets
        # pmid to a non-None value, so we can dereference it
        # safely. Pyright can't infer this from the dataclass
        # type (``pmid: str | None``) so we cast.
        for p in initial_papers[:3]:
            assert p.pmid is not None
            removed = session.remove_paper(p.pmid)
            assert removed
        assert len(session.papers) == 7

        # The summary and report were cleared by remove_paper.
        # The orchestrator would now call generate() which
        # rebuilds both. Verify the invariant: any report we
        # set must cite only papers in the (now 7) corpus.
        remaining = session.papers
        session.set_summary(_make_summary(*remaining))
        session.set_report(_make_report(*remaining))
        assert session.report is not None
        assert all(
            c.paper in remaining
            for c in session.report.citations
        )
        assert len(session.report.citations) == len(remaining)

    def test_try_to_set_stale_report_after_remove_is_rejected(self) -> None:
        """If a buggy caller tries to re-attach the old report
        (which references removed papers), the entity refuses."""
        p1 = _make_paper("111")
        p2 = _make_paper("222")
        session = _make_session(p1, p2)
        old_report = _make_report(p1, p2)
        session.set_report(old_report)
        session.remove_paper("111")
        # session.papers is now [p2]. Try to re-attach old_report
        # which references [p1, p2].
        with pytest.raises(ValueError):
            session.set_report(old_report)


# ---------------------------------------------------------------------------
# Defence in depth: set_published_report without a prior set_report
# ---------------------------------------------------------------------------


class TestSetPublishedReportDefenceInDepth:
    """The PDF embeds the report, so the citations invariant is
    transitively guaranteed -- but if ``set_published_report``
    is called WITHOUT a prior ``set_report`` (a programmer
    error), the entity refuses."""

    def test_set_published_report_without_report_raises(self) -> None:
        """Programmer-error guard: a PDF cannot exist without
        a corresponding stored report."""
        session = _make_session()
        # Build a minimal valid PublishedReport. We use
        # ``create`` which validates the PDF magic header.
        from app.domain.entities.published_report import PublishedReport
        pdf = b"%PDF-1.4\n" + b"a" * 500
        published = PublishedReport.create(
            pdf_bytes=pdf,
            workspace_id="ws-test",
        )
        with pytest.raises(RuntimeError, match="set_report"):
            session.set_published_report(published)

    def test_set_published_report_after_set_report_succeeds(self) -> None:
        """The happy path: set_report validates citations, then
        set_published_report accepts the matching PDF."""
        from app.domain.entities.published_report import PublishedReport
        p1 = _make_paper("111")
        session = _make_session(p1)
        session.set_report(_make_report(p1))
        pdf = b"%PDF-1.4\n" + b"a" * 500
        published = PublishedReport.create(
            pdf_bytes=pdf,
            workspace_id="ws-test",
        )
        session.set_published_report(published)
        assert session.published_report is published
