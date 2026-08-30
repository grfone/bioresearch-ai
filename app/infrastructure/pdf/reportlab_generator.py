"""
reportlab_generator.py

PDF report generator built on top of Reportlab.

Why reportlab
-------------
The previous hand-rolled generator (``minimal_generator.py``)
shipped a working PDF but had four user-visible bugs we could
not reasonably fix without a real PDF library:

1. **No Unicode coverage.** Helvetica base-14 + WinAnsiEncoding
   covers Latin-1 only. Greek letters (β, α, γ), Latin
   diacritics (Ş, é, ü), and other common biomedical glyphs
   came out as ``?``. Reportlab with an embedded TTF font
   (DejaVu Sans) renders them correctly.

2. **Citation references disappeared.** The hand-rolled
   generator stripped ``[paper:N]`` markers entirely; the user
   wanted the numbered refs ``[1]``, ``[2]`` to remain
   visible AND clickable, jumping to the bibliography entry
   on the same page. Reportlab's ``Paragraph`` flowables
   plus ``Anchor`` / ``Link`` flowables give us real PDF
   /Link annotations (the kind Acrobat / Preview understand).

3. **Markdown leaked through.** ``**Plasma phosphorylated
   tau (p-tau) and related blood biomarkers**`` showed the
   asterisks literally. Reportlab's Paragraph uses ReportLab
   Markup Language (RML) -- a small HTML-like subset. We
   convert the markdown to RML before handing it to
   Paragraph.

4. **Long lines overflowed the right margin.** The hand-rolled
   wrapper measured an average character width and greedily
   split words; long citation strings overflowed. Reportlab's
   Paragraph does proper text wrapping with a real font
   measurement.

Implementation
--------------
- ``_render_lab`` is the reportlab Platypus flow we hand to
  ``SimpleDocTemplate``. It contains ``Paragraph`` (wrapped
  body), ``Spacer`` (vertical gaps), ``PageBreak`` (forced
  page break before the bibliography if needed), and
  ``Link`` / ``Anchor`` pairs for clickable citation refs.
- The body markdown is preprocessed: H1 line stripped
  (becomes the page title), bold markers converted to
  ``<b>...</b>``, italic markers to ``<i>...</i>``,
  ``[paper:N]`` to ``<link href="#bib-N">[N]</link>``.
- Citations are rendered as a numbered list at the end of
  the document. Each citation gets a ``<a name="bib-N"/>``
  anchor (the clickable target for inline refs).
- Limitations / Future Work are ``<bullet>`` flowables
  with the same ``[paper:N]`` → numbered-ref conversion.
- DejaVu Sans TTF is embedded for Unicode coverage. The
  font is loaded lazily on first ``generate()`` call so
  the import of this module is fast and the cost is only
  paid by workspaces that actually publish.

Spec references
---------------
- PDF 1.4 spec (``PDF 32000-1:2008``). Reportlab handles
  the cross-reference, trailer, and indirect-object
  numbering internally; we don't touch those.
- Reportlab User Guide Chapter 5 (Platypus) for the
  flowable composition pattern.

Limitations
-----------
- DejaVu Sans covers Latin, Greek, Cyrillic, and a wide
  range of punctuation. CJK characters render as missing
  glyphs (the tofu box) -- we don't ship a CJK font. If a
  workspace's query is in CJK, the user can install one
  with a future PR.
- The PDF's title and report body come from
  ``report.summary.body``; the React UI uses the same
  field. We strip a duplicated first paragraph (a
  recurring artefact of the H1 fallback that prepends the
  first sentence of the body as the title).
- ``pdf_bytes`` is *not* byte-deterministic across runs
  (Reportlab embeds a creation-date timestamp). Tests
  asserting on byte content should compare content
  extracted via a PDF reader, not the raw bytes.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import logging
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.platypus.flowables import HRFlowable

from app.domain.entities.citation import Citation
from app.domain.entities.research_report import ResearchReport
from app.domain.interfaces.pdf_generator import PDFGenerator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Markdown / paper-marker preprocessing
# ---------------------------------------------------------------------------


# ``[paper:N]`` standalone marker (single ref).
_PAPER_MARKER_RE = re.compile(r"\[paper:(\d+)\]")

# ``[paper:N, paper:M, ...]`` grouped marker (multiple refs in one bracket).
_PAPER_GROUP_RE = re.compile(r"\[paper:(\d+)(?:,\s*paper:\d+)+\]")

# Markdown emphasis.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")

# Headings: H1 / H2 / H3 lines. Only H1 is used for the page title.
_H1_LINE_RE = re.compile(r"^#\s+(.+?)\s*$")
_H2_LINE_RE = re.compile(r"^##\s+(.+?)\s*$")
_H3_LINE_RE = re.compile(r"^###\s+(.+?)\s*$")

# Bullet lines (``- foo``).
_BULLET_LINE_RE = re.compile(r"^\s*-\s+(.+)$")


def _normalise_unicode(text: str) -> str:
    """
    Normalise Unicode punctuation to ASCII equivalents.

    Hand-rolled PDF generators can't render arbitrary
    Unicode; reportlab + DejaVu Sans can, but for users
    who want predictable byte behaviour (CI diffs,
    regression tests) we still normalise the most common
    smart-quote / dash / ellipsis cases.

    Greek letters (β, α, γ) are NOT transliterated --
    DejaVu Sans covers them. Diacritics are NOT
    transliterated either. Only the punctuation that
    LLMs frequently substitute is normalised.
    """
    return (
        text
        .replace("\u2014", "--")  # em dash
        .replace("\u2013", "-")   # en dash
        .replace("\u2212", "-")   # minus sign
        .replace("\u2015", "-")   # horizontal bar
        .replace("\u2018", "'")   # left single quote
        .replace("\u2019", "'")   # right single quote
        .replace("\u201c", '"')   # left double quote
        .replace("\u201d", '"')   # right double quote
        .replace("\u2026", "...") # ellipsis
        .replace("\u00a0", " ")   # non-breaking space
        .replace("\u2003", " ")   # em space
        .replace("\u2002", " ")   # en space
        .replace("\u2009", " ")   # thin space
    )


def _strip_first_sentence_duplicate(
    body: str, title: str
) -> str:
    """
    Remove a duplicated first sentence from the body.

    The H1-fallback path prepends the first sentence of
    the body as the title. When the LLM also writes a
    first sentence that's identical or near-identical to
    the title, the body contains the title twice. The PDF
    only needs the title once.

    We detect the duplicate by looking at the body's
    **first non-H1 line** -- the line that would become
    the executive summary's opening paragraph. If that
    line starts with the title text, drop it.

    The match is intentionally strict: we require the
    body sentence to start with the title AND to be
    noticeably longer (>= 1.5x the title length). This
    prevents false positives where the body just
    happens to begin with the same single word as the
    title (e.g. a unit test fixture with ``title="T"``
    matching every body line that starts with ``"t"``).

    Only the first sentence is considered -- if the user
    has a body that opens with the title but then
    continues with new content, the new content stays.
    """
    if not title or not body:
        return body
    title_norm = title.lower().strip().rstrip(".,;:!?")
    if len(title_norm) < 8:
        # Too short to safely match against the body
        # without false positives.
        return body
    body_lines = body.split("\n")
    if not body_lines:
        return body
    # Skip the H1 line if present -- that's the page
    # title, not part of the body prose.
    start_idx = 0
    if body_lines and body_lines[0].startswith("# "):
        start_idx = 1
    # Also skip blank lines after the H1.
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


def _convert_paper_markers_to_rlm(
    text: str, num_citations: int = 0
) -> str:
    """
    Convert ``[paper:N]`` and ``[paper:N, paper:M, ...]``
    markers to ReportLab Markup Language (RLM) link tags.

    RLM doesn't have a native ``[1]`` superscript; we
    render numbered references as plain text inside a
    blue-coloured ``<font>`` element with a clickable
    ``<link>`` that jumps to the bibliography anchor
    ``bib-N``.

    The link element is rendered as ``[N]`` so the
    printed document looks like a typical Vancouver-style
    citation: a bracketed number inline.

    The destination value is prefixed with ``#`` because
    reportlab's paragraph parser dispatches on the prefix:
    a value starting with ``#`` is treated as an internal
    bookmark and goes through ``canvas.linkRect()``
    (producing ``/Dest`` in the PDF). Without the prefix,
    the same code path emits ``/A << /S /URI ... >>``
    instead -- which Acrobat treats as a broken link to a
    non-existent URL. We hit this on 2026-08-30 during the
    PDF rewrite; the fix is the single ``#`` character
    below.

    Out-of-range markers (``[paper:99]`` when there are
    only 17 references) are dropped silently. The backend
    ``linkifyCitationMarkers`` is also responsible for
    clamping them, but we defend in depth here so the PDF
    generation never produces a broken /Link annotation
    pointing at a non-existent /Dest. Without this guard,
    reportlab raises ``ValueError: format not resolved``
    at save time (we hit this on 2026-08-30).
    """
    # Process grouped markers first (longer match wins).
    def _group_repl(match: re.Match[str]) -> str:
        nums = [
            n for n in re.findall(r"\d+", match.group(0))
            if 1 <= int(n) <= num_citations
        ]
        if not nums:
            return ""
        return ", ".join(
            f'<link destination="#bib-{n}" color="#1d4ed8"><b>[{n}]</b></link>'
            for n in nums
        )

    def _single_repl(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if n < 1 or n > num_citations:
            return ""
        return (
            f'<link destination="#bib-{n}" color="#1d4ed8"><b>[{n}]</b></link>'
        )

    text = _PAPER_GROUP_RE.sub(_group_repl, text)
    text = _PAPER_MARKER_RE.sub(_single_repl, text)
    return text


def _markdown_to_rlm(text: str, num_citations: int = 0) -> str:
    """
    Convert the small subset of Markdown we support to
    ReportLab Markup Language.

    Supported conversions:
    - ``**bold**`` -> ``<b>bold</b>``
    - ``*italic*`` -> ``<i>italic</i>``
    - `` `code` `` -> ``<font face="Courier">code</font>``
    - ``[paper:N]`` -> clickable numbered ref (see
      ``_convert_paper_markers_to_rlm``)

    Anything else passes through; RLM escapes ``<``, ``>``
    and ``&`` for us automatically.
    """
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    text = _convert_paper_markers_to_rlm(text, num_citations=num_citations)
    text = _INLINE_CODE_RE.sub(
        r'<font face="Courier">\1</font>', text
    )
    return text


def _escape_rlm_text(text: str) -> str:
    """
    Escape text for safe inclusion inside an RLM <font>
    or <para> tag.

    RML treats ``<``, ``>`` and ``&`` as markup. We
    escape them so user-supplied content (paper titles,
    author names) renders literally instead of being
    parsed as tags.
    """
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------


_DEJAVU_SANS_PATH = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)
_DEJAVU_SANS_BOLD_PATH = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)
_DEJAVU_SANS_ITALIC_PATH = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"
)
_DEJAVU_SANS_BOLD_ITALIC_PATH = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"
)


_FONTS_REGISTERED = False


def _ensure_fonts_registered() -> None:
    """
    Register the DejaVu Sans TTF fonts with reportlab on
    first use.

    We register four faces (regular, bold, italic,
    bold-italic) so Paragraphs can use ``<b>`` and
    ``<i>`` tags without falling back to the default
    Helvetica.

    Failures here are loud (the PDF generator raises)
    rather than silent (falling back to Helvetica and
    producing ``?`` for non-ASCII). The user would
    rather see an actionable error message than a
    silently-broken PDF.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", _DEJAVU_SANS_PATH))
        pdfmetrics.registerFont(
            TTFont("DejaVuSans-Bold", _DEJAVU_SANS_BOLD_PATH)
        )
        pdfmetrics.registerFont(
            TTFont("DejaVuSans-Italic", _DEJAVU_SANS_ITALIC_PATH)
        )
        pdfmetrics.registerFont(
            TTFont(
                "DejaVuSans-BoldItalic", _DEJAVU_SANS_BOLD_ITALIC_PATH
            )
        )
        # Register a font family so ``<b>`` inside a
        # Paragraph correctly switches to the bold face.
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily(
            "DejaVuSans",
            normal="DejaVuSans",
            bold="DejaVuSans-Bold",
            italic="DejaVuSans-Italic",
            boldItalic="DejaVuSans-BoldItalic",
        )
        _FONTS_REGISTERED = True
    except Exception as exc:
        raise RuntimeError(
            "Could not load DejaVu Sans TTF fonts for PDF "
            "generation. The minimal image must include the "
            "fonts-dejavu-core package (apt-get install "
            "fonts-dejavu-core). The original error was: "
            f"{exc!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Style sheet
# ---------------------------------------------------------------------------


def _build_styles() -> dict[str, ParagraphStyle]:
    """
    Define the Paragraph styles for title, headings,
    body, citations, limitations, future-work.

    All styles use the DejaVu Sans family so the bold /
    italic emphasis tags inside Paragraphs find the
    right glyphs. Font sizes are in points; leading is
    1.4x for body, 1.2x for headings.
    """
    body_font_size = 11
    title_font_size = 22
    h2_font_size = 15
    h3_font_size = 12

    return {
        "title": ParagraphStyle(
            name="Title",
            fontName="DejaVuSans-Bold",
            fontSize=title_font_size,
            leading=title_font_size * 1.25,
            spaceAfter=18,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#0f172a"),
        ),
        "subtitle": ParagraphStyle(
            name="Subtitle",
            fontName="DejaVuSans-Italic",
            fontSize=12,
            leading=16,
            spaceAfter=24,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#475569"),
        ),
        "h2": ParagraphStyle(
            name="H2",
            fontName="DejaVuSans-Bold",
            fontSize=h2_font_size,
            leading=h2_font_size * 1.3,
            spaceBefore=18,
            spaceAfter=8,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#0f172a"),
        ),
        "h3": ParagraphStyle(
            name="H3",
            fontName="DejaVuSans-Bold",
            fontSize=h3_font_size,
            leading=h3_font_size * 1.3,
            spaceBefore=10,
            spaceAfter=4,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1e293b"),
        ),
        "body": ParagraphStyle(
            name="Body",
            fontName="DejaVuSans",
            fontSize=body_font_size,
            leading=body_font_size * 1.5,
            spaceAfter=8,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1e293b"),
        ),
        "bullet": ParagraphStyle(
            name="Bullet",
            fontName="DejaVuSans",
            fontSize=body_font_size,
            leading=body_font_size * 1.4,
            spaceAfter=4,
            leftIndent=18,
            bulletIndent=4,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1e293b"),
        ),
        "citation": ParagraphStyle(
            name="Citation",
            fontName="DejaVuSans",
            fontSize=10,
            leading=14,
            spaceAfter=4,
            leftIndent=24,
            firstLineIndent=-24,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1e293b"),
        ),
    }


# ---------------------------------------------------------------------------
# Paragraph + Anchor flowable pair (numbered bibliography entries)
# ---------------------------------------------------------------------------


class _BibliographyEntry(Flowable):
    """
    A flowable that draws a numbered bibliography entry
    plus an invisible anchor at the same y-position so
    that inline ``<link href="#bib-N">`` references in
    the body jump here.

    We render text manually (instead of using a
    Paragraph) so the ``y`` coordinate is well-defined
    when the canvas saves the anchor. Reportlab's
    Paragraph flowable moves y in non-obvious ways
    (descender adjustments, leading) which would
    mis-position the anchor.

    Width is the full usable width; height is computed
    via ``stringWidth`` and a manual line-wrap. We keep
    it simple: split on spaces, greedily fit each line.
    """

    def __init__(
        self,
        number: int,
        text: str,
        anchor: str,
        *,
        font_name: str,
        font_size: float,
        leading: float,
        left_indent: float,
    ) -> None:
        super().__init__()
        self.number = number
        self.text = _normalise_unicode(text)
        self.anchor = anchor
        self.font_name = font_name
        self.font_size = font_size
        self.leading = leading
        self.left_indent = left_indent

        # Pre-compute the wrap so ``wrap`` / ``draw`` are
        # cheap.
        from reportlab.pdfbase.pdfmetrics import stringWidth

        usable_width = (
            LETTER[0]
            - 1.2 * inch   # left margin (matches doc)
            - 1.0 * inch   # right margin (matches doc)
            - left_indent
        )
        prefix = f"{number}. "
        prefix_w = stringWidth(prefix, font_name, font_size)
        text_w = stringWidth(text, font_name, font_size)
        if prefix_w + text_w <= usable_width:
            self._lines = [(prefix, text)]
        else:
            # Wrap with hanging indent: the first line
            # gets the number prefix, subsequent lines
            # start aligned with the text body (not under
            # the number).
            words = text.split()
            self._lines = []
            current_prefix = prefix
            current_text = ""
            for word in words:
                test = (
                    f"{current_prefix}{current_text} {word}".strip()
                )
                if stringWidth(test, font_name, font_size) <= usable_width:
                    current_text = (
                        f"{current_text} {word}".strip()
                    )
                else:
                    if current_text:
                        self._lines.append(
                            (current_prefix, current_text)
                        )
                    current_prefix = " " * len(prefix)
                    current_text = word
            if current_text:
                self._lines.append((current_prefix, current_text))

        self.width = usable_width + left_indent
        self.height = len(self._lines) * leading

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:  # type: ignore[override]
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        x_left = self.left_indent
        x_right = self.width
        y_top = self.height
        y_bottom = 0
        c.saveState()
        # Drop a named destination so the inline
        # ``<link destination="bib-N">`` annotations
        # in the body can jump here. Reportlab's
        # ``bookmarkHorizontal`` writes a PDF named
        # destination (``<< /D (name) >>``) that the
        # ``InternalLink`` flowable's ``linkRect``
        # resolves to via ``/A << /S /GoTo /D (name) >>``.
        c.bookmarkHorizontal(self.anchor, x_left, y_top)
        # Draw each line.
        y = y_top
        for prefix, text in self._lines:
            if prefix:
                c.setFont("DejaVuSans-Bold", self.font_size)
                c.drawString(x_left, y - self.font_size, prefix)
            c.setFont(self.font_name, self.font_size)
            c.drawString(
                x_left + (len(prefix) * self.font_size * 0.55),
                y - self.font_size,
                text,
            )
            y -= self.leading
        c.restoreState()


# ---------------------------------------------------------------------------
# Body parser
# ---------------------------------------------------------------------------


def _parse_body_to_flowables(
    body_text: str,
    styles: dict[str, ParagraphStyle],
    *,
    title: str,
    num_citations: int = 0,
) -> list[Flowable]:
    """
    Convert the markdown body string to a list of
    reportlab flowables.

    The parsing is line-oriented (not full CommonMark)
    because the LLM emits a small, well-defined subset
    of markdown. We support:

    - H1 (``# ``) line -- the very first H1 is the
      page title; subsequent H1s are rendered as H2.
    - H2 / H3 lines.
    - Bullet lines (``- foo``).
    - Empty lines -- paragraph break.
    - All other lines -- a paragraph of body text.

    The duplicate-first-sentence guard strips a body
    line that repeats the title (an artefact of the H1
    fallback).
    """
    body_text = _normalise_unicode(body_text)
    body_text = _strip_first_sentence_duplicate(body_text, title)
    lines = body_text.split("\n")
    flowables: list[Flowable] = []

    i = 0
    h1_seen = False
    while i < len(lines):
        line = lines[i].rstrip()

        # Blank line: emit a small spacer + advance.
        if not line.strip():
            flowables.append(Spacer(1, 6))
            i += 1
            continue

        # H1: only the first occurrence is the page
        # title. Subsequent H1s render as a section
        # heading so we don't drop content the user
        # intentionally wrote.
        h1_match = _H1_LINE_RE.match(line)
        if h1_match:
            heading_text = _markdown_to_rlm(
                h1_match.group(1), num_citations=num_citations
            )
            if not h1_seen:
                # Page title handled outside this helper.
                h1_seen = True
            else:
                flowables.append(
                    Paragraph(heading_text, styles["h2"])
                )
            i += 1
            continue

        # H2 / H3.
        h2_match = _H2_LINE_RE.match(line)
        if h2_match:
            flowables.append(
                Paragraph(
                    _markdown_to_rlm(
                        h2_match.group(1), num_citations=num_citations
                    ),
                    styles["h2"],
                )
            )
            i += 1
            continue
        h3_match = _H3_LINE_RE.match(line)
        if h3_match:
            flowables.append(
                Paragraph(
                    _markdown_to_rlm(
                        h3_match.group(1), num_citations=num_citations
                    ),
                    styles["h3"],
                )
            )
            i += 1
            continue

        # Bullet line. We accumulate consecutive
        # bullets into a ListFlowable so the indent
        # looks right.
        if _BULLET_LINE_RE.match(line):
            items: list[ListItem] = []
            while i < len(lines):
                bullet_match = _BULLET_LINE_RE.match(lines[i].rstrip())
                if not bullet_match:
                    break
                item_text = _markdown_to_rlm(
                    _escape_rlm_text(bullet_match.group(1)),
                    num_citations=num_citations,
                )
                items.append(
                    ListItem(
                        [Paragraph(item_text, styles["bullet"])],
                        leftIndent=18,
                    )
                )
                i += 1
            flowables.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="•",
                    leftIndent=18,
                )
            )
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
        paragraph_text = _markdown_to_rlm(
            _escape_rlm_text(" ".join(para_lines)),
            num_citations=num_citations,
        )
        flowables.append(Paragraph(paragraph_text, styles["body"]))

    return flowables


