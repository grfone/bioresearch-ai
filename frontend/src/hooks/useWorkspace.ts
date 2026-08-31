// useWorkspace.ts
/**
 * useWorkspace.ts
 * ----------------
 * Custom React hook for managing a single Research Workspace.
 *
 * The hook exposes the FSM actions via ``runAction``. The
 * orchestrator is the single source of truth — the UI talks to
 * the FSM and never calls report generation directly.
 *
 * Responsibilities:
 * - Fetch workspace data from the API.
 * - Update the workspace (e.g., changing the question).
 * - Search for papers and add them to the workspace.
 * - Run any FSM action (search, summarize, compare, report,
 *   complete, retry).
 * - Generate a report from the workspace.
 *
 * The hook manages loading, error, and data states internally and
 * provides imperative functions to trigger operations.
 *
 * It relies on the global Zustand store (``useWorkspaceStore``) to
 * persist workspace data across components.
 *
 * @module hooks/useWorkspace
 */

import { useState, useCallback, useEffect } from 'react';
import { api } from '../api/client';
import type {
  WorkspaceAction,
  WorkspaceResponse,
  WorkspaceRequest,
  WorkspaceStatusResponse,
} from '../models/workspace';
import type { ReportRequest, ReportResponse } from '../models/report';
import { useWorkspaceStore } from '../state/workspaceStore';

/**
 * Configuration options for the ``useWorkspace`` hook.
 */
interface UseWorkspaceOptions {
  /** Whether to automatically fetch the workspace on mount. Default true. */
  autoFetch?: boolean;
}

/**
 * Return type of the ``useWorkspace`` hook.
 */
interface UseWorkspaceResult {
  /** The current workspace data, or null if not loaded. */
  workspace: WorkspaceResponse | null;
  /** Whether a request is in progress. */
  loading: boolean;
  /** Any error that occurred during the last operation. */
  error: Error | null;
  /** Fetch the workspace by ID. */
  fetchWorkspace: (id: string) => Promise<void>;
  /** Update the workspace (question). */
  updateWorkspace: (request: WorkspaceRequest) => Promise<void>;
  /**
   * Search literature and advance the workspace FSM to
   * ``PAPERS_RETRIEVED``.
   *
   * Routes through the FSM-aware endpoint
   * ``POST /workspaces/{id}/actions/search`` rather than the
   * legacy ``POST /search``. The legacy endpoint returns
   * search hits but does NOT mutate the workspace, which left
   * the FSM in ``CREATED`` even though ``total_papers`` was
   * 20 -- the Generate Report button stayed greyed out. The
   * FSM-aware endpoint persists papers on the server and
   * returns the updated workspace state, so
   * ``allowed_actions`` immediately includes ``report`` (the
   * new "one-click report from PAPERS_RETRIEVED" path -- see
   * ADR-008).
   */
  searchAndAddPapers: (
    question: string,
  ) => Promise<WorkspaceResponse>;
  /**
   * Run a single FSM action. Refreshes the workspace on success.
   *
   * Return shape depends on the action (intentional split
   * between *action surface* and *data surface* -- see
   * ``app/api/routes/workspace_actions.py::report_action``):
   *
   * - Most actions (``search``, ``summarize``, ``compare``,
   *   ``complete``, ``publish``, ``retry``) return
   *   ``WorkspaceResponse`` so the page can mirror state
   *   via ``setCurrentWorkspace``.
   * - ``report`` returns ``ReportResponse`` because the
   *   ``Report.tsx`` page renders the report content
   *   directly via ``setReport(result)`` -- it doesn't
   *   need the workspace state (which is fetched
   *   separately by ``fetchWorkspace``).
   *
   * Callers narrow the return type via TypeScript's
   * discriminated union: ``action === 'report'`` implies
   * ``Promise<ReportResponse>``, anything else implies
   * ``Promise<WorkspaceResponse>``. We don't use TypeScript
   * method overloads here (the useWorkspace result is an
   * interface, where overload merging is fragile).
   */
  runAction: (
    action: WorkspaceAction,
    options?: { query?: string },
  ) => Promise<WorkspaceResponse | ReportResponse>;
  /** Fetch the FSM status (state, allowed_actions, history). */
  fetchTransitions: () => Promise<WorkspaceStatusResponse>;
  /**
   * Generate a report for the workspace.
   *
   * Routes through the FSM-aware ``/actions/report``
   * endpoint (returns ``ReportResponse``). The legacy
   * ``/reports/generate`` endpoint is deprecated.
   */
  generateReport: (
    options?: Partial<Omit<ReportRequest, 'workspace_id'>>,
  ) => Promise<ReportResponse>;
}

/**
 * Custom hook to manage a single Research Workspace.
 */
