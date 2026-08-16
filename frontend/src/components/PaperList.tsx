// components/PaperList.tsx
/**
 * PaperList.tsx
 * -------------
 * Renders a list of papers using ``PaperCard``.
 *
 * Two empty-state branches:
 *
 * 1. ``papers.length === 0`` and ``emptyMessage`` is supplied —
 *    render that message verbatim. The workspace uses this
 *    path to point the user at the three-zone workflow picker.
 *
 * 2. ``papers.length > 0`` — render one ``PaperCard`` per
 *    paper. Cards are keyed by ``pmid || doi || title`` so
 *    React doesn't lose component state when the array order
 *    shifts (which the resolver does on every refresh).
 *
 * @module components/PaperList
 */

import React from 'react';
import type { Paper } from '../models/paper';
import { PaperCard } from './PaperCard';

interface PaperListProps {
  papers: Paper[];
  /** Truncate each paper's abstract after a few lines. */
  truncateAbstract?: boolean;
  /** Tailwind/CSS className applied to the wrapping div. */
  className?: string;
  /** Text shown when ``papers`` is empty. */
  emptyMessage?: string;
  /** Optional remove handler. Passed through to ``PaperCard``. */
  onRemovePaper?: (paper: Paper) => void;
}

/**
 * Build a stable key for a paper so React keeps DOM identity
 * even when the array order changes. PMID is the most stable
 * (PubMed never reassigns PMIDs); DOI is second; the title is
 * the fallback for placeholder papers that have neither.
 */
function paperKey(paper: Paper): string {
  if (paper.pmid) return `pmid:${paper.pmid}`;
  if (paper.doi) return `doi:${paper.doi}`;
  // Title fallback. Strip whitespace because CrossRef sometimes
  // returns titles with leading/trailing spaces.
  return `t:${paper.title.trim()}`;
}

export const PaperList: React.FC<PaperListProps> = ({
  papers,
  truncateAbstract = true,
  className = '',
  emptyMessage,
  onRemovePaper,
}) => {
  if (papers.length === 0 && emptyMessage) {
    return (
      <div
        className={`paper-list-empty ${className}`}
        data-testid="paper-list-empty"
      >
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className={`paper-list ${className}`}>
      {papers.map((paper) => (
        <PaperCard
          key={paperKey(paper)}
          paper={paper}
          truncateAbstract={truncateAbstract}
          onRemove={onRemovePaper}
        />
      ))}
    </div>
  );
};
