"""
Tests for :class:`LatexReportGenerator`.

The user-visible bug being guarded against is "the PDF
came out garbled" -- LaTeX special characters in the LLM's
output would otherwise break compilation (``_`` in author
names, ``&`` in titles, ``%`` in DOIs). These tests pin
the escape contract.
"""

from __future__ import annotations

import subprocess

import pytest

from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary
from app.infrastructure.latex.latex_generator import (
    LatexReportGenerator,
    _latex_escape,
    _latex_strip_markdown,
    _latex_substitute_paper_markers,
)


def _paper(title: str, doi: str | None = None) -> Paper:
    return Paper(
        title=title,
        authors=[Author(first_name="A", last_name="Author")],
        journal=Journal(name="Nature"),
        year=2024,
        abstract="",
        doi=doi,
        pmid=None,
        keywords=[],
        url=None,
    )


def _report(
    body: str = "",
    *,
    citations: list[Paper] | None = None,
    limitations: list[str] | None = None,
    future_work: list[str] | None = None,
) -> ResearchReport:
    citations = citations or []
    return ResearchReport(
        summary=Summary(body=body, papers_used=[]),
        citations=[Citation(paper=p) for p in citations],
        limitations=limitations or [],
        future_work=future_work or [],
        metadata={},
    )


@pytest.fixture
def generator() -> LatexReportGenerator:
    return LatexReportGenerator()


