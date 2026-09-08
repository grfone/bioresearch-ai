// pages/removePaperRegression.test.tsx
//
// End-to-end regression test for the corpus divergence bug
// (reported 2026-09-02): the user reported that removing
// papers on the Workspace page did not persist, and the next
// ``fetchWorkspace`` silently resurrected the original
// corpus. Symptom: "INTERMEDIATE: [P1..P4], Generate, FINAL
// report: [P1..P20]".
//
// Root cause (fixed 2026-09-08): the Workspace page bound
// ``useWorkspaceStore.removePaper`` (a local-only Zustand
// filter) instead of calling the backend's
// ``DELETE /workspaces/{id}/papers/{paper_id}``. The fix
// wires ``useWorkspace.removePaper`` (server-authoritative)
// through the hook.
//
// These tests pin the new contract:
//
//   1. Every paper removal round-trips through the backend.
//      There is NO local-only removal action left in the
//      store (the dangerous abstraction is gone).
//
//   2. The hook's ``removePaper`` calls ``api.removePaper``
//      and mirrors the canonical ``WorkspaceResponse`` into
//      the store via ``setCurrentWorkspace``.
//
//   3. The user's exact reproduction (20 papers → remove 16
//      → corpus stays at the 4 surviving papers) holds
//      end-to-end: every removal hits the backend, the
//      store mirrors the canonical response, and a
//      subsequent ``fetchWorkspace`` returns the same 4
//      papers -- not the original 20.
//
//   4. Combined add + remove scenario (20 - 3 + 2 = 19 with
//      exact identities) also holds.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// Shared hoisted mocks so the vi.mock factories (which Vitest
// hoists above imports) and the per-test assertions reach the
// same instances.
const {
  mockGetWorkspace,
  mockRemovePaperApi,
  mockAddPaperApi,
  mockSetCurrentWorkspace,
  mockCurrentWorkspaceState,
} = vi.hoisted(() => {
  const setCurrentWorkspace = vi.fn();
  const currentWorkspaceState = {
    setCurrentWorkspace,
    currentWorkspace: null as null | ReturnType<typeof makeWorkspace>,
  };
  return {
    mockGetWorkspace: vi.fn(),
    mockRemovePaperApi: vi.fn(),
    mockAddPaperApi: vi.fn(),
    mockSetCurrentWorkspace: setCurrentWorkspace,
    mockCurrentWorkspaceState: currentWorkspaceState,
  };
});

// ``api.client`` mock -- we only need getWorkspace and the
// removePaper / addPaper methods. We use them as bare spies so
// each test can configure them via ``mockImplementation``.
vi.mock('../api/client', () => ({
  api: {
    getWorkspace: (...args: unknown[]) => mockGetWorkspace(...args),
    removePaper: (...args: unknown[]) => mockRemovePaperApi(...args),
    addPaper: (...args: unknown[]) => mockAddPaperApi(...args),
  },
}));

// Store mock -- we only need ``currentWorkspace`` (for the
// hook's reading) and ``setCurrentWorkspace`` (for the hook's
// writing after a backend round-trip).
//
// The real ``useWorkspaceStore`` is a Zustand hook that can
// be called with or without a selector:
//   - ``useWorkspaceStore()`` -> the full state
//   - ``useWorkspaceStore(selector)`` -> a slice
//
// ``useWorkspace.ts`` calls it WITHOUT a selector and
// destructures the fields it needs. Our other tests (and the
// component tests) call it WITH a selector. Both forms
// need to work.
vi.mock('../state/workspaceStore', () => ({
  useWorkspaceStore: (selector?: (state: any) => any) =>
    selector ? selector(mockCurrentWorkspaceState) : mockCurrentWorkspaceState,
}));

// -- Helpers ---------------------------------------------------------------

function makePaper(pmid: string): {
  pmid: string;
  doi: string | null;
  title: string;
} {
  return { pmid, doi: null, title: `Paper ${pmid}` };
}

const TWENTY_PAPERS = Array.from({ length: 20 }, (_, i) =>
  makePaper(String(10000000 + i)),
);

