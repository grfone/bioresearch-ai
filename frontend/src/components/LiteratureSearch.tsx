/**
 * LiteratureSearch.tsx
 * --------------------
 * Reusable component for searching biomedical literature.
 *
 * The component has two phases:
 *
 * 1. Search — the user types a query and submits. The backend
 *    returns up to 20 PubMed results.
 * 2. Select — the user picks which results to add to the workspace
 *    via checkboxes, then clicks "Add selected". The previous
 *    design auto-appended all results, which meant the user lost
 *    control over which papers entered the workspace.
 *
 * The previous "fire-and-forget auto-append" flow was the
 * consultant's Workflow C: "Exploring a new question, don't know
 * what's out there. … user clicks the checkboxes next to
 * relevant ones, 'Add selected to workspace'". This implementation
 * directly maps that workflow.
 *
 * Optional `inputRef` lets parents focus the search input from
 * a global keyboard shortcut (e.g. Ctrl+K).
 *
 * Optional `shortcutHint` displays the platform-aware shortcut
 * tip below the input ("Ctrl+K" on PC, "⌘K" on Mac).
 */

import React, { useState } from 'react';
import { Search, Loader2, Plus, Check } from 'lucide-react';
import { api } from '../api/client';
import { toast } from '../state/toastStore';
import { useWorkspaceStore } from '../state/workspaceStore';
import type { Paper } from '../models/paper';

interface LiteratureSearchProps {
  /** Initial question to pre-fill the search input */
  initialQuery?: string;
  /** Callback fired after a successful batch add (the user
   *  clicked "Add selected"). */
  onSelectComplete?: (count: number) => void;
  /** Optional ref forwarded to the underlying <input> so parents
   *  can focus it programmatically (e.g. from an empty-state card). */
  inputRef?: React.Ref<HTMLInputElement>;
  /** Optional keyboard shortcut hint displayed below the input.
   *  PC-first default; Mac users see ``⌘K``. */
  shortcutHint?: string;
}

export const LiteratureSearch: React.FC<LiteratureSearchProps> = ({
  initialQuery = '',
  onSelectComplete,
  inputRef,
  shortcutHint = 'Ctrl+K',
}) => {
  const [query, setQuery] = useState(initialQuery);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Paper[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [committing, setCommitting] = useState(false);

  const addPapers = useWorkspaceStore((state) => state.addPapersToCurrent);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    setResults(null);
    setSelected(new Set());

    try {
      const result = await api.search({ question: query.trim() });
      setResults(result.papers);
      // Select all by default — the consultant's Workflow C
      // works best when the user un-checks the irrelevant ones
      // rather than having to check every relevant one.
      setSelected(new Set(result.papers.map((_, i) => i)));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Search failed.';
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const toggleSelected = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (!results) return;
    if (selected.size === results.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(results.map((_, i) => i)));
    }
  };

  const handleAddSelected = async () => {
    if (!results || selected.size === 0) {
      toast.error('Pick at least one paper to add.');
      return;
    }
    setCommitting(true);
    try {
      const papersToAdd = results.filter((_, i) => selected.has(i));
      // The backend dedupes by PMID/DOI, so we don't strictly
      // need to filter here, but doing so saves a round trip
      // for papers the user deselected.
      addPapers(papersToAdd);
      toast.success(
        `Added ${papersToAdd.length} paper${papersToAdd.length === 1 ? '' : 's'}.`,
      );
      onSelectComplete?.(papersToAdd.length);
      // Clear the search results so the user sees the workspace
      // updated. The query stays so they can re-run if they want.
      setResults(null);
      setSelected(new Set());
    } finally {
      setCommitting(false);
    }
  };

  const paperKey = (paper: Paper, index: number): string =>
    paper.pmid || paper.doi || `idx:${index}`;

  return (
    <div className="literature-search">
      <form onSubmit={handleSearch} className="w-full">
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={18} />
            <input
              type="text"
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search PubMed for additional papers…"
              className="w-full pl-10 pr-4 py-3 bg-surface border border-border-default rounded-lg text-primary placeholder:text-muted focus:border-border-focus focus:shadow-glow transition-all outline-none"
              disabled={loading}
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary flex-shrink-0"
            disabled={loading || !query.trim()}
          >
            {loading ? <Loader2 className="animate-spin" size={18} /> : <Search size={18} />}
            {loading ? 'Searching…' : 'Search'}
          </button>
        </div>
        <p className="literature-search-shortcut-hint">
          Tip: press <kbd>{shortcutHint}</kbd> from anywhere to focus this input.
        </p>
      </form>

      {error && (
        <p className="text-error text-sm mt-2" role="alert">{error}</p>
      )}

      {/* Search results — checkbox list with select-all and add-selected. */}
      {results !== null && (
        <section className="literature-search-results" aria-label="Search results">
          <header className="literature-search-results-header">
            <h4 className="literature-search-results-title">
              {results.length} result{results.length === 1 ? '' : 's'}
            </h4>
            <button
              type="button"
              className="literature-search-select-all"
              onClick={handleSelectAll}
              disabled={committing}
            >
              {selected.size === results.length ? 'Deselect all' : 'Select all'}
            </button>
          </header>

          {results.length === 0 ? (
            <p className="text-muted text-sm">
              No PubMed results for this query. Try a different wording
              or paste a PMID/DOI directly.
            </p>
          ) : (
            <ul className="literature-search-results-list">
              {results.map((paper, index) => (
                <li
                  key={paperKey(paper, index)}
                  className={`literature-search-result ${selected.has(index) ? 'is-selected' : ''}`}
                >
                  <label className="literature-search-result-check">
                    <input
                      type="checkbox"
                      checked={selected.has(index)}
                      onChange={() => toggleSelected(index)}
                      aria-label={`Select ${paper.title}`}
                      disabled={committing}
                    />
                  </label>
                  <div className="literature-search-result-meta">
                    <div className="literature-search-result-title">
                      {paper.title}
                    </div>
                    <div className="literature-search-result-sub">
                      {paper.authors.length > 0 && (
                        <span>
                          {paper.authors
                            .slice(0, 3)
                            .map((a) => a.full_name)
                            .join(', ')}
                          {paper.authors.length > 3 && ' et al.'}
                          {' · '}
                        </span>
                      )}
                      {paper.journal?.name && (
                        <span>{paper.journal.name} · </span>
                      )}
                      {paper.year && <span>{paper.year}</span>}
                      {paper.pmid && (
                        <span className="literature-search-result-pmid">
                          {' · PMID: '}{paper.pmid}
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {results.length > 0 && (
            <footer className="literature-search-results-footer">
              <span className="literature-search-results-count">
                {selected.size} of {results.length} selected
              </span>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleAddSelected}
                disabled={committing || selected.size === 0}
              >
                {committing ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    Adding…
                  </>
                ) : (
                  <>
                    {selected.size === 0 ? (
                      <>
                        <Plus size={14} />
                        Pick papers to add
                      </>
                    ) : (
                      <>
                        <Check size={14} />
                        Add {selected.size} paper{selected.size === 1 ? '' : 's'}
                      </>
                    )}
                  </>
                )}
              </button>
            </footer>
          )}
        </section>
      )}
    </div>
  );
};