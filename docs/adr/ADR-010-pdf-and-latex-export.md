# ADR-010: Reportlab-based PDF + LaTeX export

## Status

Accepted

## Context

The first public release shipped a hand-rolled PDF 1.4
generator (`MinimalPDFGenerator`, 488 LOC in
`app/infrastructure/pdf/minimal_generator.py`). The
generator used Helvetica base-14 with WinAnsiEncoding
and emitted the report as a sequence of manually-placed
`Tj` text-position operators.

That approach hit four hard limits when exercised on
real reports:

1. **No Unicode.** Anything above `U+00FF` was mapped
   to `?` (`_pdf_escape` used `errors="replace"`). This
   broke Greek letters (`Aβ` → `A?`), Latin diacritics
   (`Lévesque` → `L?vesque`), em-dashes (`—` → `?`),
   and the Turkish `Ş` (`Şöltekin` → `??ltekin`).
2. **No real wrap.** `_wrap_text` used a greedy
   word-wrap heuristic that overflowed the right margin
   for long citation lines (e.g. `Schultz, S. A., Rao,
   Y., ...` ran off the page).
3. **No clickable references.** The bibliography was a
   flat list of strings. The PDF was missing the
   `[paper:N]` markers that the markdown frontend
   renders as clickable `[N]` links.
4. **No pagination.** All content was dumped on one
   page; long reports overflowed the page boundary.

The product surface also grew to need a **LaTeX
export** — biomedical researchers want to drop the
report into a thesis manuscript, and `.tex` is the
only format that survives that pipeline cleanly.

## Decision

Replace `MinimalPDFGenerator` with a
reportlab-based generator (`ReportLabPDFGenerator`)
that embeds **DejaVu Sans** (TTF, registered as a
font family with all four faces) and a new
**`LatexReportGenerator`** that emits a self-contained
`.tex` source.

### PDF generator (`app/infrastructure/pdf/reportlab_generator.py`)

- **`reportlab.platypus.Flowable`-based** story
  builder. Reportlab handles wrap, widow/orphan
  control, and pagination.
- **TTF embedding**: `TTFont("DejaVuSans", ...)`
  registered as a `fontFamily` so `<b>` and `<i>`
  tags in RLM resolve to bold/oblique faces.
- **Clickable numbered references**: `linkifyCitationMarkers`
  in the report payload replaces `[paper:N]` with
  `[<link destination="#bib-N">N</link>]`. Reportlab
  emits a real `/Dest` PDF annotation. The bibliography
  block writes a `canv.bookmarkHorizontal("bib-N", x,
  y_top)` for each entry — without the `#` prefix
  the `<link destination="bib-N">` route resolves to
  a broken URI handler, so the prefix is mandatory.
- **Out-of-range clamping**: `_convert_paper_markers_to_rlm`
  silently drops references beyond
  `num_citations`. The frontend already clamps via
  `linkifyCitationMarkers`, but the PDF defends in
  depth (documented 2026-08-30).
- **Docker**: `Dockerfile` installs `fonts-dejavu`
  (NOT `-core` — the `-core` package lacks italic
  faces; reportlab would `TTFError` on
  `DejaVuSans-Oblique.ttf` and crash the workspace
  into `ERROR`).

### LaTeX generator (`app/infrastructure/latex/latex_generator.py`)

- Self-contained `\documentclass[11pt,a4paper]{article}`
  with `\usepackage[hidelinks]{hyperref}`,
  `\usepackage{enumitem}`, `\usepackage[margin=1in]{geometry}`.
- Numbered references use `\hyperref[bib-N]{[N]}` so
  the click jumps to the bibliography entry.
- `\DeclareUnicodeCharacter{00E7}{\c{c}}` (and
  siblings) MUST come **before** `hyperref` because
  hyperref switches the encoding to PU which would
  override the inputenc mapping — this is a real
  bug we hit during local development.
- `textgreek` is opt-in via the
  `BIORESEARCH_RUN_LATEX_COMPILE=1` env var; CI skips
  the live compile (no `texlive-latex-extra` available
  in `ubuntu-latest` by default).

### API surface

- `GET /workspaces/{id}/published-report.pdf` —
  reportlab on demand, `Content-Disposition: attachment`.
- `GET /workspaces/{id}/published-report.tex` —
  LaTeX on demand, `Content-Type: text/x-tex`. Both
  endpoints return 404 with a clear error message if
  `workspace.report is None`.

### Frontend (`frontend/src/pages/Report.tsx`)

- "Generate PDF" button now **auto-downloads** via a
  hidden `<a download>` after the FSM transition
  succeeds (no separate Download button).
- New blue "Generate TeX" button does the same for
  the `.tex` source.

## Consequences

### Positive

- Unicode works (`Aβ`, `Lévesque`, `Şöltekin`,
  em-dashes, Greek letters).
- Clickable references match the executive summary
  rendering — Vancouver `[N]` numbering with
  jump-to-bibliography.
- Long citation strings wrap correctly with a hanging
  indent.
- Multi-page pagination works — a 20-paper report
  produces a 6-page PDF.
- LaTeX source is `pdflatex`-compileable (verified
  in `/tmp/ltx8` and via the
  `BIORESEARCH_RUN_LATEX_COMPILE=1` test).

### Negative

- `reportlab>=5.0,<6.0` added to
  `requirements/minimal-requirements.txt`
  (~9 MB pure-Python).
- `fonts-dejavu` (~10 MB) added to `Dockerfile`.
  Total minimal image growth: ~1.5%.

### Trade-offs

- The hand-rolled PDF 1.4 emitter is gone; any
  existing test that asserted on raw PDF bytes
  needed to be migrated to `pdftotext` extraction
  (`_extract_text_or_skip`). The PDF stream is
  flate-compressed so byte-level grep never worked
  reliably.
- The reportlab `<link destination>` API is brittle
  — without `#` prefix it routes through URI
  handler. This is now documented inline in
  `_convert_paper_markers_to_rlm`.

## References

- Commit `2552399 fix(report): reportlab-based PDF + LaTeX export + Generate PDF auto-download`
- Commit `0af713f test(latex): opt-in live pdflatex compile via env var`
- Commit `cde368c fix(ci): install poppler-utils so PDF tests can extract text`
- `tests/unit/test_reportlab_pdf_generator.py` (37 tests)
- `tests/unit/test_latex_report_generator.py` (35 tests)
