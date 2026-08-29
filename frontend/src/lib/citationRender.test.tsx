/**
 * Tests for ``src/lib/citationRender.tsx``.
 *
 * The render helper converts a citation string (with
 * markdown links injected by ``linkifyCitationDoi``) into
 * a JSX node tree where the DOI segments are real anchor
 * elements.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import {
  renderCitationWithDoiLink,
  renderItemWithCitationLinks,
} from "./citationRender";

describe("renderCitationWithDoiLink", () => {
  it("renders plain text as a plain span fragment", () => {
    render(<>{renderCitationWithDoiLink("Smith J. Plasma marker.")}</>);
    expect(
      screen.getByText(/Smith J\. Plasma marker\./),
    ).toBeInTheDocument();
  });

  it("renders a DOI markdown link as a real anchor element", () => {
    const citation =
      "Smith J. Plasma marker. " +
      "[10.1234/abc.123](https://doi.org/10.1234/abc.123)";
    render(<>{renderCitationWithDoiLink(citation)}</>);
    const link = screen.getByRole("link", { name: "10.1234/abc.123" });
    expect(link).toHaveAttribute(
      "href",
      "https://doi.org/10.1234/abc.123",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("preserves plain text segments between link segments", () => {
    const citation =
      "Title here. " +
      "[10.1/aaa](https://doi.org/10.1/aaa)" +
      " ; " +
      "[10.2/bbb](https://doi.org/10.2/bbb)" +
      " after";
    render(<>{renderCitationWithDoiLink(citation)}</>);
    // Both links present
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveTextContent("10.1/aaa");
    expect(links[1]).toHaveTextContent("10.2/bbb");
    // Plain text segment preserved
    expect(screen.getByText(/Title here\./)).toBeInTheDocument();
    expect(screen.getByText(/;/)).toBeInTheDocument();
    expect(screen.getByText(/after/)).toBeInTheDocument();
  });

  it("returns null for empty input", () => {
    const { container } = render(<>{renderCitationWithDoiLink("")}</>);
    expect(container.textContent).toBe("");
  });

  it("opens link in new tab (target=_blank) for external DOI host", () => {
    // DOIs resolve to https://doi.org -- a different origin
    // from the app. ``rel="noopener noreferrer"`` prevents
    // the new tab from manipulating window.opener and
    // prevents leaking the Referer header.
    const citation =
      "title. [10.1/aaa](https://doi.org/10.1/aaa)";
    render(<>{renderCitationWithDoiLink(citation)}</>);
    const link = screen.getByRole("link", { name: "10.1/aaa" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders text NOT inside a link when it has no markdown link", () => {
    // The render helper splits on markdown links. Text
    // outside any link is rendered as plain text nodes.
    const citation = "no link here, just plain text";
    render(<>{renderCitationWithDoiLink(citation)}</>);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.getByText(/no link here, just plain text/),
    ).toBeInTheDocument();
  });
});


describe("renderItemWithCitationLinks", () => {
  it("renders text with no citation markers as plain text", () => {
    // No [N](#citation-N) -- the helper passes the
    // string through unchanged.
    const item = "Sample size is small.";
    render(<li>{renderItemWithCitationLinks(item)}</li>);
    expect(
      screen.getByText(/Sample size is small\./),
    ).toBeInTheDocument();
    // No anchors were created.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a single citation marker as a real anchor", () => {
    // The exact shape ``linkifyCitationMarkers`` emits.
    const item =
      "direct cross-modality comparisons of diagnostic performance " +
      "difficult [10](#citation-10).";
    render(<li>{renderItemWithCitationLinks(item)}</li>);
    const link = screen.getByRole("link", { name: "10" });
    expect(link).toHaveAttribute("href", "#citation-10");
    // The plain-text segments are still in the DOM as
    // direct text nodes (NOT wrapped in elements).
    expect(
      screen.getByText(/direct cross-modality comparisons/),
    ).toBeInTheDocument();
  });

  it("renders multiple citation markers in one item as separate anchors", () => {
    // The user's reported example: two markers in one
    // limitation item.
    const item =
      "Associations with [8](#citation-8), " +
      "[12](#citation-12).";
    render(<li>{renderItemWithCitationLinks(item)}</li>);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveTextContent("8");
    expect(links[0]).toHaveAttribute("href", "#citation-8");
    expect(links[1]).toHaveTextContent("12");
    expect(links[1]).toHaveAttribute("href", "#citation-12");
  });

  it("preserves plain text surrounding the citation markers", () => {
    // The plain text BEFORE and AFTER the citation must
    // remain in the DOM -- the helper only converts the
    // citation markers themselves, not the surrounding
    // prose.
    const item =
      "Risks include algorithmic opacity " +
      "[6](#citation-6) " +
      "and dataset bias " +
      "[6](#citation-6).";
    render(<li>{renderItemWithCitationLinks(item)}</li>);
    // Both anchor segments render.
    const links = screen.getAllByRole("link", { name: "6" });
    expect(links).toHaveLength(2);
    // Plain text survives (note: vitest/jsdom collapses
    // adjacent text nodes in some configs, so we just
    // verify the text shows up in the rendered output).
    expect(
      screen.getByText(/Risks include algorithmic opacity/),
    ).toBeInTheDocument();
    expect(screen.getByText(/and dataset bias/)).toBeInTheDocument();
  });

  it("returns null for empty input", () => {
    const { container } = render(
      <li>{renderItemWithCitationLinks("")}</li>,
    );
    // ``null`` doesn't render anything inside ``<li>``.
    expect(container.querySelector("li")?.innerHTML).toBe("");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("preserves leading and trailing punctuation around the citation", () => {
    // The linkify helper may emit a citation with a
    // trailing comma or period. The render helper must
    // pass those through as plain text (not inside the
    // anchor's text).
    const item =
      "Stated across multiple papers [4](#citation-4),";
    render(<li>{renderItemWithCitationLinks(item)}</li>);
    const link = screen.getByRole("link", { name: "4" });
    expect(link).toHaveAttribute("href", "#citation-4");
    // The text node carrying the comma is still in the
    // DOM (separately from the anchor's "4" text node).
    expect(
      screen.getByText(/multiple papers/),
    ).toBeInTheDocument();
  });

  it("highlights citation links with the design system's primary colour", () => {
    // Cosmetic contract: citation links get the
    // ``text-primary`` Tailwind class (the workspace's
    // accent colour), so users immediately see them as
    // clickable. This matches the citation DOI links
    // (which also use ``text-primary``) and the in-page
    // anchor links generated by ReactMarkdown for the
    // Executive Summary body.
    const item = "Citation follows. [3](#citation-3)";
    render(<li>{renderItemWithCitationLinks(item)}</li>);
    const link = screen.getByRole("link", { name: "3" });
    expect(link.className).toContain("text-primary");
  });
});
