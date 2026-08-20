/**
 * ============================================================================
 * WorkspaceActionBar.tsx
 * ============================================================================
 *
 * The action bar above the workspace contents. The current
 * incarnation is intentionally minimal — two buttons:
 *
 *  - **Generate Report**: a prominent primary CTA. Calls
 *    ``onGenerateReport`` and, if the action succeeds,
 *    navigates to ``/report/{workspaceId}``. The button is
 *    disabled when the FSM doesn't currently allow report
 *    generation (i.e. ``canReport`` is false).
 *
 *  - **Advanced Search Options**: a standard blue secondary
 *    button. The label is constant (no toggle verb). Clicking
 *    it opens the Advanced Search modal — the modal is
 *    rendered separately by the parent and manages its own
 *    open/close state; this button just fires the click.
 *    We deliberately do NOT mirror the modal's open/close
 *    state in the bar: the user expects a standard button
 *    that always reads the same thing, and the modal's
 *    own close behaviour (Escape, backdrop click, onClose
 *    callback) brings the user back to the workspace page
 *    cleanly. See ADR-008 for the broader "one-click report"
 *    rationale.
 *
 * Earlier versions of this bar had a two-tier layout
 * (Summarize / Compare / Generate Report / Complete / Retry /
 * Clear All) and a "Hide processing actions" toggle. Both
 * have been removed for now — the user asked to keep the
 * bar minimal while iterating on the workspace UX. They can
 * be re-added through the same ``can(action)`` /
 * ``onRunAction(action, label)`` callbacks the parent passes
 * in if needed.
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

import React from 'react';
import { FileText } from 'lucide-react';

export interface WorkspaceActionBarProps {
  /** Whether the workspace FSM currently allows the report
   * action. The Generate Report button is disabled when
   * false. */
  canReport: boolean;
  /** Click handler for the Generate Report button. The
   * parent is responsible for the actual API call and
   * post-success navigation; this component only emits the
   * click. */
  onGenerateReport: () => void;
  /** Click handler for the Advanced Search Options button.
   * The parent is responsible for rendering the modal; this
   * component only emits the click. */
  onOpenAdvancedSearch: () => void;
}

export const WorkspaceActionBar: React.FC<WorkspaceActionBarProps> = ({
  canReport,
  onGenerateReport,
  onOpenAdvancedSearch,
}) => {
  return (
    <div
      className="lab-bench-action-bar"
      role="toolbar"
      aria-label="Workspace actions"
    >
      <div className="lab-bench-action-bar-primary">
        <button
          className="btn btn-primary btn-action-primary"
          onClick={onGenerateReport}
          disabled={!canReport}
          data-action="report"
          title={
            canReport
              ? 'Generate the final research report from the workspace papers'
              : 'Report generation is not allowed in the current state'
          }
        >
          <FileText size={18} />
          Generate Report
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={onOpenAdvancedSearch}
          data-action="advanced-search-open"
          title="Open the advanced search options (sources, year range, sort, document type)"
        >
          Advanced Search Options
        </button>
      </div>
    </div>
  );
};
