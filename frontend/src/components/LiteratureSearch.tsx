/**
 * LiteratureSearch.tsx
 * --------------------
 * Reusable component for searching biomedical literature.
 *
 * It accepts a search query, calls the backend API, and updates
 * the workspace store with the results.
 *
 * Designed to be used inside the Workspace page.
 */

import React, { useState } from 'react';
import { Search, Loader2 } from 'lucide-react';
import { api } from '../api/client';
import { toast } from '../state/toastStore';
import { useWorkspaceStore } from '../state/workspaceStore';

interface LiteratureSearchProps {
  /** Initial question to pre-fill the search input */
  initialQuery?: string;
  /** Callback fired after successful search */
  onSearchComplete?: (count: number) => void;
}

export const LiteratureSearch: React.FC<LiteratureSearchProps> = ({
  initialQuery = '',
  onSearchComplete,
}) => {
  const [query, setQuery] = useState(initialQuery);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const addPapers = useWorkspaceStore((state) => state.addPapersToCurrent);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const result = await api.search({ question: query.trim() });
      // Append papers to the current workspace via the store
      addPapers(result.papers);
      toast.success(`Added ${result.total_results} papers to workspace.`);
      onSearchComplete?.(result.total_results);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Search failed.';
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSearch} className="w-full">
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={18} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for additional papers…"
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
      {error && <p className="text-error text-sm mt-2">{error}</p>}
    </form>
  );
};