/**
 * Render helpers for citation strings in the Report page.
 *
 * The backend's citation formatter (see ``app/domain/
 * entities/citation.py::Citation.__str__``) emits each
 * citation as a flat string ending in a DOI URL:
 *
 *     "Smith J, Jones K. Plasma p-tau217 as a marker.
 *      https://doi.org/10.1234/abc.123"
 *
 * We want the DOI segment to be a clickable hyperlink so
 * the user can jump straight to the paper. The string
 * itself contains the DOI URL inline, so this module
 * converts it into a JSX node tree where the DOI portion
 * is an ``<a href="https://doi.org/...">`` element.
 *
 * Why a dedicated module
 * ----------------------
 * The Report page renders each citation as plain JSX
 * inside an ``<li>`` (not via ReactMarkdown -- a citation
 * is a single line of formatted text, not markdown).
 * That means the markdown link ``[text](url)`` produced
 * by :func:`linkifyCitationDoi` would render as literal
 * text "[text](url)" in a regular React text node. We
 * need to convert the markdown link into a real anchor
 * element to actually get the click behaviour.
 *
 * Render strategy
 * ---------------
 * - Walk the input string, splitting on the DOI URL
 *   matches produced by ``linkifyCitationDoi``.
 * - Each non-DOI segment is a plain ``<span>``.
 * - Each DOI match becomes an ``<a>`` element pointing
 *   at ``https://doi.org/{doi}`` with the bare DOI as
 *   the link text.
 *
 * Edge cases
 * ----------
 * - Empty input: returns an empty fragment.
 * - Plain string (no DOI): returns a single ``<span>``.
 * - Multiple DOIs in one string: each gets its own
 *   anchor.
 * - Trailing punctuation outside the DOI (the regex
 *   preserves ``.``/``,``/``;`` after the link): the
 *   text fragment after the anchor carries the trailing
 *   punctuation, matching the linkify helper's
 *   contract.
 */
import React from "react";

const DOI_URL_RE_WITH_LABELS =
  /\[([^\]]+)\]\((https:\/\/doi\.org\/[^)]+)\)/g;

/**
 * Render a citation string as JSX, with any DOI segment
 * turned into a clickable anchor that opens the paper's
 * landing page in a new tab.
 *
 * The output is a React fragment so callers can drop it
 * inline in any JSX position. The key={} on the outer
 * fragment is stable across renders -- the input is a
 * fixed string from the backend.
 *
 * Parameters
 * ----------
 * citation : string
 *     Plain citation text. May contain ``[doi](url)``
 *     segments (the output of :func:`linkifyCitationDoi`).
 *
 * Returns
 * -------
 * React.ReactNode
 *     A fragment with the citation text. DOI segments
 *     are real anchor elements.
 */
