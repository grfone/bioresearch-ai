// AdvancedSearchModal.tsx
//
// Modal for the Advanced Search flow.
//
// Opens when the user clicks "Search PubMed" in the action bar.
// The user picks a source set, a year range, a sort order, a
// document-type filter, and an open-access flag. The primary
// CTA reuses the existing ``runSearchAction`` API method with
// the filter bundle; the backend dispatches through
// ``WorkspaceOrchestrator.search_with_filters``.
//
// State machine
// -------------
// - ``isOpen`` (prop) controls visibility — the parent owns
//   it so the modal can be triggered from multiple places.
// - Local state: ``draftFilters`` (the unsaved filter
//   bundle the user is editing), ``overrideQuery`` (optional
//   override of the workspace's question), ``submitting``.
// - The actual search runs on ``onSubmit`` — we call
//   ``runSearchAction(workspaceId, overrideQuery, filters)``
//   and close the modal on success.
//
// UX details
// ----------
// - bioRxiv is a chronological preprint dump; the modal
//   greys it out until a date window is supplied. bioRxiv's
//   keyword search never returns results, so a query-only
//   search with bioRxiv enabled would be misleading.
// - The "Reset" button clears all filter fields back to
//   their defaults (uses the backend's defaults).
// - The modal closes on Escape and on backdrop click.
// - The "X" button also closes it.
//
// Author
// ------
// Guillermo Ramajo Fernández

import React, { useEffect, useMemo, useState } from 'react';
import {
  X,
  Search as SearchIcon,
  RotateCcw,
  Calendar,
  Check,
  FileText,
  Globe,
  Lock,
} from 'lucide-react';
import {
  api,
  type AdvancedSearchFilters,
  type AdvancedSearchSource,
  type AdvancedSearchDocumentType,
} from '../api/client';
import { useWorkspaceStore } from '../state/workspaceStore';
import { toast } from '../state/toastStore';

