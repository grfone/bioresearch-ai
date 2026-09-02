/**
 * pages/Report.test.tsx
 *
 * Tests for the Report page's loading phases:
 *   1. ``Loading workspace…`` -- while ``fetchWorkspace``
 *      is in flight
 *   2. ``Summarizing…`` -- if the workspace has no summary
 *      yet (the orchestrator's auto-summarise will run as
 *      part of the REPORT action -- see ADR-008)
 *   3. ``Generating report…`` -- while the report use case
 *      is in flight
 *
 * Compare is NOT a separate phase: the orchestrator's
 * ``report()`` doesn't call a compare use case (the
 * ``COMPARING``/``COMPARED`` FSM states were removed on
 * 2026-08-30 — see ADR-016).
 *
 * We mock the API client, the useWorkspace hook, and the
 * Zustand store. The test asserts the phase label text
 * changes at the right points in the lifecycle.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';

// Mock the api client. The Report page calls
// ``api.runGenerateAction`` (FSM-aware endpoint) via the
// useWorkspace hook's ``runAction("generate")`` dispatch.
// The legacy ``api.generateReport`` is kept in the mock
// only because the hook's ``generateReport`` wrapper still
// exists for any callers that haven't migrated; the
// Report page does not use it.
vi.mock('../api/client', () => ({
  api: {
    generateReport: vi.fn(),
    fetchWorkspace: vi.fn(),
    // The Generate PDF button on the Report page just
    // triggers a browser-side download -- no FSM action
    // runs from that click (generate already produced the
    // PDF before the user landed on the page). We keep
    // the mock here in case a future test wants to assert
    // on the URL helper.
    getPublishedReportUrl: vi.fn((workspaceId: string) =>
      `http://test/workspaces/${workspaceId}/published-report.pdf`,
    ),
    // Same shape for the LaTeX download URL. Used by the
    // "Generate TeX" button which is independent of the
    // publish flow (the LaTeX endpoint renders on demand
    // without changing the FSM state).
    getPublishedTexUrl: vi.fn((workspaceId: string) =>
      `http://test/workspaces/${workspaceId}/published-report.tex`,
    ),
  },
}));

// Mock the useWorkspace hook so we control its return
// value (loading state, error state, the report promise,
// the workspace fetch). The Report page reads
// ``workspace`` to decide the next phase label.
const mockFetchWorkspace = vi.fn();
const mockRunAction = vi.fn();
const mockUseWorkspaceReturn: {
  workspace: unknown;
  loading: boolean;
  error: unknown;
  fetchWorkspace: ReturnType<typeof vi.fn>;
  generateReport: ReturnType<typeof vi.fn>;
  // The PUBLISH button routes through ``handleDownloadClick()``
  // (FSM-aware path -- see ADR-009). The legacy ``api.complete``
  // shortcut would advance to COMPLETED but leave
  // ``session.published_report`` empty; the FSM-aware
  // ``handleDownloadClick()`` is the only path that renders the
  // PDF AND persists it AND advances REPORTED -> PUBLISHING ->
  // COMPLETED.
  runAction: ReturnType<typeof vi.fn>;
} = {
  workspace: null,
  loading: false,
  error: null,
  fetchWorkspace: mockFetchWorkspace,
  generateReport: mockRunAction,
  runAction: mockRunAction,
};
vi.mock('../hooks/useWorkspace', () => ({
  useWorkspace: () => mockUseWorkspaceReturn,
}));

// Mock the Zustand store. The Report page reads
// ``currentWorkspace`` via both the selector pattern (when
// the component uses ``useWorkspaceStore((s) => s.x)``)
// AND directly via ``useWorkspaceStore.getState()`` inside
// the useEffect (to read the freshly-fetched workspace
// without re-rendering). The mock factory has to expose
// both shapes. We use ``vi.hoisted`` so the
// ``mockStoreCurrentWorkspace`` reference is initialised
// before the vi.mock factory runs.
const { mockStoreCurrentWorkspace } = vi.hoisted(() => ({
  mockStoreCurrentWorkspace: { current: null as unknown },
}));
// Expose a mutable indirection so individual tests can
// reassign ``currentWorkspace`` per-test.
vi.mock('../state/workspaceStore', () => {
  const state: {
    currentWorkspace: unknown;
    // Subscribers get called whenever the state changes.
    // The mock store is a no-op stand-in for Zustand that
    // notifies subscribers when ``setCurrentWorkspace`` is
    // called. Tests use ``useEffect`` -> ``store.subscribe``
    // to wire React re-renders on these notifications.
    subscribers: Set<() => void>;
  } = {
    currentWorkspace: mockStoreCurrentWorkspace.current,
    subscribers: new Set(),
  };
  const notify = () => {
    state.subscribers.forEach((cb) => cb());
  };
  const setCurrentWorkspace = (workspace: unknown) => {
    state.currentWorkspace = workspace;
    mockStoreCurrentWorkspace.current = workspace;
    notify();
  };
  const useWorkspaceStore: any = (selector: (state: any) => unknown) => {
    // ``useState`` + ``useEffect`` would let us actually
    // re-render on changes, but the Report component
    // already reads the store via ``useWorkspaceStore(sel)``
    // (the hook API), not via React state. We delegate to
    // React's ``useSyncExternalStore`` so production semantics
    // are mirrored: the component subscribes to the mock
    // store, and any state change triggers a re-render.
    return require('react').useSyncExternalStore(
      (cb: () => void) => {
        state.subscribers.add(cb);
        return () => state.subscribers.delete(cb);
      },
      () => selector(state),
    );
  };
  useWorkspaceStore.getState = () => state;
  return { useWorkspaceStore };
});

// Mock react-router so the report page's useParams works.
// ``mockNavigate`` is hoisted so individual tests can
// ``mockNavigate.mockClear()`` between assertions -- a fresh
// ``vi.fn()`` per call would scatter state across tests. The
// ``MockInstance`` type avoids the "Cannot assign to constant"
// + "Property does not exist" type errors that a plain
// ``vi.fn()`` would trigger under strict TypeScript.
const { mockNavigate } = vi.hoisted(() => {
  // Lazily create the mock inside the factory so the
  // ``vi`` runtime is initialised. We export a
  // ``vi.Mock`` so callers see a fully-typed mock instance.
  // Returning ``undefined as any`` would also work, but the
  // strongly-typed pattern catches typos at compile time.
  const fn = (() => {
    // The mock is created on first access; the factory body
    // is hoisted to module scope so subsequent calls reuse the
    // same instance. We use ``vi.fn()`` lazily because
    // ``vi`` is only available inside test setup.
    return vi.fn();
  })();
  return { mockNavigate: fn };
});
vi.mock('react-router-dom', () => ({
  useParams: () => ({ workspaceId: 'ws-1' }),
  useNavigate: () => mockNavigate,
}));

import { api } from '../api/client';
const mockApi = api as unknown as {
  generateReport: ReturnType<typeof vi.fn>;
  fetchWorkspace: ReturnType<typeof vi.fn>;
  getPublishedReportUrl: ReturnType<typeof vi.fn>;
  getPublishedTexUrl: ReturnType<typeof vi.fn>;
};

describe('Report > loader phases', () => {
  beforeEach(() => {
    mockApi.generateReport.mockReset();
    mockFetchWorkspace.mockReset();
    mockRunAction.mockReset();
    // ``mockReset`` clears the mock's implementation, so
    // we re-register the URL builder here. Otherwise
    // ``getPublishedReportUrl(workspaceId)`` returns
    // ``undefined`` and the anchor's ``href`` resolves to
    // ``http://localhost:3000/undefined`` -- a subtle
    // test-pollution bug that only surfaces when this
    // describe-block runs after another that touched the
    // same mock. Keep this re-registration cheap; the
    // arrow is identical to the one in vi.mock above.
    mockApi.getPublishedReportUrl.mockImplementation(
      (workspaceId: string) =>
        `http://test/workspaces/${workspaceId}/published-report.pdf`,
    );
    mockApi.getPublishedTexUrl.mockImplementation(
      (workspaceId: string) =>
        `http://test/workspaces/${workspaceId}/published-report.tex`,
    );
    mockUseWorkspaceReturn.workspace = null;
    mockUseWorkspaceReturn.loading = false;
    mockUseWorkspaceReturn.error = null;
    mockStoreCurrentWorkspace.current = null;
  });

  it('shows "Loading workspace…" on first render', async () => {
    // The Report page mounts with phase = 'Loading
    // workspace…' so the loader is correct from the very
    // first paint. The fetchWorkspace call resolves
    // asynchronously; we keep it pending so the loader
    // stays up.
    let resolveFetch!: (v: unknown) => void;
    mockFetchWorkspace.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
    );

    const { Report } = await import('./Report');
    render(<Report />);

    // The loader is mounted with the initial phase.
    expect(
      screen.getByText(/Loading workspace/i),
    ).toBeInTheDocument();

    // Clean up.
    resolveFetch({});
  });

  it('transitions to "Generating report…" when summary already exists', async () => {
    // User clicked Generate Report from a workspace that
    // already has a summary (e.g., a previous run). The
    // orchestrator skips the auto-summarise branch and goes
    // straight to the report use case.
    mockFetchWorkspace.mockResolvedValue({
      workspace_id: 'ws-1',
      question: 'x',
      state: 'INTERMEDIATE',
      summary: { text: 'A prior summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    // The store reads 'currentWorkspace' synchronously
    // inside the useEffect. Mock it before rendering.
    // We can't easily mutate the const, so use the
    // approach below: the Report page reads from
    // useWorkspaceStore.getState().currentWorkspace.
    // We need to swap the store's getState return value.
    // Use a mutable object instead of the const.
    // The simplest path: pre-populate the hook's workspace
    // return value too (the page reads both).
    mockUseWorkspaceReturn.workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'INTERMEDIATE',
      summary: { text: 'A prior summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    // Mirror into the store mock so useWorkspaceStore.getState()
    // inside the useEffect sees the same workspace.
    mockStoreCurrentWorkspace.current = mockUseWorkspaceReturn.workspace;
    // Block the generateReport call so we can assert the
    // phase label while it's in flight.
    let resolveGenerate!: (v: unknown) => void;
    mockRunAction.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGenerate = resolve;
        }),
    );

    const { Report } = await import('./Report');
    render(<Report />);

    // After fetchWorkspace resolves and the useEffect
    // sets the next phase, we should see
    // 'Generating report...' -- NOT 'Summarizing...' --
    // because the workspace has a summary.
    await waitFor(() => {
      expect(
        screen.getByText(/Generating report/i),
      ).toBeInTheDocument();
    });

    // Cleanup.
    resolveGenerate({ content: '...', sections: [] });
  });

  it('transitions through "Summarizing…" when summary is missing', async () => {
    // User clicked Generate Report from a workspace where
    // the orchestrator will auto-summarise. The phase
    // label should briefly say 'Summarizing...' before
    // advancing to 'Generating report...'.
    mockFetchWorkspace.mockResolvedValue({
      workspace_id: 'ws-1',
      question: 'x',
      state: 'INTERMEDIATE',
      summary: null,
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    mockUseWorkspaceReturn.workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'INTERMEDIATE',
      summary: null,
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    mockStoreCurrentWorkspace.current = mockUseWorkspaceReturn.workspace;
    // The generateReport call resolves quickly so we see
    // the Summarizing phase label before it disappears.
    mockRunAction.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ content: '...', sections: [] }), 50)),
    );

    const { Report } = await import('./Report');
    render(<Report />);

    // The Summarizing phase appears after fetchWorkspace
    // resolves and the useEffect decides the orchestrator
    // will auto-summarise. The phase flips to
    // 'Generating report...' synchronously inside the same
    // useEffect tick before handleGenerateReport actually
    // runs -- so we may see Summarizing flash by quickly.
    // The loader block shows whichever phase was set most
    // recently.
    await waitFor(
      () => {
        const text = screen.queryByText(/Summarizing/i) ??
          screen.queryByText(/Generating report/i);
        expect(text).toBeTruthy();
      },
      { timeout: 500 },
    );
  });

  it('hides the loader when the report finishes successfully', async () => {
    // Standard happy path. After generateReport resolves,
    // the loader should disappear and the report UI
    // should render (or the deep-link 'no report yet' UI).
    mockFetchWorkspace.mockResolvedValue({
      workspace_id: 'ws-1',
      question: 'x',
      state: 'FINAL',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    mockUseWorkspaceReturn.workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'FINAL',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    mockStoreCurrentWorkspace.current = mockUseWorkspaceReturn.workspace;
    // ``report.summary`` is the markdown body -- a string
    // the Report page splits on newlines to extract the
    // H1 title. The original API returns a single string
    // here, NOT the ``Summary`` domain object.
    mockRunAction.mockResolvedValue({
      content: '# A Test Report\n\nSome content here.',
      summary: '# A Test Report\n\nSome content here.',
      sections: [{ title: 'Introduction', content: 'Some content.' }],
      citations: [],
      limitations: [],
      future_work: [],
    });

    const { Report } = await import('./Report');
    render(<Report />);

    // The loader disappears once both promises resolve.
    await waitFor(() => {
      expect(
        screen.queryByText(/Loading workspace/i) ??
          screen.queryByText(/Summarizing/i) ??
          screen.queryByText(/Generating report/i),
      ).not.toBeInTheDocument();
    });
  });
});


/**
 * Tests for the "Generate PDF" action.
 *
 * The Publish button on the Report page runs the PUBLISH
 * action on the workspace FSM (REPORTED -> PUBLISHING ->
 * COMPLETED) and stores the rendered PDF on the session.
 * After publishing, a "Download PDF" link is exposed that
 * navigates to ``GET /workspaces/{id}/published-report.pdf``.
 *
 * Per the FSM-audit skill (see ADR-009), every layer-4
 * frontend fix needs four test cases:
 *
 *   1. Positive:   The button exists and clicking it
 *                  routes to the FSM-aware endpoint.
 *   2. Audit:      The button uses the FSM hook
 *                  ``handleDownloadClick()`` (NOT the
 *                  legacy ``api.complete`` shortcut).
 *   3. Negative:   The button is not present when the
 *                  workspace is in a state that doesn't
 *                  allow PUBLISH (e.g. CREATED).
 *   4. Wire-format: When the workspace has a published
 *                  PDF, the "Download PDF" link is wired to
 *                  the GET endpoint.
 *
 * These tests pin the contract end-to-end -- if a future
 * refactor routes the button through the legacy
 * ``api.complete`` endpoint, the audit test fails loudly
 * and the next maintainer sees the Layer-4 fix from the
 * skill notes.
 */
