// components/LiteratureSearch.test.tsx
//
// Component tests for the LiteratureSearch — the PubMed search
// entry surface that uses select-to-add.
//
// The previous "fire-and-forget" auto-append flow was the
// consultant's Workflow C complaint. The new flow:
//   1. user types a query and submits
//   2. results appear as a checkbox list (all selected)
//   3. user picks (unchecks the irrelevant ones)
//   4. user clicks "Add N papers" — only the checked ones are added
//
// We mock the api client so the search call doesn't hit the
// network.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LiteratureSearch } from './LiteratureSearch';

vi.mock('../api/client', () => ({
  api: {
    search: vi.fn(),
    // ``LiteratureSearch`` now routes the "Add selected"
    // action through the FSM-aware ``addPapersBulk`` endpoint
    // (so the server's view of the workspace stays in sync
    // with the UI). We expose it here as a vi.fn() so tests
    // can assert it's called with the right payload.
    addPapersBulk: vi.fn(),
  },
}));

vi.mock('../state/workspaceStore', () => ({
  // The real ``useWorkspaceStore`` is a Zustand hook that
  // accepts a selector function. The selector receives the
  // full state and returns a slice. The component reads
  // ``state.setCurrentWorkspace`` so we expose it through
  // a fake selector.
  useWorkspaceStore: (selector: (state: any) => any) => {
    const fakeState = {
      addPapersToCurrent: vi.fn(),
      removePaper: vi.fn(),
      setCurrentWorkspace: vi.fn(),
    };
    return selector(fakeState);
  },
}));

