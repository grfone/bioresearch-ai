// workspace.ts
/**
 * workspace.ts
 * -------------
 * Frontend TypeScript definitions for Research Workspaces.
 *
 * These interfaces correspond to the backend request/response schemas
 * defined in `workspace_request.py` and `workspace_response.py`.
 *
 * A Workspace represents the persistent state of a biomedical investigation,
 * including the research question, retrieved papers, summaries, comparison,
 * and reports.
 *
 * The Workspace object now exposes the FSM lifecycle fields:
 * - `state`, `allowed_actions`, `progress`, `state_history`, `last_error`,
 *   `has_evidence_comparison`.
 *
 * @module models/workspace
 */

import { Paper } from './paper';

/**
 * Request payload for creating or updating a Research Workspace.
 */
export interface WorkspaceRequest {
  /** Biomedical research question that drives the investigation */
  question: string;
}

/**
 * FSM state of a Research Workspace.
 *
 * The state is the authoritative source of truth for "what can happen
 * next". The label is the enum value serialised by the backend FSM
 * (e.g. "CREATED", "PAPERS_RETRIEVED", "SUMMARIZED", "COMPARED",
 * "REPORTED", "COMPLETED", "ERROR").
 */
export type WorkspaceState =
  | 'CREATED'
  | 'SEARCHING'
  | 'PAPERS_RETRIEVED'
  | 'SUMMARIZING'
  | 'SUMMARIZED'
  | 'COMPARING'
  | 'COMPARED'
  | 'REPORTING'
  | 'REPORTED'
  | 'COMPLETED'
  | 'ERROR';

/**
 * Action that can be requested on a Research Workspace.
 *
 * The UI uses these verbs to call the orchestrator. The backend
 * rejects illegal actions with HTTP 409.
 */
export type WorkspaceAction =
  | 'search'
  | 'summarize'
  | 'compare'
  | 'report'
  | 'complete'
  | 'retry'
  | 'add_paper'
  | 'remove_paper';

/**
 * Full representation of a Research Workspace returned by the API.
 *
 * This object contains all data related to a scientific investigation,
 * including the question, retrieved papers, summaries, and reports.
 */
export interface WorkspaceResponse {
  /** Unique identifier (UUID) of the workspace */
  workspace_id: string;
  /** Original research question */
  question: string;
  /** Current FSM state (preferred over `status`) */
  state: WorkspaceState;
  /** Backwards-compatible status string. Always mirrors `state`. */
  status: string;
  /** Legal next actions, sorted alphabetically. */
  allowed_actions: WorkspaceAction[];
  /** Coarse progress indicator in [0.0, 1.0]. */
  progress: number;
  /** Last error message if the workspace is in ERROR. */
  last_error: string | null;
  /** List of scientific papers loaded into the workspace */
  papers: Paper[];
  /** Total number of papers (redundant with papers.length, but provided by API) */
  total_papers: number;
  /** Evidence summary generated from the papers, if available */
  summary: string | null;
  /** Whether a cross-paper evidence comparison exists */
  has_evidence_comparison: boolean;
  /** Whether a final research report has been generated */
  report_available: boolean;
  /** UTC timestamp of workspace creation */
  created_at: string;
  /** UTC timestamp of last update */
  updated_at: string;
}

/**
 * A single entry in the workspace's state history.
 */
export interface StateTransitionResponse {
  from_state: WorkspaceState;
  to_state: WorkspaceState;
  action: WorkspaceAction | null;
  at: string;
  reason: string | null;
}

/**
 * FSM status payload returned by ``GET /workspaces/{id}/transitions``.
 */
export interface WorkspaceStatusResponse {
  workspace_id: string;
  state: WorkspaceState;
  progress: number;
  allowed_actions: WorkspaceAction[];
  state_history: StateTransitionResponse[];
  last_error: string | null;
  is_transient: boolean;
  is_terminal: boolean;
}

/**
 * Type guard to check if a workspace has any papers.
 */
export function hasPapers(workspace: WorkspaceResponse): boolean {
  return workspace.total_papers > 0 && workspace.papers.length > 0;
}

/**
 * Type guard to check if a workspace has a summary.
 */
export function hasSummary(workspace: WorkspaceResponse): boolean {
  return !!workspace.summary && workspace.summary.trim().length > 0;
}

/**
 * Type guard to check if a workspace has an evidence comparison.
 */
export function hasEvidenceComparison(workspace: WorkspaceResponse): boolean {
  return workspace.has_evidence_comparison;
}

/**
 * Type guard to check if a workspace has a final report.
 */
export function hasReport(workspace: WorkspaceResponse): boolean {
  return workspace.report_available;
}
