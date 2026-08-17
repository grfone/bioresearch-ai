// searchFiltersStorage.test.ts
//
// Unit tests for the localStorage-backed persistence helper
// for Advanced Search filter bundles.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  loadPersistedFilters,
  savePersistedFilters,
  clearPersistedFilters,
} from './searchFiltersStorage';

describe('searchFiltersStorage', () => {
  beforeEach(() => {
    // Test setup clears localStorage between tests, but we
    // also clear in ``beforeEach`` so a test in this file
    // can run on its own.
    if (window.localStorage) {
      window.localStorage.clear();
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('loadPersistedFilters', () => {
    it('returns null when localStorage is empty', () => {
      expect(loadPersistedFilters()).toBeNull();
    });

    it('returns the parsed filter when localStorage has a valid blob', () => {
      savePersistedFilters({
        since_year: 2020,
        max_results: 50,
        sort_by: 'newest_first',
        include_abstracts: true,
        open_access_only: false,
        document_types: ['review'],
        sources: ['openalex'],
      });
      const loaded = loadPersistedFilters();
      expect(loaded).not.toBeNull();
      expect(loaded!.since_year).toBe(2020);
      expect(loaded!.max_results).toBe(50);
      expect(loaded!.sort_by).toBe('newest_first');
      expect(loaded!.sources).toEqual(['openalex']);
    });

    it('returns null when the persisted JSON is malformed', () => {
      // Simulate a half-written or corrupted entry.
      window.localStorage.setItem(
        'bioresearch-ai:advanced-search-filters:v1',
        '{not json]',
      );
      // Suppress the parse-error console noise.
      const errorSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      expect(loadPersistedFilters()).toBeNull();
      errorSpy.mockRestore();
    });

    it('returns null when the persisted shape does not match the schema', () => {
      // A valid JSON but with unrelated fields — guards
      // against future schema migrations silently
      // accepting bogus blobs.
      window.localStorage.setItem(
        'bioresearch-ai:advanced-search-filters:v1',
        JSON.stringify({ foo: 'bar' }),
      );
      expect(loadPersistedFilters()).toBeNull();
    });

    it('returns null when localStorage.getItem throws', () => {
      // Simulate SecurityError in an iframe or
      // QuotaExceededError etc.
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(
        () => {
          throw new Error('SecurityError');
        },
      );
      expect(loadPersistedFilters()).toBeNull();
    });
  });

  describe('savePersistedFilters', () => {
    it('writes the filter bundle as JSON to localStorage', () => {
      savePersistedFilters({
        since_year: 2024,
        max_results: 5,
        sort_by: 'newest_first',
      });
      const raw = window.localStorage.getItem(
        'bioresearch-ai:advanced-search-filters:v1',
      );
      expect(raw).not.toBeNull();
      const parsed = JSON.parse(raw!);
      expect(parsed.since_year).toBe(2024);
      expect(parsed.max_results).toBe(5);
      expect(parsed.sort_by).toBe('newest_first');
    });

    it('silently no-ops when localStorage.setItem throws', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(
        () => {
          throw new Error('QuotaExceeded');
        },
      );
      // Should not crash.
      expect(() =>
        savePersistedFilters({ since_year: 2020 }),
      ).not.toThrow();
    });
  });

  describe('clearPersistedFilters', () => {
    it('removes the persisted blob', () => {
      savePersistedFilters({ since_year: 2020 });
      expect(
        window.localStorage.getItem(
          'bioresearch-ai:advanced-search-filters:v1',
        ),
      ).not.toBeNull();
      clearPersistedFilters();
      expect(
        window.localStorage.getItem(
          'bioresearch-ai:advanced-search-filters:v1',
        ),
      ).toBeNull();
    });

    it('silently no-ops when localStorage.removeItem throws', () => {
      vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(
        () => {
          throw new Error('SecurityError');
        },
      );
      expect(() => clearPersistedFilters()).not.toThrow();
    });
  });

  describe('round-trip', () => {
    it('preserves every field through save/load', () => {
      const original = {
        since_year: 2018,
        until_year: 2024,
        max_results: 50,
        sort_by: 'newest_first' as const,
        include_abstracts: true,
        open_access_only: true,
        document_types: ['review', 'preprint'] as Array<
          'review' | 'preprint'
        >,
        sources: ['openalex', 'pubmed'] as Array<
          'openalex' | 'pubmed'
        >,
      };
      savePersistedFilters(original);
      const loaded = loadPersistedFilters();
      expect(loaded).toEqual(original);
    });
  });
});