# ---------------------------------------------------------------------------
# Citation rendering
# ---------------------------------------------------------------------------


def _format_citation_text(citation: Citation) -> str:
    """
    Render a ``Citation`` domain entity as a single
    formatted string for the bibliography.

    We use the domain's own ``format()`` method which
    dispatches on ``citation.style``. The Citation's
    style is whatever was set at construction (default
    is APA per the dataclass). We leave it as-is -- a
    future PR can add a per-workspace citation-style
    picker in the UI (ADR-011).
    """
    return citation.format()


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class ReportLabPDFGenerator(PDFGenerator):
    """
    Render a :class:`ResearchReport` as a PDF using
    reportlab.

    Public method
    -------------
    - :func:`generate` -- the only entry point. Returns
      ``bytes`` that start with ``b\"%PDF-\"``.

    Internal helpers
    ----------------
    - :func:`_build_story` -- assembles the reportlab
      Platypus flowables (Paragraph / Spacer / List /
      BibliographyEntry).
    - :func:`_parse_body_to_flowables` -- markdown
      parser (private, but a clean unit target).
    """

    # PDF page geometry (matches the previous
    # hand-rolled generator so the visual layout is
    # roughly familiar).
    _PAGE_LEFT_MARGIN_PT = 1.0 * inch
    _PAGE_RIGHT_MARGIN_PT = 1.0 * inch
    _PAGE_TOP_MARGIN_PT = 1.0 * inch
    _PAGE_BOTTOM_MARGIN_PT = 1.0 * inch

    def generate(self, report: ResearchReport) -> bytes:
        """
        Render ``report`` as PDF bytes.

        Raises ``ValueError`` if the report has no
        summary body. Raises ``RuntimeError`` if the
        DejaVu Sans TTF font cannot be loaded (with a
        hint about installing ``fonts-dejavu-core``).
        """
        import io

        if not report.summary or not report.summary.body:
            raise ValueError(
                "Cannot render an empty report as PDF. "
                "The report's summary body is empty."
            )

        _ensure_fonts_registered()
        styles = _build_styles()

        story = self._build_story(report, styles)

        buf = io.BytesIO()
        doc = BaseDocTemplate(
            buf,
            pagesize=LETTER,
            leftMargin=self._PAGE_LEFT_MARGIN_PT,
            rightMargin=self._PAGE_RIGHT_MARGIN_PT,
            topMargin=self._PAGE_TOP_MARGIN_PT,
            bottomMargin=self._PAGE_BOTTOM_MARGIN_PT,
            author="BioResearch AI",
            subject="Biomedical Research Report",
        )
        frame = Frame(
            doc.leftMargin,
            doc.bottomMargin,
            doc.width,
            doc.height,
            id="body",
            showBoundary=0,
        )
        template = PageTemplate(
            id="main",
            frames=[frame],
            onPage=_draw_page_footer,
        )
        doc.addPageTemplates([template])
        doc.build(story)

        out = buf.getvalue()
        assert out.startswith(b"%PDF-"), (
            "ReportLabPDFGenerator produced bytes without "
            f"the PDF magic header: starts with {out[:8]!r}"
        )
        return out

    def _build_story(
        self,
        report: ResearchReport,
        styles: dict[str, ParagraphStyle],
    ) -> list[Flowable]:
        """
        Assemble the reportlab Platypus flowables for
        the document.
        """
        body_text = report.summary.body
        # Extract H1 title.
        title = ""
        body_lines = body_text.split("\n")
        for line in body_lines:
            m = _H1_LINE_RE.match(line)
            if m:
                title = m.group(1).strip()
                break
        if not title:
            title = "Biomedical Research Report"

        story: list[Flowable] = []
        # Page title.
        story.append(
            Paragraph(_escape_rlm_text(title), styles["title"])
        )
        # Optional subtitle (the question) -- useful
        # for the printed cover. Only present if the
        # metadata carries a question.
        question = (
            report.metadata.get("question")
            if isinstance(report.metadata, dict)
            else None
        )
        if question:
            story.append(
                Paragraph(
                    _escape_rlm_text(str(question)),
                    styles["subtitle"],
                )
            )
        story.append(HRFlowable(
            width="100%", thickness=0.6,
            color=colors.HexColor("#cbd5e1"),
            spaceBefore=2, spaceAfter=10,
        ))

        # Body (H1 line already stripped via the
        # duplicate guard inside ``_parse_body_to_flowables``).
        story.extend(_parse_body_to_flowables(
            body_text,
            styles,
            title=title,
            num_citations=len(report.citations),
        ))

        # Limitations section.
        if report.limitations:
            story.append(Paragraph("Limitations", styles["h2"]))
            items = [
                ListItem(
                    [
                        Paragraph(
                            _markdown_to_rlm(
                                _escape_rlm_text(lim),
                                num_citations=len(report.citations),
                            ),
                            styles["bullet"],
                        ),
                    ],
                    leftIndent=18,
                )
                for lim in report.limitations
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="•",
                    leftIndent=18,
                )
            )

        # Future Work section.
        if report.future_work:
            story.append(Paragraph("Future Research Directions", styles["h2"]))
            items = [
                ListItem(
                    [
                        Paragraph(
                            _markdown_to_rlm(
                                _escape_rlm_text(fw),
                                num_citations=len(report.citations),
                            ),
                            styles["bullet"],
                        ),
                    ],
                    leftIndent=18,
                )
                for fw in report.future_work
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="•",
                    leftIndent=18,
                )
            )

        # Bibliography section -- numbered list with
        # one anchor per entry. Each inline ``[N]``
        # reference in the body links here via
        # ``#bib-N``.
        if report.citations:
            story.append(PageBreak())
            story.append(
                Paragraph("Bibliography", styles["h2"])
            )
            for i, citation in enumerate(report.citations, start=1):
                entry_text = _format_citation_text(citation)
                story.append(_BibliographyEntry(
                    number=i,
                    text=entry_text,
                    anchor=f"bib-{i}",
                    font_name="DejaVuSans",
                    font_size=10,
                    leading=14,
                    left_indent=24,
                ))
        return story


def _draw_page_footer(canv, doc) -> None:
    """
    Page-number footer drawn on every page.

    The footer is plain text in 9pt DejaVuSans. We use
    canv.getPageNumber() and doc.page to render
    ``Page N of M``. ``M`` is computed by the caller via
    a ``notify`` hook -- for simplicity we just render
    the page number on its own.
    """
    canv.saveState()
    canv.setFont("DejaVuSans", 9)
    canv.setFillColor(colors.HexColor("#94a3b8"))
    page_num = canv.getPageNumber()
    text = f"Page {page_num}"
    canv.drawCentredString(
        LETTER[0] / 2.0,
        0.5 * inch,
        text,
    )
    canv.restoreState()
