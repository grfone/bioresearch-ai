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
 * (e.g. "CREATED", "PAPERS_RETRIEVED", "SUMMARIZED", "REPORTED",
 * "COMPLETED", "ERROR").
 *
 * Note: the cross-paper COMPARING/COMPARED intermediate states were
 * removed on 2026-08-30 — the FSM is now linear: search → summarise
 * → report → done.
 */
export type WorkspaceState =
  | 'CREATED'
  | 'SEARCHING'
  | 'PAPERS_RETRIEVED'
  | 'SUMMARIZING'
  | 'SUMMARIZED'
  | 'REPORTING'
  | 'REPORTED'
  | 'PUBLISHING'
  | 'COMPLETED'
  | 'ERROR';

/**
 * Action that can be requested on a Research Workspace.
 *
 * The UI uses these verbs to call the orchestrator. The backend
 * rejects illegal actions with HTTP 409.
 *
 * Note: the COMPARE action was removed on 2026-08-30.
 */
export type WorkspaceAction =
  | 'search'
  | 'summarize'
  | 'report'
  | 'complete'
  | 'publish'
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
  /**
   * UTC timestamp of when ``last_error`` was set.
   *
   * Pairs with ``last_error`` (both are set/cleared together).
   * ``null`` when ``last_error`` is ``null``. ISO-8601 string
   * (e.g. ``"2026-08-26T15:30:00+00:00"``).
   */
  last_error_at: string | null;
  /** List of scientific papers loaded into the workspace */
  papers: Paper[];
  /**
   * Per-paper source attribution — maps a paper
   * identifier (PMID, DOI, or URL) to the
   * ``SearchSource`` enum value that returned it
   * (``"pubmed"`` / ``"openalex"`` / ``"europe_pmc"`` /
   * ``"biorxiv"``). Empty for legacy PubMed-only
   * workspaces; populated by the multi-source
   * Advanced Search path.
   *
   * The PaperCard UI consumes this map and renders a
   * small "via OpenAlex" badge next to each paper so
   * researchers can see which source returned it.
   */
  paper_sources: Record<string, string>;
  /** Total number of papers (redundant with papers.length, but provided by API) */
  total_papers: number;
  /** Evidence summary generated from the papers, if available */
  summary: string | null;
  /**
   * Whether a final research report has been generated.
   *
   * Note: ``has_evidence_comparison`` was retired on 2026-08-30
   * alongside the COMPARE action. The cross-paper comparison is
   * no longer a distinct FSM step.
   */
  report_available: boolean;
  /** Whether a PDF has been rendered for download by the PUBLISH
   * action. Independent of ``report_available``: a workspace may
   * have a generated report but not yet a PDF, or vice versa
   * after a previous PUBLISH. The "Download PDF" button is
   * enabled only when this is true. */
  published_report_available: boolean;
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
 * Type guard to check if a workspace has a final report.
 */
export function hasReport(workspace: WorkspaceResponse): boolean {
  return workspace.report_available;
}


/**
 * Resolve which ``SearchSource`` returned a paper, falling
 * back through the paper's identifier priority order
 * (PMID → DOI → URL).
 *
 * Returns ``null`` when:
 * - The workspace has no ``paper_sources`` map (legacy
 *   PubMed-only workspaces).
 * - None of the paper's identifiers are in the map
 *   (e.g. a paper added via the manual PDF fallback that
 *   wasn't tagged with a source).
 *
 * The PaperCard UI calls this and renders a "via
 * OpenAlex" badge when the result is non-null.
 */
export function paperSource(
  workspace: WorkspaceResponse,
  paper: Paper,
): string | null {
  const map = workspace.paper_sources;
  if (!map) return null;
  // Priority order: PMID first (canonical for biomedical),
  // DOI next, URL last. The backend's _paper_keys uses the
  // same priority so the keys match.
  if (paper.pmid && map[paper.pmid]) return map[paper.pmid];
  if (paper.doi && map[paper.doi]) return map[paper.doi];
  if (paper.url && map[paper.url]) return map[paper.url];
  return null;
}
