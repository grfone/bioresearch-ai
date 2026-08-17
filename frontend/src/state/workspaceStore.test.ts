// workspaceStore.test.ts
//
// Tests for the Zustand store actions, particularly the
// FSM-state side effects in addPapersToCurrent.

import { describe, it, expect, beforeEach } from 'vitest';
import { useWorkspaceStore } from './workspaceStore';
import type { Paper } from '../models/paper';
import type { WorkspaceResponse } from '../models/workspace';

const SAMPLE_WORKSPACE: WorkspaceResponse = {
  workspace_id: 'ws-1',
  question: 'What is X?',
  state: 'CREATED',
  status: 'CREATED',
  allowed_actions: ['add_paper', 'search'],
  progress: 0,
  last_error: null,
  papers: [],
  total_papers: 0,
  summary: null,
  has_evidence_comparison: false,
  report_available: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  paper_sources: {},
};

function makePaper(
  pmid: string | null,
  title = 'Test',
): Paper {
  return {
    title,
    authors: [],
    journal: null,
    year: 2024,
    abstract: '',
    doi: null,
    pmid,
    keywords: [],
    url: null,
  };
}

describe('workspaceStore', () => {
  beforeEach(() => {
    // The Zustand store is a module-level singleton; reset
    // state between tests by calling setCurrentWorkspace
    // with the test fixture and clearing papers.
    useWorkspaceStore.getState().setCurrentWorkspace(SAMPLE_WORKSPACE);
    useWorkspaceStore.getState().clearPapers();
    useWorkspaceStore.getState().setCurrentWorkspace(SAMPLE_WORKSPACE);
  });

  describe('addPapersToCurrent', () => {
    it('advances the FSM state from CREATED to PAPERS_RETRIEVED when papers are added', () => {
      // The user added papers via the legacy
      // LiteratureSearch path. The workspace was in
      // CREATED; after addPapers, the action bar should
      // expose Summarize (which requires PAPERS_RETRIEVED).
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper('12345'),
        makePaper('67890'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      expect(ws.state).toBe('PAPERS_RETRIEVED');
      expect(ws.allowed_actions).toContain('summarize');
      expect(ws.total_papers).toBe(2);
      expect(ws.papers.length).toBe(2);
    });

    it('does NOT regress the state — papers added in PAPERS_RETRIEVED stay there', () => {
      // Start with PAPERS_RETRIEVED (e.g. user ran the
      // advanced search modal then added papers via
      // manual entry).
      useWorkspaceStore.getState().setCurrentWorkspace({
        ...SAMPLE_WORKSPACE,
        state: 'PAPERS_RETRIEVED',
        allowed_actions: ['add_paper', 'remove_paper', 'search', 'summarize'],
        papers: [makePaper('1')],
        total_papers: 1,
      });
      useWorkspaceStore.getState().addPapersToCurrent([makePaper('2')]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      expect(ws.state).toBe('PAPERS_RETRIEVED');
      expect(ws.allowed_actions).toContain('summarize');
      expect(ws.total_papers).toBe(2);
    });

    it('dedupes by PMID before adding', () => {
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper('1', 'Alpha'),
        makePaper('1', 'Alpha duplicate'),
        makePaper('2', 'Beta'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      expect(ws.papers.length).toBe(2);
    });

    it('does NOT advance state when the dedup leaves zero new papers', () => {
      // Workspace stays in CREATED if every paper we tried
      // to add is already there. (Edge case — this matters
      // because the empty-add path shouldn't move the FSM.)
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper('1', 'Alpha'),
      ]);
      const stateBefore =
        useWorkspaceStore.getState().currentWorkspace!.state;
      expect(stateBefore).toBe('PAPERS_RETRIEVED');
      // Now try adding the same paper again — dedup, no
      // new papers.
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper('1', 'Alpha duplicate'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      // State should not change.
      expect(ws.state).toBe('PAPERS_RETRIEVED');
      // Total paper count should not change.
      expect(ws.total_papers).toBe(1);
    });
  });
});