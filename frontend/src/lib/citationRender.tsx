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
