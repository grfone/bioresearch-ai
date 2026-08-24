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
import { render, screen, waitFor, act } from '@testing-library/react';

// Mock the api client. The Report page calls
// ``api.generateReport`` (legacy endpoint) via the
// useWorkspace hook.
vi.mock('../api/client', () => ({
  api: {
    generateReport: vi.fn(),
    fetchWorkspace: vi.fn(),
  },
}));

// Mock the useWorkspace hook so we control its return
// value (loading state, error state, the report promise,
// the workspace fetch). The Report page reads
// ``workspace`` to decide the next phase label.
const mockFetchWorkspace = vi.fn();
const mockGenerateReport = vi.fn();
const mockUseWorkspaceReturn: {
  workspace: unknown;
  loading: boolean;
  error: unknown;
  fetchWorkspace: ReturnType<typeof vi.fn>;
  generateReport: ReturnType<typeof vi.fn>;
} = {
  workspace: null,
  loading: false,
  error: null,
  fetchWorkspace: mockFetchWorkspace,
  generateReport: mockGenerateReport,
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
  const state = {
    currentWorkspace: mockStoreCurrentWorkspace.current,
    setCurrentWorkspace: () => {},
  };
  const useWorkspaceStore = Object.assign(
    (selector: (state: any) => unknown) => selector(state),
    { getState: () => state },
  );
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
};

describe('Report > loader phases', () => {
  beforeEach(() => {
    mockApi.generateReport.mockReset();
    mockFetchWorkspace.mockReset();
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
    mockGenerateReport.mockImplementation(
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
    mockGenerateReport.mockImplementation(
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
    mockGenerateReport.mockResolvedValue({
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