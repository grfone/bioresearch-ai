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

import { renderCitationWithDoiLink } from "./citationRender";

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
