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

import logging

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
    return Summary(body=text, papers_used=[_paper("First paper")])


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
        must contain the actual ``summary.body`` string.
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


class TestReportGeneratorPromptBibliographySizeConstraint:
    """Pin the prompt's explicit bibliography-size constraint.

    Matches the contract pinned on the summarizer prompt
    in ``test_summarize_papers_prompt.py``. The LLM sees
    the actual paper count, not a hardcoded ``20``.
    """

    def test_user_message_includes_bibliography_size_phrase(self):
        """The user prompt must tell the LLM the bibliography
        size so it knows the valid range for ``[paper:N]``
        markers. A future refactor that drops this clause
        would regress the fix; this test pins the contract.
        """
        prompt = _build_prompt()
        user = prompt.user or ""
        assert "exactly 1 entries" in user, (
            "report prompt must tell the LLM the bibliography "
            "has exactly N entries; found: " + repr(user)
        )

    def test_user_message_size_phrase_scales_with_paper_count(self):
        """The size phrase is parameterised on
        ``len(summary.papers_used)`` so the LLM sees the
        actual count.

        We mock the ``Summary`` so we can vary its paper
        count and inspect the resulting prompt.
        """
        # 3-paper summary
        three_papers = [
            Paper(
                title=f"Paper {i}",
                authors=[Author(first_name="A", last_name="B")],
                journal=Journal(name="J"),
                year=2026,
                abstract="abs",
            )
            for i in range(1, 4)
        ]
        summary = Summary(
            body="Plasma p-tau217 is a marker [paper:1].\n",
            papers_used=three_papers,
        )
        generator = LLMReportGenerator.__new__(LLMReportGenerator)
        prompt = LLMReportGenerator._build_prompt(
            ResearchQuestion(question="What is X?"),
            summary,
        )
        user = prompt.user or ""
        assert "exactly 3 entries" in user, (
            "report prompt must use the actual paper count; "
            "found: " + repr(user)
        )
        assert "any N > 3" in user, (
            "report prompt's upper bound must match the "
            "actual paper count; found: " + repr(user)
        )

    def test_user_message_tells_llm_to_drop_unciteable_papers(self):
        """The prompt ends with: ``If you find yourself
        wanting to cite a paper that isn't in the
        bibliography, do not cite it.`` The same actionable
        language as the summarizer prompt.
        """
        prompt = _build_prompt()
        user = prompt.user or ""
        assert (
            "If you find yourself wanting to cite a paper that "
            "isn't in the bibliography, do not cite it"
            in user
        ), (
            "report prompt must tell the LLM explicitly not "
            "to cite papers outside the bibliography; found: "
            + repr(user)
        )


class TestReportGeneratorPromptEmptyBodyGuard:
    """Pin the ``summary.body or ""`` fallback so a literal
    ``None`` or empty body never leaks the string ``"None"``
    into the LLM prompt.

    Why this matters: the prompt builder uses f-string
    interpolation to embed ``{summary_text}`` directly. If
    ``summary_text`` were ``None``, the f-string would
    silently coerce to the string ``"None"`` and the LLM
    would see a literal token that means nothing. The
    ``or ""`` fallback in ``_build_prompt`` is load-bearing.

    These tests pin both edge cases:
      - ``Summary(body='')`` -> empty context, no leak.
      - ``Summary(body=None)`` -> empty context, no leak.
    """

    def test_empty_body_produces_empty_context_no_none_leak(self):
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        summary = Summary(body="", papers_used=[])
        prompt = LLMReportGenerator._build_prompt(
            ResearchQuestion(question="What is X?"), summary,
        )
        user = prompt.user or ""
        assert "None" not in user, (
            "report prompt must not contain the literal "
            "string 'None' when summary.body is empty; the "
            "`summary.body or \"\"` fallback should produce an "
            "empty context instead. Found: " + repr(user[:300])
        )

    def test_none_body_does_not_leak_into_prompt(self):
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        # ``Summary.body`` is typed ``str`` but the dataclass
        # is ``slots=True, frozen=True`` -- we have to go
        # around the type checker for this test, which is
        # exactly the situation the ``or ""`` guard handles.
        summary = Summary(body=None, papers_used=[])  # type: ignore[arg-type]
        prompt = LLMReportGenerator._build_prompt(
            ResearchQuestion(question="What is X?"), summary,
        )
        user = prompt.user or ""
        assert "None" not in user, (
            "report prompt must not contain the literal "
            "string 'None' even if Summary.body is None at "
            "runtime. The `summary.body or \"\"` fallback is "
            "load-bearing for this case. Found: " + repr(user[:300])
        )

    def test_normal_body_is_embedded_verbatim(self):
        """Pin the happy path so a future refactor that
        accidentally drops the body from the prompt gets
        caught immediately. This complements the empty-body
        guard tests above.
        """
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        summary = Summary(
            body="Plasma p-tau217 is a sensitive AD marker [paper:1].",
            papers_used=[_paper("Only paper")],
        )
        user = (
            LLMReportGenerator._build_prompt(
                ResearchQuestion(question="What is X?"), summary,
            ).user or ""
        )
        assert "Plasma p-tau217 is a sensitive AD marker" in user
        assert "[paper:1]" in user
