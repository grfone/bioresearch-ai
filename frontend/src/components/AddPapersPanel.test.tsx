// components/AddPapersPanel.test.tsx
//
// Component tests for the AddPapersPanel — the primary paper-
// entry surface for the workspace.
//
// These tests run in jsdom. They mock the ``api`` client so
// the network calls don't hit the real backend, and they
// exercise the user-visible behaviour: bulk DOI paste, PDF
// drag-and-drop, title-fallback after a no-identifier upload,
// and per-tab rendering.
//
// We can't run the full Workspace tree here because it pulls in
// every route. The panel is exercised in isolation, which is
// the right granularity for these tests.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AddPapersPanel } from './AddPapersPanel';

// Mock the API client so resolver calls don't hit the network.
// ``APIError`` is exported so consumers can distinguish error
// codes (``no_identifiers_found``, ``title_no_confident_match``)
// without string-matching the message; we re-export the same
// shape so panel tests can construct real instances.
vi.mock('../api/client', () => ({
  api: {
    resolvePapers: vi.fn(),
    addPapersBulk: vi.fn(),
    addPaper: vi.fn(),
    uploadPdf: vi.fn(),
    addPaperByTitle: vi.fn(),
  },
  APIError: class APIError extends Error {
    status: number;
    detail: unknown;
    constructor(status: number, detail: unknown, message: string) {
      super(message);
      this.name = 'APIError';
      this.status = status;
      this.detail = detail;
    }
  },
}));

import { api, APIError as MockAPIError } from '../api/client';

const mockApi = api as unknown as {
  resolvePapers: ReturnType<typeof vi.fn>;
  addPapersBulk: ReturnType<typeof vi.fn>;
  addPaper: ReturnType<typeof vi.fn>;
  uploadPdf: ReturnType<typeof vi.fn>;
  addPaperByTitle: ReturnType<typeof vi.fn>;
};

// Mock the workspace store so we don't need a real
// Zustand context. The component now mirrors the
// server's ``WorkspaceResponse`` via
// ``setCurrentWorkspace`` (commit 6e565bb + this commit
// fix the FSM-aware local-mirror pattern across the
// whole workspace page). We expose both
// ``addPapersToCurrent`` (legacy) and
// ``setCurrentWorkspace`` (current) so the test can
// assert which one is called per path.
vi.mock('../state/workspaceStore', () => ({
  useWorkspaceStore: (selector: (state: any) => any) => {
    return selector(mockWorkspaceStoreState);
  },
}));

// Mock the toast store so we don't need a ToastProvider.
// We import the mocked module after the mock is hoisted so
// the spy is stable across tests.
vi.mock('../state/toastStore', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));
import { toast } from '../state/toastStore';

// Hoisted shared mock state so individual tests can assert
// against ``setCurrentWorkspace`` (the new FSM-aware
// local-mirror) and ``addPapersToCurrent`` (the legacy
// local-push). Without this, the inline closure inside the
// vi.mock factory creates a fresh object per call, and the
// tests can't reach the same mock instance as the component
// under test.
const { mockWorkspaceStoreState } = vi.hoisted(() => ({
  mockWorkspaceStoreState: {
    addPapersToCurrent: vi.fn(),
    setCurrentWorkspace: vi.fn(),
    removePaper: vi.fn(),
  },
}));

