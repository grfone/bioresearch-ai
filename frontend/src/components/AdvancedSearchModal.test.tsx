// components/AdvancedSearchModal.test.tsx
//
// Component tests for the AdvancedSearchModal — the new
// multi-source search modal triggered by clicking "Search
// PubMed" in the action bar.
//
// These tests run in jsdom. They mock the API client and the
// workspace store so the modal can be exercised in isolation.
//
// Coverage
// --------
// - Open / close via prop
// - Default filter shape (no sources = use defaults)
// - Source toggling (with bioRxiv gated behind a date window)
// - Year range, sort order, document type chips
// - Open-access and include-abstracts toggles
// - Reset button restores defaults
// - Submit calls ``api.runSearchAction`` with the filter bundle
// - Escape key closes the modal
// - Backdrop click closes the modal

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AdvancedSearchModal } from './AdvancedSearchModal';

vi.mock('../api/client', () => ({
  api: {
    runSearchAction: vi.fn(),
  },
}));

vi.mock('../state/workspaceStore', () => ({
  useWorkspaceStore: (selector: (state: any) => any) => {
    const fakeState = { addPapersToCurrent: vi.fn() };
    return selector(fakeState);
  },
}));

vi.mock('../state/toastStore', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));
import { toast } from '../state/toastStore';

import { api } from '../api/client';

const mockApi = api as unknown as {
  runSearchAction: ReturnType<typeof vi.fn>;
};