class TestReportGeneratorPromptSanitisationHardening:
    """Pin the defence-in-depth sanitisation + length warning
    logic in ``LLMReportGenerator._build_prompt``.

    These tests document a hardening pass: even though
    ``SummarizePapersUseCase.execute`` already sanitises
    the LLM's synthesis at ingest, this re-runs the same
    sanitiser at the prompt boundary. A workspace restored
    from a pre-sanitiser backup, or a malformed body that
    somehow bypassed ingest-level sanitisation, would
    otherwise leak invalid ``[paper:N]`` markers into the
    report prompt.
    """

    def test_residual_out_of_range_markers_are_stripped(
        self, caplog
    ):
        """If the body has ``[paper:99]`` markers past the
        bibliography size, the prompt must NOT contain them
        (the sanitiser drops them). The INFO log fires so
        operators see when this defence-in-depth path is
        exercised.
        """
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        with caplog.at_level(
            logging.INFO,
            logger="app.infrastructure.llm.report_generator",
        ):
            summary = Summary(
                body=(
                    "Plasma p-tau217 is a sensitive AD marker "
                    "[paper:1]. Earlier work [paper:99] also "
                    "covers tau phosphorylation."
                ),
                papers_used=[_paper("Only paper")],
            )
            user = (
                LLMReportGenerator._build_prompt(
                    ResearchQuestion(question="What is X?"),
                    summary,
                ).user or ""
            )
        # The in-range [paper:1] marker is preserved.
        assert "[paper:1]" in user
        # The out-of-range [paper:99] marker is stripped.
        assert "[paper:99]" not in user
        # An INFO log fires to surface the defence-in-depth
        # path was exercised.
        assert any(
            "stripped residual out-of-range" in record.message
            for record in caplog.records
        ), (
            "info log should fire when residual out-of-range "
            "markers are stripped at the prompt boundary"
        )

    def test_clean_body_does_not_log(self, caplog):
        """The clean common path (in-range markers, valid
        bibliography) must NOT emit any sanitiser INFO log.
        Operators reviewing logs would get a flood of
        useless "stripped 0 markers" lines on the common
        path.
        """
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        with caplog.at_level(
            logging.INFO,
            logger="app.infrastructure.llm.report_generator",
        ):
            summary = Summary(
                body=(
                    "Plasma p-tau217 is a sensitive AD marker "
                    "[paper:1]."
                ),
                papers_used=[_paper("Only paper")],
            )
            LLMReportGenerator._build_prompt(
                ResearchQuestion(question="What is X?"), summary,
            )
        stripped_records = [
            r for r in caplog.records
            if "stripped residual out-of-range" in r.message
        ]
        assert stripped_records == [], (
            "clean body must NOT trigger the "
            "'stripped residual out-of-range' info log"
        )

    def test_long_body_emits_warning(self, caplog):
        """A body over the threshold must emit a WARNING log
        so operators see they have a runaway synthesis on
        their hands. The body is truncated by the LLM in
        practice (the actual truncation is the API server's
        job, not ours), but we surface the warning at the
        boundary.
        """
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        # A body that's clearly over the 50k threshold.
        long_body = "abc " * 15_000
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.llm.report_generator",
        ):
            summary = Summary(
                body=long_body, papers_used=[_paper("Only paper")]
            )
            LLMReportGenerator._build_prompt(
                ResearchQuestion(question="What is X?"), summary,
            )
        warning_records = [
            r for r in caplog.records if r.levelno == logging.WARNING
        ]
        length_warnings = [
            r for r in warning_records
            if "unusually long" in r.message
        ]
        assert length_warnings, (
            "long body must emit a WARNING so operators see "
            "the runaway synthesis"
        )

    def test_short_body_below_threshold_does_not_warn(self, caplog):
        """Sanity check on the threshold: a normal-sized body
        (~2k chars) must NOT trigger the length warning.
        """
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )
        summary = Summary(
            body="Plasma p-tau217 is a marker [paper:1]. " * 30,
            papers_used=[_paper("Only paper")],
        )
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.llm.report_generator",
        ):
            LLMReportGenerator._build_prompt(
                ResearchQuestion(question="What is X?"), summary,
            )
        length_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "unusually long" in r.message
        ]
        assert length_warnings == []
