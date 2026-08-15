// hooks/useKeyboardShortcut.test.ts
//
// Unit tests for the global keyboard-shortcut hook.
//
// These tests run in jsdom (the project's default Vitest
// environment) and exercise the hook end-to-end:
//   - mount a component that uses the hook
//   - dispatch a KeyboardEvent on window
//   - assert the handler ran / didn't run
//
// We test PC-first behaviour: Ctrl+K fires the binding on PC,
// and the same Ctrl+K fires on Mac (because the browser fires
// ``ctrlKey`` for both Ctrl and Cmd). The display label is
// platform-aware via ``shortcutLabel({ ctrl: true }, isMac)``.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import {
  useKeyboardShortcut,
  shortcutLabel,
  isMacPlatform,
} from './useKeyboardShortcut';

/** Dispatch a keydown event on the window with the given
 *  modifier flags. Returns the event so tests can inspect it. */
function pressKey(opts: {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  target?: EventTarget | null;
}) {
  const event = new KeyboardEvent('keydown', {
    key: opts.key,
    ctrlKey: opts.ctrlKey ?? false,
    metaKey: opts.metaKey ?? false,
    shiftKey: opts.shiftKey ?? false,
    altKey: opts.altKey ?? false,
    bubbles: true,
    cancelable: true,
  });
  const target = opts.target ?? window;
  target.dispatchEvent(event);
  return event;
}

describe('useKeyboardShortcut', () => {
  beforeEach(() => {
    // jsdom keeps a single document across tests. Clear the
    // body so leftover elements don't accidentally swallow
    // keyboard events.
    document.body.innerHTML = '';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fires the handler when the bound key is pressed', () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    pressKey({ key: 'k', ctrlKey: true });

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('preventDefault on the event so the browser does not steal the shortcut', () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    const event = pressKey({ key: 'k', ctrlKey: true });

    expect(event.defaultPrevented).toBe(true);
  });

  it('fires on Mac where Cmd is the meta key', () => {
    // jsdom reports ``platform === ''`` which is not "Mac". We
    // assert the *binding* (keyboard event) behaviour, not the
    // display label. The handler must fire when the user presses
    // Cmd+K OR Ctrl+K on a Mac because the browser fires
    // ``ctrlKey`` for both.
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    pressKey({ key: 'k', metaKey: true });

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('does not fire when only the bare key is pressed (no modifier)', () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    pressKey({ key: 'k' });

    expect(handler).not.toHaveBeenCalled();
  });

  it('does not fire when a different key is pressed', () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    pressKey({ key: 'j', ctrlKey: true });

    expect(handler).not.toHaveBeenCalled();
  });

  it('does not fire when the user is typing in an input field', () => {
    // The most common source of shortcut frustration: the user is
    // filling out a form and the shortcut hijacks their input.
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    pressKey({ key: 'k', ctrlKey: true, target: input });

    expect(handler).not.toHaveBeenCalled();
    expect(input).toBe(document.activeElement);
  });

  it('does not fire when the user is typing in a textarea', () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    const textarea = document.createElement('textarea');
    document.body.appendChild(textarea);
    textarea.focus();

    pressKey({ key: 'k', ctrlKey: true, target: textarea });

    expect(handler).not.toHaveBeenCalled();
  });

  it('does not fire when the user is typing in a contenteditable', () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    // Use ``setAttribute`` rather than the property setter
    // because jsdom doesn't reflect ``contentEditable = 'true'``
    // back to the attribute. The hook checks both property and
    // attribute so it works in real browsers AND in jsdom.
    const div = document.createElement('div');
    div.setAttribute('contenteditable', 'true');
    document.body.appendChild(div);
    div.focus();

    pressKey({ key: 'k', ctrlKey: true, target: div });

    expect(handler).not.toHaveBeenCalled();
  });

  it('fires when allowInInputs is set, even with an input focused', () => {
    // The opt-in flag is for app-level shortcuts that should
    // always fire (e.g. global search palette). Most users
    // don't want this; wire it deliberately.
    const handler = vi.fn();
    renderHook(() =>
      useKeyboardShortcut(
        { key: 'k', ctrl: true, allowInInputs: true },
        handler,
      ),
    );

    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    pressKey({ key: 'k', ctrlKey: true, target: input });

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('does not fire when shift is required but not pressed', () => {
    const handler = vi.fn();
    renderHook(() =>
      useKeyboardShortcut({ key: 'k', ctrl: true, shift: true }, handler),
    );

    pressKey({ key: 'k', ctrlKey: true });

    expect(handler).not.toHaveBeenCalled();
  });

  it('does not fire when shift is pressed but not required', () => {
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    pressKey({ key: 'k', ctrlKey: true, shiftKey: true });

    expect(handler).not.toHaveBeenCalled();
  });

  it('unbinds the listener when the hook unmounts', () => {
    const handler = vi.fn();
    const { unmount } = renderHook(() =>
      useKeyboardShortcut({ key: 'k', ctrl: true }, handler),
    );

    unmount();

    pressKey({ key: 'k', ctrlKey: true });

    expect(handler).not.toHaveBeenCalled();
  });

  it('matches keys case-insensitively', () => {
    // The hook accepts a lowercase key but the user's keyboard
    // event reports the actual key, which may have a shifted
    // character. The matcher lowercases both sides.
    const handler = vi.fn();
    renderHook(() => useKeyboardShortcut({ key: 'k', ctrl: true }, handler));

    pressKey({ key: 'K', ctrlKey: true });

    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe('shortcutLabel', () => {
  // We can't directly test the runtime platform detection in
  // jsdom because navigator.platform is empty. Instead, we test
  // the platform-aware label by passing the second argument
  // explicitly.

  it('renders Ctrl+K on PC', () => {
    const label = shortcutLabel({ key: 'k', ctrl: true }, false);
    expect(label).toBe('Ctrl+K');
  });

  it('renders ⌘K on Mac', () => {
    const label = shortcutLabel({ key: 'k', ctrl: true }, true);
    expect(label).toBe('⌘K');
  });

  it('prefixes Shift and Alt in PC order: Ctrl+Shift+Alt+K', () => {
    const label = shortcutLabel(
      { key: 'k', ctrl: true, shift: true, alt: true },
      false,
    );
    expect(label).toBe('Ctrl+Shift+Alt+K');
  });

  it('prefixes Shift and Alt in Mac order, no separators: ⌘⇧⌥K', () => {
    // macOS menu-bar convention: modifier glyphs are concatenated
    // with no separator (matches what users see in the menu bar).
    const label = shortcutLabel(
      { key: 'k', ctrl: true, shift: true, alt: true },
      true,
    );
    expect(label).toBe('⌘⇧⌥K');
  });

  it('uppercases the key', () => {
    const label = shortcutLabel({ key: 'p', ctrl: true }, false);
    expect(label).toBe('Ctrl+P');
  });

  it('returns just the key when no modifiers are set', () => {
    const label = shortcutLabel({ key: 'escape' }, false);
    expect(label).toBe('ESCAPE');
  });
});

describe('isMacPlatform', () => {
  it('returns a boolean', () => {
    // jsdom's navigator.platform is the empty string, so the
    // helper returns false. We assert the shape of the return
    // value rather than the specific result because the
    // platform is controlled by the runtime.
    expect(typeof isMacPlatform()).toBe('boolean');
  });
});
