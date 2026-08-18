// @vitest-environment node
//
// test_favicon_link.test.ts
//
// Verifies the index.html template references the
// application favicon. The Vite build copies the
// public/ directory into dist/ unchanged, so the
// template is the source of truth.
//
// This is a regression guard against accidentally
// dropping the <link rel="icon"> tag -- the
// user reported the tab logo wasn't visible, and
// part of the diagnosis was that the favicon.ico
// file was corrupted (Targa-format garbage). The
// HTML link was always there, but a working
// favicon.ico is also required for browsers that
// don't honor the SVG <link>.
//
// Runs in the node environment (not jsdom) so we
// can use ``node:fs`` to read the favicon file
// from disk.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

describe('favicon', () => {
  it('index.html references the SVG favicon', () => {
    const indexPath = resolve(__dirname, '../../index.html');
    const html = readFileSync(indexPath, 'utf-8');
    expect(html).toMatch(/<link[^>]+rel=["']icon["']/);
    expect(html).toMatch(/href=["']\/favicon\.svg["']/);
  });

  it('public/favicon.svg exists and is non-empty', () => {
    const svgPath = resolve(__dirname, '../../public/favicon.svg');
    const svg = readFileSync(svgPath, 'utf-8');
    expect(svg.length).toBeGreaterThan(100);
    expect(svg).toContain('<svg');
    expect(svg).toContain('</svg>');
  });

  it('public/favicon.ico is a valid Windows icon resource', () => {
    const icoPath = resolve(__dirname, '../../public/favicon.ico');
    const ico = readFileSync(icoPath);
    // Windows .ico files start with 0x00 0x00 0x01 0x00
    // (reserved + type=1). The number of images is at
    // bytes 4-5.
    expect(ico[0]).toBe(0x00);
    expect(ico[1]).toBe(0x00);
    expect(ico[2]).toBe(0x01);
    expect(ico[3]).toBe(0x00);
    // Number of images in the directory.
    expect(ico[4]).toBeGreaterThanOrEqual(0x01);
    // Width/height in pixels (0 means 256).
    const width = ico[6];
    const height = ico[7];
    expect([16, 32, 48, 64, 128, 256]).toContain(width);
    expect([16, 32, 48, 64, 128, 256]).toContain(height);
  });
});
