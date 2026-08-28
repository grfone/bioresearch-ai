/**
 * Citation rendering helpers for the Report page.
 *
 * Background
 * ----------
 * The LLM emits ``[paper:N]`` markers verbatim in the report
 * body (e.g. ``Plasma p-tau217 is a sensitive marker [paper:19].``)
 * so the backend's regex (``\\[paper:(\\d+)\]``) can extract
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

/**
 * Wrap DOI URLs in a citation string with markdown links.
 *
 * The backend's citation formatter (see ``app/domain/
 * entities/citation.py::Citation.__str__``) emits each
 * citation as a flat string ending in
 * ``https://doi.org/{doi}`` -- e.g.
 *
 *     "Smith J, Jones K. Plasma p-tau217 as a marker.
 *      https://doi.org/10.1234/abc.123"
 *
 * ReactMarkdown renders that as plain text. We want the
 * DOI segment to be a clickable link so the user can jump
 * to the paper's landing page. This helper rewrites the
 * DOI substring into a markdown link, leaving the rest
 * of the citation untouched.
 *
 * Link text choice
 * ----------------
 * The link text is the bare DOI (``10.1234/abc.123``)
 * rather than the full URL. Modern biomedical convention
 * (Nature, PLOS, eLife) is to render DOIs as
 * ``doi:10.1234/abc.123`` or just ``10.1234/abc.123`` --
 * not as the full ``https://doi.org/...`` URL. The full
 * URL is still in the ``href`` so clicking takes the user
 * to the right place; only the visible text is shorter.
 *
 * Edge cases
 * ----------
 * - DOI already wrapped in ``[text](...)`` markdown link:
 *   skipped (the regex looks for ``https://doi.org/``,
 *   not for ``[doi:...]``).
 * - Multiple DOIs in the same string (unusual but possible):
 *   each gets its own link.
 * - No DOI in the string: returned unchanged.
 */
export function linkifyCitationDoi(citation: string): string {
  // The backend emits ``https://doi.org/{doi}`` -- we look
  // for the literal prefix and capture the DOI portion
  // along with any trailing punctuation.
  //
  // The captured groups are:
  //   - doiSuffix: bare DOI (possibly with trailing ``.``
  //     or ``,`` -- sentence punctuation we want to keep
  //     in the rendered output, not inside the link target).
  //   - trailing: any trailing punctuation that was outside
  //     the DOI URL but should stay outside the markdown
  //     link.
  //
  // We need to preserve trailing punctuation OUTSIDE the
  // link target so the rendered text reads correctly
  // ("...https://doi.org/10.1234/abc.123." -- the period
  // is sentence-ending, not part of the DOI).
  // Match the URL body up to the next whitespace or
  // closing paren. The character class intentionally
  // INCLUDES ``.`` and ``/`` because the DOI itself
  // contains dots (``10.1234/abc.456``) and slashes. It
  // EXCLUDES whitespace, commas, semicolons, closing
  // parens, and ``]`` (a common markdown link-target
  // boundary in the source string).
  //
  // Trailing sentence-ending punctuation (``.``, ``,``,
  // ``;``) is captured separately so the rendered
  // citation retains it OUTSIDE the link target. The
  // replacement function strips any leading ``.``/``,``/
  // ``;`` that the URL body captured (defensive -- the
  // DOI itself can end in ``.`` if a future refactor
  // changes the backend's ``Citation.__str__`` shape).
  const DOI_URL_RE =
    /(https:\/\/doi\.org\/[^,\s;)\]]+)([.,;]*)/g;
  return citation.replace(
    DOI_URL_RE,
    (_match, doiUrlWithPath: string, trailing: string) => {
      // The greedy regex sometimes slurps the trailing
      // ``.``/``,``/``;`` into the URL body (the second
      // capture group is empty). Strip any trailing
      // punctuation from the URL body and re-emit it
      // AFTER the link so the rendered text reads
      // "...[10.1234/abc.789](url).".
      //
      // Example: ``https://doi.org/10.1234/abc.789.`` is
      // matched as group1="https://doi.org/10.1234/abc.789.",
      // group2="". We strip the trailing ``.`` and re-emit it
      // after the link. ``https://doi.org/10.1234/abc.111,``
      // behaves the same way (comma is sentence-ending
      // punctuation in the test citation).
      //
      // Defensive: a period at the end of a DOI URL is
      // never valid -- ``https://doi.org/10.1234/abc.123.``
      // (note the trailing period in the path) is not a
      // working URL; the period is sentence-ending.
      const TRAILING_PUNCT_RE = /[.,;]+$/;
      const urlTrailingMatch = doiUrlWithPath.match(TRAILING_PUNCT_RE);
      let doiUrlClean = doiUrlWithPath;
      let recoveredTrailing = "";
      if (urlTrailingMatch) {
        doiUrlClean = doiUrlWithPath.slice(0, -urlTrailingMatch[0].length);
        recoveredTrailing = urlTrailingMatch[0];
      }
      // The link text is the bare DOI (without the
      // ``https://doi.org/`` prefix). Modern biomedical
      // convention (Nature, PLOS, eLife) renders DOIs as
      // ``doi:10.1234/abc.123`` or just ``10.1234/abc.123``
      // -- not as the full URL. The full URL is still in
      // the ``href`` so clicking takes the user to the
      // right place; only the visible text is shorter.
      const doiText = doiUrlClean.replace(/^https:\/\/doi\.org\//, "");
      return `[${doiText}](${doiUrlClean})${recoveredTrailing}${trailing}`;
    },
  );
}
