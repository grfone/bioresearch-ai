// components/ReferencesPanel.tsx
/**
 * ReferencesPanel.tsx
 * -------------------
 * Panel that displays a list of references/citations.
 *
 * Similar to the citations section in ReportPanel, but can be used
 * independently to show references from a workspace or a search.
 *
 * Uses CSS classes: .citation-card, .glass-panel.
 *
 * @module components/ReferencesPanel
 */

import React from 'react';
import { BookOpen } from 'lucide-react';

interface ReferencesPanelProps {
  /** List of citations (strings) */
  references: string[];
  /** Title of the panel */
  title?: string;
  /** Additional CSS classes */
  className?: string;
}

export const ReferencesPanel: React.FC<ReferencesPanelProps> = ({
  references,
  title = 'References',
  className = '',
}) => {
  if (references.length === 0) {
    return (
      <div className={`glass-panel ${className}`}>
        <div className="empty-state py-6">
          <BookOpen size={32} className="text-muted" />
          <p className="text-secondary mt-2">No references available.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`glass-panel ${className}`}>
      <div className="panel-header">
        <div className="panel-header-content">
          <h3 className="panel-title">{title}</h3>
          <p className="panel-description">{references.length} references</p>
        </div>
      </div>
      <ul className="space-y-3">
        {references.map((ref, idx) => (
          <li key={idx} className="citation-card">
            <span className="citation-title">{ref}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};