function makeWorkspace(overrides?: { papers?: ReturnType<typeof makePaper>[] }) {
  const papers = overrides?.papers ?? TWENTY_PAPERS;
  return {
    workspace_id: 'ws-regression',
    question: 'biomarkers',
    state: 'INTERMEDIATE',
    status: 'INTERMEDIATE',
    progress: 0,
    last_error: null,
    last_error_at: null,
    papers,
    total_papers: papers.length,
    summary: null,
    report_available: false,
    published_report_available: false,
    allowed_actions: [
      'add_paper',
      'back_to_home',
      'generate',
      'remove_paper',
    ],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    paper_sources: {},
  };
}

// -- Tests -----------------------------------------------------------------

describe('removePaper regression — corpus invariant (2026-09-08)', () => {
  beforeEach(() => {
    mockGetWorkspace.mockReset();
    mockRemovePaperApi.mockReset();
    mockAddPaperApi.mockReset();
    mockSetCurrentWorkspace.mockReset();
    mockCurrentWorkspaceState.currentWorkspace = null;
  });

  it('contract: the store no longer exposes the local-only corpus mutations', async () => {
    // The dangerous abstraction is gone. If a future
    // refactor re-adds ``removePaper`` / ``clearPapers`` /
    // ``addPapersToCurrent`` to the store, this test fails.
    //
    // We import the REAL store (not the per-test mock at
    // the top of the file) so a mock that hides the
    // regression can't fool this assertion.
    const mod = await vi.importActual<typeof import('../state/workspaceStore')>(
      '../state/workspaceStore',
    );
    const keys = Object.keys(mod.useWorkspaceStore.getState());
    expect(keys).not.toContain('removePaper');
    expect(keys).not.toContain('clearPapers');
    expect(keys).not.toContain('addPapersToCurrent');
    // The surviving actions are still present.
    expect(keys).toEqual(
      expect.arrayContaining([
        'currentWorkspace',
        'setCurrentWorkspace',
        'updateCurrentWorkspace',
        'clearCurrentWorkspace',
        'setSummary',
        'setReportAvailable',
      ]),
    );
  });

  it('contract: useWorkspace.removePaper calls api.removePaper (round-trip, not local-only)', async () => {
    // Set up the in-test backend: 20 papers initially.
    let backendCorpus = TWENTY_PAPERS.slice();
    mockGetWorkspace.mockResolvedValue(
      makeWorkspace({ papers: backendCorpus.slice() }),
    );
    mockRemovePaperApi.mockImplementation(
      async (_workspaceId: string, paperId: string) => {
        backendCorpus = backendCorpus.filter(
          (p) => p.pmid !== paperId,
        );
        return makeWorkspace({ papers: backendCorpus.slice() });
      },
    );
    mockCurrentWorkspaceState.currentWorkspace = makeWorkspace({
      papers: backendCorpus.slice(),
    });

    // Render the hook in isolation. ``renderHook`` mounts the
    // hook once; ``autoFetch: true`` (the default) will fire
    // a ``fetchWorkspace`` on mount, which mirrors the
    // initial 20-paper workspace into the store.
    const { useWorkspace } = await import('../hooks/useWorkspace');
    const { result } = renderHook(() => useWorkspace('ws-regression'));

    // Wait for the auto-fetch to settle. We don't know the
    // exact call count up front because the hook also
    // records the workspace id on every successful fetch --
    // the simpler check is "did ``setCurrentWorkspace`` get
    // called at least once with 20 papers?"
    await act(async () => {
      await result.current.fetchWorkspace('ws-regression');
    });

    // Reset the mock so we can count the removal's calls
    // cleanly.
    mockSetCurrentWorkspace.mockClear();

    // Remove the first paper.
    await act(async () => {
      await result.current.removePaper(TWENTY_PAPERS[0].pmid);
    });

    // The contract: the API was actually called with the
    // right workspace id and the paper's PMID. NO local-only
    // mutation could have produced this observable.
    expect(mockRemovePaperApi).toHaveBeenCalledWith(
      'ws-regression',
      TWENTY_PAPERS[0].pmid,
    );
    expect(mockRemovePaperApi).toHaveBeenCalledTimes(1);

    // And the canonical response was mirrored into the
    // store via ``setCurrentWorkspace``.
    expect(mockSetCurrentWorkspace).toHaveBeenCalledTimes(1);
    const lastCallArgs =
      mockSetCurrentWorkspace.mock.calls[
        mockSetCurrentWorkspace.mock.calls.length - 1
      ];
    expect(lastCallArgs[0].papers).toHaveLength(19);

    // Most importantly: the backend corpus shrank by
    // exactly 1, the same as the store. They cannot diverge
    // (the store is just a mirror of the response).
    expect(backendCorpus).toHaveLength(19);
  });

  it('reproduction: 20 → remove 16 → corpus is exactly the 4 surviving papers (by PMID identity)', async () => {
    // Reproduces the user's exact reproduction:
    //   1. Start with 20 papers [P1..P20].
    //   2. Remove 16 of them (keeps P1..P4).
    //   3. The persisted corpus is exactly 4 papers.
    //   4. A subsequent ``fetchWorkspace`` returns the
    //      same 4 -- never the original 20.
    let backendCorpus = TWENTY_PAPERS.slice();
    mockGetWorkspace.mockImplementation(
      async () => makeWorkspace({ papers: backendCorpus.slice() }),
    );
    mockRemovePaperApi.mockImplementation(
      async (_workspaceId: string, paperId: string) => {
        backendCorpus = backendCorpus.filter(
          (p) => p.pmid !== paperId,
        );
        return makeWorkspace({ papers: backendCorpus.slice() });
      },
    );
    mockCurrentWorkspaceState.currentWorkspace = makeWorkspace({
      papers: backendCorpus.slice(),
    });

    const { useWorkspace } = await import('../hooks/useWorkspace');
    const { result } = renderHook(() => useWorkspace('ws-regression'));

    await act(async () => {
      await result.current.fetchWorkspace('ws-regression');
    });

    // Remove 16 papers, one at a time, simulating 16
    // individual user actions on the Workspace page.
    const toRemove = TWENTY_PAPERS.slice(4); // keeps P1..P4
    for (const paper of toRemove) {
      await act(async () => {
        await result.current.removePaper(paper.pmid);
      });
    }

    // The backend saw 16 removals. None were silently
    // dropped (which is what the pre-fix local-only store
    // action would have done).
    expect(mockRemovePaperApi).toHaveBeenCalledTimes(16);
    expect(backendCorpus).toHaveLength(4);

    // A subsequent ``fetchWorkspace`` -- the "Refresh/refetch
    // workspace" step from the user's reproduction --
    // returns the same 4 papers, not the original 20.
    mockGetWorkspace.mockClear();
    const afterRefresh = await result.current.fetchWorkspace(
      'ws-regression',
    );
    // ``fetchWorkspace`` returns void; the canonical
    // response is mirrored via ``setCurrentWorkspace``.
    // The store mock records the call.
    expect(mockGetWorkspace).toHaveBeenCalledWith('ws-regression');
    const mirrored =
      mockSetCurrentWorkspace.mock.calls[
        mockSetCurrentWorkspace.mock.calls.length - 1
      ][0];
    expect(mirrored.papers).toHaveLength(4);

    // Assert the EXACT PMID identities (the user explicitly
    // asked: "Assert the actual identities/PMIDs/DOIs.").
    const surviving = mirrored.papers
      .map((p: { pmid: string }) => p.pmid)
      .sort();
    expect(surviving).toEqual(
      TWENTY_PAPERS.slice(0, 4)
        .map((p) => p.pmid)
        .sort(),
    );

    // The bug-reproduction check: no paper from the
    // original search survived the corpus change other
    // than the four we explicitly kept.
    for (const removedPaper of toRemove) {
      expect(surviving).not.toContain(removedPaper.pmid);
    }
  });

  it('reproduction: 20 → remove 3 + add 2 → corpus is exactly (original - 3) + 2 = 19 with exact identities', async () => {
    // Combined add + remove scenario from the user's
    // reproduction: after the operations the corpus must be
    // [P1..P4, P6..P9, P11..P14, P16..P20, Q1, Q2] --
    // i.e. (original - {P5, P10, P15}) + {Q1, Q2} = 19.
    let backendCorpus = TWENTY_PAPERS.slice();
    mockGetWorkspace.mockImplementation(
      async () => makeWorkspace({ papers: backendCorpus.slice() }),
    );
    mockRemovePaperApi.mockImplementation(
      async (_workspaceId: string, paperId: string) => {
        backendCorpus = backendCorpus.filter(
          (p) => p.pmid !== paperId,
        );
        return makeWorkspace({ papers: backendCorpus.slice() });
      },
    );
    mockAddPaperApi.mockImplementation(
      async (_workspaceId: string, paper: { pmid: string }) => {
        backendCorpus.push({
          pmid: paper.pmid,
          doi: null,
          title: `Added ${paper.pmid}`,
        });
        return makeWorkspace({ papers: backendCorpus.slice() });
      },
    );
    mockCurrentWorkspaceState.currentWorkspace = makeWorkspace({
      papers: backendCorpus.slice(),
    });

    const { useWorkspace } = await import('../hooks/useWorkspace');
    const { result } = renderHook(() => useWorkspace('ws-regression'));

    await act(async () => {
      await result.current.fetchWorkspace('ws-regression');
    });

    // Remove 3 specific papers.
    const removed = ['10000004', '10000009', '10000014']; // P5, P10, P15
    for (const pmid of removed) {
      await act(async () => {
        await result.current.removePaper(pmid);
      });
    }
    expect(mockRemovePaperApi).toHaveBeenCalledTimes(3);

    // Add 2 specific papers.
    const newPapers = [
      { pmid: '99900001', doi: null, title: 'Added Q1' },
      { pmid: '99900002', doi: null, title: 'Added Q2' },
    ];
    for (const paper of newPapers) {
      await act(async () => {
        await result.current.addPaper(paper);
      });
    }
    expect(mockAddPaperApi).toHaveBeenCalledTimes(2);

    // The persisted corpus is exactly (original - 3) + 2 =
    // 17 surviving originals + 2 new = 19 papers.
    expect(backendCorpus).toHaveLength(19);

    // Assert the EXACT PMID identities.
    const finalPmids = backendCorpus.map((p) => p.pmid).sort();
    const originalPmids = TWENTY_PAPERS.map((p) => p.pmid);
    const expectedSurviving = originalPmids.filter(
      (pmid) => !removed.includes(pmid),
    );

    // Every surviving original is in the corpus.
    for (const pmid of expectedSurviving) {
      expect(finalPmids).toContain(pmid);
    }
    // Every removed PMID is NOT in the corpus.
    for (const pmid of removed) {
      expect(finalPmids).not.toContain(pmid);
    }
    // Every newly added PMID is in the corpus.
    for (const paper of newPapers) {
      expect(finalPmids).toContain(paper.pmid);
    }
  });

  it('regression: 409 from the backend surfaces an error and leaves the store unchanged', async () => {
    // If the backend rejects the removal (e.g. paper not in
    // the workspace, FSM doesn't allow ``remove_paper``),
    // the hook MUST surface the error and MUST NOT mirror
    // a stale state into the store.
    mockRemovePaperApi.mockRejectedValue(
      new Error('No paper with PMID 99999 in this workspace.'),
    );
    mockGetWorkspace.mockResolvedValue(
      makeWorkspace({ papers: TWENTY_PAPERS.slice() }),
    );
    mockCurrentWorkspaceState.currentWorkspace = makeWorkspace({
      papers: TWENTY_PAPERS.slice(),
    });

    const { useWorkspace } = await import('../hooks/useWorkspace');
    const { result } = renderHook(() => useWorkspace('ws-regression'));

    await act(async () => {
      await result.current.fetchWorkspace('ws-regression');
    });

    mockSetCurrentWorkspace.mockClear();

    // Attempt the removal -- expect it to throw.
    const removePromise = result.current.removePaper('99999');
    let caught: unknown = null;
    await act(async () => {
      try {
        await removePromise;
      } catch (err) {
        caught = err;
      }
    });

    expect(caught).not.toBeNull();
    expect((caught as Error).message).toContain('No paper with PMID');

    // The store MUST NOT have been touched on failure --
    // a partial mirror would leave the UI in a state the
    // backend never confirmed.
    expect(mockSetCurrentWorkspace).not.toHaveBeenCalled();

    // And the error is surfaced on the hook's ``error``
    // field so the caller (Workspace page) can show a
    // toast.
    expect(result.current.error).not.toBeNull();
  });
});
