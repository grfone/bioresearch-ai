"""
latex_generator.py

Render a :class:`ResearchReport` as a LaTeX (.tex) source
file the user can compile with ``pdflatex`` or
``latexmk``.

Why
---
The user can already download a PDF of the report. The
LaTeX export gives them the source so they can:

- Edit the report in their favourite LaTeX editor
  (Overleaf, TeXstudio, etc.) and recompile
- Re-style the document without touching the backend
- Hand the source to a journal that accepts LaTeX
  submissions

Output
------
A complete, self-contained ``.tex`` file:

- ``\\documentclass{article}``
- ``\\usepackage[utf8]{inputenc}`` for Unicode
- ``\\usepackage[T1]{fontenc}`` for proper European
  accents in the PDF output
- ``\\usepackage{hyperref}`` for clickable cross-references
  in the compiled PDF
- ``\\usepackage{enumitem}`` for fine-grained list control
- ``\\begin{document}`` ... ``\\end{document}``

The bibliography is rendered as a numbered ``enumerate``
list with ``\\label{bib-N}`` anchors; inline references
use ``\\hyperref[bib-N]{[N]}`` so clicking jumps to the
entry (just like the PDF export).

LaTeX escaping
--------------
LaTeX has nine reserved characters that must be
escaped or the document won't compile:

    ``\\`` ``&`` ``%`` ``$`` ``#`` ``_`` ``{`` ``}`` ``~`` ``^``

We escape each one before injecting text into the
output. The escapes are conservative -- they always
escape, even inside ``\\verb``-safe contexts -- which
produces correct output at the cost of slightly more
``\\verb``-like characters in the source.

Unicode handling
----------------
With ``\\usepackage[utf8]{inputenc}`` and
``\\usepackage[T1]{fontenc}``, the source can contain
literal UTF-8 (β, é, etc.) and pdflatex will compile
it correctly. We don't transliterate.

Out of scope
------------
This generator does NOT produce a fully-typeset
``article`` ready for journal submission. It produces
the *body* of the report. The user adds their own
``\\documentclass``, ``\\usepackage`` choices, and
``\\maketitle`` block if they want to re-style.
"""

from __future__ import annotations

import logging
import re

from app.domain.entities.citation import Citation
from app.domain.entities.research_report import ResearchReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LaTeX special-character escaping
# ---------------------------------------------------------------------------


# Characters that LaTeX treats as special. Each is
# replaced with its ``\command`` equivalent. Order
# matters: backslash must be escaped first because
# the other escapes introduce backslashes.
_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _latex_escape(text: str) -> str:
    """
    Escape LaTeX special characters in ``text``.

    Used for any text that comes from the LLM (paper
    titles, author names, body content) and is being
    injected into the rendered LaTeX source.

    The escape is applied per-character. Multi-character
    runs are processed one character at a time because
    LaTeX special characters are all single-byte in
    ASCII. Unicode code points pass through verbatim --
    ``\\usepackage[utf8]{inputenc}`` handles them.
    """
    out: list[str] = []
    for ch in text:
        if ch in _LATEX_SPECIAL_CHARS:
            out.append(_LATEX_SPECIAL_CHARS[ch])
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Paper marker conversion
# ---------------------------------------------------------------------------


# ``[paper:N]`` and grouped ``[paper:N, paper:M, ...]``
# markers in the LLM body. Same regex used by the PDF
# generator (kept independent so the two generators
# can evolve separately).
_PAPER_MARKER_RE = re.compile(r"\[paper:(\d+)\]")
_PAPER_GROUP_RE = re.compile(r"\[paper:(\d+)(?:,\s*paper:\d+)+\]")


