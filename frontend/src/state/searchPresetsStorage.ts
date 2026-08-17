// searchPresetsStorage.ts
//
// Named Advanced Search presets.
//
// Each preset is a named bundle of AdvancedSearchFilters that
// the researcher can recall with one click. The presets live
// in localStorage (``bioresearch-ai:adv-search-presets:v1``)
// so they survive across browser sessions.
//
// Why localStorage (not sessionStorage, not the backend)?
// - localStorage survives across browser sessions; a
//   researcher who saves "Last 5 years, reviews only,
//   OpenAlex" once gets it back across all workspaces.
// - The backend has no "presets" concept; this is a
//   pure-frontend convenience.
// - Presets are not workspace-specific; they are a
//   researcher's personalisation of the search tool.
//
// Schema is deliberately simple. A future schema change
// bumps the version string and the old blob is silently
// ignored.

import type { AdvancedSearchFilters } from '../api/client';

const PERSIST_KEY = 'bioresearch-ai:adv-search-presets:v1';

/**
 * A saved filter preset. ``savedAt`` is the timestamp (ms
 * since epoch) used to sort the list newest-first in the
 * UI.
 */
export interface SearchPreset {
  /** Display name (unique within the user's preset list). */
  name: string;
  /** The filter bundle itself. */
  filters: AdvancedSearchFilters;
  /** When the preset was saved (ms since epoch). */
  savedAt: number;
}

/**
 * Safely read the saved presets from localStorage.
 *
 * Returns ``[]`` when:
 * - localStorage is unavailable (jsdom-without-storage,
 *   private-browsing mode, etc.)
 * - the persisted blob is malformed
 * - the persisted blob isn't a valid preset list
 *
 * Never throws.
 */
export function loadPresets(): SearchPreset[] {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return [];
    }
    const raw = window.localStorage.getItem(PERSIST_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(isValidPreset);
  } catch {
    return [];
  }
}

/**
 * Persist the preset list. Silently no-ops when
 * localStorage is unavailable.
 */
export function savePresets(presets: SearchPreset[]): void {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return;
    }
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(presets));
  } catch {
    // Same reasoning as the filter storage helper.
  }
}

/**
 * Add (or overwrite) a preset by name. Returns the updated
 * list.
 *
 * If a preset with the same name already exists, the new
 * one replaces it (the user is updating an existing preset,
 * not creating a duplicate). The new one is moved to the
 * top of the list (newest-first).
 */
export function upsertPreset(
  presets: SearchPreset[],
  name: string,
  filters: AdvancedSearchFilters,
): SearchPreset[] {
  const trimmed = name.trim();
  if (!trimmed) {
    return presets;
  }
  const filtered = presets.filter((p) => p.name !== trimmed);
  return [
    { name: trimmed, filters, savedAt: Date.now() },
    ...filtered,
  ];
}

/**
 * Remove a preset by name. Returns the updated list.
 * No-op if the preset doesn't exist.
 */
export function removePreset(
  presets: SearchPreset[],
  name: string,
): SearchPreset[] {
  return presets.filter((p) => p.name !== name);
}

/**
 * Wipe all presets. Mostly useful for tests.
 */
export function clearPresets(): void {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return;
    }
    window.localStorage.removeItem(PERSIST_KEY);
  } catch {
    // Same reasoning.
  }
}

/**
 * Lightweight shape check — we don't validate every
 * field of the embedded ``AdvancedSearchFilters``, just
 * the top-level preset shape.
 */
function isValidPreset(value: unknown): value is SearchPreset {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return (
    typeof v.name === 'string' &&
    typeof v.savedAt === 'number' &&
    typeof v.filters === 'object' &&
    v.filters !== null
  );
}
