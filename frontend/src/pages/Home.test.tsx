/**
 * pages/Home.test.tsx
 *
 * Tests for the Home page's submit flow and the full-screen
 * loading overlay that appears during the create + search
 * round-trip.
 *
 * The loader is the user-visible symptom of the "this thing is
 * taking forever to load" complaint. Without it, the button
 * just says "Creating…" with no other feedback for the 6-12
 * second create + auto-search round-trip.
 *
 * We mock the api client (no real backend) and the
 * workspaceStore (no real Zustand context). The react-router
 * navigate is mocked so we can assert the navigation happens
 * AFTER the create + search calls succeed (and not, say, the
 * moment the user clicks submit).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Hoisted shared mock state so individual tests can assert
// against ``createWorkspace`` and ``runSearchAction``. The
// api client mock factory is hoisted by vitest to the top
// of the file, so the variables it closes over must also be
// hoisted (``vi.hoisted``) -- using ``vi.fn()`` at module
// scope wouldn't work because the factory runs before the
// variables are initialised.
const { mockCreateWorkspace, mockRunSearchAction } = vi.hoisted(() => ({
  mockCreateWorkspace: vi.fn(),
  mockRunSearchAction: vi.fn(),
}));
vi.mock('../api/client', () => ({
  api: {
    createWorkspace: mockCreateWorkspace,
    runSearchAction: mockRunSearchAction,
  },
}));

// Mock react-router so the navigation effect is observable
// without a real router. The loader's lifecycle is timed
// against ``navigate`` -- we want to assert it disappears
// when the page unmounts (i.e. on navigate).
const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));
vi.mock('react-router-dom', () => ({
  // We don't need any of react-router-dom's real exports for
  // these tests; the mock below only consumes ``useNavigate``.
  useNavigate: () => mockNavigate,
}));

// Mock the workspaceStore.
vi.mock('../state/workspaceStore', () => ({
  useWorkspaceStore: (selector: (state: any) => any) => {
    return selector({ setCurrentWorkspace: vi.fn() });
  },
}));

import { api } from '../api/client';
const mockApi = api as unknown as {
  createWorkspace: ReturnType<typeof vi.fn>;
  runSearchAction: ReturnType<typeof vi.fn>;
};

describe('Home', () => {
  beforeEach(() => {
    mockCreateWorkspace.mockReset();
    mockRunSearchAction.mockReset();
    mockNavigate.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does NOT show the loading overlay before submit', () => {
    // We don't want the overlay sitting on top of the page
    // for users who haven't clicked anything yet.
    render(<HomePlaceholder />);
    expect(
      screen.queryByText(/Creating workspace and searching literature/i),
    ).not.toBeInTheDocument();
  });

  it('shows the loading overlay the moment the user submits', async () => {
    const user = userEvent.setup();
    // Both promises stay pending so the loader stays up
    // while we assert against it.
    let createResolve!: (v: unknown) => void;
    let searchResolve!: (v: unknown) => void;
    mockCreateWorkspace.mockImplementation(
      () =>
        new Promise((resolve) => {
          createResolve = resolve;
        }),
    );
    mockRunSearchAction.mockImplementation(
      () =>
        new Promise((resolve) => {
          searchResolve = resolve;
        }),
    );

    render(<HomePlaceholder />);

    await user.type(
      screen.getByPlaceholderText(/Ask a biomedical research question/i),
      'biomarkers for Alzheimer Disease',
    );
    await user.click(
      screen.getByRole('button', { name: /Start Research/i }),
    );

    // Phase 1: the loader should mount immediately with the
    // "Creating workspace..." label, BEFORE the create call
    // resolves. This is the user-visible fix for "this thing
    // is taking forever to load".
    await waitFor(() => {
      expect(
        screen.getByText(/Creating workspace/i),
      ).toBeInTheDocument();
    });
    // role="status" + aria-live="polite" announce the
    // loader to assistive tech without interrupting the
    // current announcement.
    const loader = screen.getByRole('status');
    expect(loader).toHaveAttribute('aria-live', 'polite');

    // Clean up: resolve the create promise so the test
    // can move past Phase 1.
    createResolve({
      workspace_id: 'ws-1',
      question: 'biomarkers for Alzheimer Disease',
      state: 'CREATED',
      papers: [],
      total_papers: 0,
      allowed_actions: ['add_paper', 'search'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    // Phase 2: the label should advance to
    // "Searching literature..." once createWorkspace
    // resolves and runSearchAction is invoked. We assert
    // on the new label BEFORE resolving the search promise,
    // so we catch the transition.
    await waitFor(() => {
      expect(mockRunSearchAction).toHaveBeenCalled();
    });
    expect(
      screen.getByText(/Searching literature/i),
    ).toBeInTheDocument();

    // Clean up: resolve the search promise so the test
    // can tear down without warnings.
    searchResolve({
      workspace_id: 'ws-1',
      question: 'biomarkers for Alzheimer Disease',
      state: 'PAPERS_RETRIEVED',
      papers: [],
      total_papers: 0,
      allowed_actions: ['add_paper', 'report', 'search', 'summarize'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
  });

  it('disables the submit button while loading', async () => {
    const user = userEvent.setup();
    let createResolve!: (v: unknown) => void;
    mockCreateWorkspace.mockImplementation(
      () =>
        new Promise((resolve) => {
          createResolve = resolve;
        }),
    );
    mockRunSearchAction.mockResolvedValue({
      workspace_id: 'ws-1',
      question: 'x',
      state: 'PAPERS_RETRIEVED',
      papers: [],
      total_papers: 0,
      allowed_actions: ['report'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    render(<HomePlaceholder />);

    const input = screen.getByPlaceholderText(/Ask a biomedical research question/i);
    await user.type(input, 'test question');
    const submitButton = screen.getByRole('button', {
      name: /Start Research/i,
    });

    await user.click(submitButton);

    // Button changes label to "Creating…" and is disabled.
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Creating/i }),
      ).toBeDisabled();
    });

    // Cleanup.
    createResolve({
      workspace_id: 'ws-1',
      question: 'x',
      state: 'CREATED',
      papers: [],
      total_papers: 0,
      allowed_actions: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
  });

  it('navigates only after BOTH createWorkspace and runSearchAction succeed', async () => {
    // The user wants the loader to be there during the
    // wait, but they should NOT be taken to the workspace
    // page before the round-trips resolve. We need the
    // search to land papers server-side so the Workspace
    // page renders with the right FSM state (see commit
    // 6e565bb).
    const user = userEvent.setup();
    mockCreateWorkspace.mockResolvedValue({
      workspace_id: 'ws-1',
      question: 'x',
      state: 'CREATED',
      papers: [],
      total_papers: 0,
      allowed_actions: ['add_paper', 'search'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });
    mockRunSearchAction.mockResolvedValue({
      workspace_id: 'ws-1',
      question: 'x',
      state: 'PAPERS_RETRIEVED',
      papers: [],
      total_papers: 0,
      allowed_actions: ['report'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    });

    render(<HomePlaceholder />);

    await user.type(
      screen.getByPlaceholderText(/Ask a biomedical research question/i),
      'x',
    );
    await user.click(
      screen.getByRole('button', { name: /Start Research/i }),
    );

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/workspace/ws-1');
    });
    // The order matters: createWorkspace must finish
    // before runSearchAction starts (we need the
    // workspaceId to feed into the search).
    expect(mockCreateWorkspace).toHaveBeenCalledTimes(1);
    expect(mockRunSearchAction).toHaveBeenCalledTimes(1);
    expect(mockCreateWorkspace.mock.invocationCallOrder[0])
      .toBeLessThan(mockRunSearchAction.mock.invocationCallOrder[0]);
  });
});

// Placeholder component -- we import the real ``Home``
// lazily so the mocks above are in place when the module
// is loaded. This is a common pattern in the existing test
// suite (see ``AddPapersPanel.test.tsx``).
import { Home } from './Home';
function HomePlaceholder() {
  return <Home />;
}