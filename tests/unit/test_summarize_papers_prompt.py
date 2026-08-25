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

The prompt-level tests here pin the structure of the prompt so a
future refactor doesn't silently drop the markers. The
report-mapper-level tests in ``test_report_mapper.py`` pin the
extraction logic.
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
