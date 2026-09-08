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

interface WorkspaceStore {
  currentWorkspace: WorkspaceResponse | null;
  setCurrentWorkspace: (workspace: WorkspaceResponse) => void;
  updateCurrentWorkspace: (updates: Partial<WorkspaceResponse>) => void;
  clearCurrentWorkspace: () => void;
  // ``setSummary`` and ``setReportAvailable`` are local
  // metadata toggles that mirror fields already present on
  // ``WorkspaceResponse``. They are intentionally NOT
  // corpus mutations (they don't touch ``papers``) and are
  // safe to use without a backend round-trip because they
  // only flip cached flags. The previous commit (2026-09-08)
  // removed the dangerous corpus mutations
  // (``addPapersToCurrent``, ``removePaper``, ``clearPapers``)
  // but kept these two. See the store-action comments
  // below for the full rationale.
  setSummary: (summary: string) => void;
  setReportAvailable: (available: boolean) => void;
  // NOTE: ``addPapersToCurrent``, ``removePaper``, and
  // ``clearPapers`` were removed on 2026-09-08.
  //
  // They were local-only Zustand mutations that updated
  // ``currentWorkspace.papers`` without ever calling the
  // backend, so any subsequent ``fetchWorkspace`` (e.g.
  // navigating to the Report page, returning to Workspace,
  // any 409 retry) would silently resurrect the original
  // corpus. That divergence was the root cause of the
  // "INTERMEDIATE: [P1..P4], Generate, FINAL report:
  // [P1..P20]" bug.
  //
  // The persisted workspace is the single authoritative
  // corpus. Corpus mutations MUST go through the
  // ``useWorkspace`` hook (which calls ``api.removePaper`` /
  // ``api.addPaper`` and mirrors the canonical
  // ``WorkspaceResponse`` back into this store via
  // ``setCurrentWorkspace``). There is no longer any
  // independent local-only path that can diverge from the
  // backend.
}



/**
 * Compute the deduplication identity for a paper.
 *
 * Mirrors the backend's ``_paper_identity`` in
 * ``app/domain/entities/research_session.py``:
 *
 *   - PMID (preferred): unique across publishers.
 *   - DOI (fallback): unique per article, but may be missing
 *     for some preprints and conference papers.
 *   - Normalized title (last resort): lowercased and
 *     whitespace-collapsed. Less unique (two papers can
 *     share a title) but better than nothing.
 *
 * Returns ``null`` when the paper has no identity we can
 * track (no PMID, no DOI, no title). The dedup caller
 * decides what to do with unidentifiable papers (currently:
 * pass them through to avoid silent data loss).
 *
 * NOTE: ``paperIdentity``, ``paperStrongIdentities``, and
 * ``nextAllowedActions`` were removed on 2026-09-08 along
 * with the local-only ``addPapersToCurrent`` action. The
 * helpers existed solely to support that local-only path.
 * Server-authoritative ``addPaper`` / ``addPapersBulk`` on
 * the ``useWorkspace`` hook now relies on the backend's
 * dedup (which uses the same three-tier identity); the
 * frontend dedup helpers are dead code. If they are ever
 * reintroduced (e.g. for an optimistic-with-rollback
 * pattern), they should live in a pure-function module so
 * they're not coupled to a store-mutation action.
 */

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

        // ``addPapersToCurrent`` was REMOVED on 2026-09-08.
        //
        // The previous implementation was a local-only Zustand
        // mutation that mirrored the backend's three-tier
        // dedup (``_paper_identity``: PMID > DOI > title) but
        // never made an HTTP call. The dedup helper logic was
        // correct in isolation, but the action was dangerous:
        // any subsequent ``fetchWorkspace`` would replace the
        // local optimistic list with the backend's persisted
        // list and the user's additions would silently
        // disappear.
        //
        // Per the user's directive ("there is exactly one
        // authoritative corpus: the persisted workspace's
        // papers"), paper additions now go exclusively
        // through the ``useWorkspace`` hook's ``addPaper`` /
        // ``addPapersBulk`` paths, which call
        // ``POST /workspaces/{id}/papers`` and mirror the
        // canonical ``WorkspaceResponse`` back into this
        // store. There is no longer a local-only add path.
        //
        // The ``paperIdentity`` / ``paperStrongIdentities``
        // helpers and their dedup logic were removed with
        // it; if they are ever needed again (for an
        // optimistic-only flow that gets rolled back on
        // failure), they should be re-extracted into a
        // pure function module, not coupled to a
        // store-mutation action.

        // ``removePaper`` was REMOVED on 2026-09-08.
        //
        // It was a local-only Zustand filter that updated
        // ``currentWorkspace.papers`` without ever calling
        // ``DELETE /workspaces/{id}/papers/{paper_id}``.
        // This was the root cause of the "INTERMEDIATE:
        // [P1..P4], Generate, FINAL report: [P1..P20]" bug:
        // the backend kept all 20 papers, the local store
        // showed 4 optimistically, and the next
        // ``fetchWorkspace`` silently resurrected the
        // original corpus. Use the ``useWorkspace`` hook's
        // ``removePaper`` (server-authoritative) instead.

        // ``clearPapers`` was REMOVED on 2026-09-08 for the
        // same reason as ``removePaper``: it was a
        // local-only Zustand mutation that the next
        // ``fetchWorkspace`` would silently overwrite. The
        // corresponding ``handleClearPapers`` button was
        // already disabled in an earlier refactor; the
        // action stayed behind as a footgun. Removing it
        // here closes the gap. If a "Clear All Papers"
        // affordance is needed in the future it MUST go
        // through a new backend endpoint and a matching
        // server-authoritative hook action.

        setSummary: (summary: string) =>
          set((state) => {
            if (!state.currentWorkspace) return state;
            return {
              currentWorkspace: {
                ...state.currentWorkspace,
                summary,
              },
            };
          }),

        setReportAvailable: (available: boolean) =>
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