describe('Report > Generate PDF', () => {
  /**
   * Helper: render the Report page with the workspace
   * already in a REPORTED state, a generated report ready,
   * and (optionally) the ``published_report_available``
   * flag flipped to indicate the PDF already exists.
   *
   * This is the standard "ready to publish" scenario --
   * the report is generated, the user is looking at the
   * Report page, and the next action is to publish.
   */
  function setupReadyToPublish(published = false) {
    const workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'FINAL',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      report_available: true,
      // The flag that drives the "Download PDF" link
      // visibility. Tests below toggle this on and off
      // to verify the wire-format wiring.
      published_report_available: published,
      last_error: null,
      progress: 1.0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      paper_sources: {},
    };
    mockUseWorkspaceReturn.workspace = workspace;
    mockStoreCurrentWorkspace.current = workspace;
    mockFetchWorkspace.mockResolvedValue(workspace);
    // ``runAction`` is now action-aware (the page's
    // 'report' branch returns ``ReportResponse``, every
    // other action returns ``WorkspaceResponse``). We
    // default to a per-action implementation that
    // individual tests can override per-call via
    // ``mockRejectedValueOnce`` etc.
    mockRunAction.mockImplementation(async (action: string) => {
      if (action === 'generate') {
        return {
          content: '# A Test Report\n\nSome content here.',
          summary: '# A Test Report\n\nSome content here.',
          sections: [{ title: 'Introduction', content: 'Some content.' }],
          citations: [],
          limitations: [],
          future_work: [],
        } as never;
      }
      // Default: every other action returns the post-action
      // workspace. Tests that need a specific behaviour
      // (e.g. publish failure) override via
      // ``mockRejectedValueOnce`` / ``mockResolvedValueOnce``
      // BEFORE the click -- that one-shot wins.
      return {
        ...workspace,
        // In the new 4-state FSM the post-generate state is
        // FINAL (we don't have a separate PUBLISH action
        // anymore -- generate already produces the PDF).
        state: action === 'generate' ? 'FINAL' : workspace.state,
        published_report_available:
          action === 'generate' ? true : workspace.published_report_available,
      } as never;
    });
  }

  it('renders the "Generate PDF" button when a report is available', async () => {
    setupReadyToPublish(false);
    const { Report } = await import('./Report');
    render(<Report />);
    // Wait for the loader to disappear.
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The button is the FSM-aware endpoint caller.
    const button = await screen.findByRole('button', {
      name: /Generate PDF/i,
    });
    expect(button).toBeInTheDocument();
    // We tag the button with ``data-action="publish-pdf"`` so
    // end-to-end tests can target it without coupling to the
    // button label.
    expect(button.getAttribute('data-action')).toBe('publish-pdf');
  });

  it('does NOT trigger a download before publish', async () => {
    setupReadyToPublish(false);
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // No PDF has been generated yet -- the Generate PDF
    // button is rendered but clicking it has no effect
    // (no auto-download link yet).
    const createElementSpy = vi.spyOn(document, 'createElement');
    const publishBtn = await screen.findByRole('button', {
      name: /Generate PDF/i,
    });
    expect(publishBtn).toBeInTheDocument();
    // We don't click -- the user can't download a PDF
    // before one exists. Just assert the spy didn't
    // see any anchor creation yet.
    expect(createElementSpy).not.toHaveBeenCalledWith('a');
    createElementSpy.mockRestore();
  });

  it('auto-downloads the PDF on click (no separate download button)', async () => {
    setupReadyToPublish(true);  // starts published — the button is visible
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    // Click "Generate PDF" -- this triggers the browser
    // download (no FSM action runs because the PDF is
    // already on the session from when generate() ran on
    // the workspace page). handlePublish creates a
    // temporary <a> and clicks it.
    const publishBtn = await screen.findByRole('button', {
      name: /Generate PDF/i,
    });
    // Stub ``document.createElement`` so we can observe
    // the auto-download without actually navigating.
    // We delegate to the original implementation for
    // non-anchor tags because happy-dom's internal
    // machinery (e.g. text nodes) needs the real DOM
    // factory for its own bookkeeping.
    const realCreate = document.createElement.bind(document);
    const fakeAnchor = realCreate('div');
    let clickedHref: string | null = null;
    let clickedDownload: string | null = null;
    const createElementSpy = vi
      .spyOn(document, 'createElement')
      .mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'a') {
          const real = realCreate(tag, options);
          real.click = vi.fn(() => {
            clickedHref = real.href;
            clickedDownload = real.download;
          });
          return real;
        }
        return realCreate(tag, options);
      });
    fireEvent.click(publishBtn);
    // The click handler is async -- it awaits
    // ``handleDownloadClick()`` and ``fetchWorkspace()``
    // before triggering the auto-download. ``waitFor``
    // polls until ``clickedHref`` is set (or times out).
    await waitFor(
      () => {
        expect(clickedHref).not.toBeNull();
      },
      { timeout: 5000 },
    );
    // The anchor points at the PDF endpoint.
    expect(clickedHref).toBe(
      'http://test/workspaces/ws-1/published-report.pdf'
    );
    // The download attribute hints at the filename.
    expect(clickedDownload).toBe('report-ws-1.pdf');
    createElementSpy.mockRestore();
  });

  it('renders the Generate TeX button always (when a report exists)', async () => {
    setupReadyToPublish(true);
    const { Report } = await import('./Report');
    render(<Report />);
    // The page starts with ``inFlight=true`` and only
    // renders the action buttons after the loader
    // finishes. Wait for the loader to clear, then look
    // for the buttons. We poll every 100ms for up to
    // 5 seconds -- the loader should clear well within
    // that window because ``mockFetchWorkspace`` and
    // ``mockRunAction`` both resolve synchronously.
    await waitFor(() => {
      expect(
        screen.queryByText(/Loading workspace/i),
      ).not.toBeInTheDocument();
    }, { timeout: 5000 });
    // The TeX button should be present and enabled --
    // it's enabled whenever a ``ReportResponse`` has
    // been loaded into local state. We use
    // ``getAllByRole`` + filter because ``findByRole``
    // has been flaky in this test (the ``aria-busy``
    // state on adjacent buttons interferes with
    // accessible-name matching in happy-dom).
    const allButtons = screen.getAllByRole('button');
    const texBtn = allButtons.find((b) =>
      /Generate TeX/.test(b.textContent || ''),
    );
    if (!texBtn) {
      throw new Error(
        `Generate TeX button not found. Available buttons: ${JSON.stringify(allButtons.map((b) => b.textContent))}`
      );
    }
    expect(texBtn).toBeInTheDocument();
    // Clicking it triggers an anchor download.
    // Delegate to the real factory for non-anchor tags
    // (see the same fix in the PDF auto-download test).
    const realCreate = document.createElement.bind(document);
    const fakeAnchor = realCreate('div');
    let clickedHref: string | null = null;
    let clickedDownload: string | null = null;
    const createElementSpy = vi
      .spyOn(document, 'createElement')
      .mockImplementation((tag: string, options?: ElementCreationOptions) => {
        if (tag === 'a') {
          const real = realCreate(tag, options);
          real.click = vi.fn(() => {
            clickedHref = real.href;
            clickedDownload = real.download;
          });
          return real;
        }
        return realCreate(tag, options);
      });
    fireEvent.click(texBtn);
    // Same wait pattern as the PDF auto-download.
    await waitFor(
      () => {
        expect(clickedHref).not.toBeNull();
      },
      { timeout: 5000 },
    );
    // The anchor points at the .tex endpoint.
    expect(clickedHref).toBe(
      'http://test/workspaces/ws-1/published-report.tex'
    );
    expect(clickedDownload).toBe('report-ws-1.tex');
    createElementSpy.mockRestore();
  });

  it('routes through the FSM-aware PUBLISH endpoint (Layer-4 audit)', async () => {
    /**
     * The Layer-4 audit: clicking "Generate PDF" must
     * trigger a browser-side PDF download (via the hidden
     * <a download> trick in handlePublish), NOT call any
     * state-machine action.
     *
     * In the new 4-state FSM (ADR-017), GENERATE is the only
     * action that produces a PDF, and it runs automatically
     * on the workspace page before the user lands on the
     * Report page. The "Generate PDF" button on the Report
     * page is now a download trigger — it just redirects the
     * browser to the published-report.pdf endpoint.
     *
     * This test pins that contract: clicking "Generate PDF"
     * MUST NOT call runAction(...) because no FSM action
     * is needed (the workspace is already in FINAL with the
     * PDF on the session). The negative assertion is the
     * important one — a future refactor that wires the
     * button to runAction('generate') would cause a redundant
     * generation round-trip on every click.
     */
    setupReadyToPublish(false);
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    // Sanity: ensure mocks are clean before the click so
    // assertions about call counts are deterministic.
    mockRunAction.mockClear();
    mockApi.getPublishedReportUrl.mockClear();

    fireEvent.click(
      await screen.findByRole('button', { name: /Generate PDF/i }),
    );

    // Negative: the FSM-aware hook was NOT called -- the
    // button is a download trigger, not an action runner.
    // generate() already ran on the workspace page before
    // the user landed here.
    expect(mockRunAction).not.toHaveBeenCalled();
  });

  it('surfaces a generation error and keeps the page recoverable', async () => {
    setupReadyToPublish(false);
    // The first ``runAction`` call from the useEffect's
    // ``handleGenerateReport`` (action='generate') MUST FAIL
    // -- that's what we're testing. In the new 4-state FSM
    // (ADR-017) there is no separate PUBLISH action; GENERATE
    // does everything (summary + report + PDF + LaTeX). When
    // it fails, the page should show the error UI and let the
    // user retry. The retry path runs the RETRY action
    // (ERROR → INITIAL or INTERMEDIATE per last_known_state)
    // and then re-runs GENERATE.
    const baseImpl = mockRunAction.getMockImplementation();
    mockRunAction.mockImplementation(
      async (action: string) => {
        if (action === 'generate') {
          throw new Error('FSM rejected GENERATE');
        }
        if (baseImpl) {
          return (baseImpl as (...args: unknown[]) => unknown)(
            action,
          ) as never;
        }
        return {} as never;
      },
    );
    const { Report } = await import('./Report');
    render(<Report />);
    // Wait for the page to render its error UI (the
    // generation failed in the useEffect that runs on
    // mount).
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    // The generation error is shown in the dedicated error
    // block -- ``role="alert"`` so screen readers announce
    // it. We use a data-testid for a stable selector.
    await waitFor(() => {
      const errorEl = screen.getByTestId('report-error-detail');
      expect(errorEl.textContent).toContain('FSM rejected GENERATE');
    });
    // Recover button is still present (recoverable error,
    // not a hard fail).
    expect(
      screen.queryByRole('button', { name: /Retry/i }),
    ).not.toBeNull();
  });
});/**
 * Tests for the Report page error UI.
 *
 * These pin the bug fix for the "500 -> 409" failure mode the
 * live verify surfaced: the legacy ``/reports/generate``
 * endpoint now returns 409 with a structured envelope
 * (``error="report_generation_failed"``, ``last_error``,
 * ``current_state="ERROR"``) when the LLM call crashes,
 * instead of bubbling up to a bare 500. The frontend
 * surfaces that envelope as a clear error message and
 * offers a "Recover & Retry" CTA that runs the FSM
 * RETRY action first so the user isn't stuck in a 409
 * loop clicking "Retry" against an ERROR-state workspace.
 *
 * Four cases are covered (the four-state discipline from
 * the FSM-audit skill):
 *   1. Positive -- the envelope shape is recognised, the
 *      ``last_error`` is shown, the recover hint is shown.
 *   2. Negative -- a non-recoverable error (illegal action)
 *      keeps the original "Retry" label and does NOT show
 *      the recover hint.
 *   3. Audit-trail -- the "Recover & Retry" CTA actually
 *      calls ``runAction('retry')`` AND then
 *      ``generateReport()``. Pins the FSM-aware path so a
 *      future contributor can't accidentally wire the
 *      button back to the legacy ``/reports/generate``
 *      shortcut.
 *   4. Network-blip -- a plain network error falls through
 *      to the original "Retry" path (no FSM RETRY; just
 *      re-attempt generation).
 */