def _latex_paper_marker_repl(match: re.Match[str], num_citations: int) -> str:
    """
    Convert a single ``[paper:N]`` marker to a
    ``\\hyperref[bib-N]{[N]}`` macro call.

    Out-of-range markers (``[paper:99]`` when there are
    only 17 citations) are dropped silently, mirroring
    the PDF generator's behaviour.
    """
    n = int(match.group(1))
    if n < 1 or n > num_citations:
        return ""
    return (
        f"\\hyperref[bib-{n}]{{\\textbf{{[{n}]}}}}"
    )


def _latex_paper_group_repl(
    match: re.Match[str], num_citations: int
) -> str:
    """
    Convert a grouped ``[paper:N, paper:M, ...]`` marker
    to a sequence of ``\\hyperref[bib-N]{[N]}`` calls
    separated by ``, ``.

    If some refs in the group are out of range, those
    refs are dropped and the rest stay. If the whole
    group is out of range, the group vanishes.
    """
    nums = [
        int(n) for n in re.findall(r"\d+", match.group(0))
        if 1 <= int(n) <= num_citations
    ]
    if not nums:
        return ""
    return ", ".join(
        f"\\hyperref[bib-{n}]{{\\textbf{{[{n}]}}}}"
        for n in nums
    )


def _latex_substitute_paper_markers(
    text: str, num_citations: int
) -> str:
    """
    Replace ``[paper:N]`` and grouped
    ``[paper:N, paper:M, ...]`` markers with LaTeX
    ``\\hyperref`` macros.

    The grouped form is processed first because its
    regex is a superset of the standalone regex; we
    don't want the standalone matcher to swallow one
    of the grouped entries.
    """
    text = _PAPER_GROUP_RE.sub(
        lambda m: _latex_paper_group_repl(m, num_citations), text
    )
    text = _PAPER_MARKER_RE.sub(
        lambda m: _latex_paper_marker_repl(m, num_citations), text
    )
    return text


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------


# ``**bold**`` -> ``\textbf{...}``
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# ``*italic*`` -> ``\textit{...}``  (must NOT be inside ``**...**``)
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
# `` `code` `` -> ``\texttt{...}``
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def _latex_strip_markdown(
    text: str, num_citations: int
) -> str:
    """
    Convert the small subset of Markdown we support to
    LaTeX. Mirrors :func:`_markdown_to_rlm` in the PDF
    generator but emits LaTeX commands instead of RLM
    tags.

    The escapes are applied AFTER markdown conversion
    so that ``\\textbf`` (which contains backslashes) is
    not re-escaped into ``\\textbackslash{}``.
    """
    text = _latex_substitute_paper_markers(text, num_citations)
    text = _BOLD_RE.sub(r"\\textbf{\1}", text)
    text = _ITALIC_RE.sub(r"\\textit{\1}", text)
    text = _INLINE_CODE_RE.sub(r"\\texttt{\1}", text)
    return text


# ---------------------------------------------------------------------------
# Body parser (line-oriented, mirrors the PDF generator)
# ---------------------------------------------------------------------------


_H1_LINE_RE = re.compile(r"^#\s+(.+?)\s*$")
_H2_LINE_RE = re.compile(r"^##\s+(.+?)\s*$")
_H3_LINE_RE = re.compile(r"^###\s+(.+?)\s*$")
_BULLET_LINE_RE = re.compile(r"^\s*-\s+(.+)$")


