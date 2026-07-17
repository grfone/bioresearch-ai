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
            const existingPmids = new Set(
              state.currentWorkspace.papers.map((p) => p.pmid).filter(Boolean)
            );
            const newPapers = papers.filter(
              (p) => !p.pmid || !existingPmids.has(p.pmid)
            );
            if (newPapers.length === 0) return state;
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                papers: [...state.currentWorkspace.papers, ...newPapers],
                total_papers: state.currentWorkspace.total_papers + newPapers.length,
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