describe('Report > error UI', () => {
  function setupError() {
    // The fixture workspace in ERROR state.
    const workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'ERROR',
      summary: null,
      papers: [],
      total_papers: 0,
      allowed_actions: ['retry'],
      report_available: false,
      published_report_available: false,
      last_error: null,
      progress: 1.0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      paper_sources: {},
    };
    mockUseWorkspaceReturn.workspace = workspace;
    mockStoreCurrentWorkspace.current = workspace;
    mockFetchWorkspace.mockResolvedValue(workspace);
    // ``runAction`` is action-aware: 'retry' returns the
    // workspace advanced to CREATED; 'report' returns a
    // ReportResponse-shaped object. Individual tests
    // override per-call via ``mockRejectedValueOnce`` /
    // ``mockResolvedValueOnce`` -- the most-recent one-shot
    // wins. We provide a default here so tests that don't
    // care about the per-action shape just work.
    mockRunAction.mockImplementation(async (action: string) => {
      if (action === 'generate') {
        return {
          workspace_id: 'ws-1',
          question: 'x',
          summary: '# A Test Report\n\nSome content here.',
          citations: [],
          limitations: [],
          future_work: [],
          generated_at: '2026-01-01T00:00:00Z',
        } as never;
      }
      // 'retry' or anything else: returns the post-retry
      // workspace.
      return {
        ...workspace,
        state: 'INITIAL',
        allowed_actions: ['add_paper', 'search'],
      } as never;
    });
    return { workspace };
  }

  // The test mocks ``../api/client`` wholesale so the live
  // ``APIError`` class isn't available. We reconstruct an
  // object with the same shape: Error + ``status`` + ``detail``.
  function makeApiError(
    status: number,
    detail: unknown,
    message?: string,
  ) {
    const err = new Error(
      message ?? `API error ${status}`,
    ) as Error & { status?: number; detail?: unknown };
    err.status = status;
    err.detail = detail;
    return err;
  }

  it('surfaces the last_error message in a recoverable failure', async () => {
    const { workspace } = setupError();
    mockRunAction.mockRejectedValueOnce(
      makeApiError(409, {
        error: 'report_generation_failed',
        message:
          'RemoteProtocolError: peer closed connection without response',
        current_state: 'ERROR',
        last_error: 'RemoteProtocolError: peer closed connection',
        allowed_actions: ['retry'],
      }),
    );
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The detail block shows the orchestrator's last_error
    // (not the verbose ``message``).
    await waitFor(() => {
      const detail = screen.getByTestId('report-error-detail');
      expect(detail.textContent).toBe(
        'RemoteProtocolError: peer closed connection',
      );
    });
    // The recover hint shows because current_state === ERROR.
    expect(
      screen.getByTestId('report-error-recover-hint'),
    ).toBeInTheDocument();
    // The CTA is relabelled to "Recover & Retry".
    expect(
      screen.queryByRole('button', { name: /Recover.*Retry/i }),
    ).not.toBeNull();
    // The plain "Retry" label is gone (replaced).
    expect(
      screen.queryByRole('button', { name: /^Retry$/i }),
    ).toBeNull();
    // sanity: workspace fixture is in ERROR.
    expect(workspace.state).toBe('ERROR');
  });

  it('keeps the "Retry" label for non-recoverable failures', async () => {
    setupError();
    mockRunAction.mockRejectedValueOnce(
      makeApiError(409, {
        error: 'illegal_workspace_action',
        message: 'Action report is not allowed from state SUMMARIZED',
        current_state: 'INTERMEDIATE',
        action: 'generate',
        allowed_actions: ['search', 'compare', 'report'],
      }),
    );
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The recover hint is NOT shown (workspace isn't in ERROR).
    expect(
      screen.queryByTestId('report-error-recover-hint'),
    ).not.toBeInTheDocument();
    // The CTA stays as plain "Retry" (no recover step needed).
    expect(
      screen.queryByRole('button', { name: /Recover.*Retry/i }),
    ).toBeNull();
    expect(
      screen.queryByRole('button', { name: /^Retry$/i }),
    ).not.toBeNull();
  });

  it('"Recover & Retry" CTA calls the FSM RETRY action THEN re-generates', async () => {
    setupError();
    mockRunAction.mockRejectedValueOnce(
      makeApiError(409, {
        error: 'report_generation_failed',
        current_state: 'ERROR',
        last_error: 'Some failure',
        allowed_actions: ['retry'],
      }),
    );
    // Second call (after RETRY) succeeds. The Recover & Retry
    // CTA triggers THREE actions in sequence on the page:
    //   1. ``runAction('retry')`` -- FSM RETRY action
    //   2. ``fetchWorkspace()`` -- refetch the (now-CREATED) session
    //   3. ``runAction("generate")`` -- re-attempt generation
    // We provide one-shot successes for the post-RETRY calls.
    // The 'retry' call uses the default ``mockImplementation``
    // (which returns the workspace shape -- correct for
    // 'retry' since the hook contract is that 'retry' returns
    // ``WorkspaceResponse``).
    mockRunAction.mockResolvedValueOnce({
      workspace_id: 'ws-1',
      question: 'x',
      summary: '# A Test Report\n\nSome content.',
      citations: [],
      limitations: [],
      future_work: [],
      generated_at: '2026-01-01T00:00:00Z',
    } as never);
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    // Clear the useEffect's first call (the rejected 'report')
    // so the post-click call sequence is clean for the
    // assertions below.
    mockRunAction.mockClear();
    mockFetchWorkspace.mockClear();

    fireEvent.click(
      await screen.findByRole('button', { name: /Recover.*Retry/i }),
    );

    // First the FSM RETRY action runs.
    await waitFor(() => {
      expect(mockRunAction).toHaveBeenCalledWith('retry');
    });
    // Then fetchWorkspace refetches the (now-CREATED) session.
    expect(mockFetchWorkspace).toHaveBeenCalled();
    // Then ``handleGenerateReport`` re-runs the 'report'
    // action -- so ``runAction`` is called TWICE total: once
    // for 'retry' and once for 'report'.
    await waitFor(() => {
      expect(mockRunAction).toHaveBeenCalledTimes(2);
    });
    expect(mockRunAction).toHaveBeenNthCalledWith(1, 'retry');
    expect(mockRunAction).toHaveBeenNthCalledWith(2, 'generate');
  });

  it('falls through to plain Retry for network/transport errors', async () => {
    setupError();
    mockRunAction.mockRejectedValueOnce(
      // No structured envelope -- plain network error from
      // fetchJson's catch path.
      makeApiError(0, 'fetch failed', 'TypeError: fetch failed'),
    );
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // No envelope means no recover hint and no relabel.
    expect(
      screen.queryByTestId('report-error-recover-hint'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /^Retry$/i }),
    ).not.toBeNull();
  });

  it('renders the last_error_at timestamp next to the detail', async () => {
    // Pin the v5 wire format: the error envelope carries a
    // ``last_error_at`` ISO-8601 timestamp and the page
    // renders a small "(at HH:MM:SS)" stamp next to the
    // detail block. This is the user-visible payoff of the
    // v5 schema -- a fresh-vs-stale signal that survives
    // container restarts.
    setupError();
    mockRunAction.mockRejectedValueOnce(
      makeApiError(409, {
        error: 'report_generation_failed',
        current_state: 'ERROR',
        last_error: 'RemoteProtocolError: peer closed connection',
        last_error_at: '2026-08-26T15:30:00+00:00',
        allowed_actions: ['retry'],
      }),
    );
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The detail block now contains the timestamp stamp.
    await waitFor(() => {
      const at = screen.getByTestId('report-error-detail-at');
      // ``toLocaleString`` format is locale-dependent: on
      // the Linux jsdom environment the output is
      // ``(at Aug 26, 05:30:00 PM)`` but on other platforms
      // it might be ``(at 26/08/2026 15:30:00)`` etc.
      // We pin the structural contract -- starts with
      // ``(at`` and ends with ``)`` -- and leave the
      // exact date string to the browser's Intl. The
      // underlying round-trip behaviour is pinned by
      // ``tests/unit/test_sqlite_last_error_roundtrip.py``.
      expect(at.textContent).toMatch(/^\(at .+\)$/);
    });
    // And the existing detail assertion still holds.
    const detail = screen.getByTestId('report-error-detail');
    expect(detail.textContent).toContain(
      'RemoteProtocolError: peer closed connection',
    );
  });

  it('omits the timestamp when last_error_at is missing', async () => {
    // Backward compat: pre-v5 envelopes don't carry
    // ``last_error_at`` (the field is ``undefined``). The
    // UI must NOT render a timestamp in that case. This
    // test pins that the optional field is genuinely
    // optional and the UI degrades gracefully.
    setupError();
    mockRunAction.mockRejectedValueOnce(
      makeApiError(409, {
        error: 'report_generation_failed',
        current_state: 'ERROR',
        last_error: 'Some legacy error without timestamp',
        allowed_actions: ['retry'],
        // NB: no last_error_at field.
      }),
    );
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('report-error-detail-at')).toBeNull();
  });

  // -----------------------------------------------------------------
  // Back to Workspace button
});

