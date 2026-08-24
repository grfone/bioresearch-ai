// components/EvidencePanel.tsx
/**
 * EvidencePanel.tsx
 * -----------------
 * Panel that displays the evidence summary extracted from the workspace.
 *
 * Renders the summary text. Uses CSS classes: .glass-panel, .panel-header,
 * etc.
 *
 * @module components/EvidencePanel
 */

import React from 'react';
import { FileSearch } from 'lucide-react';

interface EvidencePanelProps {
  /** Summary text */
  summary: string | null;
  /** Additional CSS classes */
  className?: string;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  summary,
  className = '',
}) => {
  if (!summary) {
    return (
      <div className={`glass-panel ${className}`}>
        <div className="empty-state py-8">
          <FileSearch size={32} className="text-muted" />
          <p className="text-secondary mt-2">No evidence summary available.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`glass-panel ${className}`}>
      <div className="panel-header">
        <div className="panel-header-content">
          <h3 className="panel-title">Evidence Summary</h3>
          <p className="panel-description">
            Synthesized from the retrieved literature.
          </p>
        </div>
      </div>
      <p className="text-secondary leading-relaxed whitespace-pre-wrap">
        {summary}
      </p>
    </div>
  );
};