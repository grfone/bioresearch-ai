// test/setup.ts
//
// Vitest setup file. Runs before every test.
//
// We load the jest-dom matchers so component tests can use
// ``expect(...).toBeInTheDocument()`` and friends. The matchers
// are runtime-agnostic and don't depend on jest, so they work
// with Vitest and jsdom out of the box.
//
// We also clean up any DOM state between tests so a stale
// className from test A doesn't leak into test B.

import '@testing-library/jest-dom/vitest';

import { afterEach, beforeEach } from 'vitest';
import { cleanup } from '@testing-library/react';

beforeEach(() => {
  // Clear localStorage before each test so persisted
  // application state (searchFiltersStorage, toastStore,
  // workspaceStore, etc.) doesn't leak between tests.
  // jsdom's localStorage persists across tests in the
  // same worker unless explicitly cleared.
  if (
    typeof window !== 'undefined' &&
    window.localStorage
  ) {
    window.localStorage.clear();
  }
});

afterEach(() => {
  cleanup();
});
