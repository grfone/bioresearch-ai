// searchFiltersStorage.ts
//
// Persists the Advanced Search modal's filter bundle across
// modal opens. We use localStorage — per-user, per-machine,
// no server round-trip. The "Per-workspace via API" option is
// over-engineered for now; users can re-set filters per workspace
// if they want, and per-workspace persistence can come later.
//
// Why localStorage (not sessionStorage or Zustand+persist)?
// - localStorage persists across browser sessions: a
//   researcher who tweaks their filters once gets the same
//   defaults the next day.
// - sessionStorage is wiped on tab close; Zustand+persist
//   middleware is heavier-weight for what is essentially a
//   single-key value.
//
// The schema is deliberately simple: a single JSON blob
// keyed by ``bioresearch-ai:advanced-search-filters``. If
// the schema changes in a backwards-incompatible way, bump
// the version string (``bioresearch-ai:advanced-search-filters:v2``)
// and the old blob is silently ignored.

import { type AdvancedSearchFilters } from '../api/client';

const PERSIST_KEY = 'bioresearch-ai:advanced-search-filters:v1';

/**
 * Safely read the persisted filter bundle from localStorage.
 *
 * Returns ``null`` if:
 * - localStorage is unavailable (jsdom without storage,
 *   private-browsing mode, etc.)
 * - the persisted blob is malformed
 * - the persisted blob's shape doesn't match the current
 *   ``AdvancedSearchFilters`` schema
 */
export function loadPersistedFilters(): AdvancedSearchFilters | null {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return null;
    }
    const raw = window.localStorage.getItem(PERSIST_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!isValidFiltersShape(parsed)) {
      return null;
    }
    return parsed;
  } catch {
    // localStorage can throw (QuotaExceededError, SecurityError
    // in iframes, etc.) — never let the modal crash because of
    // a persistence snafu.
    return null;
  }
}

/**
 * Persist the user's filter bundle. Silently no-ops when
 * localStorage is unavailable.
 */
export function savePersistedFilters(filters: AdvancedSearchFilters): void {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return;
    }
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(filters));
  } catch {
    // Same reasoning as loadPersistedFilters.
  }
}

/**
 * Clear the persisted filter bundle. Mostly useful for tests
 * and a future "Reset to defaults" button if we want a
 * global clear.
 */
export function clearPersistedFilters(): void {
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
 * Lightweight shape check — we don't try to validate every
 * field, just the top-level keys. The runtime uses them as
 * duck-typed objects anyway.
 */
function isValidFiltersShape(
  value: unknown,
): value is AdvancedSearchFilters {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  // At least one of these known fields should be present.
  const v = value as Record<string, unknown>;
  return (
    'query' in v ||
    'since_year' in v ||
    'until_year' in v ||
    'sort_by' in v ||
    'document_types' in v ||
    'sources' in v
  );
}