export function renderCitationWithDoiLink(
  citation: string,
): React.ReactNode {
  if (!citation) return null;

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let keyCounter = 0;
  // Reset the regex state because of the /g flag.
  DOI_URL_RE_WITH_LABELS.lastIndex = 0;
  while ((match = DOI_URL_RE_WITH_LABELS.exec(citation)) !== null) {
    if (match.index > lastIndex) {
      parts.push(
        <React.Fragment key={`cit-text-${keyCounter++}`}>
          {citation.slice(lastIndex, match.index)}
        </React.Fragment>,
      );
    }
    const label = match[1];
    const url = match[2];
    parts.push(
      <a
        key={`cit-link-${keyCounter++}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary hover:underline"
      >
        {label}
      </a>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < citation.length) {
    parts.push(
      <React.Fragment key={`cit-tail-${keyCounter++}`}>
        {citation.slice(lastIndex)}
      </React.Fragment>,
    );
  }
  return <>{parts}</>;
}


// Markdown link pattern produced by
// ``app/lib/citationLink.ts::linkifyCitationMarkers``:
// each ``[paper:N]`` becomes ``[N](#citation-N)``. The
// groups and standalone forms both produce the same shape.
//
// We only care about the in-page anchor form -- users
// are reading the report, they want to jump to the
// bibliography entry at the bottom of the page, not
// follow an external URL.
//
// Negative lookahead excludes empty markers (defence in
// depth -- linkifyCitationMarkers never produces these,
// but a malformed backend response could).
const INLINE_CITATION_RE = /\[(\d+)\]\(#citation-(\d+)\)/g;


export function renderItemWithCitationLinks(
  item: string,
): React.ReactNode {
  /**
   * Render a Limitations or Future Research item with
   * ``[N](#citation-N)`` citation markers converted to
   * real ``<a>`` anchor elements that jump to the
   * bibliography at the bottom of the page.
   *
   * The string passed in is the output of
   * :func:`linkifyCitationMarkers` applied to the
   * backend's ``report.limitations`` / ``report.future_work``
   * entries. These strings live inside plain React
   * ``<li>`` elements (NOT inside a ReactMarkdown
   * container, like the Executive Summary body is),
   * so the markdown link ``[N](#citation-N)`` would
   * otherwise render as literal text -- which is the
   * bug this helper fixes.
   *
   * Why a dedicated helper instead of wrapping each item in
   * ``<ReactMarkdown>``
   * ------------------------------------------------
   * The Executive Summary body (``reportBody``) is wrapped
   * in ``<ReactMarkdown>`` so the citations there are
   * clickable. The same wrapper for each Limitations /
   * Future Work item would be heavier (ReactMarkdown per
   * item, plus a ``<p>`` wrapper that breaks ``<li>``
   * nesting) and would introduce a visible visual
   * inconsistency -- the Executive Summary gets
   * ``prose`` typography, the Lists get rendered markdown
   * paragraphs. This helper instead mirrors the existing
   * :func:`renderCitationWithDoiLink` pattern: walk the
   * string, split on link markers, emit anchors where
   * they're needed, emit text nodes for the rest. The
   * rendered DOM is what the user expects.
   *
   * Returns
   * -------
   * React.ReactNode
   *     A JSX fragment with anchors in place of the
   *     markdown-link citations. Plain text segments are
   *     direct text nodes (NOT wrapped in ``<span>``
   *     elements, which would be invalid children of the
   *     surrounding ``<li>``).
   *
   * Edge cases
   * ----------
   * - Empty input: returns ``null``. The caller
   *   shouldn't pass empty strings (the synthesis
   *   fallback strips empties), but defensive.
   * - String with no citation markers: returns the
   *   string as a single text node (React renders the
   *   string directly).
   * - Multiple citations in one item: every
   *   ``[N](#citation-N)`` becomes its own anchor.
   * - Out-of-range citation indices (e.g. ``[99]``
   *   when bibliography has 5 entries): linkifyCitationMarkers
   *   on the backend never produces these (its
   *   ``maxCitationIndex`` parameter drops out-of-range
   *   markers silently). If they slip through here
   *   somehow, the anchor still renders -- pointing at
   *   ``#citation-99`` (which won't exist). The user
   *   gets a dead anchor instead of broken text, which
   *   is the right failure mode for a malformed
   *   backend response.
   */
  if (!item) return null;

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let keyCounter = 0;
  // Reset the regex state because of the /g flag.
  INLINE_CITATION_RE.lastIndex = 0;
  while ((match = INLINE_CITATION_RE.exec(item)) !== null) {
    if (match.index > lastIndex) {
      parts.push(item.slice(lastIndex, match.index));
    }
    const label = match[1];
    const anchorIndex = match[2];
    parts.push(
      <a
        key={`item-citation-${keyCounter++}`}
        href={`#citation-${anchorIndex}`}
        className="text-primary hover:underline"
      >
        {label}
      </a>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < item.length) {
    parts.push(item.slice(lastIndex));
  }
  return <>{parts}</>;
}
