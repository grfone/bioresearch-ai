// EvidenceComparisonPanel.tsx
/**
 * EvidenceComparisonPanel.tsx
 * ---------------------------
 * Renders the cross-paper evidence comparison returned by
 * ``GET /workspaces/{id}/evidence-comparison``.
 *
 * The panel shows:
 * - A consensus section with each finding's claim and supporting
 *   paper IDs.
 * - A contradictions section when disagreements are detected.
 * - A research-gaps section.
 * - A future-directions section.
 * - An optional side-by-side matrix when the LLM produced one.
 *
 * @module components/EvidenceComparisonPanel
 */

import React, { useEffect, useState } from 'react';
import type { EvidenceComparisonResponse } from '../models/comparison';
import { api } from '../api/client';

interface EvidenceComparisonPanelProps {
  workspaceId: string;
  /** Whether the comparison is currently available. */
  hasComparison: boolean;
}

export const EvidenceComparisonPanel: React.FC<EvidenceComparisonPanelProps> = ({
  workspaceId,
  hasComparison,
}) => {
  const [comparison, setComparison] = useState<EvidenceComparisonResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasComparison) {
      setComparison(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getEvidenceComparison(workspaceId)
      .then((data) => {
        if (!cancelled) {
          setComparison(data);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, hasComparison]);

  if (!hasComparison) {
    return (
      <div className="evidence-comparison-panel evidence-comparison-panel--empty">
        <h3 className="evidence-comparison-title">Evidence Comparison</h3>
        <p className="evidence-comparison-empty">
          No cross-paper comparison yet. Run the COMPARE action to generate
          one from the workspace’s papers.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="evidence-comparison-panel">
        <h3 className="evidence-comparison-title">Evidence Comparison</h3>
        <p className="evidence-comparison-loading">Loading comparison…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="evidence-comparison-panel">
        <h3 className="evidence-comparison-title">Evidence Comparison</h3>
        <p className="evidence-comparison-error" role="alert">
          {error}
        </p>
      </div>
    );
  }

  if (!comparison) {
    return null;
  }

  return (
    <div className="evidence-comparison-panel">
      <h3 className="evidence-comparison-title">Evidence Comparison</h3>

      {comparison.consensus.length > 0 && (
        <section className="evidence-comparison-section">
          <h4 className="evidence-comparison-section-title">Consensus</h4>
          <ul className="evidence-comparison-list">
            {comparison.consensus.map((finding, idx) => (
              <li key={idx} className="evidence-comparison-item">
                <p className="evidence-comparison-claim">{finding.claim}</p>
                <div className="evidence-comparison-meta">
                  {finding.evidence_strength && (
                    <span className="evidence-comparison-pill">
                      {finding.evidence_strength}
                    </span>
                  )}
                  {finding.paper_ids.map((pid) => (
                    <span key={pid} className="evidence-comparison-pill">
                      {pid}
                    </span>
                  ))}
                </div>
                {finding.notes && (
                  <p className="evidence-comparison-notes">{finding.notes}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {comparison.contradictions.length > 0 && (
        <section className="evidence-comparison-section">
          <h4 className="evidence-comparison-section-title">
            Contradictions
          </h4>
          <ul className="evidence-comparison-list">
            {comparison.contradictions.map((c, idx) => (
              <li key={idx} className="evidence-comparison-item evidence-comparison-item--contradiction">
                <p className="evidence-comparison-topic">{c.topic}</p>
                <p className="evidence-comparison-description">{c.description}</p>
                <div className="evidence-comparison-meta">
                  {c.severity && (
                    <span className="evidence-comparison-pill evidence-comparison-pill--warning">
                      {c.severity}
                    </span>
                  )}
                  {c.paper_ids.map((pid) => (
                    <span key={pid} className="evidence-comparison-pill">
                      {pid}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {comparison.research_gaps.length > 0 && (
        <section className="evidence-comparison-section">
          <h4 className="evidence-comparison-section-title">Research Gaps</h4>
          <ul className="evidence-comparison-list">
            {comparison.research_gaps.map((gap, idx) => (
              <li key={idx} className="evidence-comparison-item">
                {gap}
              </li>
            ))}
          </ul>
        </section>
      )}

      {comparison.future_directions.length > 0 && (
        <section className="evidence-comparison-section">
          <h4 className="evidence-comparison-section-title">
            Future Directions
          </h4>
          <ul className="evidence-comparison-list">
            {comparison.future_directions.map((d, idx) => (
              <li key={idx} className="evidence-comparison-item">
                {d}
              </li>
            ))}
          </ul>
        </section>
      )}

      {comparison.matrix && comparison.matrix.rows.length > 0 && (
        <section className="evidence-comparison-section">
          <h4 className="evidence-comparison-section-title">Side-by-Side Matrix</h4>
          <div className="evidence-comparison-matrix-wrapper">
            <table className="evidence-comparison-matrix">
              <thead>
                <tr>
                  <th>Paper</th>
                  {comparison.matrix.columns.map((col) => (
                    <th key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {comparison.matrix.rows.map((row, idx) => (
                  <tr key={idx}>
                    <td className="evidence-comparison-matrix-paper">
                      {row.paper_id}
                    </td>
                    {comparison.matrix!.columns.map((col) => (
                      <td key={col}>{row.facets[col] || ''}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
};

export default EvidenceComparisonPanel;
