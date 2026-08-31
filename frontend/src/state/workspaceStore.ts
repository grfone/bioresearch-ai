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
 */
function paperIdentity(paper: Paper): string | null {
  if (paper.pmid) return `pmid:${paper.pmid}`;
  if (paper.doi) return `doi:${paper.doi}`;
  // ``title`` is required on the Paper interface, but
  // backend payloads in the wild sometimes omit it (e.g. when
  // the resolver falls back to a stub record). Defensively
  // guard against undefined.
  const title = paper.title?.trim().toLowerCase();
  if (title) return `title:${title}`;
  return null;
}

/**
 * Return the set of "strong" identity signals for a paper.
 *
 * A strong signal is PMID or DOI -- both are unique per
 * article across publishers. Title is NOT a strong signal:
 * two genuinely different papers can share a title (e.g.
 * "Letter to the Editor" or a generic preprint title), and
 * even when unique, a typo in one source's title would
 * silently break dedup. We only use title as a tiebreaker
 * when no PMID/DOI is available.
 *
 * Why this exists separately from ``paperIdentity``:
 * ----------------------------------------------------------
 * The simple single-identity dedup missed the cross-identity
 * case where paper A has both PMID and DOI, and paper B
 * has only the DOI -- their single canonical keys
 * (``pmid:12345`` vs ``doi:10.1/x``) didn't match, but they
 * ARE the same paper. The fix is multi-identity dedup, but
 * with a critical asymmetry: title is allowed to be a
 * *primary* identity (when nothing else is available) but
 * NOT a *cross-match* signal.
 *
 * The dedup logic is: paper B is a duplicate of paper A if
 * B's primary identity matches ANY of A's strong identities.
 * Title is only checked as a primary identity (i.e. for
 * papers with no PMID and no DOI).
 */
function paperStrongIdentities(paper: Paper): string[] {
  const ids: string[] = [];
  if (paper.pmid) ids.push(`pmid:${paper.pmid}`);
  if (paper.doi) ids.push(`doi:${paper.doi}`);
  return ids;
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
  | 'generate'
  | 'retry'
  | 'add_paper'
  | 'remove_paper'
  | 'back_to_workspace'
  | 'back_to_home'
> {
  switch (state) {
    case 'INITIAL':
      return ['add_paper', 'search'];
    case 'INTERMEDIATE':
      return [
        'add_paper',
        'back_to_home',
        'generate',
        'remove_paper',
      ];
    case 'FINAL':
      return totalPapers > 0
        ? ['back_to_workspace', 'remove_paper']
        : ['back_to_workspace'];
    case 'ERROR':
      return ['add_paper', 'remove_paper', 'retry'];
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
            // Deduplicate by PMID, DOI, or title -- mirrors the
            // backend's ``_paper_identity`` (see
            // ``app/domain/entities/research_session.py``).
            //
            // Why all three?
            // --------------
            // The original implementation only deduplicated
            // by PMID. Papers without a PMID (Springer book
            // chapters, arXiv preprints, conference papers)
            // would silently duplicate when added twice. A
            // user could add ``10.1007/978-...-..._17`` once,
            // see the paper in the workspace, add the same
            // DOI again, and end up with TWO identical
            // cards in the workspace. The backend's
            // dedup correctly handles this (it dedupes by
            // PMID, DOI, or title in ``_paper_identity``)
            // but the frontend was silently undoing the
            // backend's dedup by appending
            // ``response.papers`` (the full workspace list,
            // which always contains the existing paper)
            // without checking.
            //
            // We now mirror the backend's three-tier
            // identity: PMID preferred, DOI fallback,
            // normalized title last resort. A paper is a
            // duplicate if ANY of these collide with an
            // existing paper's identity.
            //
            // Two-tier dedup:
            //   1. STRONG identities (PMID, DOI) for every
            //      existing paper. A new paper is a duplicate
            //      if its *primary* identity (PMID > DOI >
            //      title) appears in this set.
            //   2. Title-based dedup is implicit because
            //      ``paperIdentity`` returns ``title:X`` as
            //      the primary identity when PMID/DOI are
            //      absent. We add those title-only papers to
            //      the strong set too (the title key
            //      ``title:X`` only collides with itself,
            //      never with a PMID/DOI key).
            //
            // Why not include title in the strong set for
            // papers that ALSO have PMID/DOI? Two papers can
            // legitimately share a title (e.g. multiple
            // "Letter to the Editor" replies, or a
            // conference proceeding with a generic title).
            // Title is a *weak* signal: it's only useful when
            // it's the *only* signal (i.e. for preprint
            // stubs the resolver couldn't enrich).
            //
            // The cross-identity case (paper A has PMID,
            // paper B has same DOI but no PMID) is handled
            // because A's ``paperStrongIdentities`` includes
            // ``doi:...`` and B's primary is ``doi:...``.
            const existingIds = new Set<string>();
            for (const existing of state.currentWorkspace.papers) {
              for (const id of paperStrongIdentities(existing)) {
                existingIds.add(id);
              }
              // Also include the primary identity (which
              // falls back to title when no PMID/DOI). This
              // makes title-only papers dedup against each
              // other but NOT against PMID/DOI-bearing
              // papers.
              const primary = paperIdentity(existing);
              if (primary !== null) existingIds.add(primary);
            }
            const newPapers: typeof papers = [];
            const seenInBatch = new Set<string>();
            for (const p of papers) {
              const strong = paperStrongIdentities(p);
              const primary = paperIdentity(p);
              if (strong.length === 0 && primary === null) {
                // Paper has no identity at all (no PMID,
                // no DOI, no title). The backend will
                // accept it but the frontend can't dedup;
                // push it through so we don't silently
                // drop user input. This is rare in
                // practice (every paper should have at
                // least a DOI or a title) but we handle
                // it gracefully.
                newPapers.push(p);
                continue;
              }
              // Check if the new paper's primary
              // identity matches any existing one.
              const primaryKey = primary ?? '';
              if (primaryKey !== '' && existingIds.has(primaryKey)) {
                continue;
              }
              if (primaryKey !== '' && seenInBatch.has(primaryKey)) {
                continue;
              }
              // Also check if any of the new paper's
              // strong identities collide with an existing
              // one. This catches the cross-identity
              // case: paper A has both PMID and DOI, paper
              // B has only the same DOI; A's primary is
              // ``pmid:...`` but A's strong set includes
              // ``doi:...`` which equals B's primary.
              let crossMatch = false;
              for (const id of strong) {
                if (existingIds.has(id) || seenInBatch.has(id)) {
                  crossMatch = true;
                  break;
                }
              }
              if (crossMatch) continue;
              // Add this paper's identities to the seen
              // sets so subsequent papers in the same
              // batch are deduped against it.
              if (primaryKey !== '') seenInBatch.add(primaryKey);
              for (const id of strong) seenInBatch.add(id);
              // Also add existing-side cache for the
              // cross-match on subsequent iterations.
              if (primaryKey !== '') {
                for (const id of strong) {
                  if (id !== primaryKey) existingIds.add(id);
                }
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
              prevState === 'INITIAL' ? 'INTERMEDIATE' : prevState;
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