/**
 * Tests for ``src/lib/reportTitle.ts``.
 *
 * The helpers decide what the reader sees as the report title and
 * what is left in the body below it. Tests pin both rules so a
 * future refactor can't silently reintroduce a raw-markdown title
 * or a duplicated opening paragraph.
 */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_REPORT_TITLE,
  extractReportTitle,
  stripInlineMarkdown,
  stripTitleAndDuplicate,
} from "./reportTitle";

describe("extractReportTitle", () => {
  it("returns the first H1 line", () => {
    expect(
      extractReportTitle("# Latest Biomarkers for Alzheimer's Disease\n\nBody."),
    ).toBe("Latest Biomarkers for Alzheimer's Disease");
  });

  it("returns the default label when there is no H1", () => {
    expect(extractReportTitle("Just prose, no heading.")).toBe(
      DEFAULT_REPORT_TITLE,
    );
  });

  it("never returns raw markdown", () => {
    const summary =
      "# Among the supplied studies, **plasma N-terminal tau fragment 1**\n\nBody.";
    const title = extractReportTitle(summary);
    expect(title).toBe("Among the supplied studies, plasma N-terminal tau fragment 1");
    expect(title).not.toContain("**");
  });
});

describe("stripInlineMarkdown", () => {
  it("removes bold and code markers", () => {
    expect(stripInlineMarkdown("**plasma** N-terminal `tau`")).toBe(
      "plasma N-terminal tau",
    );
  });

  it("leaves a single asterisk alone", () => {
    expect(stripInlineMarkdown("p-tau217 and 3 * 4")).toBe("p-tau217 and 3 * 4");
  });

  it("collapses whitespace", () => {
    expect(stripInlineMarkdown("a   b\n\nc")).toBe("a b c");
  });
});

describe("stripTitleAndDuplicate", () => {
  it("drops the H1 line", () => {
    const out = stripTitleAndDuplicate("# The Title\n\nThe body.");
    expect(out).not.toContain("# The Title");
    expect(out).toContain("The body.");
  });

  it("drops the opening paragraph that repeats the title", () => {
    const summary =
      "# Among the supplied studies, plasma N-terminal tau fragment 1 (NT1)\n\n" +
      "Among the supplied studies, plasma N-terminal tau fragment 1 (NT1) has the strongest evidence.\n\n" +
      "## Next section\n\nMore prose.";
    const out = stripTitleAndDuplicate(summary);
    expect(out).not.toContain("has the strongest evidence");
    expect(out).toContain("## Next section");
  });

  it("keeps a section heading that precedes the repeat", () => {
    const summary =
      "# Among the supplied studies, plasma N-terminal tau fragment 1 (NT1)\n\n" +
      "### Bottom line\n\n" +
      "Among the supplied studies, plasma N-terminal tau fragment 1 (NT1) has the strongest evidence.\n\n" +
      "## Next section\n\nMore prose.";
    const out = stripTitleAndDuplicate(summary);
    expect(out).toContain("### Bottom line");
    expect(out).not.toContain("has the strongest evidence");
  });

  it("matches the repeat even when the body carries markdown", () => {
    const summary =
      "# Among the supplied studies, plasma N-terminal tau fragment 1 (NT1)\n\n" +
      "Among the supplied studies, **plasma N-terminal tau fragment 1 (NT1)** has the strongest evidence.\n\n" +
      "## Next section\n\nMore prose.";
    const out = stripTitleAndDuplicate(summary);
    expect(out).not.toContain("has the strongest evidence");
    expect(out).toContain("## Next section");
  });

  it("keeps an opening paragraph that does not repeat the title", () => {
    const summary =
      "# Latest Biomarkers for Alzheimer's Disease\n\n" +
      "The biomarker landscape has shifted decisively toward blood-based assays.\n\n" +
      "## Next section\n\nMore prose.";
    const out = stripTitleAndDuplicate(summary);
    expect(out).toContain("The biomarker landscape has shifted");
  });

  it("does not drop a paragraph that merely starts with the same word", () => {
    const summary =
      "# Tau in the clinic\n\nTau was measured in 132 carriers compared with 75 noncarriers.\n\n" +
      "## Next\n\nMore prose.";
    const out = stripTitleAndDuplicate(summary);
    expect(out).toContain("Tau was measured in 132 carriers");
  });
});
