// pages/Home.tsx
/**
 * ============================================================================
 * Home.tsx
 * ============================================================================
 *
 * BioResearch AI
 * Scientific Research Workstation
 *
 * ----------------------------------------------------------------------------
 * Purpose
 * ----------------------------------------------------------------------------
 *
 * Landing page of the application.
 *
 * Provides the entry point for initiating a new biomedical research workspace.
 * The user enters a research question, which is then sent to the backend to
 * create a new workspace. Upon success, the user is redirected to the
 * workspace view.
 *
 * ----------------------------------------------------------------------------
 * Architecture
 * ----------------------------------------------------------------------------
 *
 *                Home (Page)
 *                      │
 *          ┌───────────┴───────────┐
 *          │                       │
 *   CommandBar (input)      Create Workspace
 *          │                       │
 *          └───────────────────────┘
 *                      │
 *                      ▼
 *              /workspace/:id
 *
 * ----------------------------------------------------------------------------
 * Design Philosophy
 * ----------------------------------------------------------------------------
 *
 * The home page should feel like a scientific research terminal.
 *
 * The primary interaction is the command bar – a large, focused input
 * that invites the user to ask a biomedical research question.
 *
 * The interface is intentionally minimal, communicating that the
 * application is ready to perform complex scientific work.
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { api } from '../api/client';
import { useWorkspaceStore } from '../state/workspaceStore';

export const Home: React.FC = () => {
  const navigate = useNavigate();
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setCurrentWorkspace = useWorkspaceStore((s) => s.setCurrentWorkspace);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    setLoading(true);
    setError(null);

    try {
      // 1. Create workspace
      const workspace = await api.createWorkspace({ question: question.trim() });
      setCurrentWorkspace(workspace);

      // 2. Auto-search with the same question via the
      //    FSM-aware endpoint. The legacy ``POST /search``
      //    returns hits but does NOT mutate the workspace
      //    FSM, which left Generate Report greyed out even
      //    with 20 papers loaded. ``runSearchAction`` goes
      //    through ``POST /workspaces/{id}/actions/search``
      //    so the returned workspace reflects
      //    PAPERS_RETRIEVED with ``report`` in
      //    ``allowed_actions`` -- ready for the user to
      //    click Generate Report on the next page.
      const updated = await api.runSearchAction(
        workspace.workspace_id,
        question.trim(),
      );
      setCurrentWorkspace(updated);

      // 3. Navigate to workspace
      navigate(`/workspace/${workspace.workspace_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create workspace.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page section min-h-screen flex flex-col items-center justify-center">
      {/* Full-screen loader overlay.

          Mirrors the ``Report`` page's loader (see
          ``pages/Report.tsx``): a centered spinner with a
          status label. We show this the moment the user
          submits the form, BEFORE the create + search
          network round-trips finish. The button text
          ("Creating…") inside the form is not enough
          feedback for a 6-12 second wait -- the user
          needs to know the app is actively working.

          The overlay disappears the moment React Router
          unmounts this page (after the
          ``navigate("/workspace/...")`` call below). We
          do NOT need a separate setTimeout because the
          component is replaced synchronously by the
          router transition. */}
      {loading && (
        <div
          className="fixed inset-0 z-50 bg-background/95 backdrop-blur-sm
                     flex items-center justify-center"
          role="status"
          aria-live="polite"
          aria-label="Creating workspace and searching literature"
        >
          <div className="text-center">
            <div className="spinner mx-auto mb-4" />
            <p className="text-secondary">
              Creating workspace and searching literature…
            </p>
          </div>
        </div>
      )}
      <div className="max-w-2xl w-full text-center">
        {/* Hero */}
        <div className="mb-12 animate-fade-up">
          <h1 className="text-4xl md:text-5xl font-extrabold text-gradient mb-4">
            BioResearch AI
          </h1>
          <p className="text-secondary text-lg md:text-xl">
            Intelligent biomedical research assistant for literature discovery
            and evidence synthesis.
          </p>
        </div>

        {/* Command Bar */}
        <form onSubmit={handleSubmit} className="w-full animate-fade-up" style={{ animationDelay: '150ms' }}>
          <div className="command-bar focus-within:shadow-glow">
            <Search className="text-muted flex-shrink-0" size={20} />
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask a biomedical research question…"
              className="flex-1 bg-transparent border-none outline-none text-primary placeholder:text-muted text-lg"
              disabled={loading}
              autoFocus
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading || !question.trim()}
            >
              {loading ? 'Creating…' : 'Start Research'}
            </button>
          </div>
          {error && (
            <p className="text-error text-sm mt-3 text-left">{error}</p>
          )}
          <p className="text-muted text-sm mt-4 text-left">
            Example: “What are the latest biomarkers for Alzheimer's Disease?”
          </p>
        </form>

      </div>
    </div>
  );
};