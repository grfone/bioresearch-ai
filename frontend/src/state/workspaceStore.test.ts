// workspaceStore.test.ts
//
// Tests for the Zustand store actions.
//
// On 2026-09-08 the local-only corpus mutations
// (``addPapersToCurrent``, ``removePaper``, ``clearPapers``)
// were removed from this store. Corpus mutations are now
// exclusively server-authoritative -- callers go through
// the ``useWorkspace`` hook's ``addPaper`` / ``addPapersBulk``
// / ``removePaper`` actions, which round-trip to the backend
// and mirror the canonical ``WorkspaceResponse`` back into
// this store via ``setCurrentWorkspace``. The previous
// "test the dedup logic lives on the frontend" tests are
// obsolete: the three-tier dedup (``_paper_identity``: PMID
// > DOI > title) now lives exclusively in
// ``app/domain/entities/research_session.py`` and is
// covered by backend tests. This file tests only the
// surviving store actions.

import { describe, it, expect, beforeEach } from 'vitest';
import { useWorkspaceStore } from './workspaceStore';
import type { WorkspaceResponse } from '../models/workspace';

const SAMPLE_WORKSPACE: WorkspaceResponse = {
  workspace_id: 'ws-1',
  question: 'What is X?',
  state: 'INITIAL',
  status: 'INITIAL',
  allowed_actions: ['add_paper', 'search'],
  progress: 0,
  last_error: null,
  last_error_at: null,
  papers: [],
  total_papers: 0,
  summary: null,
  report_available: false,
  published_report_available: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  paper_sources: {},
};

describe('workspaceStore', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().setCurrentWorkspace(SAMPLE_WORKSPACE);
  });

  describe('setCurrentWorkspace', () => {
    it('replaces the entire currentWorkspace payload atomically', () => {
      // The hook uses setCurrentWorkspace as the ONLY path to
      // update the store after a backend round-trip. The
      // store MUST NOT merge partial state into the existing
      // payload; the backend response is canonical.
      const next: WorkspaceResponse = {
        ...SAMPLE_WORKSPACE,
        state: 'INTERMEDIATE',
        papers: [
          { pmid: '11111', doi: null, title: 'A' } as never,
          { pmid: '22222', doi: null, title: 'B' } as never,
        ],
        total_papers: 2,
        allowed_actions: ['add_paper', 'back_to_home', 'generate', 'remove_paper'],
      };
      useWorkspaceStore.getState().setCurrentWorkspace(next);
      const ws = useWorkspaceStore.getState().currentWorkspace;
      expect(ws?.state).toBe('INTERMEDIATE');
      expect(ws?.total_papers).toBe(2);
      expect(ws?.papers.length).toBe(2);
      expect(ws?.papers[0]?.pmid).toBe('11111');
    });

    it('overwrites a prior workspace entirely (no merge)', () => {
      // Bug regression: a stale "set" that merged partial
      // state into the existing payload would leave the
      // previous paper list intact while updating fields
      // like ``state``. The setCurrentWorkspace contract is
      // "replace, don't merge".
      useWorkspaceStore.getState().setCurrentWorkspace({
        ...SAMPLE_WORKSPACE,
        state: 'INTERMEDIATE',
        papers: [{ pmid: '11111', doi: null, title: 'A' } as never],
        total_papers: 1,
      });
      useWorkspaceStore.getState().setCurrentWorkspace({
        ...SAMPLE_WORKSPACE,
        state: 'INTERMEDIATE',
        papers: [{ pmid: '99999', doi: null, title: 'Z' } as never],
        total_papers: 1,
      });
      const ws = useWorkspaceStore.getState().currentWorkspace;
      expect(ws?.papers.length).toBe(1);
      expect(ws?.papers[0]?.pmid).toBe('99999');
    });
  });

  describe('clearCurrentWorkspace', () => {
    it('nulls out the workspace', () => {
      useWorkspaceStore.getState().clearCurrentWorkspace();
      expect(useWorkspaceStore.getState().currentWorkspace).toBeNull();
    });
  });

  describe('setSummary', () => {
    it('sets summary on the current workspace', () => {
      useWorkspaceStore.getState().setSummary('a summary');
      expect(
        useWorkspaceStore.getState().currentWorkspace?.summary,
      ).toBe('a summary');
    });

    it('is a no-op when no workspace is loaded', () => {
      useWorkspaceStore.getState().clearCurrentWorkspace();
      useWorkspaceStore.getState().setSummary('orphan');
      // Must not crash; must not create a workspace.
      expect(useWorkspaceStore.getState().currentWorkspace).toBeNull();
    });
  });

  describe('setReportAvailable', () => {
    it('toggles report_available', () => {
      useWorkspaceStore.getState().setReportAvailable(true);
      expect(
        useWorkspaceStore.getState().currentWorkspace?.report_available,
      ).toBe(true);
    });
  });

  describe('dangerous-abstraction regression', () => {
    it('exposes NO local-only corpus mutation (removePaper / clearPapers / addPapersToCurrent)', () => {
      // The bug that motivated removing the local-only
      // mutations was that future developers could write
      // ``useWorkspaceStore.removePaper(id)`` and believe
      // they had persisted a removal. Pin the contract: the
      // store's keys are ONLY the surviving actions.
      const keys = Object.keys(useWorkspaceStore.getState());
      expect(keys).not.toContain('removePaper');
      expect(keys).not.toContain('clearPapers');
      expect(keys).not.toContain('addPapersToCurrent');
      // The surviving actions.
      expect(keys).toEqual(
        expect.arrayContaining([
          'currentWorkspace',
          'setCurrentWorkspace',
          'updateCurrentWorkspace',
          'clearCurrentWorkspace',
          'setSummary',
          'setReportAvailable',
        ]),
      );
    });
  });
});
