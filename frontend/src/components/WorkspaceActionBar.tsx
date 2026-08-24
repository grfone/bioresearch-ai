/**
 * ============================================================================
 * WorkspaceActionBar.tsx
 * ============================================================================
 *
 * The action bar above the workspace contents. The current
 * incarnation is intentionally minimal — three buttons:
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
 *  - **Add More Papers**: a standard blue tertiary button.
 *    The label is "Add More Papers" (not "Add papers")
 *    because by the time this button is reachable the
 *    workspace already has at least one paper — the FSM
 *    gates ``add_paper`` on the CREATED..REPORTED range.
 *    Clicking it opens the same Add Papers modal that
 *    the standalone button used to open; the modal is
 *    rendered by the parent (``Workspace.tsx``).
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
import { FileText, Plus } from 'lucide-react';

export interface WorkspaceActionBarProps {
  /** Whether the workspace FSM currently allows the report
   * action. The Generate Report button is disabled when
   * false. */
  canReport: boolean;
  /** Whether the workspace FSM currently allows ``add_paper``.
   * The Add More Papers button is hidden entirely when
   * false -- there's no point clicking it if the FSM will
   * reject the request. (See ``app/core/enums/workspace_state.py``
   * for the gate table; the FSM gates add_paper on the
   * CREATED..REPORTED range, so once the user has clicked
   * Generate Report the button disappears.) */
  canAddPapers: boolean;
  /** Click handler for the Generate Report button. The
   * parent is responsible for the actual API call and
   * post-success navigation; this component only emits the
   * click. */
  onGenerateReport: () => void;
  /** Click handler for the Advanced Search Options button.
   * The parent is responsible for rendering the modal; this
   * component only emits the click. */
  onOpenAdvancedSearch: () => void;
  /** Click handler for the Add More Papers button. The parent
   * is responsible for rendering the Add Papers modal; this
   * component only emits the click. */
  onAddMorePapers: () => void;
}

export const WorkspaceActionBar: React.FC<WorkspaceActionBarProps> = ({
  canReport,
  canAddPapers,
  onGenerateReport,
  onOpenAdvancedSearch,
  onAddMorePapers,
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
        {canAddPapers && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={onAddMorePapers}
            data-action="open-add-papers"
            title="Open the add-papers dialog (DOI/PMID bulk, single DOI, PDF upload)"
          >
            <Plus size={18} aria-hidden="true" />
            Add More Papers
          </button>
        )}
      </div>
    </div>
  );
};
