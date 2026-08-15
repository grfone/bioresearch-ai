// test/smoke.test.tsx
//
// Smoke test for the test setup. This file exists to verify that:
//   - Vitest picks up the test pattern ``src/**/*.{test,spec}.{ts,tsx}``.
//   - jsdom is the default environment (not node).
//   - jest-dom matchers are loaded and work.
//
// If any of these break, the rest of the frontend tests will
// silently misbehave. The smoke test is intentionally trivial —
// its job is to surface setup failures loudly, not to test
// application logic.

import { describe, it, expect } from 'vitest';

describe('test setup', () => {
  it('runs in a jsdom environment', () => {
    // jsdom exposes ``document`` and ``window``. If the environment
    // were node, these would be undefined and the assertion would
    // fail loudly.
    expect(typeof document).toBe('object');
    expect(typeof window).toBe('object');
  });

  it('loads jest-dom matchers', () => {
    // toBeInTheDocument comes from jest-dom. If the import
    // in setup.ts didn't take, this would be a "matcher not
    // found" error.
    const el = document.createElement('div');
    el.textContent = 'hello';
    document.body.appendChild(el);
    expect(el).toBeInTheDocument();
    document.body.removeChild(el);
  });

  it('cleans up between tests', () => {
    // The previous test's <div> should be gone — afterEach in
    // setup.ts calls cleanup() which removes all rendered
    // components.
    expect(document.body.children.length).toBe(0);
  });
});
