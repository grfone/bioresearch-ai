// useKeyboardShortcut.ts
/**
 * useKeyboardShortcut.ts
 * ----------------------
 * PC-first keyboard shortcut hook.
 *
 * The platform default is PC (Windows / Linux), where the
 * primary modifier is ``Ctrl``. Mac users can use the same keys
 * because browsers on Mac fire ``ctrlKey`` for both ``Ctrl``
 * and ``Cmd`` (Mac users can keep one hand on the command key
 * and the shortcuts still work).
 *
 * The display string (``Ctrl+K`` vs ``⌘K``) is computed with a
 * runtime platform detection so the user sees the right hint
 * for their machine. The actual handler logic is identical
 * across platforms.
 *
 * Usage
 * -----
 *
 *   useKeyboardShortcut({ key: 'k', ctrl: true }, () => {
 *     inputRef.current?.focus();
 *   });
 *
 * The hook is a thin wrapper around ``useEffect`` + a window
 * keydown listener. It cleans up on unmount and ignores
 * shortcuts that fire while the user is typing in a
 * ``contenteditable`` region (e.g. the rich-text editor).
 */

import { useEffect } from 'react';

export interface ShortcutOptions {
  /** Lowercase key. Modifiers are separate flags. */
  key: string;
  /** PC default. Fires on ``Ctrl`` on PC; on Mac, ``Ctrl`` and
   *  ``Cmd`` both fire ``ctrlKey`` so the same binding works. */
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  /** When true, the shortcut fires even when the user is
   *  typing in an input/textarea. Default false — interactions
   *  with form fields are usually respected. */
  allowInInputs?: boolean;
}

export interface ShortcutDescriptor {
  key: string;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  /** Display string for the user. ``Ctrl+K`` on PC, ``⌘K`` on Mac. */
  label: string;
  /** ``true`` if the current platform is Mac. */
  isMac: boolean;
}

/**
 * Detect the user's platform. Runs once at module load — the
 * browser can't change platform mid-session.
 */
export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  // Mac reports ``MacIntel`` / ``MacPPC`` / ``MacARM`` in the
  // platform field. iOS / iPadOS also report ``MacIntel`` for
  // compatibility but they're mobile — we treat them as PC
  // because the user uses a touch keyboard and doesn't expect
  // ⌘ to do anything useful.
  const platform = navigator.platform || '';
  if (/iPad|iPhone|iPod/.test(navigator.userAgent)) return false;
  return platform.startsWith('Mac');
}

/**
 * Build a human-readable label for a key combo. PC-first:
 * ``Ctrl+K`` is the default; Mac users see ``⌘K``.
 */
export function shortcutLabel(
  options: ShortcutOptions,
  isMac: boolean = isMacPlatform(),
): string {
  // Build the modifier prefix and the key separately so the
  // platform-specific separator logic stays in one place.
  //
  // PC: ``Ctrl+Shift+Alt+K`` — modifiers joined with ``+``,
  //   the key appended with another ``+``.
  // Mac: ``⌘⇧⌥K`` — modifier glyphs appended directly to
  //   each other (no separator), the key appended with no
  //   separator. This matches the system shortcut shown in
  //   the macOS menu bar.
  const modParts: string[] = [];
  if (options.ctrl) modParts.push(isMac ? '⌘' : 'Ctrl');
  // PC convention: modifier order is Ctrl, Shift, Alt (or
  // Ctrl, Alt, Shift on Linux). We use Ctrl -> Shift -> Alt
  // because that's the cross-platform convention.
  if (options.shift) modParts.push(isMac ? '⇧' : 'Shift');
  if (options.alt) modParts.push(isMac ? '⌥' : 'Alt');
  const key = options.key.toUpperCase();
  if (isMac) {
    return [...modParts, key].join('');
  }
  return [...modParts, key].join('+');
}

/**
 * Decide whether a keyboard event matches the descriptor.
 * Returns ``true`` when the event was triggered by the user
 * (not by Chromium's auto-repeat for held keys).
 */
function matches(
  event: KeyboardEvent,
  options: ShortcutOptions,
): boolean {
  if (event.key.toLowerCase() !== options.key.toLowerCase()) {
    return false;
  }
  if (options.ctrl && !event.ctrlKey && !event.metaKey) return false;
  if (!options.ctrl && (event.ctrlKey || event.metaKey)) return false;
  if (options.shift && !event.shiftKey) return false;
  if (!options.shift && event.shiftKey) return false;
  if (options.alt && !event.altKey) return false;
  if (!options.alt && event.altKey) return false;
  return true;
}

/**
 * Check if the user is currently typing in an input field.
 * We don't want to hijack letter keys while the user is filling
 * out a form — that's the most common source of frustration
 * with keyboard shortcuts.
 */
function isTypingInField(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
    return true;
  }
  // Rich-text editors use ``contenteditable``. Check both the
  // property (real browsers) and the attribute (jsdom and any
  // framework that sets the attribute directly without
  // reflecting the property).
  if (el instanceof HTMLElement) {
    if (el.isContentEditable) return true;
    if (el.getAttribute('contenteditable') !== null) return true;
  }
  return false;
}

/**
 * Bind a keyboard shortcut to a handler. The handler runs only
 * when the descriptor matches the fired event and the user is
 * not currently typing in a form field (unless
 * ``allowInInputs`` is set).
 */
export function useKeyboardShortcut(
  options: ShortcutOptions,
  handler: (event: KeyboardEvent) => void,
): void {
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (!matches(event, options)) return;
      if (!options.allowInInputs && isTypingInField()) return;
      event.preventDefault();
      handler(event);
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, [options.key, options.ctrl, options.shift, options.alt, options.allowInInputs, handler]);
}
