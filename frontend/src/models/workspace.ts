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
 * including the research question, retrieved papers, summaries, and reports.
 *
 * The module exports:
 *
 * - WorkspaceRequest   : payload for creating or updating a workspace
 * - WorkspaceResponse  : full workspace object returned by the API
 * - WorkspaceStatus    : enum of possible workspace lifecycle states
 *
 * All field names use snake_case to match the API contract.
 *
 * @module models/workspace
 */

import { Paper } from './paper';

/**
 * Request payload for creating or updating a Research Workspace.
 *
 * At minimum, a workspace is defined by a research question.
 * Future versions may add additional configuration fields.
 */
export interface WorkspaceRequest {
  /** Biomedical research question that drives the investigation */
  question: string;
}

/**
 * Possible states of a Research Workspace.
 */
export type WorkspaceStatus =
  | 'Created'
  | 'Searching'
  | 'Summarizing'
  | 'Completed'
  | 'Error';

/**
 * Full representation of a Research Workspace returned by the API.
 *
 * This object contains all data related to a scientific investigation,
 * including the question, retrieved papers, summaries, and metadata.
 */
export interface WorkspaceResponse {
  /** Unique identifier (UUID) of the workspace */
  workspace_id: string;
  /** Original research question */
  question: string;
  /** Current lifecycle status */
  status: WorkspaceStatus;
  /** List of scientific papers loaded into the workspace */
  papers: Paper[];
  /** Total number of papers (redundant with papers.length, but provided by API) */
  total_papers: number;
  /** Evidence summary generated from the papers, if available */
  summary: string | null;
  /** Whether a final research report has been generated */
  report_available: boolean;
  /** UTC timestamp of workspace creation */
  created_at: string; // ISO 8601 date string
  /** UTC timestamp of last update */
  updated_at: string; // ISO 8601 date string
}

/**
 * Type guard to check if a workspace has any papers.
 *
 * @param workspace - The workspace to check.
 * @returns True if the workspace contains at least one paper.
 */
export function hasPapers(workspace: WorkspaceResponse): boolean {
  return workspace.total_papers > 0 && workspace.papers.length > 0;
}

/**
 * Type guard to check if a workspace has a summary.
 *
 * @param workspace - The workspace to check.
 * @returns True if a summary exists.
 */
export function hasSummary(workspace: WorkspaceResponse): boolean {
  return !!workspace.summary && workspace.summary.trim().length > 0;
}