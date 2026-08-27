"""
tests/unit/test_summarize_papers_prompt.py

Tests that pin the structure of the summary prompt emitted by
``SummarizePapersUseCase``. The summary prompt MUST:

1. Number each paper as ``[paper:N]`` where ``N`` is the 1-indexed
   position in the papers list. This numbering must match the
   position the report mapper expects when it extracts markers.
2. Ask the LLM to preserve the ``[paper:N]`` markers verbatim in
   its synthesis text -- this is how downstream tools build the
   bibliography.
3. (Vancouver / ICMJE) Instruct the LLM to place citations
   INLINE at the end of the sentence or clause being cited,
   not as sentence prefixes. Real scientific reports end each
   claim with a bracketed number, not start each line with one.
   This is the user's explicit requirement -- the previous
   "prefix-style" output (``[paper:N] argues that ...``)
   was flagged as "not how we write in science".

The prompt-level tests here pin the structure of the prompt so a
future refactor doesn't silently drop the markers or regress
to the prefix style. The report-mapper-level tests in
``test_report_mapper.py`` pin the extraction logic.
"""
from typing import Iterator

import pytest

from app.application.use_cases.summarize_papers import (
    SummarizePapersUseCase,
)
from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt


class _CapturingLLM(LLMProvider):
    """Stub LLM that captures the prompt it's given."""

    def __init__(self) -> None:
        self.last_prompt: Prompt | None = None

    def generate(self, prompt: Prompt) -> LLMResponse:
        self.last_prompt = prompt
        return LLMResponse(
            content="stub summary text",
            model="stub",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            finish_reason="stop",
        )


def _paper(title: str) -> Paper:
    return Paper(
        title=title,
        authors=[Author(first_name="A", last_name="Author")],
        journal=Journal(name="Nature"),
        year=2024,
        abstract="abstract",
    )


def _execute_and_capture(papers: list[Paper]) -> Prompt:
    """Run the use case with a capturing LLM and return the prompt."""
    llm = _CapturingLLM()
    use_case = SummarizePapersUseCase(llm)
    use_case.execute(
        ResearchQuestion(question="What is the effect of X?"),
        papers,
    )
    assert llm.last_prompt is not None
    return llm.last_prompt


def test_summary_prompt_numbers_papers_with_markers() -> None:
    """Each paper appears in the context as ``[paper:N]`` where
    ``N`` is its 1-indexed position."""
    papers = [
        _paper("Alzheimer biomarker blood test"),
        _paper("Tau PET imaging longitudinal"),
        _paper("ApoE genotype risk stratification"),
    ]
    prompt = _execute_and_capture(papers)

    # Every paper appears with a marker in the context. The
    # full context is the user-supplied ``context`` field, which
    # contains the numbered paper list.
    context = prompt.context or ""
    assert "[paper:1]" in context
    assert "[paper:2]" in context
    assert "[paper:3]" in context

    # Each marker is followed by the paper's title.
    assert "Alzheimer biomarker blood test" in context
    assert "Tau PET imaging longitudinal" in context
    assert "ApoE genotype risk stratification" in context


def test_summary_prompt_asks_llm_to_preserve_markers() -> None:
    """The system prompt must instruct the LLM to keep the
    ``[paper:N]`` markers verbatim when referencing a paper."""
    papers = [_paper("Some paper title")]
    prompt = _execute_and_capture(papers)

    system = prompt.system or ""
    # The system prompt must mention ``[paper:N]`` so the LLM
    # knows to keep the markers.
    assert "[paper:N]" in system or "[paper:" in system, (
        "system prompt does not mention [paper:N] markers; the "
        "LLM has no instruction to preserve them. Without this "
        "the report mapper's marker-based matching falls back "
        "to title substring matching -- which fails because "
        "real LLM summaries paraphrase paper titles."
    )


