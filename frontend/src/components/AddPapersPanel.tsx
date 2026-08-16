// AddPapersPanel.tsx
/**
 * AddPapersPanel.tsx
 * ------------------
 * The primary paper-entry surface for a BioResearch workspace.
 *
 * Researchers add papers in one of two ways:
 *
 *   1. Paste one or more DOIs into the bulk field and click
 *      "Resolve". CrossRef is queried for each DOI; resolved
 *      papers appear in the results list with green chips and
 *      can be added in one click.
 *
 *   2. Drag-and-drop a PDF onto the dropzone. The backend
 *      extracts the DOI from the first page and routes it
 *      through the same resolver. If no DOI is found the
 *      inline title-fallback form lets the user search PubMed
 *      by free-text title instead.
 *
 * The bulk input accepts DOIs only. PMIDs still resolve on the
 * backend (PDF extraction can surface a PMID) but there is no
 * dedicated PMID entry surface — researchers who already have a
 * PMID can paste the corresponding DOI from
 * ``pubmed.ncbi.nlm.nih.gov`` instead.
 *
 * @module components/AddPapersPanel
 */

import React, { useState } from 'react';
import {
  Check,
  FileUp,
  Link2,
  Loader2,
  Plus,
  X,
  AlertCircle,
} from 'lucide-react';
import { api, APIError } from '../api/client';
import { useWorkspaceStore } from '../state/workspaceStore';
import type { PaperRequest } from '../models/paper';
import { toast } from '../state/toastStore';

interface AddPapersPanelProps {
  /** ID of the workspace to add papers to. */
  workspaceId: string;
  /** Whether the FSM allows ``add_paper`` in the current state. */
  enabled: boolean;
  /** Optional ref forwarded to the bulk DOI textarea so
   *  the global Ctrl/Cmd+K shortcut can focus it. */
  bulkInputRef?: React.Ref<HTMLTextAreaElement>;
  /** Optional keyboard-shortcut hint displayed in the textarea's
   *  placeholder. PC-first default; Mac users see ``⌘K``. */
  shortcutHint?: string;
}

type Tab = 'doi' | 'pdf';

interface ResolveResultEntry {
  identifier: string;
  status: 'success' | 'failed';
  reason?: string;
  paper?: PaperRequest;
}

/**
 * Parse a textarea of DOIs.
 */
