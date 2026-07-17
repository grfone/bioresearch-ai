// components/ReportPanel.tsx
/**
 * ReportPanel.tsx
 * ---------------
 * Panel displaying a complete generated research report.
 *
 * Includes summary, citations, limitations, future work, and confidence.
 * Designed for the Report page but reusable elsewhere.
 *
 * Uses CSS classes: .glass-panel, .citation-card, .evidence-card etc.
 *
 * @module components/ReportPanel
 */

import React from 'react';
import type { ReportResponse } from '../models/report';
import { hasLimitations, hasFutureWork } from '../models/report';../report';
import { AlertCircle, Lightbulb, CheckCircle, FileText } from 'lucide-react';

interface ReportPanelProps {
  /** The report to display */
  report: ReportResponse;
  /** Additional CSS classes */
  className?: string;
}

export const ReportPanel: React.FC<ReportPanelProps> = ({ report, className = '' }) => {
  return (
    <div className={`space-y-8 ${className}`}>
      {/* Executive Summary */}
      <section className="glass-panel">
        <h2 className="text-lg font-semibold text-primary flex items-center gap-2 mb-3">
          <FileText size={18} />
          Executive Summary
        </h2>
        <p className="text-secondary leading-relaxed whitespace-pre-wrap">
          {report.summary}
        </p>
      </section>

      {/* Citations */}
      {report.citations.length > 0 && (
        <section className="glass-panel">
          <h2 className="text-lg font-semibold text-primary mb-3">Citations</h2>
          <ul className="space-y-2 list-disc pl-5">
            {report.citations.map((citation, idx) => (
              <li key={idx} className="text-secondary text-sm leading-relaxed">
                {citation}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Limitations */}
      {hasLimitations(report) && (
        <section className="glass-panel border-l-4 border-warning">
          <h2 className="text-lg font-semibold text-warning flex items-center gap-2 mb-3">
            <AlertCircle size={18} />
            Limitations
          </h2>
          <ul className="space-y-2 list-disc pl-5">
            {report.limitations.map((item, idx) => (
              <li key={idx} className="text-secondary text-sm leading-relaxed">
                {item}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Future Work */}
      {hasFutureWork(report) && (
        <section className="glass-panel border-l-4 border-primary">
          <h2 className="text-lg font-semibold text-primary flex items-center gap-2 mb-3">
            <Lightbulb size={18} />
            Future Research Directions
          </h2>
          <ul className="space-y-2 list-disc pl-5">
            {report.future_work.map((item, idx) => (
              <li key={idx} className="text-secondary text-sm leading-relaxed">
                {item}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Confidence & metadata */}
      <div className="flex flex-wrap items-center gap-6 text-xs text-muted pt-4 border-t border-border-subtle">
        {report.confidence !== null && (
          <div className="flex items-center gap-2">
            <CheckCircle size={14} className="text-success" />
            <span>Confidence: {Math.round(report.confidence * 100)}%</span>
          </div>
        )}
        <span>Generated: {new Date(report.generated_at).toLocaleString()}</span>
        <span>Citations: {report.citations.length}</span>
      </div>
    </div>
  );
};