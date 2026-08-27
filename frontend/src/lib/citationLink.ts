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
 *   the citation list length: SILENTLY DROPPED. The
 *   backend's mapper clamps the index to the valid range,
 *   so an out-of-range marker means the LLM fabricated a
 *   citation that doesn't exist in the bibliography.
 *   Showing the user a raw ``[paper:N]`` artefact in the
 *   rendered page would be misleading -- the linkifier
 *   drops the marker and lets the backend's logs surface
 *   the bug for developers. Same policy for both
 *   standalone and grouped markers.
 * - Malformed markers like ``[paper:]`` or ``[paper:abc]``
 *   pass through unchanged (they're not parseable as
 *   numbers at all, so the regex never matches them).
 * - Mixed valid/invalid in a group: only the valid
 *   numbers are linkified; invalid ones are silently
 *   dropped so the user doesn't see a partial / broken
 *   bracket fragment.
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
  // Out-of-range policy: silently drop entries that are
  // out of range -- the backend's mapper clamps the index
  // to the valid range, so an out-of-range marker is a
  // bidirectional bug (LLM fabricated a citation, or
  // bibliography is missing one). Showing the user the
  // raw ``[paper:N]`` text as visible artefacts would be
  // ugly and misleading -- the right UX is to render the
  // valid links and let the backend's logs catch the bug.
  // This is also how the standalone pass behaves (an
  // out-of-range ``[paper:99]`` stays literal, but the
  // grouped pass is more aggressive because the surrounding
  // context makes a "mixed" rendering visually jarring --
  // ``see [1](#citation-1), [paper:99]`` looks like a typo).
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
        if (!m) continue; // Malformed piece: skip silently.
        const index = parseInt(m[1], 10);
        if (
          Number.isNaN(index) ||
          index < 1 ||
          index > maxCitationIndex
        ) {
          // Out of range: skip silently. The backend's
          // citation-extraction logs surface this as a
          // data-quality warning -- the user-facing UI
          // renders only the valid links.
          continue;
        }
        renderedNumbers.push(`[${index}](#citation-${index})`);
      }
      // If EVERY number in the group was invalid/malformed,
      // return the original match so the user at least sees
      // the LLM's text. If the group is genuinely broken
      // (e.g. all hallucinated indices), we'd rather show
      // raw ``[paper:N]`` than silently delete it.
      if (renderedNumbers.length === 0) return match;
      return renderedNumbers.join(", ");
    },
  );

  // Then handle the standalone ``[paper:N]`` markers. We
  // run this second because the first pass may have
  // converted some of them already (inside a group).
  //
  // Out-of-range policy: silently drop. An out-of-range
  // marker means the LLM fabricated a citation (the
  // bibliography doesn't have an entry at that index).
  // Showing the user a raw ``[paper:19]`` artefact when
  // the bibliography only has 9 entries is misleading.
  // The backend's logs and the citation-extraction
  // step's hallucination-detection surfaces the bug for
  // developers; the user-facing UI should never display
  // it.
  return groupedResult.replace(PAPER_MARKER_RE, (match, rawIndex) => {
    const index = parseInt(rawIndex, 10);
    if (
      Number.isNaN(index) ||
      index < 1 ||
      index > maxCitationIndex
    ) {
      // Out of range: drop silently. Returning an empty
      // string collapses the bracket to nothing, so the
      // user just sees the surrounding prose without
      // the broken marker. If the marker was the only
      // thing on its line (e.g. ``- [paper:99]\n``), the
      // line becomes empty -- the markdown list renderer
      // will skip it.
      return "";
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