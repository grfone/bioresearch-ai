"""
tests/unit/test_report_generator_prompt.py

Pin the structure of the report-generation prompt emitted by
``LLMReportGenerator._build_prompt``. The prompt MUST:

1. Include the research question in the user message.
2. Include the evidence summary as context (so the LLM has
   access to the per-paper ``[paper:N]`` markers).
3. (Vancouver / ICMJE) Instruct the LLM to place citations
   INLINE at the end of the sentence being cited, not as
   sentence prefixes. This is the user's explicit
   requirement -- the previous "prefix style"
   (``[paper:N] argues that ...``) was flagged as "not
   how we write in science".
4. Keep the ``[paper:N]`` markers verbatim in the LLM's
   output -- the regex in ``report_mapper.py`` extracts
   citations from those markers, so they cannot be dropped.

These tests pin the prompt so a future refactor doesn't
silently regress to the prefix style.
"""
from __future__ import annotations

from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.summary import Summary
from app.infrastructure.llm.report_generator import LLMReportGenerator


def _paper(title: str = "Some paper") -> Paper:
    return Paper(
        title=title,
        authors=[Author(first_name="Alice", last_name="Smith")],
        journal=Journal(name="J"),
        year=2026,
        abstract="An abstract.",
    )


def _summary(text: str = "A summary.") -> Summary:
    return Summary(text=text, papers_used=[_paper("First paper")])


def _build_prompt():
    """Build the report prompt with a minimal ``LLMReportGenerator``."""
    generator = LLMReportGenerator.__new__(LLMReportGenerator)
    # ``_build_prompt`` is a @staticmethod so it doesn't need
    # ``self`` / instance state.
    return LLMReportGenerator._build_prompt(
        ResearchQuestion(question="What is X?"),
        _summary("Plasma p-tau217 is a sensitive AD biomarker [paper:1]."),
    )


class TestReportGeneratorPromptVancouverStyle:
    """The user's pinned requirement: in-text citations inline
    at sentence end, never as sentence prefixes."""

    def test_user_message_instructs_inline_citation_placement(self):
        prompt = _build_prompt()
        user = prompt.user or ""
        assert "end of the sentence" in user.lower(), (
            "report prompt must direct the LLM to place "
            "citations at the end of the sentence; found: "
            f"{user!r}"
        )
        assert (
            "not prefix" in user.lower()
            or "do not prefix" in user.lower()
            or "not on their own lines" in user.lower()
            or "not on its own line" in user.lower()
        ), (
            "report prompt must warn against the prefix style; "
            f"found: {user!r}"
        )

    def test_user_message_names_vancouver_or_icmje(self):
        prompt = _build_prompt()
        user = prompt.user or ""
        assert "Vancouver" in user or "ICMJE" in user, (
            "report prompt should name the canonical "
            "biomedical citation style (Vancouver / ICMJE); "
            f"found: {user!r}"
        )

    def test_user_message_includes_inline_example_shape(self):
        """The user prompt must show the LLM a positive
        example of an inline-style paragraph so the model
        has a concrete shape to copy. Pinning this catches a
        refactor that strips the example block.
        """
        prompt = _build_prompt()
        user = prompt.user or ""
        assert "Plasma p-tau217" in user, (
            "report prompt must include the worked example "
            "paragraph (so the LLM has a concrete shape to "
            "copy); found: " + repr(user[:500])
        )

    def test_user_message_instructs_citations_inline_not_on_own_line(self):
        prompt = _build_prompt()
        user = prompt.user or ""
        assert (
            "not on their own lines" in user.lower()
            or "not on its own line" in user.lower()
            or "do not break the paragraph" in user.lower()
        ), (
            "report prompt must warn against emitting "
            "citations on their own line; found: " + repr(user)
        )


class TestReportGeneratorPromptMarkersPreserved:
    """The marker-preservation contract is still required --
    the regex in ``report_mapper.py`` extracts citations from
    the ``[paper:N]`` markers. The style rewrite MUST NOT
    drop the marker instruction.
    """

    def test_prompt_mentions_paper_marker_verbatim_contract(self):
        prompt = _build_prompt()
        user = (prompt.user or "") + (prompt.system or "")
        # Either the user message or the system message
        # must mention ``[paper:N]`` explicitly so the LLM
        # knows to keep emitting the markers.
        assert (
            "[paper:N]" in user or "[paper:" in user
        ), (
            "report prompt must mention [paper:N] markers "
            "so the LLM keeps emitting them; the report "
            "mapper's regex extraction relies on this."
        )

    def test_prompt_keeps_marker_for_bibliography_construction(self):
        prompt = _build_prompt()
        user = (prompt.user or "").lower()
        assert "biblio" in user or "reference" in user, (
            "report prompt must explain that the markers "
            "are how downstream tools build the "
            "bibliography; otherwise the LLM may drop them "
            "to 'clean up' the prose."
        )

    def test_summary_text_with_markers_included_in_user_message(self):
        prompt = _build_prompt()
        # The summary text (which contains ``[paper:N]``
        # markers) must be embedded in the user message so
        # the LLM sees it. The mapper regex extracts
        # citations from the *report* body, but the LLM
        # writes the report FROM the summary, so the markers
        # must be visible in the prompt.
        assert "[paper:1]" in (prompt.user or ""), (
            "report prompt must include the summary text "
            "(with its [paper:N] markers) so the LLM can "
            "preserve them in its output."
        )

    def test_prompt_uses_summary_text_not_dataclass_repr(self):
        """Pin the fix for a real bug: the prompt used to
        embed ``str(summary)`` which returns the dataclass
        repr (``Summary(papers=1)``), NOT the actual summary
        text. That meant the LLM never saw the evidence
        summary it was supposed to be writing the report
        from. The bug was masked because the prompt also
        mentioned ``[paper:N]`` in the instructions, so a
        reader could assume the summary was included.

        This test pins the corrected behaviour: the prompt
        must contain the actual ``summary.text`` string.
        """
        prompt = _build_prompt()
        # The full summary text we passed in.
        assert "Plasma p-tau217 is a sensitive AD biomarker" in (
            prompt.user or ""
        ), (
            "report prompt must embed the actual summary "
            "text (with its [paper:N] markers) so the LLM "
            "can build the report from the evidence. The "
            "dataclass repr 'Summary(papers=N)' has none of "
            "the evidence content."
        )
        # And must NOT contain the dataclass repr as a
        # substitute for the summary text.
        assert "Summary(papers=1)" not in (prompt.user or ""), (
            "report prompt must not contain the dataclass "
            "repr -- it's a clear signal that the summary "
            "text was never actually embedded in the "
            "prompt."
        )


class TestReportGeneratorPromptStructure:
    """Pin the report output structure: title + Executive
    Summary + Limitations + Future Work. The mapper
    downstream uses these exact headings to parse the
    report, so the prompt must not silently change them.
    """

    def test_user_message_contains_required_section_headings(self):
        prompt = _build_prompt()
        user = prompt.user or ""
        for required in (
            "# <report title>",
            "## Executive Summary",
            "## Limitations",
            "## Future Work",
        ):
            assert required in user, (
                f"report prompt must request section "
                f"heading '{required}' (the mapper parses "
                f"the report using these exact strings); "
                f"found: {user!r}"
            )