describe('AdvancedSearchModal', () => {
  beforeEach(() => {
    mockApi.runSearchAction.mockReset();
    mockApi.runSearchAction.mockResolvedValue({
      workspace_id: 'ws-1',
      state: 'PAPERS_RETRIEVED',
      allowed_actions: ['add_paper', 'search', 'summarize'],
      papers: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('open/close', () => {
    it('renders nothing when isOpen is false', () => {
      const { container } = render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={false}
          onClose={vi.fn()}
        />,
      );
      expect(container.firstChild).toBeNull();
    });

    it('renders the modal when isOpen is true', () => {
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      expect(
        screen.getByRole('dialog', { name: /advanced search/i }),
      ).toBeInTheDocument();
    });

    it('closes when the X button is clicked', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      await user.click(
        screen.getByRole('button', { name: /close advanced search/i }),
      );
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('closes when the backdrop is clicked', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      // The overlay is the role="dialog" element; clicking it
      // bubbles to the onClose handler. The inner .dialog
      // stops propagation.
      const overlay = screen.getByRole('dialog');
      await user.click(overlay);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('does NOT close when the dialog body is clicked', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      // Click on the title — that's inside the .dialog.
      await user.click(screen.getByText(/Advanced search/i));
      expect(onClose).not.toHaveBeenCalled();
    });

    it('closes on Escape', async () => {
      const onClose = vi.fn();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('default state', () => {
    it('shows all four sources as active by default', () => {
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      // All four source checkboxes are checked.
      const checkboxes = screen.getAllByRole('checkbox', {
        name: /PubMed|OpenAlex|Europe PMC|bioRxiv/,
      });
      expect(checkboxes.length).toBe(4);
      checkboxes.forEach((box) => {
        expect(box).toBeChecked();
      });
    });

    it('defaults to relevance sort', () => {
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const relevanceRadio = screen.getByRole('radio', {
        name: /relevance/i,
      });
      expect(relevanceRadio).toBeChecked();
    });

    it('defaults to max results = 20', () => {
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const num = screen.getByLabelText(/Max results/i);
      expect(num).toHaveValue(20);
    });

    it('restores draftFilters from localStorage on reopen', async () => {
      // Open, set a filter, close, reopen — the filter should
      // be restored (NOT reset to defaults). This is the
      // persistence behaviour: the researcher's last-used
      // filters survive modal opens.
      const user = userEvent.setup();
      const onClose = vi.fn();
      const { rerender } = render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      // Type a year.
      const sinceSelect = screen.getAllByRole('combobox')[0];
      await user.selectOptions(sinceSelect, '2020');
      // Close and reopen.
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={false}
          onClose={onClose}
        />,
      );
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      const sinceSelectAfter = screen.getAllByRole('combobox')[0];
      // The filter is restored, not reset to ''.
      expect(sinceSelectAfter).toHaveValue('2020');
    });

    it('persists year/sort across workspaces but resets the query field', async () => {
      // A researcher who fine-tuned their filters once
      // should not have to re-pick them every time they
      // switch workspaces. But the query field is a
      // one-shot per-modal value that should always start
      // empty (otherwise the modal would pre-fill with a
      // query that no longer matches the new workspace's
      // question).
      const user = userEvent.setup();
      // Step 1: open with workspace A, tweak filters.
      const { rerender } = render(
        <AdvancedSearchModal
          workspaceId="ws-A"
          workspaceQuestion="What is the amyloid cascade hypothesis?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const yearSelectA = screen.getAllByRole('combobox')[0];
      await user.selectOptions(yearSelectA, '2020');
      const queryInputA = screen.getByLabelText(/Search query/i);
      await user.type(queryInputA, 'custom query for A');
      // Close.
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-A"
          workspaceQuestion="What is the amyloid cascade hypothesis?"
          isOpen={false}
          onClose={vi.fn()}
        />,
      );

      // Step 2: re-open with workspace B (different
      // question, different ID).
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-B"
          workspaceQuestion="What is the difference between CRISPR and RNAi?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );

      // The filter bundle persists across workspaces: the
      // year is still '2020'.
      const yearSelectB = screen.getAllByRole('combobox')[0];
      expect(yearSelectB).toHaveValue('2020');

      // The query field starts empty — it should not
      // carry over "custom query for A" from workspace A.
      const queryInputB = screen.getByLabelText(/Search query/i);
      expect(queryInputB).toHaveValue('');
      // And the placeholder shows workspace B's question,
      // not workspace A's.
      expect(queryInputB).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/CRISPR|RNAi/i),
      );
      expect(queryInputB).not.toHaveAttribute(
        'placeholder',
        expect.stringMatching(/amyloid/i),
      );
    });

    it('does not persist the query field even within the same workspace', async () => {
      // Even within the same workspace, a typed query
      // override should be reset on the next modal open.
      // The persisted bundle is the filter structure only.
      const user = userEvent.setup();
      const onClose = vi.fn();
      const { rerender } = render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      const queryInput = screen.getByLabelText(/Search query/i);
      await user.type(queryInput, 'partial');
      // Close.
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={false}
          onClose={onClose}
        />,
      );
      // Reopen.
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      const queryInputAfter = screen.getByLabelText(/Search query/i);
      expect(queryInputAfter).toHaveValue('');
      // The localStorage blob should NOT contain a
      // ``query`` field under the persisted filter
      // bundle's top-level keys.
      const raw = window.localStorage.getItem(
        'bioresearch-ai:advanced-search-filters:v1',
      );
      expect(raw).not.toBeNull();
      const parsed = JSON.parse(raw!);
      expect(parsed).not.toHaveProperty('query');
    });
  });

  describe('source toggling', () => {
    it('unchecks a source when clicked', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const pubmed = screen.getByRole('checkbox', { name: /PubMed/i });
      expect(pubmed).toBeChecked();
      await user.click(pubmed);
      expect(pubmed).not.toBeChecked();
    });

    it('disables bioRxiv when no date window is set', () => {
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const biorxiv = screen.getByRole('checkbox', {
        name: /bioRxiv/i,
      });
      expect(biorxiv).toBeDisabled();
    });

    it('enables bioRxiv once a date window is supplied', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const sinceSelect = screen.getAllByRole('combobox')[0];
      await user.selectOptions(sinceSelect, '2020');
      const biorxiv = screen.getByRole('checkbox', {
        name: /bioRxiv/i,
      });
      expect(biorxiv).not.toBeDisabled();
    });

    it('shows the "chronological dump — set date window" lock on bioRxiv', () => {
      // The lock indicator explains WHY bioRxiv is gated
      // (it's a chronological dump, not a keyword search),
      // not just THAT it is.
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const biorxivLabel = screen
        .getByRole('checkbox', { name: /bioRxiv/i })
        .closest('label');
      expect(biorxivLabel).toBeTruthy();
      expect(biorxivLabel!.textContent).toMatch(/chronological dump/i);
      expect(biorxivLabel!.textContent).toMatch(/date window/i);
      // Tooltip on the lock chip carries the longer hint.
      const lockChip = biorxivLabel!.querySelector(
        '.advanced-search-modal-source-locked',
      );
      expect(lockChip).not.toBeNull();
      expect(lockChip!.getAttribute('title')).toMatch(
        /chronological/i,
      );
    });
  });

  describe('year range', () => {
    it('populates the from-year dropdown with a 30-year range', () => {
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const selects = screen.getAllByRole('combobox');
      const sinceSelect = selects[0] as HTMLSelectElement;
      // The first option is "From (any year)", then years
      // from current year back to 1990.
      const options = Array.from(sinceSelect.options);
      const yearOptions = options
        .map((o) => o.value)
        .filter((v) => v !== '');
      expect(yearOptions.length).toBeGreaterThanOrEqual(30);
      // First year option should be current year.
      const currentYear = new Date().getFullYear();
      expect(yearOptions[0]).toBe(String(currentYear));
    });
  });

  describe('document types', () => {
    it('toggles a doc type when clicked', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const reviewChip = screen.getByRole('button', { name: /Review/i });
      expect(reviewChip).toHaveAttribute('aria-pressed', 'false');
      await user.click(reviewChip);
      expect(reviewChip).toHaveAttribute('aria-pressed', 'true');
    });
  });

  describe('sort order', () => {
    it('switches between relevance and newest_first', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const newestRadio = screen.getByRole('radio', {
        name: /newest first/i,
      });
      await user.click(newestRadio);
      expect(newestRadio).toBeChecked();
      const relevanceRadio = screen.getByRole('radio', {
        name: /relevance/i,
      });
      expect(relevanceRadio).not.toBeChecked();
    });
  });

  describe('reset', () => {
    it('clears all filters back to defaults', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      // Set a filter.
      const newestRadio = screen.getByRole('radio', {
        name: /newest first/i,
      });
      await user.click(newestRadio);
      expect(newestRadio).toBeChecked();
      // Reset.
      const resetBtn = screen.getByRole('button', { name: /^Reset$/ });
      await user.click(resetBtn);
      const relevanceRadio = screen.getByRole('radio', {
        name: /relevance/i,
      });
      expect(relevanceRadio).toBeChecked();
    });

    it('clears the persisted filter bundle in localStorage', async () => {
      // The Reset button should also clear localStorage so a
      // researcher who resets and closes the browser truly
      // has no history. The next modal open starts from
      // defaults and localStorage is empty.
      const user = userEvent.setup();
      // Pre-populate localStorage with non-default filters.
      window.localStorage.setItem(
        'bioresearch-ai:advanced-search-filters:v1',
        JSON.stringify({
          since_year: 2020,
          max_results: 50,
          sort_by: 'newest_first',
        }),
      );
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      // The persisted filters were loaded — verify by setting
      // a filter and clicking Reset.
      const resetBtn = screen.getByRole('button', { name: /^Reset$/ });
      await user.click(resetBtn);
      // localStorage should now be cleared.
      const persisted = window.localStorage.getItem(
        'bioresearch-ai:advanced-search-filters:v1',
      );
      expect(persisted).toBeNull();
    });
  });

  describe('presets', () => {
    it('shows the empty-state hint when no presets exist', () => {
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is X?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      expect(
        screen.getByText(/No saved presets yet/i),
      ).toBeInTheDocument();
    });

    it('saves a preset under the typed name', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is X?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const nameInput = screen.getByLabelText(/New preset name/i);
      await user.type(nameInput, 'My preset');
      const saveBtn = screen.getByRole('button', {
        name: 'Save preset',
      });
      await user.click(saveBtn);
      // The preset is now in the list (state updates are
      // async via setPresets / setPresetName). Use
      // waitFor for both the new preset appearing and the
      // input clearing.
      await waitFor(() => {
        expect(
          screen.getByText('My preset'),
        ).toBeInTheDocument();
      });
      // Re-query the input — React may have swapped the
      // DOM node during the re-render.
      await waitFor(() => {
        expect(
          screen.getByLabelText(/New preset name/i),
        ).toHaveValue('');
      });
      // The localStorage blob is updated.
      const raw = window.localStorage.getItem(
        'bioresearch-ai:adv-search-presets:v1',
      );
      expect(raw).not.toBeNull();
      const parsed = JSON.parse(raw!);
      expect(parsed[0].name).toBe('My preset');
    });

    it('rejects an empty or whitespace-only name', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is X?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const saveBtn = screen.getByRole('button', {
        name: 'Save preset',
      });
      // Disabled by default (empty input).
      expect(saveBtn).toBeDisabled();
      // Whitespace-only name also keeps it disabled.
      const nameInput = screen.getByLabelText(/New preset name/i);
      await user.type(nameInput, '   ');
      expect(saveBtn).toBeDisabled();
    });

    it('loads a preset back into the draftFilters', async () => {
      const user = userEvent.setup();
      // Pre-populate localStorage with a preset.
      window.localStorage.setItem(
        'bioresearch-ai:adv-search-presets:v1',
        JSON.stringify([
          {
            name: 'Saved preset',
            filters: {
              since_year: 2018,
              max_results: 50,
              sort_by: 'newest_first',
              sources: ['openalex'],
            },
            savedAt: 1700000000000,
          },
        ]),
      );
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is X?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      // The preset shows up in the list.
      const loadBtn = screen.getByRole('button', {
        name: /Load preset/i,
      });
      expect(loadBtn).toBeInTheDocument();
      await user.click(loadBtn);
      // The year dropdown now reflects the preset's filter.
      const sinceSelect = screen.getAllByRole('combobox')[0];
      expect(sinceSelect).toHaveValue('2018');
      // The sort order is also picked up.
      const newestRadio = screen.getByRole('radio', {
        name: /newest first/i,
      });
      expect(newestRadio).toBeChecked();
    });

    it('deletes a preset when the trash icon is clicked', async () => {
      const user = userEvent.setup();
      window.localStorage.setItem(
        'bioresearch-ai:adv-search-presets:v1',
        JSON.stringify([
          {
            name: 'Throwaway',
            filters: {
              since_year: 2020,
              max_results: 20,
              sort_by: 'relevance',
              sources: [],
            },
            savedAt: 1700000000000,
          },
        ]),
      );
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is X?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const deleteBtn = screen.getByRole('button', {
        name: /Delete preset Throwaway/i,
      });
      await user.click(deleteBtn);
      await waitFor(() => {
        expect(
          screen.queryByText('Throwaway'),
        ).not.toBeInTheDocument();
      });
      // The empty-state hint is back.
      expect(
        screen.getByText(/No saved presets yet/i),
      ).toBeInTheDocument();
      // The localStorage blob is now an empty list.
      const raw = window.localStorage.getItem(
        'bioresearch-ai:adv-search-presets:v1',
      );
      expect(JSON.parse(raw!)).toEqual([]);
    });

    it('refreshes the preset list when the modal reopens', async () => {
      // Save a preset in modal 1.
      const user = userEvent.setup();
      const { rerender } = render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="X"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      await user.type(
        screen.getByLabelText(/New preset name/i),
        'Session 1 preset',
      );
      await user.click(
        screen.getByRole('button', { name: 'Save preset' }),
      );
      // Wait for the input to clear (state has updated).
      await waitFor(() => {
        expect(
          screen.getByLabelText(/New preset name/i),
        ).toHaveValue('');
      });
      // Close.
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="X"
          isOpen={false}
          onClose={vi.fn()}
        />,
      );
      // Open again.
      rerender(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="X"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      expect(screen.getByText('Session 1 preset')).toBeInTheDocument();
    });
  });

  describe('submit', () => {
    it('calls runSearchAction with the workspace question when no override is typed', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      const submitBtn = screen.getByRole('button', { name: /^Search$/i });
      await user.click(submitBtn);
      await waitFor(() => {
        expect(mockApi.runSearchAction).toHaveBeenCalledTimes(1);
      });
      const [workspaceId, query, filters] =
        mockApi.runSearchAction.mock.calls[0];
      expect(workspaceId).toBe('ws-1');
      // Empty override → null is sent; backend falls back to
      // the workspace's existing question.
      expect(query).toBeNull();
      expect(filters).toBeDefined();
      expect(filters.sort_by).toBe('relevance');
      // No sources specified (empty list = use defaults).
      expect(filters.sources).toEqual([]);
    });

    it('passes the override query when the user types one', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const queryInput = screen.getByLabelText(/Search query/i);
      await user.type(queryInput, 'amyloid cascade 2024');
      const submitBtn = screen.getByRole('button', { name: /^Search$/i });
      await user.click(submitBtn);
      await waitFor(() => {
        expect(mockApi.runSearchAction).toHaveBeenCalledTimes(1);
      });
      const [, query] = mockApi.runSearchAction.mock.calls[0];
      expect(query).toBe('amyloid cascade 2024');
    });

    it('passes year range and document type filters', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      // Set year range.
      const selects = screen.getAllByRole('combobox');
      await user.selectOptions(selects[0], '2020');
      await user.selectOptions(selects[1], '2024');
      // Toggle a doc type.
      await user.click(
        screen.getByRole('button', { name: /Review/i }),
      );
      // Submit.
      const submitBtn = screen.getByRole('button', { name: /^Search$/i });
      await user.click(submitBtn);
      await waitFor(() => {
        expect(mockApi.runSearchAction).toHaveBeenCalledTimes(1);
      });
      const [, , filters] = mockApi.runSearchAction.mock.calls[0];
      expect(filters.since_year).toBe(2020);
      expect(filters.until_year).toBe(2024);
      expect(filters.document_types).toEqual(['review']);
    });

    it('passes restricted source set when the user unchecks sources', async () => {
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      // Uncheck PubMed and OpenAlex.
      await user.click(screen.getByRole('checkbox', { name: /PubMed/i }));
      await user.click(
        screen.getByRole('checkbox', { name: /OpenAlex/i }),
      );
      const submitBtn = screen.getByRole('button', { name: /^Search$/i });
      await user.click(submitBtn);
      await waitFor(() => {
        expect(mockApi.runSearchAction).toHaveBeenCalledTimes(1);
      });
      const [, , filters] = mockApi.runSearchAction.mock.calls[0];
      // sources is the explicit restricted set.
      expect(filters.sources).toEqual(['europe_pmc', 'biorxiv']);
    });

    it('closes the modal on successful submit', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={onClose}
        />,
      );
      const submitBtn = screen.getByRole('button', { name: /^Search$/i });
      await user.click(submitBtn);
      await waitFor(() => {
        expect(onClose).toHaveBeenCalledTimes(1);
      });
    });

    it('toasts an error if the search fails', async () => {
      const user = userEvent.setup();
      mockApi.runSearchAction.mockRejectedValue(
        new Error('Network error'),
      );
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const submitBtn = screen.getByRole('button', { name: /^Search$/i });
      await user.click(submitBtn);
      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(
          expect.stringMatching(/Network error/),
        );
      });
    });

    it('disables the submit button while a search is in flight', async () => {
      // Mock a slow-resolving promise.
      let resolveSearch: ((value: unknown) => void) | null = null;
      mockApi.runSearchAction.mockReturnValue(
        new Promise((resolve) => {
          resolveSearch = resolve;
        }),
      );
      const user = userEvent.setup();
      render(
        <AdvancedSearchModal
          workspaceId="ws-1"
          workspaceQuestion="What is GLP-1?"
          isOpen={true}
          onClose={vi.fn()}
        />,
      );
      const submitBtn = screen.getByRole('button', { name: /^Search$/i });
      await user.click(submitBtn);
      // While pending, the button label changes to
      // "Searching…" and is disabled.
      const searchingBtn = await screen.findByRole('button', {
        name: /Searching/i,
      });
      expect(searchingBtn).toBeDisabled();
      // Resolve the promise so the test cleans up.
      resolveSearch!({});
    });
  });
});