"""
Tests for the H1 title directive in the report prompt.

Background
----------
The LLM occasionally omits the leading ``# <title>``
heading, which causes both the PDF generator and the React
UI to fall back to the generic placeholder
``"Biomedical Research Report"``. The user-visible bug is
that every PDF in the system gets the same title.

The fix: add a prominent directive to the user prompt that
spells out (a) WHY the H1 matters (the PDF/UI extract it
from the first line), (b) WHAT it should look like
(5-15 word headline, no prefix), and (c) CONCRETE EXAMPLES
(three real-world biomedical-report titles).

Tests pin the new directive so a future refactor doesn't
silently weaken it back to the pre-fix one-liner.
"""


class TestReportGeneratorPromptH1TitleDirective:
    """Pin the H1-title directive in the report prompt.

    The directive has to be loud enough that the LLM
    actually emits a H1 (the empirical failure mode we
    observed pre-fix). The tests below check the prompt
    contains:

    1. The literal ``# <report title>`` placeholder (the
       parser's anchor).
    2. An emphatic instruction that this line is required
       (e.g. "REQUIRED", "must", "THIS LINE").
    3. The reason (the PDF/UI extract the title from the
       first line).
    4. Length guidance (5-15 words is a useful range --
       too short loses specificity, too long loses the
       "headline" feel).
    5. Concrete worked examples (LLMs respond better to
       examples than to abstract rules).
    6. An anti-pattern warning (no prefix, no date, no
       question mark in the title).
    """

    def test_user_prompt_contains_h1_placeholder(self):
        from app.infrastructure.llm.report_generator import (
            LLMReportGenerator,
        )
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )

        papers = [
            Paper(
                title="P1",
                authors=[Author(first_name="A", last_name="B")],
                journal=Journal(name="J"),
                year=2024,
                abstract="",
                doi="10.1/x",
            )
        ]
        summary = Summary(body="body", papers_used=papers)
        prompt = LLMReportGenerator(
            llm_provider=None, report_mapper=None
        )._build_prompt(
            ResearchQuestion(question="What is X?"), summary
        )
        user = prompt.user or ""
        assert "# <report title>" in user, (
            "report prompt must include the # <report title> "
            "placeholder so the LLM knows what shape the "
            "expected output starts with"
        )

    def test_user_prompt_emphasises_h1_is_required(self):
        """The directive must be loud enough to overcome the
        LLM's tendency to skip preamble. An emphatic word
        like ``REQUIRED``, ``MUST``, or ``THIS LINE`` in
        the same paragraph as the H1 is the empirical
        pattern that works.
        """
        from app.infrastructure.llm.report_generator import (
            LLMReportGenerator,
        )
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )

        papers = [
            Paper(
                title="P1",
                authors=[Author(first_name="A", last_name="B")],
                journal=Journal(name="J"),
                year=2024,
                abstract="",
                doi="10.1/x",
            )
        ]
        summary = Summary(body="body", papers_used=papers)
        prompt = LLMReportGenerator(
            llm_provider=None, report_mapper=None
        )._build_prompt(
            ResearchQuestion(question="What is X?"), summary
        )
        user = prompt.user or ""
        # Find the H1 section.
        idx = user.find("# <report title>")
        assert idx > -1, "H1 placeholder missing from prompt"
        # Look at the surrounding 800 chars for the emphatic
        # instruction. "REQUIRED" is the keyword we used.
        section = user[idx : idx + 800]
        assert "REQUIRED" in section or "MUST" in section, (
            f"H1 section must contain an emphatic 'REQUIRED' "
            f"or 'MUST' to overcome the LLM's tendency to "
            f"skip preamble; got: {section[:400]!r}"
        )

    def test_user_prompt_explains_why_h1_matters(self):
        """Tell the LLM WHY it must emit the H1.

        Without the why, the LLM treats the directive as a
        stylistic preference and may emit an empty
        preamble. With the why (``the PDF generator and
        React UI extract the title from the first line``),
        the LLM treats it as a hard requirement.
        """
        from app.infrastructure.llm.report_generator import (
            LLMReportGenerator,
        )
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )

        papers = [
            Paper(
                title="P1",
                authors=[Author(first_name="A", last_name="B")],
                journal=Journal(name="J"),
                year=2024,
                abstract="",
                doi="10.1/x",
            )
        ]
        summary = Summary(body="body", papers_used=papers)
        prompt = LLMReportGenerator(
            llm_provider=None, report_mapper=None
        )._build_prompt(
            ResearchQuestion(question="What is X?"), summary
        )
        user = prompt.user or ""
        idx = user.find("# <report title>")
        section = user[idx : idx + 1000]
        # The why explanation mentions PDF/UI/title-extraction.
        assert "PDF" in section, (
            "H1 section must explain WHY (mention the PDF generator) "
            "so the LLM treats the directive as load-bearing"
        )
        assert "title" in section.lower()

    def test_user_prompt_includes_concrete_examples(self):
        """A few-shot example helps the LLM calibrate. We
        include three real-world biomedical-report titles
        so the LLM has a target distribution.
        """
        from app.infrastructure.llm.report_generator import (
            LLMReportGenerator,
        )
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )

        papers = [
            Paper(
                title="P1",
                authors=[Author(first_name="A", last_name="B")],
                journal=Journal(name="J"),
                year=2024,
                abstract="",
                doi="10.1/x",
            )
        ]
        summary = Summary(body="body", papers_used=papers)
        prompt = LLMReportGenerator(
            llm_provider=None, report_mapper=None
        )._build_prompt(
            ResearchQuestion(question="What is X?"), summary
        )
        user = prompt.user or ""
        # Three concrete examples -- if a future refactor
        # drops the examples the LLM has less to anchor on.
        examples_present = sum(
            1
            for example in [
                "Plasma p-tau217",
                "Tau Biomarkers",
                "Blood-Based Biomarkers",
            ]
            if example in user
        )
        assert examples_present >= 2, (
            f"H1 section should contain at least 2 of 3 worked "
            f"examples to anchor the LLM; found {examples_present}"
        )

    def test_user_prompt_includes_length_guidance(self):
        """A length range (e.g. 5-15 words) prevents the
        LLM from emitting either single-word stubs or
        full-paragraph "headlines" that don't fit a
        H1.
        """
        from app.infrastructure.llm.report_generator import (
            LLMReportGenerator,
        )
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )

        papers = [
            Paper(
                title="P1",
                authors=[Author(first_name="A", last_name="B")],
                journal=Journal(name="J"),
                year=2024,
                abstract="",
                doi="10.1/x",
            )
        ]
        summary = Summary(body="body", papers_used=papers)
        prompt = LLMReportGenerator(
            llm_provider=None, report_mapper=None
        )._build_prompt(
            ResearchQuestion(question="What is X?"), summary
        )
        user = prompt.user or ""
        # The length guidance is a digit range -- look for
        # "5-15" or similar patterns.
        import re

        assert re.search(r"\d+\s*-\s*\d+\s*word", user), (
            "H1 section should include a word-count range "
            "to bound the title length"
        )

    def test_user_prompt_lists_anti_patterns(self):
        """Anti-patterns the LLM should NOT emit in the H1
        line: number prefixes (``# 1. Title``), date
        prefixes (``# 2024 Title``), question marks
        (``# What is X?``). These are common LLM
        defaults when the H1 directive is unclear.
        """
        from app.infrastructure.llm.report_generator import (
            LLMReportGenerator,
        )
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_question import (
            ResearchQuestion,
        )

        papers = [
            Paper(
                title="P1",
                authors=[Author(first_name="A", last_name="B")],
                journal=Journal(name="J"),
                year=2024,
                abstract="",
                doi="10.1/x",
            )
        ]
        summary = Summary(body="body", papers_used=papers)
        prompt = LLMReportGenerator(
            llm_provider=None, report_mapper=None
        )._build_prompt(
            ResearchQuestion(question="What is X?"), summary
        )
        user = prompt.user or ""
        # Tell the LLM not to prefix with a number, date,
        # or question mark. These are the common LLM
        # bad-patterns we want to avoid.
        assert "DO NOT" in user or "do not" in user, (
            "prompt should contain a 'DO NOT' or 'do not' "
            "directive guarding the H1 line"
        )