def test_summary_prompt_marker_numbering_matches_papers_used_order() -> None:
    """Paper 1 in the marker scheme must be the first paper in
    ``papers_used``. This is the invariant the report mapper
    depends on (it converts marker N to papers_used[N-1])."""
    papers = [
        _paper("First paper"),
        _paper("Second paper"),
        _paper("Third paper"),
    ]
    prompt = _execute_and_capture(papers)
    context = prompt.context or ""

    # Find positions of each [paper:N] marker in the context.
    p1_pos = context.find("[paper:1]")
    p2_pos = context.find("[paper:2]")
    p3_pos = context.find("[paper:3]")

    # Markers appear in ascending order.
    assert 0 <= p1_pos < p2_pos < p3_pos, (
        f"markers not in ascending order: p1={p1_pos}, "
        f"p2={p2_pos}, p3={p3_pos}"
    )

    # The paper title following each marker matches the
    # position in the original papers list.
    p1_block = context[p1_pos:context.find("[paper:2]")]
    p2_block = context[p2_pos:context.find("[paper:3]")]
    p3_block = context[p3_pos:]

    assert "First paper" in p1_block
    assert "Second paper" in p2_block
    assert "Third paper" in p3_block
class TestSummarizePromptVancouverStyle:
    """Pin the Vancouver / ICMJE in-text citation rules.

    These tests guard against a regression to the "prefix
    style" the user explicitly rejected (``[paper:N] argues
    that ...`` as a sentence opener). Real scientific writing
    closes each claim with a citation, not opens each line
    with one.
    """

    def test_system_prompt_instructs_inline_citation_placement(self):
        """The system prompt must instruct the LLM to place
        ``[paper:N]`` markers INLINE at the end of the cited
        sentence or clause -- not as sentence prefixes.

        Concretely, the prompt must mention the phrase
        ``END of the sentence`` (or the equivalent) so the
        LLM knows where to position the marker. Pinning the
        exact phrase is brittle but the user has been clear
        about this requirement, so we want a sharp failure
        if a future refactor regresses the wording.
        """
        papers = [_paper("Some paper title")]
        prompt = _execute_and_capture(papers)
        system = prompt.system or ""
        # The prompt must explicitly direct the LLM to put
        # citations at the end of the sentence, not the
        # beginning. ``end of the sentence`` and ``NOT prefix``
        # are the two key signals.
        assert "end of the sentence" in system.lower(), (
            "system prompt must instruct the LLM to place "
            "citations at the END of the sentence; found: "
            f"{system!r}"
        )
        assert "not prefix" in system.lower() or "do not prefix" in system.lower(), (
            "system prompt must warn against the prefix style; "
            f"found: {system!r}"
        )

    def test_system_prompt_prohibits_one_citation_per_line(self):
        """The previous behaviour was "one citation per line"
        because the system prompt didn't actively forbid it.
        The new prompt must say ``do NOT emit one citation
        per line`` (or equivalent) so the LLM doesn't fall
        back to the bullet-style output.
        """
        papers = [_paper("Some paper title")]
        prompt = _execute_and_capture(papers)
        system = (prompt.system or "").lower()
        assert "one citation per line" in system, (
            "system prompt must explicitly forbid one "
            "citation per line; found: " + repr(prompt.system)
        )

    def test_system_prompt_includes_vancouver_or_icmje_label(self):
        """The prompt names the canonical citation style so
        the LLM has a recognised reference. ``Vancouver``
        and/or ``ICMJE`` (the International Committee of
        Medical Journal Editors) are the standard biomedical
        styles and the right choice here.
        """
        papers = [_paper("Some paper title")]
        prompt = _execute_and_capture(papers)
        system = prompt.system or ""
        assert "Vancouver" in system or "ICMJE" in system, (
            "system prompt should reference the canonical "
            "biomedical citation style (Vancouver / ICMJE); "
            f"found: {system!r}"
        )

    def test_system_prompt_includes_good_and_bad_output_examples(self):
        """A few-shot example is the most reliable way to
        teach an LLM a citation pattern. The prompt must
        include BOTH a ``GOOD`` example (inline, paragraph
        form) and a ``BAD`` example (one-per-line, prefix
        form) so the model has unambiguous positive and
        negative anchors.
        """
        papers = [_paper("Some paper title")]
        prompt = _execute_and_capture(papers)
        system = prompt.system or ""
        assert "GOOD" in system and "BAD" in system, (
            "system prompt must include both GOOD and BAD "
            "examples; found: " + repr(prompt.system)
        )

    def test_system_prompt_warns_against_breaking_paragraph_per_citation(self):
        """The LLM's instinct when seeing the bare marker
        instruction was to break the paragraph at every
        marker -- producing the "bibliography" layout the
        user rejected. The prompt must explicitly forbid
        that.
        """
        papers = [_paper("Some paper title")]
        prompt = _execute_and_capture(papers)
        system = (prompt.system or "").lower()
        assert "do not break" in system or "not break" in system, (
            "system prompt must explicitly warn against "
            "breaking the paragraph after every citation; "
            f"found: {prompt.system!r}"
        )

    def test_marker_format_paragraph_instruction_still_present(self):
        """The original marker-preservation contract (the
        regex relies on it) must still be in the prompt
        even after the style rewrite. Otherwise the LLM
        might drop ``[paper:N]`` entirely and we'd lose
        reliable citation extraction.
        """
        papers = [_paper("Some paper title")]
        prompt = _execute_and_capture(papers)
        system = prompt.system or ""
        assert "[paper:N]" in system or "[paper:" in system, (
            "system prompt must still mention [paper:N] so "
            "the LLM keeps emitting the markers downstream "
            "tooling extracts. Without this, the report "
            "mapper's marker-based matching falls back to "
            "title substring matching, which fails because "
            "real LLM summaries paraphrase paper titles."
        )

    def test_system_prompt_documents_grouped_citation_syntax(self):
        """Multiple sources for one claim collapse to a single
        bracketed group: ``[paper:5, paper:12]``. The prompt
        must document this so the LLM groups instead of
        scattering.
        """
        papers = [_paper("Some paper title")]
        prompt = _execute_and_capture(papers)
        system = (prompt.system or "").lower()
        # The prompt's "grouped" wording could be expressed
        # several ways; we assert on a representative one.
        assert (
            "bracketed group" in system
            or "[paper:5, paper:12]" in system
            or "group of citations" in system
            or "multiple sources" in system
        ), (
            "system prompt must explain how to handle multiple "
            "citations for one claim (group them inline); "
            f"found: {prompt.system!r}"
        )


