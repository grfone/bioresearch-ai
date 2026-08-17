// workspaceStore.ts
/**
 * workspaceStore.ts
 * ------------------
 * Zustand store for managing Research Workspace state across the frontend.
 *
 * This store holds the current workspace (if any) and provides actions
 * to set, update, and clear workspace data. It can be extended to manage
 * multiple workspaces or a list of workspaces.
 *
 * The store is designed to work seamlessly with the `useWorkspace` hook
 * and API client.
 *
 * @module state/workspaceStore
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type { WorkspaceResponse } from '../models/workspace';
import type { Paper } from '../models/paper';

interface WorkspaceStore {
  currentWorkspace: WorkspaceResponse | null;
  setCurrentWorkspace: (workspace: WorkspaceResponse) => void;
  updateCurrentWorkspace: (updates: Partial<WorkspaceResponse>) => void;
  clearCurrentWorkspace: () => void;
  addPapersToCurrent: (papers: Paper[]) => void;
  removePaper: (paperId: string) => void;   // NEW
  clearPapers: () => void;                  // NEW
  setSummary: (summary: string) => void;
  setReportAvailable: (available: boolean) => void;
}



/**
 * Mirror of the backend's allowed_actions logic.
 *
 * The frontend uses this when ``addPapersToCurrent`` adds
 * papers via the legacy LiteratureSearch path (which
 * bypasses the orchestrator). For the modal path the
 * response carries the right ``allowed_actions`` already.
 *
 * Keep in sync with ``app/core/enums/workspace_state.py``.
 */
function nextAllowedActions(
  state: string,
  totalPapers: number,
): Array<
  | 'search'
  | 'summarize'
  | 'compare'
  | 'report'
  | 'complete'
  | 'retry'
  | 'add_paper'
  | 'remove_paper'
> {
  switch (state) {
    case 'CREATED':
      return ['add_paper', 'search'];
    case 'PAPERS_RETRIEVED':
      return ['add_paper', 'remove_paper', 'search', 'summarize'];
    case 'SUMMARIZED':
      return ['add_paper', 'compare', 'remove_paper', 'search'];
    case 'COMPARED':
      return ['add_paper', 'remove_paper', 'report', 'search'];
    case 'REPORTED':
      return ['complete', 'remove_paper', 'search'];
    case 'COMPLETED':
      return totalPapers > 0
        ? ['remove_paper', 'search']
        : ['search'];
    case 'ERROR':
      return ['retry'];
    default:
      return ['search'];
  }
}
export const useWorkspaceStore = create<WorkspaceStore>()(
  devtools(
    persist(
      (set) => ({
        currentWorkspace: null,

        setCurrentWorkspace: (workspace) =>
          set({ currentWorkspace: workspace }),

        updateCurrentWorkspace: (updates) =>
          set((state) => {
            if (!state.currentWorkspace) return state;
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                ...updates,
              },
            };
          }),

        clearCurrentWorkspace: () => set({ currentWorkspace: null }),

        addPapersToCurrent: (papers) =>
          set((state) => {
            if (!state.currentWorkspace) return state;
            // Track PMIDs already in the workspace AND PMIDs
            // we're about to add — so two papers with the
            // same PMID in the incoming batch don't both
            // pass the dedup filter.
            const seenPmids = new Set<string>();
            const existingPmids = new Set(
              state.currentWorkspace.papers
                .map((p) => p.pmid)
                .filter((p): p is string => Boolean(p))
            );
            const newPapers: typeof papers = [];
            for (const p of papers) {
              if (p.pmid) {
                if (existingPmids.has(p.pmid)) continue;
                if (seenPmids.has(p.pmid)) continue;
                seenPmids.add(p.pmid);
              }
              newPapers.push(p);
            }
            if (newPapers.length === 0) return state;
            const mergedPapers = [
              ...state.currentWorkspace.papers,
              ...newPapers,
            ];
            const totalPapers = mergedPapers.length;
            // Mirror the backend FSM transition:
            // ``WorkspaceState.CREATED + ADD_PAPER -> PAPERS_RETRIEVED``.
            // We also recompute ``allowed_actions`` from the
            // new state so the action bar reflects the right
            // permissions without a round-trip to the
            // backend. The set of allowed actions matches the
            // backend's TRANSITIONS table.
            const prevState = state.currentWorkspace.state;
            const nextState =
              prevState === 'CREATED' ? 'PAPERS_RETRIEVED' : prevState;
            const nextAllowed = nextAllowedActions(
              nextState,
              totalPapers,
            );
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                state: nextState,
                allowed_actions: nextAllowed,
                papers: mergedPapers,
                total_papers: totalPapers,
              },
            };
          }),

        // NEW: Remove a paper by PMID or DOI (fallback to index)
        removePaper: (paperId: string) =>
          set((state) => {
            if (!state.currentWorkspace) return state;
            const filtered = state.currentWorkspace.papers.filter(
              (p) => p.pmid !== paperId && p.doi !== paperId
            );
            if (filtered.length === state.currentWorkspace.papers.length) {
              // If no match, maybe remove by index? Not needed.
              return state;
            }
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                papers: filtered,
                total_papers: filtered.length,
              },
            };
          }),

        // NEW: Clear all papers
        clearPapers: () =>
          set((state) => {
            if (!state.currentWorkspace) return state;
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                papers: [],
                total_papers: 0,
              },
            };
          }),

        setSummary: (summary) =>
          set((state) => {
            if (!state.currentWorkspace) return state;
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                summary,
              },
            };
          }),

        setReportAvailable: (available) =>
          set((state) => {
            if (!state.currentWorkspace) return state;
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                report_available: available,
              },
            };
          }),
      }),
      {
        name: 'workspace-storage',
        partialize: (state) => ({ currentWorkspace: state.currentWorkspace }),
      }
    )
  )
);