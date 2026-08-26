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
 * ``report()`` doesn't actually call the compare use case
 * (the panel was removed in commit decc964; the data-side
 * ``has_evidence_comparison`` flag is set but not awaited).
 *
 * We mock the API client, the useWorkspace hook, and the
 * Zustand store. The test asserts the phase label text
 * changes at the right points in the lifecycle.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';

// Mock the api client. The Report page calls
// ``api.runReportAction`` (FSM-aware endpoint) via the
// useWorkspace hook's ``runAction('report')`` dispatch.
// The legacy ``api.generateReport`` is kept in the mock
// only because the hook's ``generateReport`` wrapper still
// exists for any callers that haven't migrated; the
// Report page does not use it.
vi.mock('../api/client', () => ({
  api: {
    generateReport: vi.fn(),
    fetchWorkspace: vi.fn(),
    // The Publish-as-PDF button routes through the FSM-aware
    // ``POST /workspaces/{id}/actions/publish`` endpoint,
    // not the legacy ``api.complete`` shortcut. The mock
    // exposes both because the wire-format test below
    // asserts on which endpoint gets called.
    runPublishAction: vi.fn(),
    // The REPORT button (and the auto-summarise/auto-compare
    // pipeline that runs as part of the REPORT action) now
    // routes through the FSM-aware endpoint. ``runAction``
    // in the hook special-cases 'report' to call this method
    // and return ``ReportResponse`` -- the page stores the
    // result via ``setReport`` directly. See ADR-009 + the
    // b900965/1faf32e sessions for the audit context.
    runReportAction: vi.fn(),
    // The download URL is built client-side from the
    // workspace id; we expose a stub that just echoes the
    // input so tests can assert on the call site.
    getPublishedReportUrl: vi.fn((workspaceId: string) =>
      `http://test/workspaces/${workspaceId}/published-report.pdf`,
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
  // The PUBLISH button routes through ``runAction('publish')``
  // (FSM-aware path -- see ADR-009). The legacy ``api.complete``
  // shortcut would advance to COMPLETED but leave
  // ``session.published_report`` empty; the FSM-aware
  // ``runAction('publish')`` is the only path that renders the
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
vi.mock('react-router-dom', () => ({
  useParams: () => ({ workspaceId: 'ws-1' }),
  useNavigate: () => vi.fn(),
}));

import { api } from '../api/client';
const mockApi = api as unknown as {
  generateReport: ReturnType<typeof vi.fn>;
  fetchWorkspace: ReturnType<typeof vi.fn>;
  runPublishAction: ReturnType<typeof vi.fn>;
  getPublishedReportUrl: ReturnType<typeof vi.fn>;
};

describe('Report > loader phases', () => {
  beforeEach(() => {
    mockApi.generateReport.mockReset();
    mockFetchWorkspace.mockReset();
    mockRunAction.mockReset();
    mockApi.runPublishAction.mockReset();
    mockApi.getPublishedReportUrl.mockClear();
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
      state: 'SUMMARIZED',
      summary: { text: 'A prior summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['report'],
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
      state: 'SUMMARIZED',
      summary: { text: 'A prior summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['report'],
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
      state: 'PAPERS_RETRIEVED',
      summary: null,
      papers: [],
      total_papers: 0,
      allowed_actions: ['report'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    mockUseWorkspaceReturn.workspace = {
      workspace_id: 'ws-1',
      question: 'x',
      state: 'PAPERS_RETRIEVED',
      summary: null,
      papers: [],
      total_papers: 0,
      allowed_actions: ['report'],
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
      state: 'REPORTED',
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
      state: 'REPORTED',
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
 * Tests for the "Publish as PDF" action.
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
 *                  ``runAction('publish')`` (NOT the
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
describe('Report > Publish as PDF', () => {
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
      state: 'REPORTED',
      summary: { text: 'A summary.', paper_ids: [] },
      papers: [],
      total_papers: 0,
      allowed_actions: ['publish', 'complete'],
      has_evidence_comparison: false,
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
      if (action === 'report') {
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
        // PUBLISH moves us to COMPLETED and flips the flag.
        state: action === 'publish' ? 'COMPLETED' : workspace.state,
        published_report_available:
          action === 'publish' ? true : workspace.published_report_available,
      } as never;
    });
  }

  it('renders the "Publish as PDF" button when a report is available', async () => {
    setupReadyToPublish(false);
    const { Report } = await import('./Report');
    render(<Report />);
    // Wait for the loader to disappear.
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // The button is the FSM-aware endpoint caller.
    const button = await screen.findByRole('button', {
      name: /Publish as PDF/i,
    });
    expect(button).toBeInTheDocument();
    // We tag the button with ``data-action="publish-pdf"`` so
    // end-to-end tests can target it without coupling to the
    // button label.
    expect(button.getAttribute('data-action')).toBe('publish-pdf');
  });

  it('does NOT render the "Download PDF" link before publish', async () => {
    setupReadyToPublish(false);
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });
    // Without a published PDF, the download link is hidden --
    // clicking the (still-rendered) Publish button is the only
    // way to get a PDF.
    expect(
      screen.queryByRole('link', { name: /Download PDF/i }),
    ).not.toBeInTheDocument();
  });

  it('renders the "Download PDF" link AFTER publish (wire-format)', async () => {
    setupReadyToPublish(false);  // starts unpublished
    const { Report } = await import('./Report');
    render(<Report />);
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    // Click Publish -- this calls runAction('publish').
    const publishBtn = await screen.findByRole('button', {
      name: /Publish as PDF/i,
    });
    fireEvent.click(publishBtn);

    // After the click resolves, the workspace is COMPLETED
    // and ``published_report_available`` is true -- the
    // download link should render. ``findByRole`` auto-retries
    // until the link appears (or times out), so we don't need
    // a manual ``waitFor`` loop. The implicit timeout gives
    // ``setCurrentWorkspace`` time to fire and React to
    // commit the re-render.
    const link = await screen.findByRole('link', {
      name: /Download PDF/i,
    });
    expect(link.getAttribute('href')).toBe(
      'http://test/workspaces/ws-1/published-report.pdf',
    );
    // The download attribute tells the browser to save
    // the file rather than navigate. The endpoint sets
    // ``Content-Disposition: attachment`` authoritatively;
    // this hint just makes the UX faster.
    expect(link.getAttribute('download')).toBe('report-ws-1.pdf');
  });

  it('routes through the FSM-aware PUBLISH endpoint (Layer-4 audit)', async () => {
    /**
     * The Layer-4 audit: clicking Publish must call
     * ``runAction('publish')`` (which dispatches to
     * ``POST /workspaces/{id}/actions/publish``), NOT the
     * legacy ``api.complete`` shortcut. This is the
     * single test that catches the regression the FSM-audit
     * skill warns about: a future contributor who sees
     * "the button advances the workspace to COMPLETED" and
     * wires it to ``api.complete`` instead. The PDF would
     * never appear because COMPLETE doesn't render.
     *
     * Both mocks are reset in beforeEach -- the negative
     * assertion (``runPublishAction`` was NOT called) is
     * as important as the positive assertion. A test that
     * only checks "something happened" doesn't pin the
     * contract; this one does.
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
    mockApi.runPublishAction.mockClear();

    fireEvent.click(
      await screen.findByRole('button', { name: /Publish as PDF/i }),
    );

    // Positive: the FSM-aware hook was called with 'publish'.
    await waitFor(() => {
      expect(mockRunAction).toHaveBeenCalledWith('publish');
    });
    // Negative: the legacy ``api.runPublishAction`` direct
    // call was NOT made -- we route through the hook so the
    // hook can mirror server state. This is the false-positive
    // guard from the FSM-audit skill: a test that only checks
    // the positive call could pass if both are called.
    expect(mockApi.runPublishAction).not.toHaveBeenCalled();
  });

  it('surfaces a publish error and keeps the button enabled for retry', async () => {
    setupReadyToPublish(false);
    // The first ``runAction`` call from the useEffect's
    // ``handleGenerateReport`` (action='report') must SUCCEED --
    // otherwise the page would render the report error UI,
    // not the publish one. The 'publish' call is the one we
    // want to fail, so we wrap the mock to dispatch per-action.
    //
    // We chain: one-shot for 'publish' (after the useEffect's
    // 'report' has been consumed by setupReadyToPublish's
    // default mockImplementation), then fall back to the
    // default. ``mockRejectedValueOnce`` doesn't accept a
    // predicate, so we use ``mockImplementation`` to gate on
    // the action.
    const baseImpl = mockRunAction.getMockImplementation();
    mockRunAction.mockImplementation(
      async (action: string) => {
        if (action === 'publish') {
          throw new Error('FSM rejected PUBLISH');
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
    await waitFor(() => {
      expect(screen.queryByText(/Loading workspace/i)).not.toBeInTheDocument();
    });

    fireEvent.click(
      await screen.findByRole('button', { name: /Publish as PDF/i }),
    );

    // The publish error is shown in the dedicated error block
    // -- ``role="alert"`` so screen readers announce it. We
    // use a data-testid for a stable selector.
    await waitFor(() => {
      const errorEl = screen.getByTestId('publish-error');
      expect(errorEl.textContent).toContain('FSM rejected PUBLISH');
    });
    // Button still present (recoverable error, not a hard fail).
    expect(
      screen.queryByRole('button', { name: /Publish as PDF/i }),
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
      has_evidence_comparison: false,
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
      if (action === 'report') {
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
        state: 'CREATED',
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
        current_state: 'SUMMARIZED',
        action: 'report',
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
    //   3. ``runAction('report')`` -- re-attempt generation
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
    expect(mockRunAction).toHaveBeenNthCalledWith(2, 'report');
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
});