export function useWorkspace(
  initialWorkspaceId?: string,
  options: UseWorkspaceOptions = { autoFetch: true },
): UseWorkspaceResult {
  const { autoFetch = true } = options;

  // Local state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | undefined>(
    initialWorkspaceId,
  );

  // Global store
  const { currentWorkspace, setCurrentWorkspace, clearCurrentWorkspace, addPapersToCurrent } =
    useWorkspaceStore();

  // Fetch workspace by ID
  const fetchWorkspace = useCallback(
    async (id: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getWorkspace(id);
        setCurrentWorkspace(data);
        setWorkspaceId(id);
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error(String(err));
        setError(errorObj);
        clearCurrentWorkspace();
        throw errorObj;
      } finally {
        setLoading(false);
      }
    },
    [setCurrentWorkspace, clearCurrentWorkspace],
  );

  // Auto-fetch on mount if initialWorkspaceId provided
  useEffect(() => {
    if (initialWorkspaceId && autoFetch) {
      fetchWorkspace(initialWorkspaceId);
    }
  }, [initialWorkspaceId, autoFetch, fetchWorkspace]);

  // Update workspace
  const updateWorkspace = useCallback(
    async (request: WorkspaceRequest) => {
      if (!workspaceId) {
        throw new Error('No workspace ID available. Please fetch a workspace first.');
      }
      setLoading(true);
      setError(null);
      try {
        const data = await api.updateWorkspace(workspaceId, request);
        setCurrentWorkspace(data);
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error(String(err));
        setError(errorObj);
        throw errorObj;
      } finally {
        setLoading(false);
      }
    },
    [workspaceId, setCurrentWorkspace],
  );

  // Search and add papers to the current workspace.
  const searchAndAddPapers = useCallback(
    async (question: string) => {
      if (!workspaceId) {
        throw new Error('No workspace ID available. Please fetch a workspace first.');
      }
      setLoading(true);
      setError(null);
      try {
        // FSM-aware search: persists papers server-side and
        // advances the workspace to PAPERS_RETRIEVED. The
        // returned workspace is the canonical post-search
        // state -- its ``allowed_actions`` list reflects the
        // new state, so the Generate Report button is
        // enabled without a follow-up fetch.
        const data = await api.runSearchAction(
          workspaceId,
          question,
        );
        setCurrentWorkspace(data);
        return data;
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error(String(err));
        setError(errorObj);
        throw errorObj;
      } finally {
        setLoading(false);
      }
    },
    [workspaceId, setCurrentWorkspace],
  );

  // Run a single FSM action. Refreshes the workspace on success.
  //
  // The 'report' case is a special case: the backend returns
  // ``ReportResponse`` (the report content), not a
  // ``WorkspaceResponse``. We still mirror the workspace
  // state via a separate ``fetchWorkspace`` call so the
  // store stays consistent, but we don't try to feed the
  // report content into ``setCurrentWorkspace`` (it would
  // crash the state machine -- ``WorkspaceResponse`` and
  // ``ReportResponse`` have different shapes).
  const runAction = useCallback(
    async (
      action: WorkspaceAction,
      actionOptions?: { query?: string },
    ): Promise<WorkspaceResponse | ReportResponse> => {
      if (!workspaceId) {
        throw new Error('No workspace ID available.');
      }
      setLoading(true);
      setError(null);
      try {
        if (action === 'generate') {
          // FSM-aware GENERATE action. Runs the full pipeline
          // (summary + report + PDF + LaTeX) in one server call
          // and returns a ReportResponse. The page then calls
          // fetchWorkspace separately to refresh the store.
          // See ADR-017.
          const data = await api.runGenerateAction(workspaceId);
          await fetchWorkspace(workspaceId).catch(() => undefined);
          return data;
        }
        if (action === 'back_to_workspace' || action === 'back_to_home') {
          const data = await api.runRegressionAction(
            workspaceId, action,
          );
          setCurrentWorkspace(data);
          return data;
        }

        let data: WorkspaceResponse;
        switch (action) {
          case 'search':
            data = await api.runSearchAction(workspaceId, actionOptions?.query);
            break;
          case 'retry':
            data = await api.runRetryAction(workspaceId);
            break;
          case 'add_paper':
          case 'remove_paper':
            // Paper CRUD goes through dedicated endpoints
            // (see addPaper / removePaper in this hook);
            // the actions here are session-level state
            // transitions only.
            throw new Error(
              `Action '${action}' is not exposed via runAction.`,
            );
          default:
            throw new Error(
              `Action '${action}' is not exposed via runAction.`,
            );
        }
        setCurrentWorkspace(data);
        return data;
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error(String(err));
        setError(errorObj);
        throw errorObj;
      } finally {
        setLoading(false);
      }
    },
    [workspaceId, fetchWorkspace, setCurrentWorkspace],
  );

  // Fetch the FSM status payload.
  const fetchTransitions = useCallback(async () => {
    if (!workspaceId) {
      throw new Error('No workspace ID available.');
    }
    return api.getTransitions(workspaceId);
  }, [workspaceId]);

  // Generate report (legacy — kept for the existing Report page).
  const generateReport = useCallback(
    async (options?: Partial<Omit<ReportRequest, 'workspace_id'>>) => {
      if (!workspaceId) {
        throw new Error('No workspace ID available.');
      }
      setLoading(true);
      setError(null);
      try {
        const request: ReportRequest = {
          workspace_id: workspaceId,
          include_limitations: options?.include_limitations ?? true,
          include_future_work: options?.include_future_work ?? true,
        };
        const report = await api.generateReport(request);
        await fetchWorkspace(workspaceId);
        return report;
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error(String(err));
        setError(errorObj);
        throw errorObj;
      } finally {
        setLoading(false);
      }
    },
    [workspaceId, fetchWorkspace],
  );

  // Expose workspace from store
  const workspace = currentWorkspace;

  return {
    workspace,
    loading,
    error,
    fetchWorkspace,
    updateWorkspace,
    searchAndAddPapers,
    runAction,
    fetchTransitions,
    generateReport,
  };
}