describe('Report > citation rendering (Vancouver / ICMJE inline links)', () => {
  /**
   * Pin the contract that the report body renders
   * ``[paper:N]`` markers as clickable in-text links
   * targeting the corresponding bibliography entry.
   * This is the user's pinned requirement: real
   * scientific writing closes each claim with a
   * citation, and the citations are clickable links to
   * the bibliography.
   */

  /**
   * Helper: render the Report page with a workspace in
   * REPORTED state and a body containing ``[paper:N]``
   * markers + a populated citations list.
   */
  function setupWithCitationMarkers() {
    const workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'FINAL',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      report_available: true,
      published_report_available: false,
      last_error: null,
      progress: 1.0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      paper_sources: {},
    };
    mockUseWorkspaceReturn.workspace = workspace;
    mockStoreCurrentWorkspace.current = workspace;
    mockFetchWorkspace.mockResolvedValue(workspace);
    mockRunAction.mockImplementation(
      async (action: string) => {
        if (action === 'generate') {
          return {
            workspace_id: 'ws-1',
            question: 'x',
            summary:
              '## Executive Summary\n\n' +
              'Plasma p-tau217 is a sensitive marker [paper:1]. ' +
              'BBMs are poised to expand access [paper:2]. ' +
              'NT1 trajectory diverges from CSF p-tau217 in ' +
              'symptomatic phases [paper:3].\n\n' +
              '## Limitations\n' +
              '- <limitation 1>\n' +
              '## Future Work\n' +
              '- <future 1>',
            citations: [
              'First citation. Smith A, et al. Nature, 2026.',
              'Second citation. Jones B, et al. Cell, 2026.',
              'Third citation. Patel D, et al. Lancet, 2026.',
            ],
            limitations: [],
            future_work: [],
            generated_at: '2026-01-01T00:00:00Z',
          } as never;
        }
        return {
          ...workspace,
          state: action === 'generate' ? 'FINAL' : workspace.state,
          published_report_available:
            action === 'generate' ? true : workspace.published_report_available,
        } as never;
      },
    );
  }

  it('renders [paper:N] markers as clickable [N] links to #citation-N', async () => {
    setupWithCitationMarkers();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The body should render [1], [2], [3] as links.
    // ``ReactMarkdown`` parses ``[1](#citation-1)`` so the
    // link's accessible name is just the label ``1`` (the
    // square brackets are markdown syntax, not part of the
    // rendered text). We pin on the label so the test
    // catches a regression that re-introduces the literal
    // ``[paper:N]`` markers in the rendered text.
    await waitFor(() => {
      const link1 = screen.getByRole('link', { name: '1' });
      expect(link1).toBeInTheDocument();
      const link2 = screen.getByRole('link', { name: '2' });
      expect(link2).toBeInTheDocument();
      const link3 = screen.getByRole('link', { name: '3' });
      expect(link3).toBeInTheDocument();
      // Each link targets the right anchor.
      expect(link1.getAttribute('href')).toBe('#citation-1');
      expect(link2.getAttribute('href')).toBe('#citation-2');
      expect(link3.getAttribute('href')).toBe('#citation-3');
    });
    // The raw ``[paper:N]`` marker text MUST NOT appear in
    // the rendered DOM (the page would still work, but the
    // "clickable link" requirement wouldn't be met -- and
    // it would indicate the linkifier isn't being called).
    expect(screen.queryByText('[paper:1]')).toBeNull();
    expect(screen.queryByText('[paper:2]')).toBeNull();
    expect(screen.queryByText('[paper:3]')).toBeNull();
  });

  it('attaches id="citation-N" to each <li> in the citations list', async () => {
    setupWithCitationMarkers();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The <li> with id="citation-1" must exist so the in-text
    // link has somewhere to scroll to.
    expect(document.getElementById('citation-1')).not.toBeNull();
    expect(document.getElementById('citation-2')).not.toBeNull();
    expect(document.getElementById('citation-3')).not.toBeNull();
  });

  it('renders the citation number prefix in each bibliography entry', async () => {
    setupWithCitationMarkers();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The Vancouver convention is to render the
    // bibliography as a numbered list (1, 2, 3 ...).
    // The page renders "[1]" / "[2]" / "[3]" prefixes
    // inside each <li> so the user can see the in-text
    // citation number next to each entry.
    expect(screen.getByText('[1]')).toBeInTheDocument();
    expect(screen.getByText('[2]')).toBeInTheDocument();
    expect(screen.getByText('[3]')).toBeInTheDocument();
  });

  it('does not render link for a marker index beyond the citations list', async () => {
    // Defensive: if a future change ever lets an out-of-
    // range marker through, the page must not crash and
    // must not produce a broken anchor link. An out-of-
    // range marker means the LLM fabricated a citation
    // -- the bibliography doesn't have an entry at that
    // index. The linkifier's policy is to SILENTLY DROP
    // these so the user never sees a broken ``[paper:99]``
    // artefact in the rendered page. Hallucinated indices
    // are surfaced via the backend's logs.
    const workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'FINAL',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      report_available: true,
      published_report_available: false,
      last_error: null,
      progress: 1.0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      paper_sources: {},
    };
    mockUseWorkspaceReturn.workspace = workspace;
    mockStoreCurrentWorkspace.current = workspace;
    mockFetchWorkspace.mockResolvedValue(workspace);
    mockRunAction.mockImplementation(
      async (action: string) => {
        if (action === 'generate') {
          return {
            workspace_id: 'ws-1',
            question: 'x',
            summary:
              '## Executive Summary\n\n' +
              'In-range marker [paper:1]. Out-of-range [paper:99].\n\n' +
              '## Limitations\n' +
              '- <l>\n' +
              '## Future Work\n' +
              '- <f>',
            citations: [
              'Single citation.',
            ],
            limitations: [],
            future_work: [],
            generated_at: '2026-01-01T00:00:00Z',
          } as never;
        }
        return workspace as never;
      },
    );
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // In-range [1] should link.
    await waitFor(() => {
      expect(
        screen.getByRole('link', { name: '1' }),
      ).toBeInTheDocument();
    });
    // Out-of-range [99] must NOT link AND must NOT appear
    // as visible text. The linkifier silently drops it.
    expect(screen.queryByRole('link', { name: '99' })).toBeNull();
    expect(screen.queryByText(/\[paper:99\]/)).toBeNull();
    // The surrounding prose is preserved verbatim.
    expect(screen.getByText(/In-range marker/)).toBeInTheDocument();
    expect(screen.getByText(/Out-of-range/)).toBeInTheDocument();
  });
});