class TestSummarizePromptBibliographySizeConstraint:
    """Pin the prompt's explicit bibliography-size constraint.

    The Vancouver / ICMJE prompt tells the LLM not to
    fabricate citation indices, but the LLM still
    hallucinates ``[paper:N]`` markers where N exceeds
    ``len(papers_used)``. The fix has two layers: the
    prompt explicitly states the bibliography size, AND
    the backend ``sanitize_citation_markers`` helper
    drops out-of-range markers at the ingest boundary.
    This class pins the prompt layer so a future prompt
    refactor doesn't lose the size-constraint wording.
    """

    def test_system_prompt_includes_bibliography_size_phrase(self):
        # Use a single paper so the size phrase is clear.
        papers = [_paper("Only paper")]
        prompt = _execute_and_capture(papers)
        system = prompt.system or ""
        # Phrase: the bibliography is exactly N entries,
        # for any N. We assert on the size-bound substring
        # which appears for any N.
        assert "exactly 1 entries" in system, (
            "system prompt must tell the LLM the bibliography "
            "has exactly N entries; found: " + repr(system)
        )

    def test_system_prompt_size_phrase_scales_with_paper_count(self):
        """The size phrase is parameterised on ``len(papers)``
        so the LLM sees the actual count, not a hardcoded
        ``20``. Verify with 3 papers that the prompt says
        ``3 entries`` -- a future prompt refactor that
        hardcodes the count would silently mis-inform the
        LLM.
        """
        papers = [_paper(f"Paper {i}") for i in range(1, 4)]  # 3 papers
        prompt = _execute_and_capture(papers)
        system = prompt.system or ""
        assert "exactly 3 entries" in system, (
            "system prompt must use the actual paper count, "
            "not a hardcoded number; found: " + repr(system)
        )
        # And the upper bound is 3, not 20 (a common
        # misconfiguration if someone hardcodes).
        assert "any N > 3" in system, (
            "system prompt's upper bound must match the "
            "actual paper count; found: " + repr(system)
        )

    def test_system_prompt_tells_llm_to_drop_unciteable_papers(self):
        """The prompt ends with the actionable instruction:
        ``If you find yourself wanting to cite a paper that
        isn't in the bibliography, do not cite it.`` This
        is the final pin -- the LLM may otherwise rationalise
        ``[paper:99]`` as ``I happen to know a paper with
        that ID, so I'll cite it``.
        """
        papers = [_paper("Only paper")]
        prompt = _execute_and_capture(papers)
        system = prompt.system or ""
        assert (
            "If you find yourself wanting to cite a paper that "
            "isn't in the bibliography, do not cite it"
            in system
        ), (
            "system prompt must tell the LLM explicitly not "
            "to cite papers outside the bibliography; found: "
            + repr(system)
        )
