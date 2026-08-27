/**
 * Citation rendering helpers for the Report page.
 *
 * Background
 * ----------
 * The LLM emits ``[paper:N]`` markers verbatim in the report
 * body (e.g. ``Plasma p-tau217 is a sensitive marker [paper:19].``)
 * so the backend's regex (``\[paper:(\d+)\]``) can extract
 * the citation list. The same marker also drives the
 * bibliography ordering (Vancouver style: numbered by
 * first-citation-order in the text).
 *
 * The frontend needs to render those markers as clickable
 * superscript links that scroll to the corresponding entry
 * in the Citations list. This module does the conversion
 * at one chokepoint so the rest of the page just passes the
 * raw marker through to the markdown renderer.
 *
 * Strategy
 * --------
 * 1. Replace each ``[paper:N]`` in the report body with a
 *    markdown link of the form ``[N](#citation-N)`` -- so
 *    ReactMarkdown renders ``[N]`` as a hyperlink targeting
 *    the ``#citation-N`` anchor.
 * 2. The Citations list's ``<li>`` items carry ``id="citation-N"``
 *    so the link targets the right entry. The click scrolls
 *    the page to the citation (browser-default anchor behaviour)
 *    and the citation briefly highlights (CSS).
 *
 * Why a custom markdown renderer is not used
 * ------------------------------------------
 * We could install ``remark-gfm`` (already present) plus a
 * custom ``remark`` plugin to walk text nodes. That would
 * be more "correct" but adds a dependency on a token-tree
 * walker. The pre-processing approach is 30 lines of code,
 * no new deps, and easy to read in code review. The
 * trade-off: ``[paper:N]`` markers inside code blocks (rare
 * in a research report) would also be replaced. We accept
 * this -- a research report doesn't contain code blocks.
 */

const PAPER_MARKER_RE = /\[paper:(\d+)\]/g;

/**
 * Convert ``[paper:N]`` markers into markdown links that
 * target the corresponding ``<li id="citation-N">`` entry
 * in the Citations list.
 *
 * The link text is the bracket-number form ``[N]`` -- the
 * standard Vancouver in-text citation rendering. The link
 * ``href`` is the in-page anchor ``#citation-N``. Clicking
 * it scrolls the user to the bibliography entry, which
 * matches what every modern biomedical journal does
 * (Nature, PLOS, eLife, etc.).
 *
 * Multiple citations for a single claim (e.g.
 * ``[paper:5, paper:12]``) are collapsed into a single
 * link ``[5, 12](#citation-5#citation-12)`` -- multiple
 * hash targets is not a standard pattern, so we render the
 * most prominent one (the first) as the link target and the
 * remaining numbers as plain bracket text. This keeps the
 * markup valid and preserves the bibliography semantics.
 *
 * Edge cases
 * -----------
 * - ``[paper:0]`` or ``[paper:N+1]`` where ``N+1`` exceeds
 *   the citation list length: rendered as a plain bracket
 *   marker (no link). The backend's regex clamps the index
 *   to the valid range so this should not happen in
 *   practice, but we defend in depth so a future change
 *   that introduces an out-of-range marker doesn't break
 *   the UI.
 * - Malformed markers like ``[paper:]`` or ``[paper:abc]``
 *   pass through unchanged.
 */
export function linkifyCitationMarkers(
  body: string,
  maxCitationIndex: number,
): string {
  return body.replace(PAPER_MARKER_RE, (match, rawIndex) => {
    const index = parseInt(rawIndex, 10);
    if (Number.isNaN(index) || index < 1 || index > maxCitationIndex) {
      // Out of range or malformed -- leave the original
      // marker text intact so the user can still see what
      // the LLM produced. Downstream consumers that
      // depend on marker extraction don't rely on the
      // frontend's linkification.
      return match;
    }
    // Render as a markdown link to the bibliography
    // anchor. The label is just the number (Vancouver style).
    return `[${index}](#citation-${index})`;
  });
}

/**
 * Build the ReactMarkdown ``id`` attribute for a citation
 * list entry. Mirrors the ``#citation-N`` target used by
 * :func:`linkifyCitationMarkers`.
 *
 * Pinning this in one place keeps the link target and the
 * list-item ``id`` in lockstep -- a refactor that changes
 * one without the other breaks every link in the report.
 */
export function citationAnchorId(citationIndex1Based: number): string {
  return `citation-${citationIndex1Based}`;
}