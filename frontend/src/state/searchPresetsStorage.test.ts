// searchPresetsStorage.test.ts
//
// Unit tests for the named-preset storage helper.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  loadPresets,
  savePresets,
  upsertPreset,
  removePreset,
  clearPresets,
} from './searchPresetsStorage';

const SAMPLE_FILTERS = {
  since_year: 2020,
  max_results: 50,
  sort_by: 'newest_first' as const,
  sources: ['openalex'] as Array<'openalex'>,
  document_types: [] as Array<never>,
  include_abstracts: true,
  open_access_only: false,
};

describe('searchPresetsStorage', () => {
  beforeEach(() => {
    if (window.localStorage) {
      window.localStorage.clear();
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('loadPresets', () => {
    it('returns an empty list when localStorage is empty', () => {
      expect(loadPresets()).toEqual([]);
    });

    it('returns the parsed list when localStorage has a valid blob', () => {
      const data = [
        {
          name: 'Last 5 years',
          filters: SAMPLE_FILTERS,
          savedAt: 1700000000000,
        },
      ];
      savePresets(data);
      expect(loadPresets()).toEqual(data);
    });

    it('returns an empty list when localStorage.getItem throws', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(
        () => {
          throw new Error('SecurityError');
        },
      );
      expect(loadPresets()).toEqual([]);
    });

    it('returns an empty list when the persisted blob is not an array', () => {
      window.localStorage.setItem(
        'bioresearch-ai:adv-search-presets:v1',
        JSON.stringify({ name: 'wrong' }),
      );
      expect(loadPresets()).toEqual([]);
    });

    it('drops entries that fail the shape check', () => {
      const data = [
        { name: 'Good', filters: SAMPLE_FILTERS, savedAt: 1 },
        { name: 'Bad' }, // missing filters + savedAt
        { filters: SAMPLE_FILTERS, savedAt: 1 }, // missing name
      ];
      window.localStorage.setItem(
        'bioresearch-ai:adv-search-presets:v1',
        JSON.stringify(data),
      );
      const loaded = loadPresets();
      expect(loaded.length).toBe(1);
      expect(loaded[0].name).toBe('Good');
    });
  });

  describe('savePresets', () => {
    it('writes the preset list as JSON', () => {
      const data = [
        { name: 'A', filters: SAMPLE_FILTERS, savedAt: 1 },
      ];
      savePresets(data);
      const raw = window.localStorage.getItem(
        'bioresearch-ai:adv-search-presets:v1',
      );
      expect(JSON.parse(raw!)).toEqual(data);
    });

    it('silently no-ops when localStorage.setItem throws', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(
        () => {
          throw new Error('QuotaExceeded');
        },
      );
      expect(() => savePresets([])).not.toThrow();
    });
  });

  describe('upsertPreset', () => {
    it('appends a new preset to the top of the list', () => {
      const before = [
        { name: 'B', filters: SAMPLE_FILTERS, savedAt: 1000 },
      ];
      const after = upsertPreset(before, 'A', SAMPLE_FILTERS);
      expect(after[0].name).toBe('A');
      expect(after[1].name).toBe('B');
      expect(after.length).toBe(2);
    });

    it('overwrites an existing preset with the same name', () => {
      const before = [
        { name: 'A', filters: SAMPLE_FILTERS, savedAt: 1000 },
        { name: 'B', filters: SAMPLE_FILTERS, savedAt: 2000 },
      ];
      const newFilters = {
        ...SAMPLE_FILTERS,
        max_results: 100,
      };
      const after = upsertPreset(before, 'A', newFilters);
      expect(after.length).toBe(2);
      expect(after[0].name).toBe('A');
      expect(after[0].filters.max_results).toBe(100);
      expect(after[0].savedAt).toBeGreaterThan(1000);
      expect(after[1].name).toBe('B');
    });

    it('rejects empty or whitespace-only names', () => {
      const before = [
        { name: 'A', filters: SAMPLE_FILTERS, savedAt: 1 },
      ];
      expect(upsertPreset(before, '', SAMPLE_FILTERS)).toBe(before);
      expect(upsertPreset(before, '   ', SAMPLE_FILTERS)).toBe(before);
    });

    it('trims the name before dedup', () => {
      const before: Array<{
        name: string;
        filters: typeof SAMPLE_FILTERS;
        savedAt: number;
      }> = [];
      const after = upsertPreset(before, '  My preset  ', SAMPLE_FILTERS);
      expect(after[0].name).toBe('My preset');
    });
  });

  describe('removePreset', () => {
    it('removes the preset with the matching name', () => {
      const before = [
        {
          name: 'A',
          filters: SAMPLE_FILTERS,
          savedAt: 1,
        },
        {
          name: 'B',
          filters: SAMPLE_FILTERS,
          savedAt: 2,
        },
      ];
      const after = removePreset(before, 'A');
      expect(after.length).toBe(1);
      expect(after[0].name).toBe('B');
    });

    it('is a no-op when the preset doesn\'t exist', () => {
      const before = [
        {
          name: 'A',
          filters: SAMPLE_FILTERS,
          savedAt: 1,
        },
      ];
      const after = removePreset(before, 'nonexistent');
      // The list is unchanged; ``filter`` returns a new
      // array reference but the contents are identical.
      expect(after).toEqual(before);
    });
  });

  describe('clearPresets', () => {
    it('removes the persisted blob', () => {
      savePresets([
        { name: 'A', filters: SAMPLE_FILTERS, savedAt: 1 },
      ]);
      expect(
        window.localStorage.getItem(
          'bioresearch-ai:adv-search-presets:v1',
        ),
      ).not.toBeNull();
      clearPresets();
      expect(
        window.localStorage.getItem(
          'bioresearch-ai:adv-search-presets:v1',
        ),
      ).toBeNull();
    });

    it('silently no-ops when localStorage.removeItem throws', () => {
      vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(
        () => {
          throw new Error('SecurityError');
        },
      );
      expect(() => clearPresets()).not.toThrow();
    });
  });

  describe('round-trip', () => {
    it('preserves the preset list through save + load', () => {
      const original = [
        {
          name: 'Last 5 years',
          filters: SAMPLE_FILTERS,
          savedAt: 1700000000000,
        },
        {
          name: 'Reviews only',
          filters: {
            ...SAMPLE_FILTERS,
            document_types: ['review'] as Array<'review'>,
          },
          savedAt: 1700000001000,
        },
      ];
      savePresets(original);
      expect(loadPresets()).toEqual(original);
    });
  });
});
