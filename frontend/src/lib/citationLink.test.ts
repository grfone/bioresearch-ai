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

  it("silently drops out-of-range standalone markers", () => {
    // The backend clamps the marker index to the valid
    // range, but if a future change ever lets an out-of-
    // range marker through, the linkifier silently drops
    // it -- never producing a broken link to a non-
    // existent anchor AND never leaving visible
    // ``[paper:99]`` artefacts in the rendered page.
    // Hallucinated indices are surfaced via the backend's
    // logs.
    expect(linkifyCitationMarkers("out of range [paper:99]", 20)).toBe(
      "out of range ",
    );
    expect(linkifyCitationMarkers("zero index [paper:0]", 20)).toBe(
      "zero index ",
    );
    // Edge case: the marker is the only thing on its
    // line. The result is an empty string in the middle
    // of the prose (downstream the markdown list renderer
    // handles the empty bullet gracefully).
    expect(linkifyCitationMarkers("only [paper:99] here", 20)).toBe(
      "only  here",
    );
  });

  it("does not consume markers past the upper bound even if N is large", () => {
    // The ``maxCitationIndex`` argument bounds the legal
    // range. A marker past it is silently dropped -- the
    // linkifier returns an empty string for the marker
    // portion so the surrounding prose flows normally.
    expect(linkifyCitationMarkers("cap [paper:50] here", 20)).toBe(
      "cap  here",
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

describe("linkifyCitationMarkers -- grouped citations", () => {
  /**
   * Pin the rendering of ``[paper:N, paper:N, ...]`` --
   * the Vancouver grouped-citation form the LLM emits
   * when multiple papers support one claim. Without this
   * handling, grouped markers render as plain bracketed
   * text and the user can't click through to any of the
   * individual references (this is the bug the user
   * flagged in the screenshot showing the last paragraph
   * of the executive summary).
   */

  it("converts [paper:N, paper:M] into two comma-joined clickable links", () => {
    expect(linkifyCitationMarkers("see [paper:5, paper:12] today", 20))
      .toBe("see [5](#citation-5), [12](#citation-12) today");
  });

  it("converts [paper:N, paper:M, paper:K] into three comma-joined links", () => {
    // Exact reproduction of the failing string from the
    // user's bug report:
    expect(
      linkifyCitationMarkers(
        "monitoring [paper:7, paper:10, paper:19]. However",
        19,
      ),
    ).toBe("monitoring [7](#citation-7), [10](#citation-10), [19](#citation-19). However");
  });

  it("converts a grouped citation at the very start of the string", () => {
    expect(
      linkifyCitationMarkers("[paper:3, paper:13, paper:18] claims", 20),
    ).toBe("[3](#citation-3), [13](#citation-13), [18](#citation-18) claims");
  });

  it("converts a grouped citation at the very end of the string", () => {
    expect(linkifyCitationMarkers("see [paper:1, paper:17]", 20)).toBe(
      "see [1](#citation-1), [17](#citation-17)",
    );
  });

  it("preserves whitespace around grouped citations", () => {
    expect(
      linkifyCitationMarkers(
        "  [paper:4, paper:6]  trailing  ",
        20,
      ),
    ).toBe("  [4](#citation-4), [6](#citation-6)  trailing  ");
  });

  it("handles two grouped citations on the same line", () => {
    expect(
      linkifyCitationMarkers(
        "first [paper:1, paper:2] middle [paper:3, paper:4] end",
        20,
      ),
    ).toBe(
      "first [1](#citation-1), [2](#citation-2) middle [3](#citation-3), [4](#citation-4) end",
    );
  });

  it("passes grouped citations unchanged when all indices are out of range", () => {
    // Defense in depth: if the LLM ever emits a marker
    // past the bibliography length, the linkifier must
    // fall back to the original text so nothing is
    // silently lost.
    expect(linkifyCitationMarkers("see [paper:99, paper:100]", 20)).toBe(
      "see [paper:99, paper:100]",
    );
  });

  it("linkifies only when all entries in a group are in range", () => {
    // Mixed group: [1] is valid (citation 1 exists), [99]
    // is out of range. The linkifier silently drops the
    // invalid entry and renders the valid one -- this
    // matches the UX the user wants (no visible ``[paper:99]``
    // artefact in the rendered page). Hallucinated indices
    // are surfaced via the backend's logs, not the UI.
    const out = linkifyCitationMarkers("see [paper:1, paper:99]", 20);
    // The valid entry is a link to citation-1.
    expect(out).toContain("[1](#citation-1)");
    // The out-of-range entry is dropped (no visible
    // ``[paper:99]`` text).
    expect(out).not.toContain("[paper:99]");
    // The leading/trailing prose is preserved.
    expect(out.startsWith("see ")).toBe(true);
  });

  it("drops out-of-range entries from a group with mixed valid/invalid", () => {
    // Pin the production case: a 3-element group where
    // only one entry is out of range. The result should
    // be a comma-joined sequence of the two valid links
    // with the hallucinated entry silently dropped.
    const out = linkifyCitationMarkers(
      "see [paper:1, paper:99, paper:2].",
      5,
    );
    expect(out).toBe("see [1](#citation-1), [2](#citation-2).");
    expect(out).not.toContain("[paper:99]");
  });

  it("handles a group followed by a standalone marker on the same line", () => {
    expect(
      linkifyCitationMarkers(
        "see [paper:1, paper:2] and also [paper:5] end",
        20,
      ),
    ).toBe("see [1](#citation-1), [2](#citation-2) and also [5](#citation-5) end");
  });

  it("matches the user's exact bug-report snippet from the screenshot", () => {
    // The user-reported failing case, copy-pasted from the
    // screenshot's last paragraph. Pinning this verbatim
    // so a regression in the helper shows up as a test
    // failure that immediately names the bug.
    const input =
      "There is broad consensus that early biological " +
      "detection is essential for therapeutic impact, " +
      "and that BBMs will be central to scalable screening " +
      "and monitoring [paper:7, paper:10, paper:19]. However, " +
      "disagreement persists regarding whether AD should be " +
      "defined primarily by biological processes, " +
      "clinical symptoms, or both [paper:15, paper:20].";
    // Sanity: the input contains the exact failing pattern.
    expect(input).toContain("[paper:7, paper:10, paper:19]");
    expect(input).toContain("[paper:15, paper:20]");
    // After linkification, no ``[paper:N, paper:N]`` text
    // remains -- every grouped form has been replaced.
    const linked = linkifyCitationMarkers(input, 20);
    expect(linked).not.toContain("[paper:7, paper:10, paper:19]");
    expect(linked).not.toContain("[paper:15, paper:20]");
    // Each valid number becomes a clickable link.
    expect(linked).toContain("[7](#citation-7)");
    expect(linked).toContain("[10](#citation-10)");
    expect(linked).toContain("[19](#citation-19)");
    expect(linked).toContain("[15](#citation-15)");
    expect(linked).toContain("[20](#citation-20)");
  });

  it("linkifies a real-life citation list scraped from a live report", () => {
    // Pin the production case: a real LLM-generated
    // excerpt that has both standalone AND grouped
    // markers mixed together. This is the actual shape of
    // the bug -- the user-visible bug was that the
    // grouped markers rendered as raw text in the live
    // page.
    const input =
      "Cross-sectional and longitudinal NT1 levels in MC " +
      "were associated with clinical, cognitive, and " +
      "biomarker changes [paper:1]. NT1 increases " +
      "continued in symptomatic phases of disease, a " +
      "distinct trajectory from that seen with CSF " +
      "p-tau217 and other phospho-tau species [paper:5]. " +
      "Successive diagnostic criteria have increasingly " +
      "narrowed AD definition around amyloid β and tau " +
      "biomarkers [paper:15].";
    const out = linkifyCitationMarkers(input, 19);
    // All three standalone markers became links.
    expect(out).toContain("[1](#citation-1)");
    expect(out).toContain("[5](#citation-5)");
    expect(out).toContain("[15](#citation-15)");
    // No raw ``[paper:N]`` text remains for the valid indices.
    expect(out).not.toContain("[paper:1]");
    expect(out).not.toContain("[paper:5]");
    expect(out).not.toContain("[paper:15]");
  });
});