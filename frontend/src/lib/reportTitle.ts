/**
 * Report title helpers for the Report page.
 *
 * Background
 * ----------
 * The report title is the first ``# `` line of ``report.summary``.
 * The backend guarantees that line exists and is clean: the H1
 * fallback (``app/infrastructure/llm/title_fallback.py``) derives
 * it from the synthesis body, skipping any leading section
 * heading and stripping inline markdown. Both consumers -- this
 * page and the PDF generator -- read the same line, so they
 * always agree.
 *
 * The duplicated opening paragraph
 * --------------------------------
 * The fallback derives the title from the body's opening
 * sentence, so the body still contains that sentence: the title
 * appears once as the page heading and once as the opening
 * paragraph. The PDF generator strips the repeat (see
 * ``_strip_first_sentence_duplicate``). This module does the
 * same for the page, so the two renderings match.
 *
 * The repeat is not always the first paragraph: the synthesis
 * LLM sometimes opens with a section label written at the wrong
 * level ("### Bottom line"). That label is structure and is kept;
 * the paragraph after it is the repeat.
 *
 * @author Guillermo Ramajo Fernández
 */

/** The label shown when the summary carries no title at all. */
export const DEFAULT_REPORT_TITLE = "Research Report";

/** A markdown heading at any level. */
const HEADING_RE = /^#{1,6}\s/;

/**
 * Remove inline markdown markers and collapse whitespace.
 *
 * Mirrors the backend's ``app/core/markdown_text.py``. The title
 * is plain text, while the body's opening sentence may still
 * carry markup ("**plasma** N-terminal tau"), so the comparison
 * has to be made on the text the reader actually sees.
 */
export function stripInlineMarkdown(text: string): string {
  return text.replace(/\*\*|`/g, "").replace(/\s+/g, " ").trim();
}

/**
 * Extract the report title from the summary markdown.
 *
 * @param summary - The report summary markdown.
 * @returns The first ``# `` line's text, or the default label.
 */
export function extractReportTitle(summary: string): string {
  const line = summary.split("\n").find((l) => l.startsWith("# "));
  if (!line) return DEFAULT_REPORT_TITLE;
  const title = stripInlineMarkdown(line.replace(/^#\s+/, ""));
  return title || DEFAULT_REPORT_TITLE;
}

/**
 * Remove the title line and the opening paragraph that repeats it.
 *
 * @param summary - The report summary markdown.
 * @returns The body to render below the title.
 */
export function stripTitleAndDuplicate(summary: string): string {
  // 1. Drop the H1 line -- that is the page title.
  const body = summary.replace(/^# .*\n?/, "");

  // 2. Find the opening paragraph. Section headings that come
  //    first are structure, not prose, so skip past them.
  const blocks = body.split(/\n\s*\n/);
  let index = 0;
  while (
    index < blocks.length &&
    (blocks[index].trim() === "" || HEADING_RE.test(blocks[index].trim()))
  ) {
    index += 1;
  }
  if (index >= blocks.length) return body;

  // 3. If the opening paragraph repeats the title, drop it.
  const title = extractReportTitle(summary);
  const opening = stripInlineMarkdown(blocks[index]).toLowerCase();
  const normalizedTitle = stripInlineMarkdown(title)
    .toLowerCase()
    .replace(/[.,;:!?]+$/, "");
  const normalizedOpening = opening.replace(/[.,;:!?]+$/, "");
  if (
    normalizedTitle.length >= 8 &&
    (normalizedOpening === normalizedTitle ||
      normalizedOpening.startsWith(normalizedTitle))
  ) {
    blocks.splice(index, 1);
    return blocks.join("\n\n");
  }

  return body;
}