function parseDois(raw: string): string[] {
  return raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export const AddPapersPanel: React.FC<AddPapersPanelProps> = ({
  workspaceId,
  enabled,
  bulkInputRef,
  shortcutHint = 'Ctrl+K',
}) => {
  const [tab, setTab] = useState<Tab>('doi');
  const [pdfDragOver, setPdfDragOver] = useState(false);
  const [pdfUploading, setPdfUploading] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfSuccess, setPdfSuccess] = useState<string | null>(null);
  const [bulkText, setBulkText] = useState('');
  const [results, setResults] = useState<ResolveResultEntry[]>([]);
  const [resolving, setResolving] = useState(false);
  const [committing, setCommitting] = useState(false);

  // Title-fallback state — set when ``uploadPdf`` returns
  // ``422 no_identifiers_found``. The PDF didn't yield a DOI or
  // PMID; we offer the user a second chance by typing the title
  // and calling ``/papers/from-title``.
  const [titleFallbackOpen, setTitleFallbackOpen] = useState(false);
  const [titleFallbackName, setTitleFallbackName] = useState<string | null>(null);
  const [titleFallbackText, setTitleFallbackText] = useState('');
  const [titleFallbackYear, setTitleFallbackYear] = useState('');
  const [titleFallbackJournal, setTitleFallbackJournal] = useState('');
  const [titleFallbackAuthor, setTitleFallbackAuthor] = useState('');
  const [titleFallbackBusy, setTitleFallbackBusy] = useState(false);
  const [titleFallbackError, setTitleFallbackError] = useState<string | null>(null);

  const addPapersToCurrent = useWorkspaceStore((s) => s.addPapersToCurrent);

  const handleResolve = async () => {
    const ids = parseDois(bulkText);
    if (ids.length === 0) {
      toast.error('Paste at least one DOI.');
      return;
    }
    setResolving(true);
    try {
      const response = await api.resolvePapers(workspaceId, ids);
      const entries: ResolveResultEntry[] = response.results.map(
        (entry) => {
          if (entry.resolved) {
            return {
              identifier: entry.resolved.identifier,
              status: 'success' as const,
              paper: entry.resolved.paper as unknown as PaperRequest,
            };
          }
          return {
            identifier: entry.failed!.identifier,
            status: 'failed' as const,
            reason: entry.failed!.reason,
          };
        },
      );
      setResults(entries);
      const resolvedCount = response.resolved_count;
      const failedCount = response.failed_count;
      if (resolvedCount === 0) {
        toast.error(
          `Could not resolve any of the ${ids.length} DOIs.`,
        );
      } else if (failedCount === 0) {
        toast.success(`Resolved all ${resolvedCount} DOIs.`);
      } else {
        toast.success(
          `Resolved ${resolvedCount}/${ids.length} DOIs.`,
        );
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : 'Resolution failed.',
      );
    } finally {
      setResolving(false);
    }
  };

  const handleCommitResolved = async () => {
    const resolved = results
      .filter((r) => r.status === 'success' && r.paper)
      .map((r) => r.paper as PaperRequest);
    if (resolved.length === 0) {
      toast.error('No resolved papers to add.');
      return;
    }
    setCommitting(true);
    try {
      const response = await api.addPapersBulk(workspaceId, resolved);
      addPapersToCurrent(response.papers);
      toast.success(
        `Added ${resolved.length} paper${resolved.length === 1 ? '' : 's'}.`,
      );
      // Clear the resolver state so the user can start fresh.
      setResults([]);
      setBulkText('');
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : 'Failed to add papers.',
      );
    } finally {
      setCommitting(false);
    }
  };

  const handlePdfDrop = async (
    event: React.DragEvent<HTMLLabelElement>,
  ) => {
    event.preventDefault();
    setPdfDragOver(false);
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    if (file.type !== 'application/pdf') {
      setPdfError(
        `Only PDF files are accepted (got ${file.type || 'unknown'}).`,
      );
      setPdfSuccess(null);
      return;
    }
    await uploadPdf(file);
  };

  const handlePdfPick = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;
    // The native file picker enforces the ``accept`` attribute
    // in most browsers, but a determined user can override it
    // (drag-drop, file type spoofing). Validate again here so
    // the click-to-pick path is as tight as the drag-drop path.
    if (file.type !== 'application/pdf') {
      setPdfError(
        `Only PDF files are accepted (got ${file.type || 'unknown'}).`,
      );
      setPdfSuccess(null);
      event.target.value = '';
      return;
    }
    await uploadPdf(file);
    // Reset the input so picking the same file twice still fires
    // the change event.
    event.target.value = '';
  };

  const uploadPdf = async (file: File) => {
    setPdfUploading(file.name);
    setPdfError(null);
    setPdfSuccess(null);
    // Reset the title-fallback state when the user starts a new
    // upload; the previous fallback's data is no longer relevant.
    setTitleFallbackOpen(false);
    setTitleFallbackError(null);
    try {
      const response = await api.uploadPdf(workspaceId, file);
      addPapersToCurrent(response.papers);
      const count = response.papers.length;
      setPdfSuccess(
        `Added ${count} paper${count === 1 ? '' : 's'} from ${file.name}.`,
      );
      toast.success(
        `Added ${count} paper${count === 1 ? '' : 's'} from ${file.name}.`,
      );
    } catch (err) {
      // The PDF extractor returns ``422 no_identifiers_found`` when
      // it can't read a DOI or PMID off the first page. That's the
      // recovery path — we surface the inline title-fallback form
      // instead of a generic error chip. Other errors fall through
      // to the inline error chip + toast as before.
      if (err instanceof APIError
          && err.status === 422
          && (err.detail as { error?: string } | undefined)?.error
              === 'no_identifiers_found') {
        setTitleFallbackOpen(true);
        setTitleFallbackName(file.name);
        setTitleFallbackError(
          (err.detail as { message?: string } | undefined)?.message
            ?? 'We could not find a DOI or PMID on the first page.',
        );
        // Don't toast — the inline fallback panel is the feedback.
        // The user is already looking at the PDF tab.
        return;
      }
      const message = err instanceof Error
        ? err.message
        : 'Could not extract identifiers from the PDF.';
      setPdfError(message);
      toast.error(message);
    } finally {
      setPdfUploading(null);
    }
  };

  const submitTitleFallback = async (event: React.FormEvent) => {
    event.preventDefault();
    const title = titleFallbackText.trim();
    if (!title) {
      setTitleFallbackError('Type the paper title to search PubMed.');
      return;
    }
    const yearNum = titleFallbackYear.trim()
      ? Number(titleFallbackYear)
      : null;
    if (yearNum !== null && (!Number.isFinite(yearNum) || yearNum < 1800 || yearNum > 2100)) {
      setTitleFallbackError('Year must be between 1800 and 2100.');
      return;
    }
    setTitleFallbackBusy(true);
    setTitleFallbackError(null);
    try {
      const response = await api.addPaperByTitle(workspaceId, {
        title,
        first_author: titleFallbackAuthor.trim() || null,
        journal: titleFallbackJournal.trim() || null,
        year: yearNum,
      });
      addPapersToCurrent(response.papers);
      const matched = response.papers[response.papers.length - 1];
      toast.success(
        `Added "${matched?.title ?? title}" from ${titleFallbackName ?? 'PDF'}.`,
      );
      // Reset the fallback panel so a fresh PDF upload starts
      // from a clean slate.
      setTitleFallbackOpen(false);
      setTitleFallbackText('');
      setTitleFallbackAuthor('');
      setTitleFallbackJournal('');
      setTitleFallbackYear('');
    } catch (err) {
      if (err instanceof APIError
          && err.status === 422
          && (err.detail as { error?: string } | undefined)?.error
              === 'title_no_confident_match') {
        setTitleFallbackError(
          (err.detail as { message?: string } | undefined)?.message
            ?? 'No paper matched that title. Try a different wording.',
        );
        return;
      }
      const message = err instanceof Error
        ? err.message
        : 'Could not find the paper by title.';
      setTitleFallbackError(message);
    } finally {
      setTitleFallbackBusy(false);
    }
  };

  const dismissTitleFallback = () => {
    setTitleFallbackOpen(false);
    setTitleFallbackText('');
    setTitleFallbackAuthor('');
    setTitleFallbackJournal('');
    setTitleFallbackYear('');
    setTitleFallbackError(null);
  };

  if (!enabled) {
    return null;
  }

  const resolvedCount = results.filter((r) => r.status === 'success').length;
  const failedCount = results.filter((r) => r.status === 'failed').length;

  return (
    <section
      className="add-papers-panel glass-panel"
      aria-label="Add papers to this workspace"
    >
      <header className="add-papers-header">
        <h3 className="add-papers-title">
          <Plus size={18} />
          Add papers
        </h3>
        <p className="add-papers-subtitle">
          Paste one DOI per line, or comma-separated. The full
          metadata is fetched from CrossRef.
        </p>
      </header>

      <div className="add-papers-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'doi'}
          className={`add-papers-tab ${tab === 'doi' ? 'is-active' : ''}`}
          onClick={() => setTab('doi')}
        >
          <Link2 size={14} />
          DOI
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'pdf'}
          className={`add-papers-tab ${tab === 'pdf' ? 'is-active' : ''}`}
          onClick={() => setTab('pdf')}
        >
          <FileUp size={14} />
          PDF
        </button>
      </div>

      {tab === 'doi' && (
        <div className="add-papers-tab-body">
          <textarea
            className="add-papers-bulk-input"
            rows={5}
            ref={bulkInputRef}
            placeholder={'10.1038/s41591-023-02505-2\nhttps://doi.org/10.1038/s41591-023-02505-2'}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            aria-label="DOI list"
          />

          <p className="add-papers-shortcut-hint">
            Tip: press <kbd>{shortcutHint}</kbd> from anywhere to focus
            this input.
          </p>

          <div className="add-papers-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleResolve}
              disabled={resolving || bulkText.trim().length === 0}
            >
              {resolving ? (
                <>
                  <Loader2 size={14} className="spin" />
                  Resolving…
                </>
              ) : (
                <>
                  <Link2 size={14} />
                  Resolve DOIs
                </>
              )}
            </button>

            {results.length > 0 && (
              <>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setResults([]);
                    setBulkText('');
                  }}
                >
                  Clear
                </button>
                {resolvedCount > 0 && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleCommitResolved}
                    disabled={committing}
                  >
                    {committing ? (
                      <>
                        <Loader2 size={14} className="spin" />
                        Adding…
                      </>
                    ) : (
                      <>
                        <Check size={14} />
                        Add {resolvedCount} resolved paper
                        {resolvedCount === 1 ? '' : 's'}
                      </>
                    )}
                  </button>
                )}
              </>
            )}
          </div>

          {results.length > 0 && (
            <div className="add-papers-results">
              <div className="add-papers-results-summary">
                <span className="add-papers-chip add-papers-chip--success">
                  <Check size={12} />
                  {resolvedCount} resolved
                </span>
                {failedCount > 0 && (
                  <span className="add-papers-chip add-papers-chip--error">
                    <X size={12} />
                    {failedCount} failed
                  </span>
                )}
              </div>
              <ul className="add-papers-results-list">
                {results.map((entry) => (
                  <li
                    key={entry.identifier}
                    className={`add-papers-result ${entry.status === 'success' ? 'is-success' : 'is-failed'}`}
                  >
                    <span className="add-papers-result-id">
                      {entry.identifier}
                    </span>
                    {entry.status === 'success' && entry.paper ? (
                      <span className="add-papers-result-meta">
                        {entry.paper.title}
                      </span>
                    ) : (
                      <span className="add-papers-result-meta add-papers-result-meta--failed">
                        <AlertCircle size={12} />
                        {entry.reason}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {tab === 'pdf' && (
        <div className="add-papers-tab-body">
          <label
            className={`add-papers-pdf-drop${pdfDragOver ? ' is-dragover' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setPdfDragOver(true);
            }}
            onDragLeave={() => setPdfDragOver(false)}
            onDrop={handlePdfDrop}
          >
            <FileUp size={32} />
            <p className="add-papers-pdf-title">
              Drop a PDF here, or click to choose a file
            </p>
            <p className="add-papers-pdf-note">
              We read the first page and look for a DOI. The full
              metadata is fetched from CrossRef. If the PDF is
              scanned, the title-fallback form below lets you
              search PubMed by free-text title instead.
            </p>
            <input
              type="file"
              accept="application/pdf"
              onChange={handlePdfPick}
              style={{ display: 'none' }}
            />
          </label>

          {pdfUploading && (
            <p className="add-papers-pdf-status">
              <Loader2 size={14} className="spin" />
              Extracting identifiers from {pdfUploading}…
            </p>
          )}
          {pdfError && (
            <p className="add-papers-pdf-status add-papers-pdf-status--error">
              <AlertCircle size={14} />
              {pdfError}
            </p>
          )}
          {pdfSuccess && (
            <p className="add-papers-pdf-status add-papers-pdf-status--success">
              <Check size={14} />
              {pdfSuccess}
            </p>
          )}

          {titleFallbackOpen && (
            <form
              className="add-papers-title-fallback"
              onSubmit={submitTitleFallback}
            >
              <div className="add-papers-title-fallback-header">
                <span className="add-papers-title-fallback-tag">
                  No DOI / PMID found
                </span>
                <button
                  type="button"
                  className="add-papers-title-fallback-dismiss"
                  onClick={dismissTitleFallback}
                  aria-label="Dismiss title fallback"
                >
                  <X size={14} />
                </button>
              </div>
              <p className="add-papers-title-fallback-help">
                {titleFallbackName
                  ? <>We could not find a DOI or PMID in <code>{titleFallbackName}</code>. Type the paper title and we'll search PubMed for a match.</>
                  : <>Type the paper title and we'll search PubMed for a match.</>
                }
              </p>
              <label className="add-papers-title-fallback-field">
                <span>Paper title <span className="required">*</span></span>
                <input
                  type="text"
                  value={titleFallbackText}
                  onChange={(e) => setTitleFallbackText(e.target.value)}
                  placeholder="e.g. Amyloid cascade in 2025"
                  disabled={titleFallbackBusy}
                  autoFocus
                />
              </label>
              <details className="add-papers-title-fallback-disambiguate">
                <summary>Disambiguate (optional)</summary>
                <label className="add-papers-title-fallback-field">
                  <span>First-author surname</span>
                  <input
                    type="text"
                    value={titleFallbackAuthor}
                    onChange={(e) => setTitleFallbackAuthor(e.target.value)}
                    placeholder="e.g. Smith"
                    disabled={titleFallbackBusy}
                  />
                </label>
                <label className="add-papers-title-fallback-field">
                  <span>Journal</span>
                  <input
                    type="text"
                    value={titleFallbackJournal}
                    onChange={(e) => setTitleFallbackJournal(e.target.value)}
                    placeholder="e.g. Nature"
                    disabled={titleFallbackBusy}
                  />
                </label>
                <label className="add-papers-title-fallback-field">
                  <span>Year</span>
                  <input
                    type="number"
                    value={titleFallbackYear}
                    onChange={(e) => setTitleFallbackYear(e.target.value)}
                    placeholder="e.g. 2025"
                    min="1800"
                    max="2100"
                    disabled={titleFallbackBusy}
                  />
                </label>
              </details>
              {titleFallbackError && (
                <p className="add-papers-title-fallback-error">
                  <AlertCircle size={14} />
                  {titleFallbackError}
                </p>
              )}
              <div className="add-papers-title-fallback-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={dismissTitleFallback}
                  disabled={titleFallbackBusy}
                >
                  Dismiss
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={titleFallbackBusy || !titleFallbackText.trim()}
                >
                  {titleFallbackBusy
                    ? <><Loader2 size={14} className="spin" /> Searching…</>
                    : <>Find paper by title</>}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </section>
  );
};

export default AddPapersPanel;