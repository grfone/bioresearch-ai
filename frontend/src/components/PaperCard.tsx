// components/PaperCard.tsx
/**
 * PaperCard.tsx
 * -------------
 * Card component displaying a single scientific publication.
 *
 * Renders the paper's title, authors, journal, year, abstract, and metadata
 * badges (PMID, DOI). Designed to be used inside a PaperList.
 *
 * Uses CSS classes from the design system:
 * - .paper-card, .paper-header, .paper-title, .paper-authors, etc.
 *
 * @module components/PaperCard
 */

import React from 'react';
import type { Paper } from '../models/paper';
import { ExternalLink, X } from 'lucide-react';

interface PaperCardProps {
  paper: Paper;
  truncateAbstract?: boolean;
  className?: string;
  onRemove?: (paper: Paper) => void; // NEW
}

export const PaperCard: React.FC<PaperCardProps> = ({
  paper,
  truncateAbstract = true,
  className = '',
  onRemove,
}) => {
  // ... existing logic for abstract truncation

  return (
    <div className={`paper-card ${className}`}>
      <div className="paper-header">
        <div className="flex-1">
          <h3 className="paper-title">{paper.title}</h3>
          {/* ... */}
        </div>
        <div className="flex items-center gap-2">
          {paper.url && (
            <a href={paper.url} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={18} />
            </a>
          )}
          {onRemove && (
            <button
              onClick={() => onRemove(paper)}
              className="text-muted hover:text-error transition-colors"
              aria-label="Remove paper"
            >
              <X size={18} />
            </button>
          )}
        </div>
      </div>
      {/* rest of the card */}
    </div>
  );
};