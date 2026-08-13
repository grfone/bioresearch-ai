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
import type {
  EvidenceComparisonResponse,
} from '../models/comparison';
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
  /** Search literature and add papers to the current workspace. */
  searchAndAddPapers: (question: string) => Promise<{ papers: unknown[]; total_results: number }>;
  /** Run a single FSM action. Refreshes the workspace on success. */
  runAction: (
    action: WorkspaceAction,
    options?: { query?: string },
  ) => Promise<WorkspaceResponse>;
  /** Fetch the FSM status (state, allowed_actions, history). */
  fetchTransitions: () => Promise<WorkspaceStatusResponse>;
  /** Fetch the stored evidence comparison. */
  fetchEvidenceComparison: () => Promise<EvidenceComparisonResponse>;
  /** Generate a report for the workspace (legacy wrapper). */
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
        const searchResult = await api.search({ question });
        addPapersToCurrent(searchResult.papers);
        return searchResult;
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error(String(err));
        setError(errorObj);
        throw errorObj;
      } finally {
        setLoading(false);
      }
    },
    [workspaceId, addPapersToCurrent],
  );

  // Run a single FSM action. Refreshes the workspace on success.
  const runAction = useCallback(
    async (
      action: WorkspaceAction,
      actionOptions?: { query?: string },
    ): Promise<WorkspaceResponse> => {
      if (!workspaceId) {
        throw new Error('No workspace ID available.');
      }
      setLoading(true);
      setError(null);
      try {
        let data: WorkspaceResponse;
        switch (action) {
          case 'search':
            data = await api.runSearchAction(workspaceId, actionOptions?.query);
            break;
          case 'summarize':
            data = await api.runSummarizeAction(workspaceId);
            break;
          case 'compare':
            data = await api.runCompareAction(workspaceId);
            break;
          case 'report':
            data = await api.runReportAction(workspaceId);
            break;
          case 'complete':
            data = await api.runCompleteAction(workspaceId);
            break;
          case 'retry':
            data = await api.runRetryAction(workspaceId);
            break;
          default:
            throw new Error(`Action '${action}' is not exposed via runAction.`);
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
    [workspaceId, setCurrentWorkspace],
  );

  // Fetch the FSM status payload.
  const fetchTransitions = useCallback(async () => {
    if (!workspaceId) {
      throw new Error('No workspace ID available.');
    }
    return api.getTransitions(workspaceId);
  }, [workspaceId]);

  // Fetch the stored evidence comparison.
  const fetchEvidenceComparison = useCallback(async () => {
    if (!workspaceId) {
      throw new Error('No workspace ID available.');
    }
    return api.getEvidenceComparison(workspaceId);
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
    fetchEvidenceComparison,
    generateReport,
  };
}
