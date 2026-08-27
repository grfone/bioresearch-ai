/**
 * Tests for ``src/lib/citationLink.ts``.
 *
 * The helpers convert ``[paper:N]`` markers in the LLM
 * output into clickable markdown links targeting the
 * bibliography list. Tests pin the conversion rules so a
 * future refactor doesn't silently break the click-through
 * contract.
 */
import { describe, expect, it } from "vitest";

import {
  citationAnchorId,
  linkifyCitationMarkers,
} from "./citationLink";

describe("linkifyCitationMarkers", () => {
  it("converts a single [paper:N] to a markdown link to #citation-N", () => {
    expect(linkifyCitationMarkers("is a marker [paper:5] today.", 20)).toBe(
      "is a marker [5](#citation-5) today.",
    );
  });

  it("converts every [paper:N] in the body", () => {
    const input =
      "Plasma p-tau217 is a sensitive marker [paper:19]. " +
      "BBMs are poised to expand access [paper:10]. " +
      "NT1 trajectory diverges [paper:5].";
    const expected =
      "Plasma p-tau217 is a sensitive marker [19](#citation-19). " +
      "BBMs are poised to expand access [10](#citation-10). " +
      "NT1 trajectory diverges [5](#citation-5).";
    expect(linkifyCitationMarkers(input, 20)).toBe(expected);
  });

  it("leaves the body untouched when there are no markers", () => {
    const text = "A research report with no citations in this paragraph.";
    expect(linkifyCitationMarkers(text, 20)).toBe(text);
  });

  it("returns an empty string unchanged", () => {
    expect(linkifyCitationMarkers("", 5)).toBe("");
  });

  it("leaves malformed markers alone (no link)", () => {
    expect(linkifyCitationMarkers("test [paper:] case", 20)).toBe(
      "test [paper:] case",
    );
    expect(linkifyCitationMarkers("test [paper:abc] case", 20)).toBe(
      "test [paper:abc] case",
    );
    expect(linkifyCitationMarkers("test [paper:1.5] case", 20)).toBe(
      "test [paper:1.5] case",
    );
  });

  it("leaves out-of-range markers alone as a defense-in-depth guard", () => {
    // The backend clamps the marker index to the valid
    // range, but if a future change ever lets an out-of-
    // range marker through, the frontend must not crash
    // and must not produce a broken link to a non-existent
    // anchor.
    expect(linkifyCitationMarkers("out of range [paper:99]", 20)).toBe(
      "out of range [paper:99]",
    );
    expect(linkifyCitationMarkers("zero index [paper:0]", 20)).toBe(
      "zero index [paper:0]",
    );
  });

  it("does not consume markers past the upper bound even if N is large", () => {
    // The ``maxCitationIndex`` argument bounds the legal
    // range. A marker past it must not produce a link.
    expect(linkifyCitationMarkers("cap [paper:50] here", 20)).toBe(
      "cap [paper:50] here",
    );
  });

  it("preserves marker format inside text that contains other bracket pairs", () => {
    // Verify the regex matches the full marker, not just
    // an open-bracket heuristic -- so surrounding square
    // brackets in the prose don't break extraction.
    expect(
      linkifyCitationMarkers(
        "[some note] p-tau217 [paper:1] [footnote: not a marker]",
        5,
      ),
    ).toBe("[some note] p-tau217 [1](#citation-1) [footnote: not a marker]");
  });

  it("handles a marker at the very start of the string", () => {
    expect(linkifyCitationMarkers("[paper:1] leading marker", 5)).toBe(
      "[1](#citation-1) leading marker",
    );
  });

  it("handles a marker at the very end of the string with no trailing punctuation", () => {
    expect(linkifyCitationMarkers("trailing marker [paper:3]", 5)).toBe(
      "trailing marker [3](#citation-3)",
    );
  });

  it("treats multiple consecutive markers as independent conversions", () => {
    expect(linkifyCitationMarkers("a[paper:1][paper:2]b", 5)).toBe(
      "a[1](#citation-1)[2](#citation-2)b",
    );
  });
});

describe("citationAnchorId", () => {
  it("formats 1-based index into #citation-N anchor", () => {
    expect(citationAnchorId(1)).toBe("citation-1");
    expect(citationAnchorId(7)).toBe("citation-7");
    expect(citationAnchorId(20)).toBe("citation-20");
  });

  it("matches the link target produced by linkifyCitationMarkers", () => {
    // The two helpers must agree on the anchor format --
    // if one changes to ``cite-1`` and the other to
    // ``citation-1``, every in-text link in every report
    // silently stops working. This test pins the
    // round-trip.
    const anchor = citationAnchorId(5);
    const linkedBody = linkifyCitationMarkers("see [paper:5]", 5);
    expect(linkedBody).toContain(`#${anchor}`);
    expect(anchor).toBe("citation-5");
  });
});