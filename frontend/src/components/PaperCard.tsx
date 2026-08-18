// components/PaperCard.tsx
/**
 * PaperCard.tsx
 * ------------
 * Renders a single scientific publication as a card.
 *
 * Layout:
 * - Header: title + external-link / remove buttons.
 * - Authors: comma-separated full names. Truncates with "et
 *   al." after the first three.
 * - Journal / year: "Nature, 2025" style citation.
 * - Abstract: truncated to ~3 lines with a "Show more" toggle.
 * - Identifiers: DOI and PMID badges, each linking to its
 *   canonical resolver.
 * - Partial-metadata marker: an asterisk (*) right after the
 *   title when the paper was added with thin metadata (no
 *   abstract AND no authors). This is the user-visible cue
 *   for the failure mode the consultant flagged: the user
 *   inserts a DOI, CrossRef returns whatever it has (sometimes
 *   just the title), and the workspace must signal that this
 *   paper won't have enough material for the LLM stages.
 *
 * @module components/PaperCard
 */

import React from 'react';
import type { Paper } from '../models/paper';
import {
  formatPaperCitation,
  googleScholarUrl,
  hasDoi,
} from '../models/paper';
import { ExternalLink, X, AlertTriangle } from 'lucide-react';

interface PaperCardProps {
  paper: Paper;
  /** Truncate the abstract after this many lines. ``false``
   *  disables truncation. Default: ``true`` (truncate). */
  truncateAbstract?: boolean;
  /** Tailwind/CSS className to append to the card. */
  className?: string;
  /** Called when the user clicks the remove button. */
  onRemove?: (paper: Paper) => void;
  /** Show the partial-metadata asterisk. Default: ``true``.
   *  Callers (e.g. ``PaperList`` for the "all papers" view)
   *  can opt out when they're rendering papers that haven't
   *  gone through the resolver yet. */
  showPartialMarker?: boolean;
  /** Which literature source returned this paper (one of
   *  ``"pubmed"`` / ``"openalex"`` / ``"europe_pmc"`` /
   *  ``"biorxiv"``). When set, a small badge appears
   *  under the title so researchers can see the source.
   *  Default: ``undefined`` (no badge — the typical case
   *  for legacy PubMed-only workspaces). */
  source?: string;
}

const ABSTRACT_TRUNCATE_LINES = 3;

/**
 * A paper has "thin metadata" if BOTH authors AND abstract are
 * empty. CrossRef's bare-minimum record is just a title, so a
 * thin paper is the common failure mode when a DOI resolves but
 * the publisher doesn't expose the full record.
 */
export function isThinPaper(paper: Paper): boolean {
  const noAuthors = paper.authors.length === 0;
  const noAbstract =
    !paper.abstract || paper.abstract.trim().length === 0;
  return noAuthors && noAbstract;
}

export const PaperCard: React.FC<PaperCardProps> = ({
  paper,
  truncateAbstract = true,
  className = '',
  onRemove,
  showPartialMarker = true,
  source,
}) => {
  const [expanded, setExpanded] = React.useState(false);
  const hasAbstract =
    paper.abstract && paper.abstract.trim().length > 0;
  const showTruncation = truncateAbstract && hasAbstract && !expanded;
  const thin = isThinPaper(paper);
  // Scholar link is the escape hatch when the abstract is
  // missing entirely -- the resolver, OpenAlex, and the
  // HTML meta-tag fallback all failed. Pre-compute the URL
  // here so the JSX below can decide whether to render the
  // link in one place.
  const scholarUrl =
    !hasAbstract ? googleScholarUrl(paper) : null;

  // Construct a short author list — comma-separated, "et al."
  // once we exceed the visible limit.
  const authorLine =
    paper.authors.length === 0
      ? null
      : paper.authors.length <= 3
        ? paper.authors.map((a) => a.full_name).join(', ')
        : `${paper.authors
            .slice(0, 3)
            .map((a) => a.full_name)
            .join(', ')} et al.`;

  // Journal/year citation.
  const journalLine =
    paper.journal || paper.year
      ? `${paper.journal?.name ?? 'Unknown journal'}${
          paper.year ? `, ${paper.year}` : ''
        }`
      : null;

  return (
    <div
      className={`paper-card ${className}`}
      data-paper-pmid={paper.pmid ?? ''}
      data-paper-doi={paper.doi ?? ''}
      data-thin-metadata={thin ? 'true' : 'false'}
    >
      <div className="paper-header">
        <div className="flex-1 min-w-0">
          <h3 className="paper-title">
            {paper.title}
            {showPartialMarker && thin && (
              <span
                className="paper-title-partial-marker"
                title="Partial metadata — CrossRef returned only the title. The LLM stages won't have authors or an abstract to work with."
                aria-label="Partial metadata — no authors and no abstract were returned."
              >
                {' *'}
              </span>
            )}
            {source && (
              <span
                className="paper-source-badge"
                data-source={source}
                title={`Returned by ${source}`}
                aria-label={`Source: ${source}`}
              >
                via {source}
              </span>
            )}
          </h3>
          {authorLine && (
            <p className="paper-authors">{authorLine}</p>
          )}
          {journalLine && (
            <p className="paper-journal">{journalLine}</p>
          )}
        </div>
        <div className="paper-actions">
          {paper.url && (
            <a
              href={paper.url}
              target="_blank"
              rel="noopener noreferrer"
              className="paper-action-button"
              aria-label="Open paper in a new tab"
              title={paper.url}
            >
              <ExternalLink size={16} />
            </a>
          )}
          {onRemove && (
            <button
              type="button"
              onClick={() => onRemove(paper)}
              className="paper-action-button paper-action-button--remove"
              aria-label="Remove paper from workspace"
            >
              <X size={16} />
            </button>
          )}
        </div>
      </div>

      {hasAbstract && (
        <div
          className={`paper-abstract ${
            showTruncation ? 'paper-abstract--truncated' : ''
          }`}
        >
          {paper.abstract}
        </div>
      )}

      {showPartialMarker && thin && (
        <div className="paper-thin-warning">
          <AlertTriangle size={14} />
          <span>
            CrossRef returned only the title for this DOI. The
            paper will not have authors or an abstract, so
            summarisation and comparison may be thin.
          </span>
        </div>
      )}

      <div className="paper-identifiers">
        {hasDoi(paper) && (
          <a
            className="paper-identifier paper-identifier--doi"
            href={`https://doi.org/${paper.doi}`}
            target="_blank"
            rel="noopener noreferrer"
            title={paper.doi ?? ''}
          >
            DOI: {paper.doi}
          </a>
        )}
        {paper.pmid && (
          <a
            className="paper-identifier paper-identifier--pmid"
            href={`https://pubmed.ncbi.nlm.nih.gov/${paper.pmid}/`}
            target="_blank"
            rel="noopener noreferrer"
            title={paper.pmid}
          >
            PMID: {paper.pmid}
          </a>
        )}
        {scholarUrl && (
          <a
            className="paper-identifier paper-identifier--scholar"
            href={scholarUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="Search on Google Scholar to find the abstract"
          >
            Scholar
          </a>
        )}
      </div>

      {truncateAbstract && hasAbstract && paper.abstract && paper.abstract.length > 200 && (
        <button
          type="button"
          className="paper-abstract-toggle"
          onClick={() => setExpanded((prev) => !prev)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
};