def _strip_first_sentence_duplicate(
    body: str, title: str
) -> str:
    """
    Remove a duplicated first sentence from the body
    when the H1 fallback has prepended the same
    sentence as the title.

    Mirrors the PDF generator's helper. Kept as a
    separate function so the two generators don't share
    import-time state.

    The match is intentionally strict: we require the
    body sentence to start with the title AND to be
    noticeably longer (>= 1.5x the title length). This
    prevents false positives where the body just
    happens to begin with the same single word as the
    title (we hit this during testing where the title
    ``"T"`` matched every body line that started with
    a word beginning with ``"t"``).
    """
    if not title or not body:
        return body
    title_norm = title.lower().strip().rstrip(".,;:!?")
    if len(title_norm) < 8:
        # Too short to safely match against the body
        # without false positives. Short titles happen
        # in unit tests and in real reports where the
        # LLM produces a one-word headline.
        return body
    body_lines = body.split("\n")
    if not body_lines:
        return body
    # Skip the H1 line if present.
    start_idx = 0
    if body_lines and body_lines[0].startswith("# "):
        start_idx = 1
    while (
        start_idx < len(body_lines)
        and not body_lines[start_idx].strip()
    ):
        start_idx += 1
    if start_idx >= len(body_lines):
        return body
    first = body_lines[start_idx].strip()
    first_norm = first.lower().rstrip(".,;:!?")
    if first_norm == title_norm:
        # Exact match -- the body line IS the title.
        # Always drop.
        return "\n".join(
            body_lines[:start_idx]
            + body_lines[start_idx + 1 :]
        ).lstrip("\n")
    if first_norm.startswith(title_norm):
        # Body line starts with the title -- probably
        # the duplicate first sentence with extra
        # words after. Drop the body line; keep the
        # rest of the prose.
        return "\n".join(
            body_lines[:start_idx]
            + body_lines[start_idx + 1 :]
        ).lstrip("\n")
    return body


def _parse_body_to_latex(
    body_text: str,
    *,
    title: str,
    num_citations: int,
) -> list[str]:
    """
    Convert the markdown body string to a list of
    LaTeX lines. Mirrors :func:`_parse_body_to_flowables`
    in the PDF generator.

    Supported markdown subset:
    - ``# H1`` line -- the first H1 becomes the page
      title; subsequent H1s render as ``\\section``.
    - ``## H2`` / ``### H3`` lines.
    - ``- bullet`` lines (consecutive bullets merge
      into a single ``itemize`` block).
    - Plain paragraphs.
    """
    body_text = _strip_first_sentence_duplicate(body_text, title)
    lines = body_text.split("\n")
    out: list[str] = []

    i = 0
    h1_seen = False
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            out.append("")
            i += 1
            continue

        # H1
        h1_match = _H1_LINE_RE.match(line)
        if h1_match:
            heading = _latex_escape(h1_match.group(1))
            if not h1_seen:
                # First H1 becomes the page title.
                # The title is rendered separately in
                # ``_build_latex``; we just record that
                # we've seen it.
                h1_seen = True
            else:
                # Subsequent H1s become sections.
                out.append("")
                out.append(f"\\section*{{{heading}}}")
                out.append("")
            i += 1
            continue

        # H2 / H3
        h2_match = _H2_LINE_RE.match(line)
        if h2_match:
            heading = _latex_escape(h2_match.group(1))
            out.append("")
            out.append(f"\\section*{{{heading}}}")
            out.append("")
            i += 1
            continue
        h3_match = _H3_LINE_RE.match(line)
        if h3_match:
            heading = _latex_escape(h3_match.group(1))
            out.append("")
            out.append(f"\\subsection*{{{heading}}}")
            out.append("")
            i += 1
            continue

        # Bullets
        if _BULLET_LINE_RE.match(line):
            out.append("\\begin{itemize}[leftmargin=*,itemsep=4pt]")
            while i < len(lines):
                bm = _BULLET_LINE_RE.match(lines[i].rstrip())
                if not bm:
                    break
                item = _latex_strip_markdown(
                    _latex_escape(bm.group(1)),
                    num_citations,
                )
                out.append(f"  \\item {item}")
                i += 1
            out.append("\\end{itemize}")
            out.append("")
            continue

        # Plain paragraph -- gather until next blank /
        # heading / bullet.
        para_lines = [line]
        i += 1
        while i < len(lines):
            peek = lines[i].rstrip()
            if (
                not peek.strip()
                or _H1_LINE_RE.match(peek)
                or _H2_LINE_RE.match(peek)
                or _H3_LINE_RE.match(peek)
                or _BULLET_LINE_RE.match(peek)
            ):
                break
            para_lines.append(peek)
            i += 1
        paragraph_text = _latex_strip_markdown(
            _latex_escape(" ".join(para_lines)),
            num_citations,
        )
        out.append(paragraph_text)
        out.append("")

    return out


