"""
minimal_generator.py

Hand-rolled PDF 1.4 generator. No third-party dependency.

Why hand-rolled
---------------
We considered:

  - ``reportlab``: heavyweight, pulls in many transitive deps
    (Pillow, etc.). Adds ~30 MB to the image for a feature we
    exercise once per workspace.
  - ``weasyprint``: needs Cairo + Pango system libs. Big and
    fiddly to install in our minimal image.
  - ``fpdf2``: lighter than reportlab but still a third-party
    dep for a feature whose output is intentionally minimal
    (a research report is mostly text).

The PDF format is well-documented and ASCII-only text rendering
is a few hundred lines. We produce a single-page, single-font,
left-aligned, monospace layout. That's enough for the "I want a
PDF I can email to a colleague" use case.

Spec references
---------------
- PDF 1.4 spec (Adobe): ``PDF 32000-1:2008``. We follow the
  subset documented in the inline comments.
- The font we use is the standard PDF Helvetica
  (``/Helvetica``). It's one of the 14 base 14 fonts guaranteed
  to exist in every PDF reader; no font embedding required.

Limitations
----------
This generator is intentionally minimal. It handles ASCII text
in Helvetica and produces one or more pages (auto-extended for
long content -- we don't currently implement widow/orphan control
or keep-with-next; the layout simply emits a fresh page when the
y-coordinate crosses the bottom margin). A real-world report
body of 2-4 paragraphs plus a short citations list typically
fits in 2 pages; long reports (10+ papers) may need 3-4.

To extend: add a streaming text-layout loop that issues
multiple ``BT...ET`` blocks per page, plus a ``/Pages`` array
with multiple ``/Page`` entries.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import io

from app.domain.entities.research_report import ResearchReport
from app.domain.interfaces.pdf_generator import PDFGenerator


# PDF 1.4 default: letter-size page (612 x 792 points, 8.5" x 11").
_PAGE_WIDTH_PT: int = 612
_PAGE_HEIGHT_PT: int = 792

# Margins (1 inch = 72 points). Leave room for the report title
# at the top, citations at the bottom.
_MARGIN_TOP_PT: int = 72
_MARGIN_BOTTOM_PT: int = 72
_MARGIN_LEFT_PT: int = 72
_MARGIN_RIGHT_PT: int = 72

# Helvetica 11pt with 14pt leading. Tighter than a typical Word
# document but readable on screen and on print.
_BODY_FONT_SIZE_PT: int = 11
_BODY_LINE_HEIGHT_PT: int = 14

_TITLE_FONT_SIZE_PT: int = 18
_SECTION_FONT_SIZE_PT: int = 13


class MinimalPDFGenerator(PDFGenerator):
    """
    Produce a single-page PDF from a :class:`ResearchReport`.

    Layout
    ------
    +----------------------------------------+
    |  Title                                 |
    |                                        |
    |  Summary                               |
    |  Lorem ipsum dolor sit amet, consec-   |
    |  tetur adipiscing elit, sed do eius-   |
    |  mod tempor incididunt ut labore et    |
    |  dolore magna aliqua.                  |
    |  ...                                   |
    |                                        |
    |  Citations                             |
    |  1. Author, A. (2024). Title...        |
    |  2. ...                                |
    |                                        |
    |  Limitations                           |
    |  - Limitation one                      |
    |                                        |
    |  Future Work                           |
    |  - Direction one                       |
    +----------------------------------------+

    Text wraps at the right margin. Long lines break on word
    boundaries. The body uses Helvetica; section headings use
    a slightly larger Helvetica for emphasis.

    The output is byte-deterministic for a given input
    (modulo the fixed-width layout) -- the same report produces
    the same bytes across runs. This lets tests assert on
    content (e.g. that the report's title appears in the PDF).
    """

    def generate(self, report: ResearchReport) -> bytes:
        raw_text = report.summary.body.strip()
        if not raw_text:
            raise ValueError(
                "Cannot render an empty report as PDF. The report's "
                "summary body is empty."
            )

        # Extract the report title from the first ``# `` heading
        # line, mirroring the React UI's ``reportTitle``
        # derivation in ``frontend/src/pages/Report.tsx``. The
        # LLM is prompted to emit a top-level heading at the
        # very start of the body (e.g. ``# Tau Biomarkers in
        # Alzheimer's Disease: A Synthesis of Recent Evidence``)
        # -- if the heading is missing, fall back to the
        # generic label.
        report_title = "Biomedical Research Report"
        body_lines = raw_text.split("\n")
        for line in body_lines:
            if line.startswith("# "):
                report_title = line[2:].strip()
                break

        # Strip the title line from the body so we don't print it
        # twice (once as the page heading, once inline in the
        # Executive Summary section).
        if any(line.startswith("# ") for line in body_lines):
            title_idx = next(
                i for i, line in enumerate(body_lines) if line.startswith("# ")
            )
            body_lines = body_lines[title_idx + 1 :]
        text = self._strip_paper_markers("\n".join(body_lines).strip())

        # Step 1: collect the stream of text lines that will be
        # drawn on the page. We flatten the structured report
        # into a list of (size_pt, text) tuples -- one per line.
        # Section headings get a larger font.
        page_lines: list[tuple[int, str]] = []
        page_lines.append((_TITLE_FONT_SIZE_PT, report_title))
        page_lines.append((_BODY_FONT_SIZE_PT, ""))  # spacer

        # --- Summary section ---
        page_lines.append((_SECTION_FONT_SIZE_PT, "Executive Summary"))
        page_lines.append((_BODY_FONT_SIZE_PT, ""))
        for line in self._wrap_text(text, _BODY_FONT_SIZE_PT):
            page_lines.append((_BODY_FONT_SIZE_PT, line))
        page_lines.append((_BODY_FONT_SIZE_PT, ""))

        # --- Citations section ---
        if report.citations:
            page_lines.append((_SECTION_FONT_SIZE_PT, "Citations"))
            page_lines.append((_BODY_FONT_SIZE_PT, ""))
            for i, citation in enumerate(report.citations, start=1):
                citation_text = self._strip_paper_markers(str(citation))
                page_lines.append(
                    (_BODY_FONT_SIZE_PT, f"{i}. {citation_text}")
                )
            page_lines.append((_BODY_FONT_SIZE_PT, ""))

        # --- Limitations section ---
        if report.limitations:
            page_lines.append((_SECTION_FONT_SIZE_PT, "Limitations"))
            page_lines.append((_BODY_FONT_SIZE_PT, ""))
            for lim in report.limitations:
                clean_lim = self._strip_paper_markers(lim)
                page_lines.append((_BODY_FONT_SIZE_PT, f"- {clean_lim}"))
            page_lines.append((_BODY_FONT_SIZE_PT, ""))

        # --- Future Work section ---
        if report.future_work:
            page_lines.append((_SECTION_FONT_SIZE_PT, "Future Work"))
            page_lines.append((_BODY_FONT_SIZE_PT, ""))
            for fw in report.future_work:
                clean_fw = self._strip_paper_markers(fw)
                page_lines.append((_BODY_FONT_SIZE_PT, f"- {clean_fw}"))

        # Step 2: lay out the lines on the page(s). PDF
        # coordinates are bottom-up (origin at bottom-left).
        # We measure from the top down and flip
        # y = page_height - top_offset.
        #
        # Multi-page flow: when the next line would cross
        # the bottom margin, close the current page (its
        # lines stay in ``pages[-1]``) and start a fresh
        # page with y reset to the top margin. This is the
        # simplest possible pagination -- no widow control,
        # no keep-with-next, no orphans. A real-world report
        # body of 2-4 paragraphs plus a short citations list
        # typically fits in 2 pages; long reports (10+ papers)
        # may need 3-4.
        #
        # The result is a list of pages, each a list of
        # ``BT...ET`` content-stream lines. Step 3 assembles
        # one PDF content-stream object per page (all
        # sharing the same font resource).
        pages: list[list[str]] = [[]]
        y = _PAGE_HEIGHT_PT - _MARGIN_TOP_PT
        for size, line in page_lines:
            if y < _MARGIN_BOTTOM_PT:
                # Out of vertical space on this page --
                # start a fresh page and continue. We don't
                # break out of the loop: every remaining
                # ``page_lines`` entry gets a chance to render
                # on a subsequent page. The number of pages
                # in the output is whatever's needed to fit
                # all the content (no silent truncation).
                pages.append([])
                y = _PAGE_HEIGHT_PT - _MARGIN_TOP_PT
            current_page = pages[-1]
            if line == "":
                # Spacer lines just consume vertical space --
                # no glyphs drawn. The y-decrement still
                # happens here, so a paragraph break at the
                # bottom of a page correctly advances y to
                # the next page (the y < MARGIN_BOTTOM check
                # above catches it on the next iteration).
                y -= _BODY_LINE_HEIGHT_PT
                continue
            current_page.append(
                f"BT /F1 {size} Tf "
                f"{_MARGIN_LEFT_PT} {y} Td "
                f"({self._pdf_escape(line)}) Tj ET"
            )
            y -= _BODY_LINE_HEIGHT_PT

        # Step 3: assemble the PDF document. The format is:
        #
        #   %PDF-1.4
        #   %binary marker (high-bit bytes so grep tools see this
        #                     as a binary file)
        #   1 0 obj << ... >> endobj     (catalog)
        #   2 0 obj << ... >> endobj     (pages collection)
        #   3 0 obj << ... >> endobj     (page 1)
        #   4 0 obj << ... >> endobj     (font)
        #   5 0 obj << ... >> endobj     (content stream 1)
        #   6 0 obj << ... >> endobj     (page 2)
        #   7 0 obj << ... >> endobj     (content stream 2)
        #   ...
        #
        # Object numbering: catalog (1) + pages (2) + each
        # page is 2 objects (page dict + content stream).
        # The font is shared -- defined once as object 4,
        # referenced by every page's ``/Resources`` dict.
        #
        # The xref tracks every object's byte offset for
        # random-access readers. ``/Size`` in the trailer
        # is the count of objects plus 1 (for the always-
        # present free object 0 at the start of the table).

        out = io.BytesIO()
        offsets: list[int] = []

        # Header
        out.write(b"%PDF-1.4\n")
        out.write(b"%\xe2\xe3\xcf\xd3\n")  # binary marker (4 high-bit bytes)

        # Object 1: Catalog
        offsets.append(out.tell())
        out.write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

        # Object 2: Pages collection -- one entry per page,
        # in document order. /Count is the number of pages.
        # We fill in the page IDs later (after we know the
        # object numbering), so write a placeholder first
        # then patch the byte range with the real ID list.
        page_ids_placeholder_offset = out.tell()
        offsets.append(page_ids_placeholder_offset)
        out.write(b"__PAGES_PLACEHOLDER__\nendobj\n")

        # Object 3: Font (defined once, shared by every
        # page's /Resources dict).
        font_object_id = 3
        offsets.append(out.tell())
        out.write(
            b"3 0 obj\n"
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>\n"
            b"endobj\n"
        )

        # Objects 4, 5, 6, 7, ... : alternating page dict +
        # content stream. Each page is exactly 2 objects
        # in the PDF. The list of page IDs is needed in the
        # Pages collection object (object 2), but we don't
        # know those IDs until AFTER we emit the per-page
        # objects here. So we wrote object 2 with a
        # placeholder text earlier and patch it in-place
        # below with the real ``/Kids`` list.
        #
        # Note: ``page_text_ops`` here refers to the PER-PAGE
        # text ops (a ``list[str]``) -- distinct from the
        # ``page_lines`` in the layout loop above
        # (``list[tuple[int, str]]``).

        # Re-emit pages, dropping any trailing empty ones.
        # An "empty" page is one with zero non-empty text
        # ops (spacers alone are still effectively empty --
        # they'd render as a blank page with no text).
        def _is_non_empty(page: list[str]) -> bool:
            return any(line.strip() for line in page)

        non_empty_pages = [p for p in pages if _is_non_empty(p)]
        if not non_empty_pages:
            # Defensive: if every page is empty (zero content),
            # force-emit a single placeholder page so the
            # PDF has at least one page. The placeholder
            # contains a single text op so the file is a
            # valid single-page PDF.
            non_empty_pages = [
                [
                    f"BT /F1 {_BODY_FONT_SIZE_PT} Tf "
                    f"{_MARGIN_LEFT_PT} {_PAGE_HEIGHT_PT - _MARGIN_TOP_PT} Td "
                    f"({self._pdf_escape('(empty report)')}) Tj ET"
                ]
            ]

        page_object_ids: list[int] = []
        next_object_id = font_object_id + 1
        for page_text_ops in non_empty_pages:
            page_obj_id = next_object_id
            content_obj_id = next_object_id + 1
            page_object_ids.append(page_obj_id)
            next_object_id += 2

            # Page dict: references its content stream and
            # the shared font resource.
            offsets.append(out.tell())
            out.write(
                f"{page_obj_id} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {_PAGE_WIDTH_PT} {_PAGE_HEIGHT_PT}] "
                f"/Resources << /Font << /F1 {font_object_id} 0 R >> >> "
                f"/Contents {content_obj_id} 0 R >>\n"
                f"endobj\n".encode("latin-1")
            )

            # Content stream: the BT/ET ops for this page.
            content_bytes = "\n".join(page_text_ops).encode("latin-1")
            offsets.append(out.tell())
            out.write(
                f"{content_obj_id} 0 obj\n"
                f"<< /Length {len(content_bytes)} >>\n"
                f"stream\n".encode("latin-1")
            )
            out.write(content_bytes)
            out.write(b"\nendstream\nendobj\n")

        # Now patch the Pages collection object with the
        # real page IDs. The placeholder sits between the
        # line ``b"__PAGES_PLACEHOLDER__\n"`` (inclusive)
        # and ``b"\nendobj\n"``. We replace the whole
        # object in-place by overwriting its bytes.
        kids_list = " ".join(f"{pid} 0 R" for pid in page_object_ids)
        pages_object_text = (
            f"2 0 obj\n"
            f"<< /Type /Pages /Kids [{kids_list}] "
            f"/Count {len(page_object_ids)} >>\n"
            f"endobj\n"
        ).encode("latin-1")

        # Splice the real Pages object over the placeholder.
        # The placeholder was written at ``page_ids_placeholder_offset``
        # with a known fixed length. After the splice, every
        # object whose offset came AFTER the placeholder will
        # have shifted by ``len(pages_object_text) -
        # placeholder_len``. We adjust the offsets list in
        # place so the xref points to the new positions.
        placeholder_start = page_ids_placeholder_offset
        placeholder_len = len(b"__PAGES_PLACEHOLDER__\nendobj\n")

        # Read the tail (everything after the placeholder).
        out.seek(placeholder_start + placeholder_len)
        tail = out.read()
        # Truncate back to just-before-the-placeholder, then
        # write the real Pages object and the tail. Net effect
        # is in-place replacement of the placeholder.
        out.seek(placeholder_start)
        out.write(pages_object_text)
        out.write(tail)

        # Compute the size delta and shift every offset that
        # comes AFTER the placeholder's original end position.
        # The placeholder's last byte was at
        # ``placeholder_start + placeholder_len``. Offsets
        # strictly greater than that need to move by
        # ``new_total_len - old_total_len``.
        delta = len(pages_object_text) - placeholder_len
        for i, off in enumerate(offsets):
            if off > placeholder_start + placeholder_len - 1:
                offsets[i] = off + delta
        out.seek(0, 2)  # seek to end

        # xref + trailer
        total_objects = next_object_id
        xref_offset = out.tell()
        out.write(f"xref\n0 {total_objects}\n".encode("latin-1"))
        out.write(b"0000000000 65535 f \n")  # free object 0
        for offset in offsets:
            # PDF spec: each xref entry is exactly 20 bytes --
            # 10-digit zero-padded byte offset, space, 5-digit
            # generation number, space, 'n'/'f' (in-use/free),
            # newline.
            out.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
        out.write(
            f"trailer\n<< /Size {total_objects} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n"
            f"%%EOF\n".encode("latin-1")
        )

        pdf_bytes = out.getvalue()
        # Self-check: every valid PDF starts with this magic header.
        # If anything below accidentally stripped or mangled the
        # header, fail loud instead of returning silently-broken
        # bytes that would fail downstream consumers in obscure
        # ways.
        assert pdf_bytes.startswith(b"%PDF-"), (
            f"MinimalPDFGenerator produced bytes without the PDF "
            f"magic header: starts with {pdf_bytes[:8]!r}"
        )
        return pdf_bytes

    @staticmethod
    def _pdf_escape(text: str) -> str:
        """
        Escape a string for use inside a PDF text object.

        PDF text-object strings are parenthesised. Three
        characters must be escaped:

          ``\\`` -> ``\\\\``
          ``(`` -> ``\\(``
          ``)`` -> ``\\)``

        Non-ASCII bytes outside WinAnsiEncoding (the encoding we
        declared on the font) are passed through as Latin-1 --
        see the ``encode("latin-1")`` call in ``generate``. If
        the user wants non-Latin scripts the base-14 Helvetica
        doesn't cover that; this is a known limitation of the
        minimal generator. Real-world biomedical content is
        overwhelmingly ASCII, so this is acceptable for v1.

        Control characters (newlines, tabs) are not legal inside
        PDF text-object strings -- they terminate the string
        prematurely. Replace them with spaces.
        """
        # Step 1: normalize common Unicode punctuation to ASCII
        # equivalents. LLMs frequently emit these characters
        # (``—`` ``"`` ``"`` ``'`` ``'`` ``…``) and a single
        # non-ASCII codepoint blows up the latin-1 encode
        # pipeline. The mappings are conservative: each
        # replacement preserves the visible meaning while
        # staying inside the WinAnsiEncoding glyph range.
        text = (
            text
            # Em dash / en dash / minus / horizontal bar
            .replace("\u2014", "--")     # em dash
            .replace("\u2013", "-")      # en dash
            .replace("\u2212", "-")      # minus sign
            .replace("\u2015", "-")      # horizontal bar
            # Smart quotes
            .replace("\u2018", "'")      # left single quote
            .replace("\u2019", "'")      # right single quote
            .replace("\u201c", '"')      # left double quote
            .replace("\u201d", '"')      # right double quote
            # Ellipsis
            .replace("\u2026", "...")    # ellipsis
            # Spaces
            .replace("\u00a0", " ")      # non-breaking space
            .replace("\u2003", " ")      # em space
            .replace("\u2002", " ")      # en space
            .replace("\u2009", " ")      # thin space
            # Misc punctuation that real-world biomedical
            # text routinely contains
            .replace("\u2022", "*")      # bullet
            .replace("\u00b7", "*")      # middle dot
        )
        # Step 2: PDF text-object escapes + control-char
        # replacement. Non-ASCII characters that survived
        # Step 1 (rare for biomedical content) are dropped
        # via ``errors='replace'`` rather than blowing up.
        out = []
        for ch in text:
            if ch in ("\\", "(", ")"):
                out.append("\\" + ch)
            elif ch in ("\n", "\r", "\t"):
                out.append(" ")
            elif ord(ch) > 127:
                # Latin-1 only covers U+0000..U+00FF. Anything
                # beyond that is replaced with ``?`` -- a
                # visible fallback, not a crash. (We do this
                # explicitly so a stray emoji in the report
                # doesn't kill the PDF render.)
                out.append("?")
            else:
                out.append(ch)
        return "".join(out)

    @staticmethod
    def _strip_paper_markers(text: str) -> str:
        """
        Remove ``[paper:N]`` citation markers from text for
        PDF rendering.

        Why
        ---
        The LLM emits ``[paper:N]`` markers inline in the
        report body so the backend's regex
        (``\\[paper:(\\d+)\\]``) can extract citations and
        the frontend's ``linkifyCitationMarkers`` can render
        them as clickable superscripts. In the PDF the
        markers are visual noise -- the citations list at
        the bottom of the page already provides the
        reader-to-paper mapping, so showing ``[paper:3,
        paper:13]`` in the prose is redundant.

        The marker form we strip
        ------------------------
        - Standalone: ``[paper:N]`` -- deleted entirely.
          The ``[`` and ``]`` would otherwise leave
          dangling brackets in the prose ("...research
          cohorts [ ].").
        - Grouped: ``[paper:N, paper:M, ...]`` -- deleted
          entirely for the same reason. We do NOT replace
          with ``[N, M]`` because (a) it adds visual noise
          in a printed document where superscripts aren't
          available, and (b) the reader sees the numbered
          citations list at the bottom of the page, which
          is the natural place to look up references.

        Edges
        -----
        - The strip operates per-paragraph (split on ``\\n``)
          so a marker at the very end of a paragraph is
          caught.
        - Malformed markers (e.g. ``[paper:abc]``) pass
          through unchanged -- the regex requires
          ``\\d+``, so non-numeric content is never
          matched.
        - Double spaces left after a marker removal are
          collapsed to a single space -- ``"cohorts [paper:3]
          ."`` becomes ``"cohorts ."`` (single space + period).
        """
        import re
        # Match the standalone ``[paper:N]`` form. The
        # greedy match captures up to ``]``.
        text = re.sub(r"\s*\[paper:\d+\]", "", text)
        # Match the grouped form ``[paper:N, paper:M, ...]``
        # -- the regex captures the whole bracket group
        # including any spaces inside. We strip trailing
        # spaces before the bracket so ``"... [paper:N,
        # paper:M] ."`` collapses cleanly.
        text = re.sub(r"\s*\[paper:\d+(?:,\s*paper:\d+)+\]", "", text)
        # Collapse runs of whitespace that the marker
        # removal may have left behind (``"... [paper:3]
        # ."`` -> ``"...  ."`` -- double space before the
        # period). Limit to single spaces so newlines and
        # paragraph breaks are preserved.
        text = re.sub(r" +", " ", text)
        return text

    @staticmethod
    def _wrap_text(text: str, font_size_pt: int) -> list[str]:
        """
        Word-wrap ``text`` to fit the page width.

        Approximate average character width at 11pt Helvetica
        is ~6pt. The usable width is the page width minus
        both margins. We do a rough greedy wrap -- good enough
        for prose; not for fixed-width code listings.

        Empty input returns an empty list. The caller treats
        blank lines as spacers in the layout.
        """
        usable_width_pt = _PAGE_WIDTH_PT - _MARGIN_LEFT_PT - _MARGIN_RIGHT_PT
        # Average glyph width for Helvetica ~= 0.5 * font_size.
        # For 11pt that's 5.5pt/char; we round up to 6 to be safe
        # (a slightly-too-tight wrap is OK; over-running the right
        # margin looks broken).
        chars_per_line = max(1, usable_width_pt // max(1, int(font_size_pt * 0.55)))

        wrapped: list[str] = []
        for paragraph in text.splitlines():
            if not paragraph.strip():
                wrapped.append("")
                continue
            words = paragraph.split()
            current = ""
            for word in words:
                if not current:
                    current = word
                elif len(current) + 1 + len(word) <= chars_per_line:
                    current += " " + word
                else:
                    wrapped.append(current)
                    current = word
            if current:
                wrapped.append(current)
        return wrapped