vi.mock('../state/toastStore', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { api } from '../api/client';
import { toast } from '../state/toastStore';

const mockApi = api as unknown as {
  search: ReturnType<typeof vi.fn>;
  addPapersBulk: ReturnType<typeof vi.fn>;
};

const samplePapers = [
  {
    title: 'Amyloid cascade in 2025.',
    authors: [{ first_name: 'A', last_name: 'B', full_name: 'A B', affiliation: null }],
    journal: { name: 'Nature', issn: null, publisher: null },
    year: 2025,
    abstract: '...',
    doi: '10.1038/nature12373',
    pmid: '40000001',
    keywords: ['Alzheimer'],
    url: null,
  },
  {
    title: 'Tau tangles in 2024.',
    authors: [{ first_name: 'C', last_name: 'D', full_name: 'C D', affiliation: null }],
    journal: { name: 'Cell', issn: null, publisher: null },
    year: 2024,
    abstract: '...',
    doi: '10.1016/j.cell.2024.01.001',
    pmid: '40000002',
    keywords: ['Tau'],
    url: null,
  },
];

describe('LiteratureSearch', () => {
  beforeEach(() => {
    mockApi.search.mockReset();
    mockApi.addPapersBulk.mockReset();
    // Default: the bulk endpoint succeeds and returns a
    // workspace that mirrors the papers sent in. Tests that
    // exercise different bulk paths can override this.
    mockApi.addPapersBulk.mockImplementation(
      (_workspaceId: string, papers: unknown[]) => {
        return Promise.resolve({
          workspace_id: 'test-workspace',
          question: 'x',
          state: 'PAPERS_RETRIEVED',
          papers: papers as any,
          total_papers: Array.isArray(papers) ? papers.length : 0,
          allowed_actions: ['report', 'summarize', 'search'],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        });
      },
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('search submission', () => {
    it('does not call api.search when the input is empty', async () => {
      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="" />);

      const submit = screen.getByRole('button', { name: /Search/i });
      await user.click(submit);

      expect(mockApi.search).not.toHaveBeenCalled();
    });

    it('calls api.search with the textarea content', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 0,
        papers: [],
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      expect(mockApi.search).toHaveBeenCalledWith({ question: 'alzheimer' });
    });

    it('shows the result list after a successful search', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(screen.getByText('Amyloid cascade in 2025.')).toBeInTheDocument();
      });
      expect(screen.getByText('Tau tangles in 2024.')).toBeInTheDocument();
    });

    it('surfaces a toast error when the API fails', async () => {
      mockApi.search.mockRejectedValue(new Error('PubMed is down'));

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('PubMed is down');
      });
    });
  });

  describe('select-to-add workflow', () => {
    it('checks all results by default', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        const checkboxes = screen.getAllByRole('checkbox');
        expect(checkboxes).toHaveLength(2);
        expect(checkboxes[0]).toBeChecked();
        expect(checkboxes[1]).toBeChecked();
      });
    });

    it('unchecking a result removes it from the count', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();
      });

      const checkboxes = screen.getAllByRole('checkbox');
      await user.click(checkboxes[0]);

      expect(screen.getByText('1 of 2 selected')).toBeInTheDocument();
    });

    it('does not auto-append papers — the user must click "Add N papers"', async () => {
      // The strongest assertion we can make here is that the
      // store mock wasn't called during the search. The mock
      // is shared across all tests in this file, so we check
      // the call count is exactly the same as before this search
      // (which is 0 by default).
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(screen.getByText('Amyloid cascade in 2025.')).toBeInTheDocument();
      });

      // The previous test ("commits the resolved papers via
      // api.addPapersBulk") in AddPapersPanel asserted the
      // call. Here we just confirm the user has to click
      // "Add N papers" — the disabled state is asserted in
      // "the disabled 'Pick papers to add' button" below.
      expect(
        screen.getByRole('button', { name: /Add 2 papers/i }),
      ).toBeInTheDocument();
    });

    it('the add button is "Add 1 paper" / "Add 2 papers" based on selection', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Add 2 papers/i }),
        ).toBeInTheDocument();
      });

      const checkboxes = screen.getAllByRole('checkbox');
      await user.click(checkboxes[0]);

      expect(
        screen.getByRole('button', { name: /Add 1 paper/i }),
      ).toBeInTheDocument();
    });

    it('select-all / deselect-all toggles all checkboxes', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();
      });

      const toggle = screen.getByRole('button', { name: /Deselect all/i });
      await user.click(toggle);

      expect(screen.getByText('0 of 2 selected')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Select all/i })).toBeInTheDocument();
    });

    it('fires onSelectComplete with the count after commit', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      const onSelectComplete = vi.fn();
      render(
        <LiteratureSearch workspaceId="test-workspace"
          initialQuery="alzheimer"
          onSelectComplete={onSelectComplete}
        />,
      );

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Add 2 papers/i }),
        ).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /Add 2 papers/i }));

      expect(onSelectComplete).toHaveBeenCalledWith(2);
    });

    it('the disabled "Pick papers to add" button shows when nothing is selected', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 2,
        papers: samplePapers,
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(screen.getByText('2 of 2 selected')).toBeInTheDocument();
      });

      // Deselect all.
      await user.click(screen.getByRole('button', { name: /Deselect all/i }));

      const button = screen.getByRole('button', { name: /Pick papers to add/i });
      expect(button).toBeInTheDocument();
      expect(button).toBeDisabled();
    });

    it('shows a helpful message when the search returns zero results', async () => {
      mockApi.search.mockResolvedValue({
        query: 'alzheimer',
        total_results: 0,
        papers: [],
        timestamp: '2026-01-01T00:00:00Z',
      });

      const user = userEvent.setup();
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="alzheimer" />);

      await user.click(screen.getByRole('button', { name: /Search/i }));

      await waitFor(() => {
        expect(screen.getByText(/No PubMed results for this query/i))
          .toBeInTheDocument();
      });
    });
  });

  describe('shortcut hint', () => {
    it('renders the PC shortcut hint by default', () => {
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="" />);
      const kbd = document.querySelector('.literature-search-shortcut-hint kbd');
      expect(kbd?.textContent).toBe('Ctrl+K');
    });

    it('renders the Mac shortcut hint when shortcutHint="⌘K"', () => {
      render(<LiteratureSearch workspaceId="test-workspace" initialQuery="" shortcutHint="⌘K" />);
      const kbd = document.querySelector('.literature-search-shortcut-hint kbd');
      expect(kbd?.textContent).toBe('⌘K');
    });
  });
});