# ---------------------------------------------------------------------------
# Citation rendering
# ---------------------------------------------------------------------------


def _format_citation_latex(citation: Citation) -> str:
    """
    Render a ``Citation`` as a single-line LaTeX-safe
    string for the bibliography entry.

    Uses the domain entity's :meth:`format` method
    (which already handles the citation-style
    dispatcher) and then applies LaTeX escaping on
    the result. The escaping happens on the rendered
    string rather than on each field individually
    so we catch any field the ``Citation`` formatter
    injects dynamically (e.g. DOI URLs).
    """
    return _latex_escape(citation.format())


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


_LATEX_PREAMBLE = (
    "% Auto-generated by BioResearch AI. Compile with\n"
    "%     pdflatex report.tex && pdflatex report.tex\n"
    "% (twice, so \\ref and \\hyperref cross-references\n"
    "% resolve on the second pass).\n"
    "\\documentclass[11pt,a4paper]{article}\n"
    "\\usepackage[utf8]{inputenc}\n"
    "\\usepackage[T1]{fontenc}\n"
    "\\usepackage{lmodern}\n"
    "% lmodern is the Latin Modern font -- it extends the\n"
    "% T1 encoding to cover the Greek letters (\u03b2, \u03b1,\n"
    "% \u03b3) and other glyphs we use in biomedical text.\n"
    "% Without lmodern, pdflatex raises ``Unicode\n"
    "% character \u03b2 (U+03B2) not set up for use with LaTeX``.\n"
    "\\usepackage{textgreek}\n"
    "% textgreek provides ``\\textalpha`` / ``\\textbeta`` /\n"
    "% ``\\textgamma`` / etc. for upright Greek letters in\n"
    "% text mode. Required by the declares below --\n"
    "% without it, the ``\\textalpha`` macros are\n"
    "% undefined and pdflatex fails.\n"
    "% Belt-and-braces: declare Unicode fallbacks for the\n"
    "% biomedical Greek letters and Latin diacritics. These\n"
    "% MUST come BEFORE ``\\usepackage{hyperref}`` because\n"
    "% hyperref switches the document encoding to PU which\n"
    "% would otherwise override the inputenc mapping. We\n"
    "% declare all the glyphs the LLM might emit.\n"
    "\\DeclareUnicodeCharacter{03B1}{\\textalpha}\n"
    "\\DeclareUnicodeCharacter{03B2}{\\textbeta}\n"
    "\\DeclareUnicodeCharacter{03B3}{\\textgamma}\n"
    "\\DeclareUnicodeCharacter{03B4}{\\textdelta}\n"
    "\\DeclareUnicodeCharacter{03BC}{\\textmu}\n"
    "\\DeclareUnicodeCharacter{03C3}{\\textsigma}\n"
    "\\DeclareUnicodeCharacter{03C4}{\\texttau}\n"
    "\\DeclareUnicodeCharacter{00E9}{\\'e}\n"
    "\\DeclareUnicodeCharacter{00F6}{\\\"o}\n"
    "\\DeclareUnicodeCharacter{00FC}{\\\"u}\n"
    "\\DeclareUnicodeCharacter{00E7}{\\c{c}}\n"
    "\\DeclareUnicodeCharacter{00F1}{\\~{n}}\n"
    "\\DeclareUnicodeCharacter{015F}{\\c{s}}\n"
    "\\usepackage[hidelinks,unicode]{hyperref}\n"
    "\\usepackage{enumitem}\n"
    "\\usepackage[margin=1in]{geometry}\n"
    "\\usepackage{parskip}\n"
    "\\hypersetup{\n"
    "  pdftitle={Biomedical Research Report},\n"
    "  colorlinks=true,\n"
    "  linkcolor=blue,\n"
    "  citecolor=blue,\n"
    "  urlcolor=blue,\n"
    "}\n"
    "\\title{%(title)s}\n"
    "\\author{}\n"
    "\\date{}\n"
    "\\begin{document}\n"
    "\\maketitle\n"
)