describe('AddPapersPanel', () => {
  beforeEach(() => {
    mockApi.resolvePapers.mockReset();
    mockApi.addPapersBulk.mockReset();
    mockApi.addPaper.mockReset();
    mockApi.uploadPdf.mockReset();
    mockApi.addPaperByTitle.mockReset();
    mockWorkspaceStoreState.addPapersToCurrent.mockReset();
    mockWorkspaceStoreState.setCurrentWorkspace.mockReset();
    mockWorkspaceStoreState.removePaper.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('rendering', () => {
    it('renders the two tabs (DOI, PDF)', () => {
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );
      expect(screen.getByRole('tab', { name: /^DOI$/i }))
        .toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /PDF/i }))
        .toBeInTheDocument();
      // The Manual tab is gone — the panel exposes DOI + PDF only.
      expect(screen.queryByRole('tab', { name: /Manual/i }))
        .not.toBeInTheDocument();
    });

    it('the DOI tab is the default', () => {
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );
      const doiTab = screen.getByRole('tab', { name: /^DOI$/i });
      expect(doiTab)
        .toHaveAttribute('aria-selected', 'true');
    });

    it('renders nothing when disabled', () => {
      const { container } = render(
        <AddPapersPanel workspaceId="ws-1" enabled={false} />,
      );
      // The panel uses ``return null`` when disabled.
      expect(container.firstChild).toBeNull();
    });

    it('shows the Ctrl+K shortcut hint by default', () => {
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );
      // The hint is ``Tip: press <kbd>Ctrl+K</kbd> from anywhere to
      // focus this input.`` The default platform is PC.
      const kbd = document.querySelector('.add-papers-shortcut-hint kbd');
      expect(kbd).toBeInTheDocument();
      expect(kbd?.textContent).toBe('Ctrl+K');
    });

    it('shows the Mac shortcut hint when shortcutHint="⌘K"', () => {
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} shortcutHint="⌘K" />,
      );
      const kbd = document.querySelector('.add-papers-shortcut-hint kbd');
      expect(kbd?.textContent).toBe('⌘K');
    });

    it('DOI textarea placeholder shows both valid DOI forms (no bad prefix examples)', () => {
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );
      const textarea = screen.getByLabelText(/DOI list/i);
      const placeholder = textarea.getAttribute('placeholder') ?? '';
      // Bare DOI form
      expect(placeholder).toMatch(/10\.1038\/s41591-023-02505-2/);
      // Full https://doi.org/... form
      expect(placeholder).toMatch(
        /https:\/\/doi\.org\/10\.1038\/s41591-023-02505-2/,
      );
      // Neither the bad "di:" nor the old "doi:" prefix should
      // appear in the placeholder — researchers have to type
      // the bare DOI or paste the full https://doi.org/... URL.
      expect(placeholder).not.toMatch(/^\s*di:/im);
      expect(placeholder).not.toMatch(/^\s*doi:/im);
    });
  });

  describe('DOI bulk tab', () => {
    it('shows the textarea and Resolve button', () => {
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );
      expect(
        screen.getByLabelText(/DOI list/i),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /Resolve DOIs/i }),
      ).toBeInTheDocument();
    });

    it('disables the Resolve button when the textarea is empty', () => {
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );
      const button = screen.getByRole('button', { name: /Resolve DOIs/i });
      expect(button).toBeDisabled();
    });

    it('calls api.resolvePapers with the textarea content', async () => {
      const user = userEvent.setup();
      mockApi.resolvePapers.mockResolvedValue({
        results: [],
        resolved_count: 0,
        failed_count: 0,
      });

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      const textarea = screen.getByLabelText(/DOI list/i);
      await user.type(textarea, '10.1038/nature12373\n10.1126/science.1566067\nbogus-doi');

      const button = screen.getByRole('button', { name: /Resolve DOIs/i });
      await user.click(button);

      expect(mockApi.resolvePapers).toHaveBeenCalledWith(
        'ws-1',
        ['10.1038/nature12373', '10.1126/science.1566067', 'bogus-doi'],
      );
    });

    it('parses comma-separated DOIs on a single line', async () => {
      const user = userEvent.setup();
      mockApi.resolvePapers.mockResolvedValue({
        results: [],
        resolved_count: 0,
        failed_count: 0,
      });

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      const textarea = screen.getByLabelText(/DOI list/i);
      await user.type(textarea, '10.1038/a, 10.1038/b, 10.1038/c');

      await user.click(
        screen.getByRole('button', { name: /Resolve DOIs/i }),
      );

      expect(mockApi.resolvePapers).toHaveBeenCalledWith(
        'ws-1',
        ['10.1038/a', '10.1038/b', '10.1038/c'],
      );
    });

    it('displays per-identifier results with green/red chips', async () => {
      const user = userEvent.setup();
      mockApi.resolvePapers.mockResolvedValue({
        results: [
          {
            resolved: {
              identifier: '10.1038/nature12373',
              identifier_type: 'doi',
              paper: {
                title: 'A real paper.',
                authors: [],
                journal: null,
                year: null,
                abstract: '',
                doi: '10.1038/nature12373',
                pmid: null,
                keywords: [],
                url: null,
              },
            },
            failed: null,
          },
          {
            resolved: null,
            failed: {
              identifier: '10.9999/bogus',
              reason: 'CrossRef returned no record',
            },
          },
        ],
        resolved_count: 1,
        failed_count: 1,
      });

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      await user.type(
        screen.getByLabelText(/DOI list/i),
        '10.1038/nature12373\n10.9999/bogus',
      );
      await user.click(
        screen.getByRole('button', { name: /Resolve DOIs/i }),
      );

      await waitFor(() => {
        expect(screen.getByText('1 resolved')).toBeInTheDocument();
        expect(screen.getByText('1 failed')).toBeInTheDocument();
      });

      expect(screen.getByText('10.1038/nature12373')).toBeInTheDocument();
      expect(screen.getByText('10.9999/bogus')).toBeInTheDocument();
      expect(screen.getByText('A real paper.')).toBeInTheDocument();
      expect(screen.getByText('CrossRef returned no record'))
        .toBeInTheDocument();
    });

    it('commits the resolved papers via api.addPapersBulk', async () => {
      const user = userEvent.setup();
      const resolvedPaper = {
        title: 'A real paper.',
        authors: [],
        journal: null,
        year: null,
        abstract: '',
        doi: '10.1038/nature12373',
        pmid: null,
        keywords: [],
        url: null,
      };
      mockApi.resolvePapers.mockResolvedValue({
        results: [
          {
            resolved: {
              identifier: '10.1038/nature12373',
              identifier_type: 'doi',
              paper: resolvedPaper,
            },
            failed: null,
          },
        ],
        resolved_count: 1,
        failed_count: 0,
      });
      mockApi.addPapersBulk.mockResolvedValue({
        workspace_id: 'ws-1',
        papers: [resolvedPaper],
      });

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      await user.type(
        screen.getByLabelText(/DOI list/i),
        '10.1038/nature12373',
      );
      await user.click(
        screen.getByRole('button', { name: /Resolve DOIs/i }),
      );

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Add 1 resolved paper/i }))
          .toBeInTheDocument();
      });

      await user.click(
        screen.getByRole('button', { name: /Add 1 resolved paper/i }),
      );

      expect(mockApi.addPapersBulk).toHaveBeenCalledWith(
        'ws-1',
        [resolvedPaper],
      );
    });

    it('surfaces a toast error when the resolver fails', async () => {
      const user = userEvent.setup();
      mockApi.resolvePapers.mockRejectedValue(new Error('Network error'));

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      await user.type(
        screen.getByLabelText(/DOI list/i),
        '10.1038/nature12373',
      );
      await user.click(
        screen.getByRole('button', { name: /Resolve DOIs/i }),
      );

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Network error');
      });
    });

    it('mirrors the server response via setCurrentWorkspace (FSM-aware)', async () => {
      // Regression test for the "Generate Report button stayed
      // greyed out after I added a paper" bug: the panel
      // used to call ``addPapersToCurrent(response.papers)``
      // (local-push only) which left ``workspace.state`` /
      // ``allowed_actions`` stale. It must instead call
      // ``setCurrentWorkspace(response)`` so the workspace
      // page re-renders with the post-add FSM state and the
      // Generate Report button becomes enabled. See commit
      // 6e565bb for the sibling fix on the search paths.
      const user = userEvent.setup();
      const resolvedPaper = {
        title: 'A real paper.',
        authors: [],
        journal: null,
        year: null,
        abstract: '',
        doi: '10.1038/nature12373',
        pmid: null,
        keywords: [],
        url: null,
      };
      mockApi.resolvePapers.mockResolvedValue({
        results: [
          {
            resolved: {
              identifier: '10.1038/nature12373',
              identifier_type: 'doi',
              paper: resolvedPaper,
            },
            failed: null,
          },
        ],
        resolved_count: 1,
        failed_count: 0,
      });
      const serverWorkspace = {
        workspace_id: 'ws-1',
        question: 'x',
        state: 'INTERMEDIATE',
        papers: [resolvedPaper],
        total_papers: 1,
        allowed_actions: ['report', 'summarize', 'search'],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      };
      mockApi.addPapersBulk.mockResolvedValue(serverWorkspace);

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      await user.type(
        screen.getByLabelText(/DOI list/i),
        '10.1038/nature12373',
      );
      await user.click(
        screen.getByRole('button', { name: /Resolve DOIs/i }),
      );

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Add 1 resolved paper/i }),
        ).toBeInTheDocument();
      });

      await user.click(
        screen.getByRole('button', { name: /Add 1 resolved paper/i }),
      );

      // The fix: the panel must call setCurrentWorkspace with
      // the full server response, NOT the legacy
      // addPapersToCurrent(response.papers) local-push.
      expect(
        mockWorkspaceStoreState.setCurrentWorkspace,
      ).toHaveBeenCalledWith(serverWorkspace);
      expect(
        mockWorkspaceStoreState.addPapersToCurrent,
      ).not.toHaveBeenCalled();
    });
  });

  describe('PDF tab', () => {
    it('renders a drop zone with a hidden file input', async () => {
      const user = userEvent.setup();
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      await user.click(screen.getByRole('tab', { name: /PDF/i }));

      const dropZone = document.querySelector('.add-papers-pdf-drop');
      expect(dropZone).toBeInTheDocument();
      // The drop zone contains a file input that's hidden via
      // inline style. We can still find it.
      const fileInput = screen.getByLabelText(/Drop a PDF here/i)
        .closest('label')
        ?.querySelector('input[type="file"]');
      expect(fileInput).toBeInTheDocument();
      expect((fileInput as HTMLInputElement)?.accept).toBe('application/pdf');
    });

    it('rejects files that are not PDFs', async () => {
      // ``userEvent.upload`` doesn't reliably set files on
      // hidden inputs in jsdom (a known limitation). Use
      // ``fireEvent.change`` with a manually constructed
      // DataTransfer so the panel's onChange handler fires
      // exactly as it would in a real browser.
      const user = userEvent.setup();
      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      await user.click(screen.getByRole('tab', { name: /PDF/i }));

      const fileInput = screen.getByLabelText(/Drop a PDF here/i)
        .closest('label')
        ?.querySelector('input[type="file"]') as HTMLInputElement;

      const file = new File(['hello'], 'test.txt', { type: 'text/plain' });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        const errorEls = document.querySelectorAll('.add-papers-pdf-status--error');
        expect(errorEls.length).toBeGreaterThan(0);
      });
      expect(mockApi.uploadPdf).not.toHaveBeenCalled();
    });

    it('calls api.uploadPdf on a valid PDF', async () => {
      mockApi.uploadPdf.mockResolvedValue({
        workspace_id: 'ws-1',
        papers: [
          { title: 'From PDF', doi: '10.1038/nature12373', pmid: null },
        ],
      });

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      const user = userEvent.setup();
      await user.click(screen.getByRole('tab', { name: /PDF/i }));

      const fileInput = screen.getByLabelText(/Drop a PDF here/i)
        .closest('label')
        ?.querySelector('input[type="file"]') as HTMLInputElement;

      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(mockApi.uploadPdf).toHaveBeenCalledWith('ws-1', file);
      });
    });

    it('mirrors the server response via setCurrentWorkspace (FSM-aware)', async () => {
      // The user's exact reproduction: "I just added a paper
      // and the Generate Report button got greyed out."
      // The panel used to call
      // ``addPapersToCurrent(response.papers)`` which only
      // pushed the new paper into local state but left the
      // workspace FSM stuck at CREATED (no ``report`` in
      // ``allowed_actions``). It must instead mirror the
      // full server response so the workspace page
      // re-renders with the post-add FSM state.
      const serverWorkspace = {
        workspace_id: 'ws-1',
        question: 'x',
        state: 'INTERMEDIATE',
        papers: [
          { title: 'From PDF', doi: '10.1038/nature12373', pmid: null },
        ],
        total_papers: 21,
        allowed_actions: [
          'add_paper', 'remove_paper', 'report', 'search', 'summarize',
        ],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      };
      mockApi.uploadPdf.mockResolvedValue(serverWorkspace);

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      const user = userEvent.setup();
      await user.click(screen.getByRole('tab', { name: /PDF/i }));

      const fileInput = screen.getByLabelText(/Drop a PDF here/i)
        .closest('label')
        ?.querySelector('input[type="file"]') as HTMLInputElement;

      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          mockWorkspaceStoreState.setCurrentWorkspace,
        ).toHaveBeenCalledWith(serverWorkspace);
      });
      expect(
        mockWorkspaceStoreState.addPapersToCurrent,
      ).not.toHaveBeenCalled();
    });

    it('shows the extractor error from the API', async () => {
      mockApi.uploadPdf.mockRejectedValue(
        new Error("Couldn't find a DOI on the first page."),
      );

      render(
        <AddPapersPanel workspaceId="ws-1" enabled={true} />,
      );

      const user = userEvent.setup();
      await user.click(screen.getByRole('tab', { name: /PDF/i }));

      const fileInput = screen.getByLabelText(/Drop a PDF here/i)
        .closest('label')
        ?.querySelector('input[type="file"]') as HTMLInputElement;

      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          screen.getByText(/Couldn't find a DOI on the first page/i),
        ).toBeInTheDocument();
      });
    });
  });

  // -----------------------------------------------------------------------
  // Title-fallback flow
  // -----------------------------------------------------------------------
  // When the PDF extractor returns ``422 no_identifiers_found``
  // (typically because the PDF is scanned, the DOI is garbled,
  // or the user pasted a PDF from a non-PubMed source) we
  // surface an inline form that asks the user to type the paper
  // title. The form calls ``api.addPaperByTitle`` which hits
  // PubMed ESearch and resolves the title to a real paper.

  describe('PDF tab > title-fallback flow', () => {
    // Build real ``APIError`` instances so the panel's
    // ``instanceof`` check works. We use the mocked class so
    // ``err instanceof APIError`` succeeds when the panel
    // inspects the rejection.
    const noIdError = new MockAPIError(
      422,
      {
        error: 'no_identifiers_found',
        message:
          "The PDF didn't contain a recognisable DOI or PMID on the first page.",
      },
      'API error 422: {"error":"no_identifiers_found",...}',
    );

    const titleMismatchError = new MockAPIError(
      422,
      {
        error: 'title_no_confident_match',
        message:
          'PubMed returned no paper that matched the supplied title.',
      },
      'API error 422: {"error":"title_no_confident_match",...}',
    );

    /** Helper: switch to the PDF tab and grab the file input. */
    async function goToPdfTabAndGetFileInput(user: ReturnType<
      typeof userEvent.setup
    >) {
      await user.click(screen.getByRole('tab', { name: /PDF/i }));
      const fileInput = screen
        .getByLabelText(/Drop a PDF here/i)
        .closest('label')
        ?.querySelector('input[type="file"]') as HTMLInputElement;
      return fileInput;
    }

    /** Helper: submit the title-fallback form.
     *
     * ``user.click(submitButton)`` doesn't reliably trigger a
     * form's ``onSubmit`` in jsdom because the browser's native
     * form-submission behavior isn't simulated. We use
     * ``fireEvent.submit(form)`` directly so the panel's
     * ``submitTitleFallback`` handler runs.
     */
    function submitFallbackForm() {
      const form = document.querySelector(
        'form.add-papers-title-fallback',
      ) as HTMLFormElement;
      fireEvent.submit(form);
    }

    it('shows the fallback form when uploadPdf returns no_identifiers_found', async () => {
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);
      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      // The fallback form is the recovery surface — no toast,
      // no inline error chip, just the dashed-border form.
      await waitFor(() => {
        expect(
          screen.getByText(/No DOI \/ PMID found/i),
        ).toBeInTheDocument();
      });
      // The help text names the PDF the user just dropped so
      // they have context for why this form is asking them to
      // do more work.
      expect(screen.getByText(/paper\.pdf/)).toBeInTheDocument();
      // The Find button is disabled until the user types
      // something — keeps them from submitting an empty title.
      const findButton = screen.getByRole('button', {
        name: /Find paper by title/i,
      });
      expect(findButton).toBeDisabled();
      // The toast error path must NOT fire for no_identifiers.
      // The recovery form is the feedback.
      expect(toast.error).not.toHaveBeenCalled();
    });

    it('calls addPaperByTitle with the typed title when the user submits', async () => {
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);
      mockApi.addPaperByTitle.mockResolvedValue({
        workspace_id: 'ws-1',
        papers: [
          {
            title: 'amyloid cascade 2025',
            authors: [],
            journal: null,
            year: 2025,
            abstract: '',
            doi: null,
            pmid: '40000001',
            keywords: [],
            url: null,
          },
        ],
      });

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      // Step 1: drop a PDF that fails to extract.
      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      // Step 2: wait for the fallback form to render.
      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Find paper by title/i }),
        ).toBeInTheDocument();
      });

      // Step 3: type the title and submit.
      const titleInput = screen.getByPlaceholderText(
        /Amyloid cascade in 2025/i,
      );
      await user.type(titleInput, 'amyloid cascade 2025');
      submitFallbackForm();

      // The endpoint was called with exactly the title (no
      // optional hints because the user didn't fill them).
      await waitFor(() => {
        expect(mockApi.addPaperByTitle).toHaveBeenCalledWith('ws-1', {
          title: 'amyloid cascade 2025',
          first_author: null,
          journal: null,
          year: null,
        });
      });
    });

    it('passes disambiguation hints through to addPaperByTitle', async () => {
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);
      mockApi.addPaperByTitle.mockResolvedValue({
        workspace_id: 'ws-1',
        papers: [
          {
            title: 'amyloid cascade 2025',
            authors: [],
            journal: { name: 'Nature', issn: null, publisher: null },
            year: 2025,
            abstract: '',
            doi: null,
            pmid: '40000001',
            keywords: [],
            url: null,
          },
        ],
      });

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Find paper by title/i }),
        ).toBeInTheDocument();
      });

      // Fill in the title.
      await user.type(
        screen.getByPlaceholderText(/Amyloid cascade in 2025/i),
        'amyloid cascade 2025',
      );

      // Open the disambiguation details and fill the optional fields.
      const disambiguate = screen.getByText(/Disambiguate/i);
      await user.click(disambiguate);

      await user.type(screen.getByPlaceholderText(/e\.g\. Smith/i), 'Smith');
      await user.type(screen.getByPlaceholderText(/e\.g\. Nature/i), 'Nature');
      await user.type(screen.getByPlaceholderText(/e\.g\. 2025/i), '2025');

      submitFallbackForm();

      await waitFor(() => {
        expect(mockApi.addPaperByTitle).toHaveBeenCalledWith('ws-1', {
          title: 'amyloid cascade 2025',
          first_author: 'Smith',
          journal: 'Nature',
          year: 2025,
        });
      });
    });

    it('rejects an out-of-range year before hitting the API', async () => {
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);
      mockApi.addPaperByTitle.mockResolvedValue({
        workspace_id: 'ws-1',
        papers: [],
      });

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Find paper by title/i }),
        ).toBeInTheDocument();
      });

      await user.type(
        screen.getByPlaceholderText(/Amyloid cascade in 2025/i),
        't',
      );
      await user.click(screen.getByText(/Disambiguate/i));
      // 1500 is below the panel's 1800 floor.
      await user.type(screen.getByPlaceholderText(/e\.g\. 2025/i), '1500');
      submitFallbackForm();

      await waitFor(() => {
        const errorEl = document.querySelector(
          '.add-papers-title-fallback-error',
        );
        expect(errorEl?.textContent).toMatch(
          /Year must be between 1800 and 2100/i,
        );
      });
      expect(mockApi.addPaperByTitle).not.toHaveBeenCalled();
    });

    it('closes the form on success and toasts the matched paper', async () => {
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);
      mockApi.addPaperByTitle.mockResolvedValue({
        workspace_id: 'ws-1',
        papers: [
          {
            title: 'amyloid cascade 2025',
            authors: [],
            journal: null,
            year: null,
            abstract: '',
            doi: null,
            pmid: '40000001',
            keywords: [],
            url: null,
          },
        ],
      });

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Find paper by title/i }),
        ).toBeInTheDocument();
      });

      await user.type(
        screen.getByPlaceholderText(/Amyloid cascade in 2025/i),
        'amyloid cascade 2025',
      );
      submitFallbackForm();

      // Form is gone.
      await waitFor(() => {
        expect(
          screen.queryByRole('button', { name: /Find paper by title/i }),
        ).not.toBeInTheDocument();
      });
      // The success toast mentions the matched paper so the
      // user has a one-line confirmation of what was added.
      expect(toast.success).toHaveBeenCalledWith(
        'Added "amyloid cascade 2025" from paper.pdf.',
      );
    });

    it('mirrors the title-fallback response via setCurrentWorkspace', async () => {
      // Third commit path that used to call
      // ``addPapersToCurrent(response.papers)``. Same
      // FSM-aware mirror as the DOI-bulk and PDF-upload
      // paths.
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);
      const serverWorkspace = {
        workspace_id: 'ws-1',
        question: 'x',
        state: 'INTERMEDIATE',
        papers: [
          {
            title: 'amyloid cascade 2025',
            authors: [],
            journal: null,
            year: null,
            abstract: '',
            doi: null,
            pmid: '40000001',
            keywords: [],
            url: null,
          },
        ],
        total_papers: 1,
        allowed_actions: ['report', 'summarize', 'search'],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      };
      mockApi.addPaperByTitle.mockResolvedValue(serverWorkspace);

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Find paper by title/i }),
        ).toBeInTheDocument();
      });

      await user.type(
        screen.getByPlaceholderText(/Amyloid cascade in 2025/i),
        'amyloid cascade 2025',
      );
      submitFallbackForm();

      await waitFor(() => {
        expect(
          mockWorkspaceStoreState.setCurrentWorkspace,
        ).toHaveBeenCalledWith(serverWorkspace);
      });
      expect(
        mockWorkspaceStoreState.addPapersToCurrent,
      ).not.toHaveBeenCalled();
    });

    it('surfaces title_no_confident_match as an inline error', async () => {
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);
      mockApi.addPaperByTitle.mockRejectedValue(titleMismatchError);

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: /Find paper by title/i }),
        ).toBeInTheDocument();
      });

      await user.type(
        screen.getByPlaceholderText(/Amyloid cascade in 2025/i),
        'A paper nobody wrote',
      );
      submitFallbackForm();

      await waitFor(() => {
        // The error chip wraps the text in a <p> that contains
        // an inline SVG icon, so testing-library's substring
        // matcher can't see it directly. We use a function
        // matcher instead, which inspects the rendered text.
        const errorEl = document.querySelector(
          '.add-papers-title-fallback-error',
        );
        // The backend's message is "PubMed returned no paper
        // that matched the supplied title." — the substring
        // we assert on must include the "that" connector so we
        // don't false-positive on a future shorter message.
        expect(errorEl?.textContent).toMatch(
          /no paper that matched the supplied title/i,
        );
      });
      // The form is still visible — the user can adjust the
      // title and resubmit.
      expect(
        screen.getByRole('button', { name: /Find paper by title/i }),
      ).toBeInTheDocument();
    });

    it('dismisses the fallback form via the X button', async () => {
      const user = userEvent.setup();
      mockApi.uploadPdf.mockRejectedValue(noIdError);

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(
          screen.getByRole('button', {
            name: /Dismiss title fallback/i,
          }),
        ).toBeInTheDocument();
      });

      await user.click(
        screen.getByRole('button', { name: /Dismiss title fallback/i }),
      );

      // Form is closed.
      expect(
        screen.queryByRole('button', { name: /Find paper by title/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(/No DOI \/ PMID found/i),
      ).not.toBeInTheDocument();
    });

    it('does NOT show the fallback form for non-PDF errors', async () => {
      // Generic 500 / pdf_read_failed should still go through
      // the inline error chip + toast — the recovery path is
      // reserved for ``no_identifiers_found`` only.
      const user = userEvent.setup();
      const genericError = new MockAPIError(
        422,
        { error: 'pdf_read_failed', message: 'PDF was unreadable' },
        'API error 422',
      );
      mockApi.uploadPdf.mockRejectedValue(genericError);

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);
      const file = new File(['%PDF-1.4 fake'], 'paper.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalled();
      });
      // The fallback form did NOT appear.
      expect(
        screen.queryByText(/No DOI \/ PMID found/i),
      ).not.toBeInTheDocument();
    });

    it('resets the fallback form when a new PDF upload succeeds', async () => {
      // If the user fixes the PDF (re-drops a different one
      // that yields an identifier) the previous fallback
      // session is cleared so the new state is clean.
      const user = userEvent.setup();
      mockApi.uploadPdf
        .mockRejectedValueOnce(noIdError)
        .mockResolvedValueOnce({
          workspace_id: 'ws-1',
          papers: [
            {
              title: 'A real paper.',
              authors: [],
              journal: null,
              year: null,
              abstract: '',
              doi: '10.1038/nature12373',
              pmid: null,
              keywords: [],
              url: null,
            },
          ],
        });

      render(<AddPapersPanel workspaceId="ws-1" enabled={true} />);

      const fileInput = await goToPdfTabAndGetFileInput(user);

      // First upload — fallback opens.
      Object.defineProperty(fileInput, 'files', {
        value: [new File(['%PDF-1.4'], 'no-id.pdf', { type: 'application/pdf' })],
        configurable: true,
      });
      fireEvent.change(fileInput);
      await waitFor(() => {
        expect(
          screen.getByText(/No DOI \/ PMID found/i),
        ).toBeInTheDocument();
      });

      // Second upload — succeeds.
      Object.defineProperty(fileInput, 'files', {
        value: [new File(['%PDF-1.4'], 'good.pdf', { type: 'application/pdf' })],
        configurable: true,
      });
      fireEvent.change(fileInput);

      // Fallback closes, success message appears.
      await waitFor(() => {
        expect(
          screen.queryByText(/No DOI \/ PMID found/i),
        ).not.toBeInTheDocument();
      });
      expect(toast.success).toHaveBeenCalledWith(
        'Added 1 paper from good.pdf.',
      );
    });
  });
});
