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
  published_report_available: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  paper_sources: {},
};

function makePaper(
  pmid: string | null = null,
  doi: string | null = null,
  title = 'Test',
): Paper {
  return {
    title,
    authors: [],
    journal: null,
    year: 2024,
    abstract: '',
    doi,
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
        makePaper('1', null, 'Alpha'),
      ]);
      const stateBefore =
        useWorkspaceStore.getState().currentWorkspace!.state;
      expect(stateBefore).toBe('PAPERS_RETRIEVED');
      // Now try adding the same paper again — dedup, no
      // new papers.
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper('1', null, 'Alpha duplicate'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      // State should not change.
      expect(ws.state).toBe('PAPERS_RETRIEVED');
      // Total paper count should not change.
      expect(ws.total_papers).toBe(1);
    });

    // --------------------------------------------------------------
    // DOI-based deduplication
    // --------------------------------------------------------------
    //
    // The original PMID-only dedup missed papers without a
    // PMID -- e.g. Springer book chapters, arXiv preprints,
    // conference proceedings. A user could add the same DOI
    // twice and end up with two identical cards. These tests
    // pin the contract that mirrors the backend's
    // ``_paper_identity``: PMID first, DOI fallback,
    // normalized title last resort.
    it('dedupes by DOI when PMID is absent', () => {
      // The user's reproduction: add a Springer book
      // chapter (DOI only, no PMID) twice in a row. Should
      // produce exactly one card, not two.
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, '10.1007/978-3-031-64636-2_17', 'Springer chapter'),
      ]);
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, '10.1007/978-3-031-64636-2_17', 'Springer chapter'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      expect(ws.papers.length).toBe(1);
      expect(ws.total_papers).toBe(1);
    });

    it('dedupes by DOI even when PMID is also present and matches', () => {
      // Paper has both PMID and DOI. The first add lands.
      // The second add (with the same DOI but a different
      // -- or absent -- PMID) is a duplicate because DOI
      // is enough.
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper('12345', '10.1038/nature14539', 'Deep learning'),
      ]);
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, '10.1038/nature14539', 'Deep learning'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      expect(ws.papers.length).toBe(1);
    });

    it('does NOT dedup papers with the same title but different DOI', () => {
      // Two genuinely distinct papers can share a title
      // (e.g. "Letter to the Editor"). Without the DOI
      // check, the title dedup would falsely merge them.
      // This is the contract that title is a LAST resort,
      // not a primary key.
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, '10.1234/aaa', 'Letter to the Editor'),
      ]);
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, '10.5678/bbb', 'Letter to the Editor'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      // Both papers kept -- different DOIs, same title is
      // not a duplicate signal.
      expect(ws.papers.length).toBe(2);
    });

    it('dedupes by normalized title only when no PMID and no DOI', () => {
      // Pre-print / stub record with no PMID and no DOI.
      // The only signal we have is the title; we should
      // still dedup because a duplicate entry is worse
      // than a possible false-positive.
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, null, 'Glucose metabolism in hepatocytes'),
      ]);
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, null, 'Glucose metabolism in hepatocytes'),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      expect(ws.papers.length).toBe(1);
    });

    it('treats case-only title differences as duplicates', () => {
      // Title normalization is lowercased + whitespace-
      // collapsed before comparison, so "Foo" and "foo "
      // are the same identity.
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, null, 'Foo Bar'),
      ]);
      useWorkspaceStore.getState().addPapersToCurrent([
        makePaper(null, null, 'foo bar '),
      ]);
      const ws = useWorkspaceStore.getState().currentWorkspace!;
      expect(ws.papers.length).toBe(1);
    });
  });
});