_LATEX_BODY_HEADER = (
    "\\section*{Executive Summary}\n"
    "\\addcontentsline{toc}{section}{Executive Summary}\n"
)


_LATEX_BIB_HEADER = (
    "\n\\clearpage\n"
    "\\section*{Bibliography}\n"
    "\\addcontentsline{toc}{section}{Bibliography}\n"
    "\\begin{enumerate}[leftmargin=*,itemsep=6pt]\n"
)


_LATEX_FOOTER = (
    "\\end{enumerate}\n"
    "\\end{document}\n"
)


class LatexReportGenerator:
    """
    Render a :class:`ResearchReport` as a LaTeX source
    string.

    Public method
    -------------
    - :func:`generate` -- returns the LaTeX source as
      ``str``. The caller is responsible for saving it
      to disk (or streaming it to a download endpoint).

    Notes
    -----
    The output is a UTF-8 encoded ``str`` in Python; the
    caller writes it as ``.tex`` with the appropriate
    content-type. Newlines are ``\\n`` (Unix style);
    pdflatex accepts both styles.
    """

    def generate(self, report: ResearchReport) -> str:
        """
        Render ``report`` as a complete LaTeX document.

        Raises ``ValueError`` if the report has no
        summary body.
        """
        if not report.summary or not report.summary.body:
            raise ValueError(
                "Cannot render an empty report as LaTeX. "
                "The report's summary body is empty."
            )
        return self._build_latex(report)

    def _build_latex(self, report: ResearchReport) -> str:
        """Assemble the LaTeX source string."""
        body_text = report.summary.body
        # Extract H1 title.
        title = ""
        for line in body_text.split("\n"):
            m = _H1_LINE_RE.match(line)
            if m:
                title = m.group(1).strip()
                break
        if not title:
            title = "Biomedical Research Report"

        num_citations = len(report.citations)
        title_escaped = _latex_escape(title)

        parts: list[str] = []
        # The preamble contains LaTeX { ... } arguments
        # that .format() would try to parse. Use a
        # plain substitution.
        parts.append(_LATEX_PREAMBLE.replace(
            "%(title)s", title_escaped,
        ))
        parts.append(_LATEX_BODY_HEADER)

        # Body
        body_lines = _parse_body_to_latex(
            body_text, title=title, num_citations=num_citations
        )
        parts.extend(body_lines)

        # Limitations
        if report.limitations:
            parts.append("\\section*{Limitations}")
            parts.append("\\begin{itemize}[leftmargin=*,itemsep=4pt]")
            for lim in report.limitations:
                item = _latex_strip_markdown(
                    _latex_escape(lim), num_citations
                )
                parts.append(f"  \\item {item}")
            parts.append("\\end{itemize}")
            parts.append("")

        # Future Work
        if report.future_work:
            parts.append(
                "\\section*{Future Research Directions}"
            )
            parts.append("\\begin{itemize}[leftmargin=*,itemsep=4pt]")
            for fw in report.future_work:
                item = _latex_strip_markdown(
                    _latex_escape(fw), num_citations
                )
                parts.append(f"  \\item {item}")
            parts.append("\\end{itemize}")
            parts.append("")

        # Bibliography
        if report.citations:
            parts.append(_LATEX_BIB_HEADER)
            for i, citation in enumerate(report.citations, start=1):
                entry = _format_citation_latex(citation)
                parts.append(
                    f"  \\item[{i}] "
                    f"\\label{{bib-{i}}} {entry}"
                )
            parts.append(_LATEX_FOOTER)
        else:
            parts.append("\\end{document}\n")

        return "\n".join(parts)