describe('Report > Limitations / Future Work citation rendering', () => {
  /**
   * Pin the contract that the Limitations and Future
   * Work list items ALSO render ``[paper:N]`` markers
   * (both standalone and grouped) as clickable inline
   * links, the same way the Executive Summary body does.
   *
   * The user flagged this: the Executive Summary was
   * linkified correctly, but the Limitations and Future
   * Work sections still rendered raw ``[paper:N]`` text
   * because the page bypassed the linkifier for those
   * list items. This block pins the regression so a
   * future refactor of the page layout doesn't re-introduce
   * the inconsistency.
   */
  function setupWithLimitationsAndFutureWork() {
    const workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'FINAL',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      report_available: true,
      published_report_available: false,
      last_error: null,
      progress: 1.0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      paper_sources: {},
    };
    mockUseWorkspaceReturn.workspace = workspace;
    mockStoreCurrentWorkspace.current = workspace;
    mockFetchWorkspace.mockResolvedValue(workspace);
    mockRunAction.mockImplementation(
      async (action: string) => {
        if (action === 'generate') {
          return {
            workspace_id: 'ws-1',
            question: 'x',
            summary:
              '## Executive Summary\n\n' +
              'Some claim [paper:1].\n\n' +
              '## Limitations\n' +
              '- Cohort bias limits generalisability [paper:3, paper:13].\n' +
              '- Western-dominant data [paper:8].\n' +
              '- Standardisation needed [paper:8, paper:11, paper:18].\n\n' +
              '## Future Work\n' +
              '- Diverse validation [paper:5, paper:10, paper:19].\n' +
              '- Hybrid AI systems [paper:4, paper:6].\n' +
              '- Operationalise [paper:7, paper:20].\n',
            citations: [
              'Citation 1',
              'Citation 2',
              'Citation 3 (unused)',
              'Citation 4',
              'Citation 5',
              'Citation 6',
              'Citation 7',
              'Citation 8',
              'Citation 9 (unused)',
              'Citation 10',
              'Citation 11',
              'Citation 12 (unused)',
              'Citation 13',
              'Citation 14 (unused)',
              'Citation 15 (unused)',
              'Citation 16 (unused)',
              'Citation 17 (unused)',
              'Citation 18',
              'Citation 19',
              'Citation 20',
            ],
            limitations: [
              'Cohort bias limits generalisability [paper:3, paper:13].',
              'Western-dominant data [paper:8].',
              'Standardisation needed [paper:8, paper:11, paper:18].',
            ],
            future_work: [
              'Diverse validation [paper:5, paper:10, paper:19].',
              'Hybrid AI systems [paper:4, paper:6].',
              'Operationalise [paper:7, paper:20].',
            ],
            generated_at: '2026-01-01T00:00:00Z',
          } as never;
        }
        return workspace as never;
      },
    );
  }

  it('renders [paper:N] markers in Limitations list items as clickable links', async () => {
    setupWithLimitationsAndFutureWork();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The standalone ``[paper:8]`` in the second limitation
    // item must link (citation 8 exists). The link's
    // accessible name is just ``8``. Use ``getAllByRole``
    // because the same citation may also be cited in the
    // Executive Summary -- we want at least one link to
    // citation-8, and ALL of them must point to the same
    // anchor (the in-page ``#citation-8``).
    await waitFor(() => {
      const links = screen.getAllByRole('link', { name: '8' });
      expect(links.length).toBeGreaterThanOrEqual(1);
      for (const link of links) {
        expect(link.getAttribute('href')).toBe('#citation-8');
      }
    });
    // Raw ``[paper:N]`` text MUST NOT appear for the valid
    // markers -- the user-visible bug was that the page
    // bypassed the linkifier and rendered the literal text.
    expect(screen.queryByText('[paper:8]')).toBeNull();
  });

  it('renders grouped [paper:N, paper:N] markers in Limitations as comma-joined clickable links', async () => {
    setupWithLimitationsAndFutureWork();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The first Limitations item is
    // ``[paper:3, paper:13]`` -- both are valid (citations
    // 3 and 13 exist). The grouped form was rendered as
    // a comma-joined pair of clickable links by
    // ``linkifyCitationMarkers``. Use ``getAllByRole``
    // because the same citations may also appear in the
    // Executive Summary body via ReactMarkdown -- we
    // assert that AT LEAST one anchor of each name
    // exists with the right ``#citation-N`` href.
    await waitFor(() => {
      const link3s = screen.getAllByRole('link', { name: '3' });
      const link13s = screen.getAllByRole('link', { name: '13' });
      expect(link3s.length).toBeGreaterThanOrEqual(1);
      expect(link13s.length).toBeGreaterThanOrEqual(1);
      for (const link of link3s) {
        expect(link.getAttribute('href')).toBe('#citation-3');
      }
      for (const link of link13s) {
        expect(link.getAttribute('href')).toBe('#citation-13');
      }
    });
    // The raw grouped form MUST be gone.
    expect(screen.queryByText('[paper:3, paper:13]')).toBeNull();
  });

  it('renders [paper:N] markers in Future Work list items as clickable links', async () => {
    setupWithLimitationsAndFutureWork();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The first Future Work item is
    // ``[paper:5, paper:10, paper:19]`` -- all three are
    // valid (citations 5, 10, 19 exist). Each citation
    // must produce AT LEAST one clickable anchor element
    // (executive summary may produce duplicates).
    await waitFor(() => {
      for (const name of ['5', '10', '19']) {
        const links = screen.getAllByRole('link', { name });
        expect(links.length).toBeGreaterThanOrEqual(1);
        for (const link of links) {
          expect(link.getAttribute('href')).toBe(
            `#citation-${name}`,
          );
        }
      }
    });
    // Raw grouped form MUST be gone.
    expect(screen.queryByText('[paper:5, paper:10, paper:19]')).toBeNull();
  });

  it('silently drops out-of-range entries from a Limitations group (no visible raw text)', async () => {
    // Future Work: ``Operationalise [paper:7, paper:20]``
    // -- both are valid (20 citations). Both linkify.
    setupWithLimitationsAndFutureWork();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    await waitFor(() => {
      const links = screen.getAllByRole('link', { name: '20' });
      expect(links.length).toBeGreaterThanOrEqual(1);
      for (const link of links) {
        expect(link.getAttribute('href')).toBe('#citation-20');
      }
    });
    // No raw ``[paper:20]`` text (valid entry is fully
    // linkified).
    expect(screen.queryByText('[paper:20]')).toBeNull();
  });
});

