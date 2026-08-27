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
 * The Frontend needs to render those markers as clickable
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
 *
 * Grouped citations
 * -----------------
 * The Vancouver prompt encourages the LLM to emit grouped
 * in-text citations when multiple papers support one
 * claim: ``...elevated in carriers [paper:5, paper:12].``
 * Each ``[paper:N]`` inside the group is still a discrete
 * citation entry; the brackets around the whole group are
 * just one of the legal grouped citation formats. The
 * helper below renders each ``N`` as its own clickable
 * link (``[5](#citation-5), [12](#citation-12)``) so the
 * user can jump to either reference -- this matches the
 * practice of Nature, PLOS, eLife and other modern
 * biomedical journals.
 */

const PAPER_MARKER_RE = /\[paper:(\d+)\]/g;
const GROUPED_PAPER_MARKER_RE = /\[paper:(\d+(?:,\s*paper:\d+)+)\]/g;

/**
 * Convert ``[paper:N]`` markers into markdown links that
 * target the corresponding ``<li id="citation-N">`` entry
 * in the Citations list.
 *
 * The link text is the bracket-number form ``[N]`` -- the
 * standard Vancouver in-text citation rendering. The link
 * ``href`` is the in-page anchor ``#citation-N``. Clicking
 * it scrolls the user to the bibliography entry, which
 * matches what every modern biomedical journals does
 * (Nature, PLOS, eLife, etc.).
 *
 * Grouped citations (the LLM's preferred form when multiple
 * papers support one claim) are rendered as a comma-joined
 * sequence of clickable links: ``[5](#citation-5), [12](#citation-12)``.
 * Each number is its own link target, so clicking either
 * jumps to the corresponding bibliography entry. This
 * matches what Nature, PLOS, eLife and other modern
 * biomedical journals do.
 *
 * Edge cases
 * -----------
 * - ``[paper:0]`` or ``[paper:N+1]`` where ``N+1`` exceeds
 *   the citation list length: rendered as a plain bracket
 *   marker (no link). The backend's regex clamps the index
 *   to the valid range so, this should not happen in
 *   practice, but we defend in depth so a future change
 *   that introduces an out-of-range marker doesn't break
 *   the UI.
 * - Malformed markers like ``[paper:]`` or ``[paper:abc]``
 *   pass through unchanged.
 * - Mixed valid/invalid in a group: only the valid
 *   numbers are linkified; invalid ones fall through
 *   unchanged so the user still sees the LLM's intended
 *   intent rather than losing characters silently.
 */
export function linkifyCitationMarkers(
  body: string,
  maxCitationIndex: number,
): string {
  // Process grouped citations first (``[paper:N, paper:M, ...]``)
  // so the inner ``[paper:N]`` tokens can't be picked up by
  // the standalone pass. Each group becomes a comma-joined
  // sequence of clickable links.
  //
  // Out-of-range policy: if ANY entry in the group is
  // out of range, we fall back to the original match
  // (preserving the LLM's text). The rationale: the
  // backend's mapper clamps the index to the valid range,
  // so an out-of-range marker in a report is a
  // bidirectional bug -- either the LLM fabricated a
  // citation, or the bibliography is missing one. Losing
  // either entry silently would mislead the user; the
  // visible "stuck" text makes the bug obvious so a
  // developer can fix it. Compare with the standalone
  // pass, where we preserve each out-of-range entry
  // verbatim -- the trade-off there is the same.
  const groupedResult = body.replace(
    GROUPED_PAPER_MARKER_RE,
    (match, innerList: string) => {
      // The regex captures the entire comma-joined number
      // list (e.g. ``"5, paper:12, paper:17"``). Split on
      // the comma to get one piece per citation, then
      // normalise each piece to its bare integer index.
      // We accept BOTH ``"N"`` (the first element, which
      // is just a digit per the regex) and ``"paper:N"``
      // (subsequent elements). This defensive parsing
      // keeps the helper working if a future maintainer
      // tweaks the regex to a more permissive form.
      const pieces = innerList
        .split(",")
        .map((piece) => piece.trim());
      const renderedNumbers: string[] = [];
      for (const piece of pieces) {
        const m = /(?:paper:)?(\d+)/.exec(piece);
        if (!m) {
          // Malformed piece (no digits at all). Fall
          // back to the original match -- don't try to
          // partial-render an unparseable group.
          return match;
        }
        const index = parseInt(m[1], 10);
        if (
          Number.isNaN(index) ||
          index < 1 ||
          index > maxCitationIndex
        ) {
          // Out of range. Fall back to the original
          // match so the user sees the LLM's text
          // unchanged (and the developer sees the bug).
          return match;
        }
        renderedNumbers.push(`[${index}](#citation-${index})`);
      }
      return renderedNumbers.join(", ");
    },
  );

  // Then handle the standalone ``[paper:N]`` markers. We
  // run this second because the first pass may have
  // converted some of them already (inside a group).
  return groupedResult.replace(PAPER_MARKER_RE, (match, rawIndex) => {
    const index = parseInt(rawIndex, 10);
    if (
      Number.isNaN(index) ||
      index < 1 ||
      index > maxCitationIndex
    ) {
      // Out of range or malformed -- leave the original
      // marker text intact so the user can still see what
      // the LLM produced. Downstream consumers that
      // depend on marker extraction don't rely on the
      // Frontend's linkification.
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