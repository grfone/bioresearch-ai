// components/PaperList.tsx
/**
 * PaperList.tsx
 * -------------
 * Component that renders a list of scientific papers.
 *
 * Uses PaperCard for each item and handles empty state.
 *
 * @module components/PaperList
 */

import React from 'react';
import type { Paper } from '../models/paper';
import { PaperCard } from './PaperCard';

interface PaperListProps {
  papers: Paper[];
  truncateAbstract?: boolean;
  className?: string;
  emptyMessage?: string;
  onRemovePaper?: (paper: Paper) => void; // NEW
}

export const PaperList: React.FC<PaperListProps> = ({
  papers,
  truncateAbstract = true,
  className = '',
  emptyMessage = 'No papers retrieved yet.',
  onRemovePaper,
}) => {
  // ... empty state

  return (
    <div className={`space-y-4 ${className}`}>
      {papers.map((paper, idx) => (
        <PaperCard
          key={idx}
          paper={paper}
          truncateAbstract={truncateAbstract}
          onRemove={onRemovePaper}
        />
      ))}
    </div>
  );
};