// components/EvidencePanel.tsx
/**
 * EvidencePanel.tsx
 * -----------------
 * Panel that displays the evidence summary extracted from the workspace.
 *
 * Renders the summary text and optionally the confidence score.
 * Uses CSS classes: .glass-panel, .panel-header, etc.
 *
 * @module components/EvidencePanel
 */

import React from 'react';
import { FileSearch } from 'lucide-react';

interface EvidencePanelProps {
  /** Summary text */
  summary: string | null;
  /** Confidence score (0-1) */
  confidence?: number | null;
  /** Additional CSS classes */
  className?: string;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  summary,
  confidence,
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
        {confidence !== null && confidence !== undefined && (
          <div className="flex items-center gap-2">
            <span className="text-muted text-sm">Confidence:</span>
            <span className="font-semibold text-success">
              {Math.round(confidence * 100)}%
            </span>
          </div>
        )}
      </div>
      <p className="text-secondary leading-relaxed whitespace-pre-wrap">
        {summary}
      </p>
    </div>
  );
};