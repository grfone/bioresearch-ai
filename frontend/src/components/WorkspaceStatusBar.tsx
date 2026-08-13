// WorkspaceStatusBar.tsx
/**
 * WorkspaceStatusBar.tsx
 * ----------------------
 * Lab-bench progress strip for a Research Workspace.
 *
 * The status bar visualises the FSM lifecycle as a sequence of
 * named "stations" (Question → Papers → Summary → Comparison →
 * Report). Each station is either pending, in progress, complete,
 * or error. The bar is purely visual; the actual state machine
 * lives in the backend.
 *
 * @module components/WorkspaceStatusBar
 */

import React from 'react';
import type {
  WorkspaceState,
  WorkspaceAction,
} from '../models/workspace';

interface WorkspaceStatusBarProps {
  /** Current FSM state. */
  state: WorkspaceState;
  /** Coarse progress indicator in [0.0, 1.0]. */
  progress: number;
  /** Legal next actions. */
  allowedActions: WorkspaceAction[];
  /** Whether the workspace is in ERROR. */
  lastError?: string | null;
}

/**
 * Ordered list of stations shown on the progress strip.
 */
const STATIONS: Array<{
  label: string;
  description: string;
  states: WorkspaceState[];
}> = [
  {
    label: 'Question',
    description: 'Workspace created',
    states: ['CREATED'],
  },
  {
    label: 'Papers',
    description: 'PubMed retrieval',
    states: ['SEARCHING', 'PAPERS_RETRIEVED'],
  },
  {
    label: 'Summary',
    description: 'Evidence synthesis',
    states: ['SUMMARIZING', 'SUMMARIZED'],
  },
  {
    label: 'Comparison',
    description: 'Cross-paper analysis',
    states: ['COMPARING', 'COMPARED'],
  },
  {
    label: 'Report',
    description: 'Final report',
    states: ['REPORTING', 'REPORTED', 'COMPLETED'],
  },
];

function classifyStation(
  stationIndex: number,
  currentState: WorkspaceState,
): 'pending' | 'in-progress' | 'complete' | 'error' {
  if (currentState === 'ERROR') {
    return 'error';
  }
  const reachedIndex = STATIONS.findIndex((s) => s.states.includes(currentState));
  if (reachedIndex < 0) return 'pending';
  if (reachedIndex > stationIndex) return 'complete';
  if (reachedIndex === stationIndex) {
    // Distinguish a transient state from a stable one.
    const transient = ['SEARCHING', 'SUMMARIZING', 'COMPARING', 'REPORTING'];
    return transient.includes(currentState) ? 'in-progress' : 'complete';
  }
  return 'pending';
}

export const WorkspaceStatusBar: React.FC<WorkspaceStatusBarProps> = ({
  state,
  progress,
  allowedActions,
  lastError,
}) => {
  return (
    <div className="lab-bench-panel" aria-label="Workspace lifecycle">
      <div className="lab-bench-header">
        <span className="lab-bench-title">Lifecycle</span>
        <span className="lab-bench-state" data-state={state}>
          {state}
        </span>
        <span className="lab-bench-progress" aria-label="Progress">
          {Math.round(progress * 100)}%
        </span>
      </div>

      <div className="lab-bench-stations" role="list">
        {STATIONS.map((station, index) => {
          const classification = classifyStation(index, state);
          return (
            <div
              key={station.label}
              role="listitem"
              className={`lab-bench-station lab-bench-station--${classification}`}
            >
              <div className="lab-bench-station-dot" aria-hidden="true" />
              <div className="lab-bench-station-label">{station.label}</div>
              <div className="lab-bench-station-description">
                {station.description}
              </div>
            </div>
          );
        })}
      </div>

      <div className="lab-bench-progress-bar" aria-hidden="true">
        <div
          className="lab-bench-progress-fill"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>

      {lastError && (
        <div className="lab-bench-error" role="alert">
          <strong>Last error:</strong> {lastError}
        </div>
      )}

      <div className="lab-bench-actions">
        <span className="lab-bench-actions-label">Available actions:</span>
        {allowedActions.length === 0 ? (
          <span className="lab-bench-actions-empty">none</span>
        ) : (
          allowedActions.map((action) => (
            <span key={action} className="lab-bench-action-pill">
              {action}
            </span>
          ))
        )}
      </div>
    </div>
  );
};

export default WorkspaceStatusBar;