interface AdvancedSearchModalProps {
  /** ID of the workspace the search runs against. */
  workspaceId: string;
  /** The workspace's question (used as the default query text). */
  workspaceQuestion: string;
  /** Whether the modal is open. */
  isOpen: boolean;
  /** Called when the user closes the modal (X, Escape, backdrop). */
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Source / document-type metadata
// ---------------------------------------------------------------------------
//
// We render source and document-type metadata as a constant
// table so the labels and tooltips live next to the enum
// strings. Backend has the same enum strings; the filter
// bundle is a pure string array.

const SOURCE_LABELS: Record<AdvancedSearchSource, { label: string; hint: string }> = {
  pubmed: {
    label: 'PubMed',
    hint: 'NCBI biomedical canon. 36M+ citations. Free.',
  },
  openalex: {
    label: 'OpenAlex',
    hint: '200M+ works across all disciplines. Free, polite pool with mailto.',
  },
  europe_pmc: {
    label: 'Europe PMC',
    hint: 'Open-access aggregator: PubMed + preprints + publishers.',
  },
  biorxiv: {
    label: 'bioRxiv',
    hint: 'Preprint server. Chronological dump — needs a date window.',
  },
};

const DOC_TYPE_LABELS: Record<AdvancedSearchDocumentType, string> = {
  'journal-article': 'Journal article',
  'review': 'Review',
  'preprint': 'Preprint',
  'dataset': 'Dataset',
  'conference-paper': 'Conference paper',
  'book-chapter': 'Book chapter',
  'thesis': 'Thesis',
};

// Default filter shape — every field absent, which lets the
// backend apply its defaults. We keep the default state as a
// "reset" target.
const DEFAULT_FILTERS: AdvancedSearchFilters = {
  since_year: null,
  until_year: null,
  max_results: 20,
  sort_by: 'relevance',
  include_abstracts: true,
  open_access_only: false,
  document_types: [],
  sources: [],
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const AdvancedSearchModal: React.FC<AdvancedSearchModalProps> = ({
  workspaceId,
  workspaceQuestion,
  isOpen,
  onClose,
}) => {
  const [draftFilters, setDraftFilters] =
    useState<AdvancedSearchFilters>(DEFAULT_FILTERS);
  const [overrideQuery, setOverrideQuery] = useState<string>('');
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Reset to defaults every time the modal opens, so a previous
  // session's choices don't leak in.
  useEffect(() => {
    if (isOpen) {
      setDraftFilters(DEFAULT_FILTERS);
      setOverrideQuery('');
    }
  }, [isOpen]);

  // Close on Escape.
  useEffect(() => {
    if (!isOpen) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // Computed: which sources are currently "active" (i.e. the
  // user picked them in the modal). When ``sources`` is empty
  // we use every registered source. The modal always shows
  // the four canonical sources regardless of which are
  // actually registered in the container — the backend
  // silently drops unregistered ones via the
  // ``MultiSourceSearcher`` fallback.
  const allSources: AdvancedSearchSource[] = [
    'pubmed',
    'openalex',
    'europe_pmc',
    'biorxiv',
  ];
  const activeSources = useMemo<Set<AdvancedSearchSource>>(() => {
    if (!draftFilters.sources || draftFilters.sources.length === 0) {
      // Empty = "use defaults" → flag all as active.
      return new Set(allSources);
    }
    return new Set(draftFilters.sources);
  }, [draftFilters.sources]);

  // bioRxiv is greyed out unless a date window is supplied
  // — bioRxiv has no keyword search, so a query-only search
  // with bioRxiv enabled would always return [].
  const hasDateWindow =
    draftFilters.since_year != null || draftFilters.until_year != null;
  const isBiorxivDisabled = !hasDateWindow;

  // Toggle a source. If the user empties the set we drop the
  // ``sources`` key entirely so the backend applies its
  // defaults.
  const toggleSource = (source: AdvancedSearchSource) => {
    if (source === 'biorxiv' && isBiorxivDisabled) return;
    setDraftFilters((prev) => {
      const current = new Set(
        prev.sources && prev.sources.length > 0
          ? prev.sources
          : allSources
      );
      if (current.has(source)) {
        current.delete(source);
      } else {
        current.add(source);
      }
      // If the user explicitly toggled everything to match the
      // default (i.e. all four are selected), drop the
      // ``sources`` field so the backend's defaults apply.
      const isAllSelected = allSources.every((s) => current.has(s));
      const sources = isAllSelected
        ? []
        : Array.from(current);
      return { ...prev, sources };
    });
  };

  // Toggle a document type. Empty list = no filter.
  const toggleDocType = (docType: AdvancedSearchDocumentType) => {
    setDraftFilters((prev) => {
      const current = new Set(prev.document_types ?? []);
      if (current.has(docType)) {
        current.delete(docType);
      } else {
        current.add(docType);
      }
      return { ...prev, document_types: Array.from(current) };
    });
  };

  const handleReset = () => {
    setDraftFilters(DEFAULT_FILTERS);
    setOverrideQuery('');
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      // If the user typed nothing in the override field, the
      // backend falls back to the workspace's existing
      // question.
      const queryToUse = overrideQuery.trim() || null;
      const filters: AdvancedSearchFilters = {
        ...draftFilters,
        document_types:
          draftFilters.document_types && draftFilters.document_types.length > 0
            ? draftFilters.document_types
            : [],
        sources:
          draftFilters.sources && draftFilters.sources.length > 0
            ? draftFilters.sources
            : [],
      };
      await api.runSearchAction(workspaceId, queryToUse, filters);
      toast.success(
        queryToUse
          ? `Advanced search ran for "${queryToUse}".`
          : 'Advanced search ran with the workspace question.',
      );
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`Advanced search failed: ${message}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  const yearOptions = (): number[] => {
    const current = new Date().getFullYear();
    const years: number[] = [];
    for (let y = current; y >= 1990; y -= 1) {
      years.push(y);
    }
    return years;
  };

  return (
    <div
      className="overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Advanced search"
    >
      <div
        className="dialog advanced-search-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <form onSubmit={handleSubmit}>
          {/* Header */}
          <div className="dialog-header advanced-search-modal-header">
            <div>
              <h2 className="dialog-title">Advanced search</h2>
              <p className="advanced-search-modal-subtitle">
                Pick sources, year range, and filters. The
                backend fans out to every selected source and
                dedupes by DOI.
              </p>
            </div>
            <button
              type="button"
              className="icon-button"
              onClick={onClose}
              aria-label="Close advanced search"
            >
              <X size={20} />
            </button>
          </div>

          {/* Query override */}
          <div className="advanced-search-modal-section">
            <label
              className="advanced-search-modal-label"
              htmlFor="advanced-search-query"
            >
              Search query
            </label>
            <input
              id="advanced-search-query"
              type="text"
              className="input"
              placeholder={workspaceQuestion || 'Type a query…'}
              value={overrideQuery}
              onChange={(e) => setOverrideQuery(e.target.value)}
            />
            <p className="advanced-search-modal-hint">
              Leave empty to search with this workspace's
              question:{' '}
              <em>{workspaceQuestion || '—'}</em>
            </p>
          </div>

          {/* Sources */}
          <div className="advanced-search-modal-section">
            <span className="advanced-search-modal-label">
              Sources
            </span>
            <div className="advanced-search-modal-sources">
              {allSources.map((source) => {
                const isActive = activeSources.has(source);
                const isDisabled =
                  source === 'biorxiv' && isBiorxivDisabled;
                return (
                  <label
                    key={source}
                    className={`advanced-search-modal-source ${
                      isActive ? 'is-active' : ''
                    } ${isDisabled ? 'is-disabled' : ''}`}
                    title={SOURCE_LABELS[source].hint}
                  >
                    <input
                      type="checkbox"
                      checked={isActive}
                      disabled={isDisabled}
                      onChange={() => toggleSource(source)}
                    />
                    <span className="advanced-search-modal-source-label">
                      {SOURCE_LABELS[source].label}
                    </span>
                    {isDisabled && (
                      <span className="advanced-search-modal-source-locked">
                        <Lock size={12} />
                        date window required
                      </span>
                    )}
                  </label>
                );
              })}
            </div>
            <p className="advanced-search-modal-hint">
              Empty = all default sources. bioRxiv needs a
              year range (it's a chronological preprint
              dump, not a keyword search).
            </p>
          </div>

          {/* Year range */}
          <div className="advanced-search-modal-section">
            <span className="advanced-search-modal-label">
              <Calendar size={14} /> Year range
            </span>
            <div className="advanced-search-modal-year-row">
              <select
                className="select"
                value={draftFilters.since_year ?? ''}
                onChange={(e) =>
                  setDraftFilters((prev) => ({
                    ...prev,
                    since_year: e.target.value
                      ? Number(e.target.value)
                      : null,
                  }))
                }
              >
                <option value="">From (any year)</option>
                {yearOptions().map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
              <span className="advanced-search-modal-year-sep">
                to
              </span>
              <select
                className="select"
                value={draftFilters.until_year ?? ''}
                onChange={(e) =>
                  setDraftFilters((prev) => ({
                    ...prev,
                    until_year: e.target.value
                      ? Number(e.target.value)
                      : null,
                  }))
                }
              >
                <option value="">To (any year)</option>
                {yearOptions().map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Sort + max results */}
          <div className="advanced-search-modal-section">
            <span className="advanced-search-modal-label">
              Sort
            </span>
            <div className="advanced-search-modal-sort-row">
              <label
                className={`advanced-search-modal-pill ${
                  draftFilters.sort_by === 'relevance' ? 'is-active' : ''
                }`}
              >
                <input
                  type="radio"
                  name="sort"
                  checked={draftFilters.sort_by === 'relevance'}
                  onChange={() =>
                    setDraftFilters((prev) => ({
                      ...prev,
                      sort_by: 'relevance',
                    }))
                  }
                />
                Relevance
              </label>
              <label
                className={`advanced-search-modal-pill ${
                  draftFilters.sort_by === 'newest_first' ? 'is-active' : ''
                }`}
              >
                <input
                  type="radio"
                  name="sort"
                  checked={draftFilters.sort_by === 'newest_first'}
                  onChange={() =>
                    setDraftFilters((prev) => ({
                      ...prev,
                      sort_by: 'newest_first',
                    }))
                  }
                />
                Newest first
              </label>
            </div>
            <div className="advanced-search-modal-max-results">
              <label
                className="advanced-search-modal-label"
                htmlFor="advanced-search-max-results"
              >
                Max results
              </label>
              <input
                id="advanced-search-max-results"
                type="number"
                className="input advanced-search-modal-num"
                min={1}
                max={200}
                value={draftFilters.max_results ?? 20}
                onChange={(e) =>
                  setDraftFilters((prev) => ({
                    ...prev,
                    max_results: Math.max(
                      1,
                      Math.min(200, Number(e.target.value) || 20)
                    ),
                  }))
                }
              />
            </div>
          </div>

          {/* Document types */}
          <div className="advanced-search-modal-section">
            <span className="advanced-search-modal-label">
              <FileText size={14} /> Document types
            </span>
            <div className="advanced-search-modal-doctypes">
              {(
                Object.keys(DOC_TYPE_LABELS) as AdvancedSearchDocumentType[]
              ).map((docType) => {
                const isActive =
                  (draftFilters.document_types ?? []).includes(docType);
                return (
                  <button
                    type="button"
                    key={docType}
                    className={`advanced-search-modal-chip ${
                      isActive ? 'is-active' : ''
                    }`}
                    aria-pressed={isActive}
                    onClick={() => toggleDocType(docType)}
                  >
                    {isActive && <Check size={12} />}
                    {DOC_TYPE_LABELS[docType]}
                  </button>
                );
              })}
            </div>
            <p className="advanced-search-modal-hint">
              Empty = no filter. Providers that don't support a
              type silently drop it.
            </p>
          </div>

          {/* Open access toggle */}
          <div className="advanced-search-modal-section">
            <label className="advanced-search-modal-toggle">
              <input
                type="checkbox"
                checked={!!draftFilters.open_access_only}
                onChange={(e) =>
                  setDraftFilters((prev) => ({
                    ...prev,
                    open_access_only: e.target.checked,
                  }))
                }
              />
              <Globe size={14} />
              <span>Open-access papers only</span>
            </label>
            <label className="advanced-search-modal-toggle">
              <input
                type="checkbox"
                checked={draftFilters.include_abstracts !== false}
                onChange={(e) =>
                  setDraftFilters((prev) => ({
                    ...prev,
                    include_abstracts: e.target.checked,
                  }))
                }
              />
              <span>Include abstracts</span>
            </label>
          </div>

          {/* Footer */}
          <div className="dialog-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleReset}
              disabled={submitting}
            >
              <RotateCcw size={14} /> Reset
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
            >
              <SearchIcon size={14} />{' '}
              {submitting ? 'Searching…' : 'Search'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
