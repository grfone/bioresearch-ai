"""
Tests for the H1 fallback's wire-in at synthesis-ingest time.

The fallback lives in
``app/infrastructure/llm/title_fallback.py`` (covered by
``tests/unit/test_title_fallback.py``). This file pins the
integration point: the synthesis use case must invoke the
fallback before returning the Summary entity.

Why a separate test file
------------------------
``test_title_fallback.py`` exercises the helper in
isolation. ``test_summarize_papers_h1_fallback.py``
exercises the integration: the use case wraps an LLM
output and the resulting Summary's body contains the
injected H1 when the LLM omits one.

Both files pin different contracts -- a regression in
either is a different class of bug.
"""
from __future__ import annotations

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


class _StubLLM(LLMProvider):
    """Stub LLM that returns a pre-canned response string."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    def generate(self, prompt: Prompt) -> LLMResponse:
        return LLMResponse(
            content=self._response_text,
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


def _execute_with_response(response_text: str) -> str:
    """Run the synthesis use case with a stubbed LLM
    returning ``response_text``. Return the body of the
    resulting Summary so tests can assert on it directly.
    """
    llm = _StubLLM(response_text)
    use_case = SummarizePapersUseCase(llm)
    summary = use_case.execute(
        ResearchQuestion(question="What is X?"),
        [_paper("Some paper")],
    )
    return summary.body


class TestSummarizePapersH1FallbackIntegration:
    """Pin the synthesis use case's invocation of the H1
    fallback. The fallback lives in title_fallback.py; this
    test pins that the synthesis use case ACTUALLY invokes
    it before constructing the Summary entity.
    """

    def test_llm_with_no_h1_gets_one_injected(self):
        """Live failure mode: the LLM emits synthesis prose
        without an H1. The synthesis use case must invoke
        the fallback and the resulting Summary.body must
        start with ``# <title>``.
        """
        body = (
            "Plasma p-tau217 has emerged as a sensitive "
            "marker [paper:1]. The body has more text."
        )
        result = _execute_with_response(body)
        first_line = result.split("\n", 1)[0]
        assert first_line.startswith("# "), (
            f"synthesis use case must inject H1 when LLM "
            f"omits one; got first line: {first_line!r}"
        )
        # The derived title is the first sentence.
        assert first_line == (
            "# Plasma p-tau217 has emerged as a sensitive marker"
        )
        # The original body is preserved below the H1.
        assert body in result

    def test_llm_with_h1_kept_verbatim(self):
        """When the LLM emits a real ``# <title>`` line,
        the synthesis use case must NOT overwrite it --
        the LLM's choice of title wins.
        """
        body = "# Real LLM Title\n\nBody text here."
        result = _execute_with_response(body)
        # First line is the LLM's title, unchanged.
        first_line = result.split("\n", 1)[0]
        assert first_line == "# Real LLM Title"
        # No double-prepending. Count lines starting with
        # ``# `` (the H1 pattern). One H1 is the contract --
        # if the fallback had run, there would be two.
        h1_count = sum(
            1 for line in result.split("\n") if line.startswith("# ")
        )
        assert h1_count == 1, (
            f"fallback must be idempotent: if the LLM "
            f"already emitted an H1, don't prepend another "
            f"one above it. Got {h1_count} H1 lines."
        )

    def test_citation_markers_dont_break_injection(self):
        """The first sentence contains a ``[paper:1]``
        marker. The fallback strips markers from the
        derived title so the H1 reads cleanly.
        """
        body = "Plasma p-tau217 is sensitive [paper:1]."
        result = _execute_with_response(body)
        first_line = result.split("\n", 1)[0]
        assert first_line == "# Plasma p-tau217 is sensitive"
        assert "[paper:" not in first_line

    def test_summary_body_has_no_double_h1_lines(self):
        """Defensive: a body with a malformed H1 followed
        by real content shouldn't get a second H1 from
        the fallback. The fallback should leave the
        existing line alone.
        """
        # Body has an ``## `` (H2) line. ``has_h1_title``
        # only matches ``# `` (single hash). So the
        # fallback SHOULD inject -- but the body still
        # ends up with exactly one injected H1, not two.
        body = "## Limitations\n\n- too small"
        result = _execute_with_response(body)
        h1_count = sum(
            1
            for line in result.split("\n")
            if line.startswith("# ")
        )
        assert h1_count == 1, (
            f"body should have exactly one injected H1; got {h1_count}"
        )

    def test_long_first_sentence_truncated_to_12_words(self):
        """The injected H1 stays within the 12-word cap
        even when the first sentence is longer.
        """
        long_sentence = (
            "one two three four five six seven eight nine ten "
            "eleven twelve thirteen fourteen fifteen sixteen."
        )
        result = _execute_with_response(long_sentence)
        first_line = result.split("\n", 1)[0]
        title = first_line[2:]  # strip "# "
        assert len(title.split()) == 12