def _try_compile(tex_source: str) -> tuple[bool, str]:
    """
    Best-effort ``pdflatex`` compilation. Returns
    ``(success, log_tail)``.

    Skips the test gracefully if ``pdflatex`` isn't on
    PATH (it's a heavy system dep that the minimal
    Docker image doesn't ship).

    Writes the source to a temp file rather than
    streaming via stdin: pdflatex's stdin handling
    drops the first line and other quirks on
    certain TeX Live versions.
    """
    import os
    import tempfile

    out_dir = "/tmp/latex_test_out"
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tex", dir=out_dir, delete=False,
    ) as f:
        f.write(tex_source)
        tex_path = f.name
    try:
        proc = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={out_dir}",
                tex_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode == 0, proc.stdout[-2000:]
    except FileNotFoundError:
        pytest.skip("pdflatex not installed")
    finally:
        # Cleanup the .tex file. Leave the .pdf for
        # debugging if a later run fails.
        try:
            os.unlink(tex_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# LaTeX escape contract (unit)
# ---------------------------------------------------------------------------


class TestLatexEscape:
    """Pin every special-character escape."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("plain text", "plain text"),
            ("_underscore_", r"\_underscore\_"),
            ("& ampersand", r"\& ampersand"),
            ("% percent", r"\% percent"),
            ("$ dollar", r"\$ dollar"),
            ("# hash", r"\# hash"),
            ("curly {braces}", r"curly \{braces\}"),
            ("tilde ~ character", r"tilde \textasciitilde{} character"),
            ("caret ^ character", r"caret \textasciicircum{} character"),
            ("back\\slash", r"back\textbackslash{}slash"),
        ],
    )
    def test_special_chars_escaped(
        self, raw: str, expected: str
    ) -> None:
        assert _latex_escape(raw) == expected

    def test_unicode_passes_through(self) -> None:
        """Unicode characters are NOT escaped -- the
        ``inputenc`` package handles them."""
        text = "Plasma Aβ and α-synuclein"
        assert _latex_escape(text) == text

    def test_combination(self) -> None:
        raw = "Smith & Jones _2025_"
        assert _latex_escape(raw) == r"Smith \& Jones \_2025\_"


# ---------------------------------------------------------------------------
# Paper marker substitution
# ---------------------------------------------------------------------------


class TestPaperMarkerSubstitution:
    """Convert ``[paper:N]`` markers to LaTeX hyperref calls."""

    def test_standalone_marker_becomes_hyperref(self) -> None:
        out = _latex_substitute_paper_markers(
            "text [paper:3]", num_citations=5
        )
        assert r"\hyperref[bib-3]{\textbf{[3]}}" in out

    def test_grouped_marker_becomes_multiple_hyperrefs(self) -> None:
        out = _latex_substitute_paper_markers(
            "text [paper:3, paper:5]", num_citations=10
        )
        assert r"\hyperref[bib-3]{\textbf{[3]}}" in out
        assert r"\hyperref[bib-5]{\textbf{[5]}}" in out

    def test_out_of_range_marker_dropped(self) -> None:
        out = _latex_substitute_paper_markers(
            "text [paper:99]", num_citations=5
        )
        assert "[99]" not in out

    def test_zero_or_negative_marker_dropped(self) -> None:
        out = _latex_substitute_paper_markers(
            "[paper:0] and [paper:-3]", num_citations=5
        )
        assert "[0]" not in out
        assert "[-3]" not in out

    def test_partial_group_dropped_silently(self) -> None:
        out = _latex_substitute_paper_markers(
            "[paper:1, paper:99, paper:2]", num_citations=5
        )
        assert "[1]" in out
        assert "[2]" in out
        assert "[99]" not in out


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------


class TestLatexMarkdownStrip:
    """Markdown -> LaTeX command conversion."""

    def test_bold_marker_converted(self) -> None:
        out = _latex_strip_markdown("**bold text**", num_citations=0)
        assert r"\textbf{bold text}" in out

    def test_italic_marker_converted(self) -> None:
        out = _latex_strip_markdown("*italic text*", num_citations=0)
        assert r"\textit{italic text}" in out

    def test_inline_code_converted(self) -> None:
        out = _latex_strip_markdown("`code`", num_citations=0)
        assert r"\texttt{code}" in out


# ---------------------------------------------------------------------------
# Generator behaviour
# ---------------------------------------------------------------------------


class TestLatexGenerator:
    """Pin the generated LaTeX source's contract."""

    def test_generate_rejects_empty_body(
        self, generator: LatexReportGenerator
    ) -> None:
        with pytest.raises(ValueError, match="empty"):
            generator.generate(_report(body=""))

    def test_output_starts_with_documentclass(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# Title\n\nBody text.",
        ))
        assert r"\documentclass" in tex

    def test_output_ends_with_end_document(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# Title\n\nBody text.",
        ))
        assert tex.rstrip().endswith(r"\end{document}")

    def test_title_appears_in_output(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# Tau Biomarkers\n\nBody text.",
        ))
        assert "Tau Biomarkers" in tex

    def test_body_text_appears_in_output(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# T\n\nThe unique body content sentence.",
        ))
        assert "unique body content sentence" in tex

    def test_exec_summary_section_present(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(body="# T\n\nBody."))
        assert r"\section*{Executive Summary}" in tex

    def test_limitations_section_present(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# T\n\nBody.",
            limitations=["Limitation A.", "Limitation B."],
        ))
        assert r"\section*{Limitations}" in tex
        assert "Limitation A." in tex
        assert "Limitation B." in tex

    def test_future_work_section_present(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# T\n\nBody.",
            future_work=["Direction 1.", "Direction 2."],
        ))
        assert r"\section*{Future Research Directions}" in tex
        assert "Direction 1." in tex
        assert "Direction 2." in tex

    def test_bibliography_section_present(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# T\n\nBody.",
            citations=[_paper("First paper"), _paper("Second paper")],
        ))
        assert r"\section*{Bibliography}" in tex
        assert r"\begin{enumerate}" in tex
        assert r"\label{bib-1}" in tex
        assert r"\label{bib-2}" in tex

    def test_paper_markers_become_hyperref(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# T\n\nBody [paper:1] and [paper:3].",
            citations=[
                _paper("A"), _paper("B"), _paper("C"),
            ],
        ))
        assert r"\hyperref[bib-1]{\textbf{[1]}}" in tex
        assert r"\hyperref[bib-3]{\textbf{[3]}}" in tex

    def test_out_of_range_markers_dropped(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body="# T\n\nBody [paper:99].",
            citations=[_paper("A"), _paper("B")],
        ))
        # No dangling ``[99]``.
        assert "[99]" not in tex
        assert r"\hyperref[bib-99]" not in tex

    def test_duplicate_first_sentence_stripped(
        self, generator: LatexReportGenerator
    ) -> None:
        """Same fix as the PDF generator: the H1
        fallback duplicates the first sentence; we
        strip it from the body so the title appears
        only once."""
        body = (
            "# Tau biomarkers are central\n\n"
            "Tau biomarkers are central to AD.\n"
            "Plasma p-tau217 is the leading marker.\n"
        )
        tex = generator.generate(_report(body=body))
        # Duplicate sentence dropped.
        assert "Tau biomarkers are central to AD.\n" not in tex
        # Subsequent prose preserved.
        assert "Plasma p-tau217" in tex

    def test_special_chars_in_body_escaped(
        self, generator: LatexReportGenerator
    ) -> None:
        """Paper titles with ``_`` or ``&`` would
        otherwise break LaTeX compilation."""
        tex = generator.generate(_report(
            body="# T\n\nBody with & and _underscore_.",
        ))
        assert r"\&" in tex
        assert r"\_" in tex

    def test_special_chars_in_citation_escaped(
        self, generator: LatexReportGenerator
    ) -> None:
        """Citation strings can contain LaTeX-reserved
        chars from the title or DOI URL."""
        tex = generator.generate(_report(
            body="# T\n\nBody.",
            citations=[_paper("Title_with_underscore", doi="10.0/100%test")],
        ))
        assert r"\_" in tex
        assert r"\%" in tex


# ---------------------------------------------------------------------------
# Live compilation
# ---------------------------------------------------------------------------


class TestLatexCompiles:
    """
    End-to-end smoke test: the generated LaTeX actually
    compiles with ``pdflatex``. Skipped if pdflatex
    isn't installed.
    """

    def test_generated_latex_compiles(
        self, generator: LatexReportGenerator
    ) -> None:
        tex = generator.generate(_report(
            body=(
                "# Tau biomarkers in Alzheimer's disease\n\n"
                "Plasma p-tau217 is a leading marker "
                "[paper:1]. Cerebrospinal fluid (CSF) "
                "biomarkers remain important.\n\n"
                "## Diagnostic frameworks\n\n"
                "Multi-analyte panels may outperform "
                "single markers [paper:2].\n"
            ),
            citations=[
                _paper("First paper with _underscores_", doi="10.0/100%test"),
                _paper("Second paper"),
            ],
            limitations=["Limited sample size [paper:1]."],
            future_work=["Multi-centre trials [paper:2]."],
        ))
        # Skip if pdflatex isn't on PATH.
        success, log_tail = _try_compile(tex)
        if not success:
            pytest.fail(
                f"pdflatex failed to compile generated "
                f"LaTeX:\n{log_tail}"
            )
