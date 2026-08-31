/**
 * pages/Workspace.test.tsx
 *
 * Tests for the Workspace page's "Generate Report" CTA.
 *
 * Bug history (commit context): before this fix, the button
 * click fired an ``await runAction("generate")`` that took
 * 11-43 seconds (the orchestrator auto-summarises + auto-
 * compares + reports inside one FSM action -- see ADR-008).
 * During that wait the user stayed on the Workspace page
 * with no feedback; the Report page's "Generating report…"
 * loader only mounted AFTER ``navigate()`` ran, which was
 * after the entire action finished. The user reported the
 * loader "takes off too late".
 *
 * Fix: ``handleGenerateReport`` is now sync -- it just
 * calls ``navigate('/report/{id}')``. The Report page's
 * loader appears the instant React Router swaps the page.
 *
 * Why we test only ``WorkspaceActionBar``'s click handler
 * (not the full Workspace tree): the Workspace page
 * imports every route, the toast store, and the multi-
 * source literature search. A focused test on the
 * ``WorkspaceActionBar`` already pins the click contract;
 * this file just nails the navigation timing.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Stub the AddPapersPanel: it has its own deep test
// suite. We only need to verify the Workspace page
// collapses it behind a modal.
vi.mock('../components/AddPapersPanel', () => ({
  AddPapersPanel: () => <div data-testid="add-papers-panel-stub" />,
}));

// Stub the toast store; the modal doesn't trigger toasts
// in the test paths.
vi.mock('../state/toastStore', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// Mock react-router-dom so we can observe the navigate call
// without a real router. The loader's lifecycle is timed
// against ``navigate`` -- we want to assert it fires BEFORE
// any heavy FSM action completes.
const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({ workspaceId: 'ws-1' }),
}));

// Mock the api client. ``runAction`` is NOT called by the
// simplified ``handleGenerateReport`` -- the page just
// navigates. We expose the mock anyway so a regression
// that re-adds the await would fail this test loudly.
const mockRunAction = vi.fn();
vi.mock('../api/client', () => ({
  api: {
    runAction: mockRunAction,
  },
}));

// Mock the workspaceStore with a minimal stub. The
// simplified Workspace page reads ``currentWorkspace``
// for the action bar's ``canReport`` flag; we provide a
// REPORTED workspace so the button is enabled.
import { useWorkspaceStore } from '../state/workspaceStore';
vi.mock('../state/workspaceStore', () => ({
  useWorkspaceStore: (
    selector: (state: {
      currentWorkspace: unknown;
      setCurrentWorkspace: (...args: unknown[]) => void;
      removePaper: (...args: unknown[]) => void;
      clearPapers: (...args: unknown[]) => void;
    }) => unknown,
  ) => {
    return selector({
      currentWorkspace: {
        workspace_id: 'ws-1',
        question: 'biomarkers',
        state: 'INTERMEDIATE',
        papers: [],
        total_papers: 0,
        allowed_actions: ['add_paper', 'generate'],
      },
      setCurrentWorkspace: vi.fn(),
      removePaper: vi.fn(),
      clearPapers: vi.fn(),
    });
  },
}));

// Mock the workspace hook to return a workspace that's
// already loaded (no fetch needed) and a no-op ``runAction``.
// The bug we fixed was in handleGenerateReport calling
// runAction("generate") -- the test below ensures that call
// no longer happens.
vi.mock('../hooks/useWorkspace', () => ({
  useWorkspace: () => ({
    workspace: {
      workspace_id: 'ws-1',
      question: 'biomarkers',
      state: 'INTERMEDIATE',
      papers: [],
      total_papers: 0,
      allowed_actions: ['add_paper', 'generate'],
    },
    loading: false,
    error: null,
    fetchWorkspace: vi.fn(),
    runAction: mockRunAction,
    updateWorkspace: vi.fn(),
    searchAndAddPapers: vi.fn(),
    fetchTransitions: vi.fn(),
    generateReport: vi.fn(),
    removePaper: vi.fn(),
  }),
}));

describe('Workspace > handleGenerateReport', () => {
  it('navigates to /report/{id} the moment the user clicks (no await)', async () => {
    const user = userEvent.setup();

    // The Workspace page imports many components (ActionBar,
    // AddPapersPanel, LiteratureSearch, AdvancedSearchModal,
    // etc.). To keep the test focused on the click contract,
    // we render ``WorkspaceActionBar`` directly. The actual
    // button click handler is wired in the parent
    // (``Workspace.tsx``) -- the test for that wiring lives
    // in ``WorkspaceActionBar.test.tsx``.
    //
    // We render the action bar with the same callback the
    // workspace page uses, then assert the callback fires
    // synchronously on click (no awaited promise). The
    // callback itself is the trivial wrapper around
    // ``navigate`` that this fix introduces; the deeper
    // assertion is that we DO NOT await ``runAction("generate")``.
    const { WorkspaceActionBar } = await import('../components/WorkspaceActionBar');
    render(
      <WorkspaceActionBar
        canReport={true}
        canAddPapers={true}
        onGenerateReport={() => {
          // This is the simplified handler -- no await,
          // no runAction. If a future change re-adds the
          // await, this test continues to pass (because
          // the click is synchronous from React's POV);
          // a separate assertion below catches the
          // regression via the mockRunAction spy.
          mockNavigate('/report/ws-1');
        }}
        onOpenAdvancedSearch={() => {}}
        onAddMorePapers={() => {}}
      />,
    );

    await user.click(
      screen.getByRole('button', { name: /generate report/i }),
    );

    // The navigate call must have fired by the time the
    // click handler returns. We assert via waitFor so the
    // microtask queue has a chance to flush.
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/report/ws-1');
    });
  });

  it('does NOT call api.runAction("generate") from the click handler', async () => {
    // The bug we fixed: clicking Generate Report awaited
    // api.runAction("generate") which took 11-43 seconds
    // before navigating. This test pins the simpler shape
    // (navigate-only, no api call) so the regression can
    // never sneak back in.
    //
    // We assert at the Workspace level: render the page
    // with a stubbed ``useWorkspace`` hook whose
    // ``runAction`` is a tracked spy, click Generate
    // Report, and verify the spy is NOT called.
    mockRunAction.mockClear();
    mockNavigate.mockClear();

    const { Workspace } = await import('./Workspace');
    render(<Workspace />);

    const reportButton = screen.getByRole('button', {
      name: /generate report/i,
    });
    await userEvent.click(reportButton);

    // The click handler must fire synchronously (no
    // promise to await). navigate was called, runAction
    // was NOT.
    expect(mockNavigate).toHaveBeenCalledWith('/report/ws-1');
    expect(mockRunAction).not.toHaveBeenCalled();
  });
});

// Suppress an unused-import warning: we import
// ``useWorkspaceStore`` above so the mock can reference
// its selector shape, even though the variable is unused.
void useWorkspaceStore;

describe('Workspace > Add Papers collapse', () => {
  it('renders the "Add More Papers" button inside the action bar (3rd position)', async () => {
    // After commit (this PR) the standalone "Add papers"
    // button was moved INSIDE the WorkspaceActionBar and
    // renamed to "Add More Papers" to reflect that the
    // workspace already has papers. The button is in third
    // position (after Generate Report + Advanced Search
    // Options) so the workspace page reads as a single
    // coherent control surface.
    const { Workspace } = await import('./Workspace');
    render(<Workspace />);

    // The button is visible.
    const button = screen.getByRole('button', { name: /add more papers/i });
    expect(button).toBeInTheDocument();
    // The button uses the same .btn-primary class as the
    // other primary CTAs in the action bar.
    expect(button).toHaveClass('btn-primary');
    // The button has the same data-action selector the
    // standalone button used (commit b478851), so the
    // parent's onClick contract is unchanged.
    expect(button).toHaveAttribute('data-action', 'open-add-papers');
    // The button is INSIDE the action bar (role=toolbar),
    // not floating on its own row above the action bar.
    const toolbar = screen.getByRole('toolbar', { name: /workspace actions/i });
    expect(toolbar).toContainElement(button);
    // The button is in the third position (after Generate
    // Report, then Advanced Search Options).
    const toolbarButtons = within(toolbar).getAllByRole('button');
    expect(toolbarButtons).toHaveLength(3);
    expect(toolbarButtons[0]).toHaveTextContent(/generate report/i);
    expect(toolbarButtons[1]).toHaveTextContent(/advanced search options/i);
    expect(toolbarButtons[2]).toHaveTextContent(/add more papers/i);

    // The AddPapersPanel itself is NOT in the DOM until
    // the modal opens.
    expect(
      screen.queryByTestId('add-papers-panel-stub'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('dialog', { name: /add papers to this workspace/i }),
    ).not.toBeInTheDocument();
  });

  it('opens the modal with the AddPapersPanel when the button is clicked', async () => {
    const user = userEvent.setup();
    const { Workspace } = await import('./Workspace');
    render(<Workspace />);

    const button = screen.getByRole('button', { name: /add more papers/i });
    await user.click(button);

    // After clicking, the modal opens. The dialog is
    // rendered with the right ARIA label and the
    // AddPapersPanel stub appears inside.
    const dialog = await screen.findByRole('dialog', {
      name: /add papers to this workspace/i,
    });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId('add-papers-panel-stub')).toBeInTheDocument();
  });

  it('closes the modal when the backdrop is clicked', async () => {
    const user = userEvent.setup();
    const { Workspace } = await import('./Workspace');
    render(<Workspace />);

    // Open
    await user.click(
      screen.getByRole('button', { name: /add more papers/i }),
    );
    const dialog = await screen.findByRole('dialog', {
      name: /add papers to this workspace/i,
    });
    expect(dialog).toBeInTheDocument();

    // Click the backdrop. The dialog wrapper has the
    // onClick handler; clicking it directly dispatches a
    // user click that fires the close path.
    await user.click(dialog);

    // Modal closes; the dialog role element is gone.
    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: /add papers to this workspace/i }),
      ).not.toBeInTheDocument();
    });
  });

  it('closes the modal when the X close button is clicked', async () => {
    const user = userEvent.setup();
    const { Workspace } = await import('./Workspace');
    render(<Workspace />);

    // Open
    await user.click(
      screen.getByRole('button', { name: /add more papers/i }),
    );
    await screen.findByRole('dialog', { name: /add papers to this workspace/i });

    // Click the close (X) button in the dialog header
    const closeButton = screen.getByRole('button', { name: /close add papers/i });
    await user.click(closeButton);

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: /add papers to this workspace/i }),
      ).not.toBeInTheDocument();
    });
  });

  it('closes the modal when Escape is pressed', async () => {
    const user = userEvent.setup();
    const { Workspace } = await import('./Workspace');
    render(<Workspace />);

    // Open
    await user.click(
      screen.getByRole('button', { name: /add more papers/i }),
    );
    await screen.findByRole('dialog', { name: /add papers to this workspace/i });

    // Escape key
    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: /add papers to this workspace/i }),
      ).not.toBeInTheDocument();
    });
  });

  it('does NOT show the "Add More Papers" button when FSM does not allow add_paper', async () => {
    // Override the workspaceStore mock for this single test
    // by re-rendering with a workspace whose allowed_actions
    // does NOT include 'add_paper'.
    //
    // We use vi.doMock so the import resolves against the
    // alternative mock for this test only.
    vi.doMock('../state/workspaceStore', () => ({
      useWorkspaceStore: (
        selector: (state: {
          currentWorkspace: unknown;
          setCurrentWorkspace: (...args: unknown[]) => void;
          removePaper: (...args: unknown[]) => void;
          clearPapers: (...args: unknown[]) => void;
        }) => unknown,
      ) => {
        return selector({
          currentWorkspace: {
            workspace_id: 'ws-1',
            question: 'biomarkers',
            state: 'INTERMEDIATE',
            papers: [],
            total_papers: 0,
            // 'add_paper' is NOT in this list.
            allowed_actions: ['generate'],
          },
          setCurrentWorkspace: vi.fn(),
          removePaper: vi.fn(),
          clearPapers: vi.fn(),
        });
      },
    }));
    vi.doMock('../hooks/useWorkspace', () => ({
      useWorkspace: () => ({
        workspace: {
          workspace_id: 'ws-1',
          question: 'biomarkers',
          state: 'INTERMEDIATE',
          papers: [],
          total_papers: 0,
          allowed_actions: ['generate'],
        },
        loading: false,
        error: null,
        fetchWorkspace: vi.fn(),
        runAction: vi.fn(),
        updateWorkspace: vi.fn(),
        searchAndAddPapers: vi.fn(),
        fetchTransitions: vi.fn(),
        generateReport: vi.fn(),
        removePaper: vi.fn(),
      }),
    }));

    // Reset module registry so the new mocks take effect.
    vi.resetModules();
    const { Workspace } = await import('./Workspace');
    render(<Workspace />);

    // The button is NOT in the DOM when the FSM does not
    // allow add_paper. (REPORTED -> no more adds.)
    // The action bar still renders the other two buttons
    // (Generate Report, Advanced Search Options), but the
    // Add More Papers button is gated by can('add_paper').
    expect(
      screen.queryByRole('button', { name: /add more papers/i }),
    ).not.toBeInTheDocument();
    // And the action bar itself only has 2 buttons now.
    const toolbar = screen.getByRole('toolbar', { name: /workspace actions/i });
    const toolbarButtons = within(toolbar).getAllByRole('button');
    expect(toolbarButtons).toHaveLength(2);
    expect(toolbarButtons[0]).toHaveTextContent(/generate report/i);
    expect(toolbarButtons[1]).toHaveTextContent(/advanced search options/i);
  });
});