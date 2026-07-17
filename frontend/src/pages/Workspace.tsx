/**
 * ============================================================================
 * Workspace.tsx
 * ============================================================================
 *
 * BioResearch AI
 * Scientific Research Workstation
 *
 * ----------------------------------------------------------------------------
 * Purpose
 * ----------------------------------------------------------------------------
 *
 * Displays a research workspace, including the research question, evidence
 * summary, literature search interface, and the list of retrieved papers.
 *
 * This page is the central hub for building a collection of relevant
 * literature around a specific biomedical query.
 *
 * ----------------------------------------------------------------------------
 * Architecture
 * ----------------------------------------------------------------------------
 *
 *                Workspace (Page)
 *                      │
 *              useWorkspace (hook)
 *                      │
 *       ┌──────────────┼──────────────┐
 *       │              │              │
 * LiteratureSearch  PaperList   WorkspaceHeader
 *       │              │              │
 *   SearchBar       PaperItem   Metadata/Controls
 *       │              │
 *   Results count   Remove/Clear
 *
 * ----------------------------------------------------------------------------
 * Responsibilities
 * ----------------------------------------------------------------------------
 *
 * • Display the research question and metadata (created date, status).
 * • Show an evidence summary if available.
 * • Provide a literature search component to add new papers.
 * • List all papers associated with the workspace.
 * • Allow removal of individual papers and clearing all papers.
 * • Provide a "Generate Report" action to create a research report.
 * • Navigate to the generated report when ready.
 *
 * The page integrates with the workspace store for local state management
 * and uses the `useWorkspace` hook for API interactions.
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

import React, { useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useWorkspace } from '../hooks/useWorkspace';
import { LiteratureSearch } from '../components/LiteratureSearch';
import { PaperList } from '../components/PaperList';
import { BookOpen, Clock, FileText, Trash2 } from 'lucide-react';
import { useWorkspaceStore } from '../state/workspaceStore';
import { toast } from '../state/toastStore'; // if you have

export const Workspace: React.FC = () => {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();

  // Get the workspace from the store
  const storeWorkspace = useWorkspaceStore((s) => s.currentWorkspace);

  // We only fetch if the store doesn't have the workspace with this ID
  const shouldFetch = !storeWorkspace || storeWorkspace.workspace_id !== workspaceId;

  const {
    workspace,
    loading,
    error,
    fetchWorkspace,
    generateReport,
  } = useWorkspace(workspaceId, { autoFetch: false });

  // Fetch only if needed
  useEffect(() => {
    if (shouldFetch && workspaceId) {
      (async () => {
        try {
          await fetchWorkspace(workspaceId);
        } catch (err) {
          console.error('Workspace fetch error:', err);
        }
      })();
    }
  }, [workspaceId, shouldFetch, fetchWorkspace]);

    // Get store actions
    const removePaper = useWorkspaceStore((s) => s.removePaper);
    const clearPapers = useWorkspaceStore((s) => s.clearPapers);

  const handleGenerateReport = async () => {
    try {
      await generateReport();
      toast.success('Report generated successfully!');
      navigate(`/report/${workspaceId}`);
    } catch (err) {
      toast.error('Failed to generate report.');
    }
  };

  const handleRemovePaper = (paper: any) => {
    const id = paper.pmid || paper.doi;
    if (id) {
      removePaper(id);
      toast.info('Paper removed');
    }
  };

  const handleClearPapers = () => {
    if (window.confirm('Remove all papers from this workspace?')) {
      clearPapers();
      toast.info('All papers cleared');
    }
  };

  if (loading) {
    return (
      <div className="page section flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="spinner mx-auto mb-4" />
          <p className="text-secondary">Loading workspace…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page section flex items-center justify-center min-h-screen">
        <div className="text-center text-error">
          <p>Error loading workspace.</p>
          <p className="text-sm text-secondary mt-2">{error.message}</p>
        </div>
      </div>
    );
  }

  // Use the store's workspace if available, otherwise the fetched one
  const currentWorkspace = storeWorkspace?.workspace_id === workspaceId ? storeWorkspace : workspace;

  if (!currentWorkspace) {
    return (
      <div className="page section flex items-center justify-center min-h-screen">
        <div className="empty-state">
          <BookOpen size={48} className="text-muted" />
          <h3 className="empty-state-title">Workspace not found</h3>
          <p className="empty-state-description">
            The workspace you are looking for does not exist.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page section">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-primary">{currentWorkspace.question}</h1>
          <div className="flex items-center gap-3 mt-2 text-sm text-muted">
            <span className="flex items-center gap-1">
              <Clock size={14} />
              {new Date(currentWorkspace.created_at).toLocaleDateString()}
            </span>
            <span className="badge badge-neutral">{currentWorkspace.status}</span>
            {currentWorkspace.report_available && (
              <span className="badge badge-success">Report Available</span>
            )}
          </div>
        </div>
        <div className="flex gap-3">
          <button
            className="btn btn-secondary"
            onClick={handleClearPapers}
            disabled={currentWorkspace.total_papers === 0}
          >
            <Trash2 size={16} />
            Clear All
          </button>
          <button
            className="btn btn-primary"
            onClick={handleGenerateReport}
            disabled={currentWorkspace.total_papers === 0}
          >
            <FileText size={16} />
            Generate Report
          </button>
        </div>
      </div>

      {/* Summary */}
      {currentWorkspace.summary && (
        <div className="glass-panel mb-6">
          <h4 className="text-sm font-semibold uppercase text-muted tracking-wider mb-2">
            Evidence Summary
          </h4>
          <p className="text-secondary leading-relaxed">{currentWorkspace.summary}</p>
        </div>
      )}

      {/* Literature Search */}
      <div className="mb-6">
        <LiteratureSearch
          initialQuery={currentWorkspace.question}
          onSearchComplete={(count) => {
            toast.success(`Added ${count} papers`);
          }}
        />
      </div>

      {/* Papers List */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-primary flex items-center gap-2">
            <BookOpen size={20} />
            Literature ({currentWorkspace.total_papers})
          </h2>
        </div>

        <PaperList
          papers={currentWorkspace.papers}
          emptyMessage="No papers retrieved yet. Use the search above."
          onRemovePaper={handleRemovePaper}
        />
      </div>
    </div>
  );
};