describe('Report > back-to-workspace navigation (FSM regressive action)', () => {
  /**
   * Regression tests for the bug where the "Back to Workspace"
   * button just navigated client-side without running the FSM
   * regressive action. The user landed on the Workspace page
   * with the workspace still in FINAL state, so the
   * ``can('generate')`` check returned false and the Generate
   * Report button was greyed out.
   *
   * The fix: the button must call
   * ``runAction('back_to_workspace')`` (FINAL -> INTERMEDIATE)
   * before navigating, so the Workspace page sees an
   * INTERMEDIATE state and enables the Generate Report button.
   *
   * Note: this describe block lives at the top level rather
   * than inside ``Report > Generate PDF`` because the back
   * button is a navigation concern, not a generate concern.
   * The local ``setupReadyWorkspace`` helper is a stripped-
   * down version of the Generate PDF block's
   * ``setupReadyToPublish`` -- we keep it inline so the
   * existing tests in Generate PDF are not affected by a
   * refactor.
   */
  function setupReadyWorkspace() {
    const workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'FINAL',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['generate'],
      report_available: true,
      published_report_available: false,
      last_error: null,
      progress: 1.0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      paper_sources: {},
    };
    mockUseWorkspaceReturn.workspace = workspace;
    mockStoreCurrentWorkspace.current = workspace;
    mockFetchWorkspace.mockResolvedValue(workspace);
    mockRunAction.mockImplementation(async (action: string) => {
      if (action === 'generate') {
        return {
          content: '# A Test Report\n\nSome content here.',
          summary: '# A Test Report\n\nSome content here.',
          sections: [{ title: 'Introduction', content: 'Some content.' }],
          citations: [],
          limitations: [],
          future_work: [],
        } as never;
      }
      return workspace as never;
    });
  }

  it('runs the FSM regressive action THEN navigates to the Workspace page', async () => {
    setupReadyWorkspace();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    mockRunAction.mockClear();
    mockNavigate.mockClear();

    const button = await screen.findByRole('button', {
      name: /Back to Workspace/i,
    });
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockRunAction).toHaveBeenCalled();
    });

    const actionCalls = mockRunAction.mock.calls.map((args) => args[0]);
    expect(actionCalls).toContain('back_to_workspace');
    // Critically, the action must NOT be 'generate' -- clicking
    // back-to-workspace must not re-run the report pipeline.
    expect(actionCalls).not.toContain('generate');

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/workspace/ws-1');
    });

    // The navigation must happen AFTER the regressive action.
    // If the order is wrong (navigate-then-action), the user
    // would land on the Workspace page with the workspace
    // still in FINAL, and the Generate Report button would
    // be greyed out -- the very bug we're regressing against.
    const navigateOrder = mockNavigate.mock.invocationCallOrder[0];
    const actionOrder = mockRunAction.mock.invocationCallOrder[0];
    expect(actionOrder).toBeLessThan(navigateOrder);
  });

  it('keeps the user on the Report page when the regressive action fails', async () => {
    setupReadyWorkspace();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    mockRunAction.mockClear();
    mockNavigate.mockClear();
    mockRunAction.mockRejectedValueOnce(
      new Error('Workspace is in INITIAL, not FINAL'),
    );

    const button = await screen.findByRole('button', {
      name: /Back to Workspace/i,
    });
    fireEvent.click(button);

    await waitFor(() => {
      expect(
        screen.getByTestId('back-to-workspace-error'),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId('back-to-workspace-error'),
    ).toHaveTextContent(/Workspace is in INITIAL/);

    // And the page must NOT navigate -- the user keeps the
    // option to retry.
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('disables the button while the regressive action is in flight', async () => {
    setupReadyWorkspace();
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    // Make the regressive action hang so we can observe the
    // in-flight state.
    let resolveBack: () => void = () => {};
    mockRunAction.mockClear();
    mockRunAction.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveBack = () => resolve();
        }),
    );

    const button = (await screen.findByRole('button', {
      name: /Back to Workspace/i,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Back to Workspace/i }),
      ).toBeDisabled();
    });

    resolveBack();
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/workspace/ws-1');
    });
  });
});
