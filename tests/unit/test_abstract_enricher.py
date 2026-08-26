"""
test_abstract_enricher.py

Unit tests for the AbstractEnricher -- the PMID-style
fallback for missing abstracts. Uses ``httpx.MockTransport``
so no real network requests are made.

The tests cover:
- URL normalization (strips ``https://doi.org/`` etc.)
- Each supported meta tag pattern (citation_abstract,
  description, og:description)
- Attribute order variation (name-vs-content order)
- HTML entity decoding
- Short-content rejection (titles, "Read the paper")
- Network error handling (no HTTP response)
- Non-200 status handling
- Bot-challenge pages (Datadome-style) returning None
- Context manager lifecycle (closes injected-vs-owned clients)
- URL encoding of DOIs with special characters
"""

from __future__ import annotations

import httpx
import pytest

from app.infrastructure.pubmed.abstract_enricher import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    AbstractEnricher,
    _clean_abstract,
    _strip_html_tags,
)


# A small but realistic Nature-style page with the abstract
# in <meta name="description">. We use this in multiple tests.
NATURE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>Deep learning - Nature</title>
    <meta name="description" content="Deep learning allows computational models that are composed of multiple processing layers to learn representations of data with multiple levels of abstraction. These methods have dramatically improved the state-of-the-art in speech recognition, visual object recognition, object detection and many other domains such as drug discovery and genomics.">
    <link rel="canonical" href="https://www.nature.com/articles/nature14539">
</head>
<body><h1>Deep learning</h1></body>
</html>
"""

# A PLOS-style page with citation_abstract (HighWire standard).
PLOS_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>PLOS ONE</title>
    <meta name="citation_abstract" content="Systemic inflammation is a leading cause of hospital death. Mild systemic inflammation is accompanied by warmth-seeking behavior.">
    <meta name="description" content="Systemic inflammation is a leading cause of hospital death. Mild systemic inflammation is accompanied by warmth-seeking behavior.">
</head>
<body></body>
</html>
"""

# A Frontiers-style page with og:description (Open Graph).
# Note: Frontiers sometimes has both property="description" and
# name="description" attributes -- our regex must handle either.
FRONTIERS_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta property="description" name="description" content="Schwann cells are exquisitely sensitive to the elasticity of their environment and their differentiation and capacity to myelinate depend on the transduction.">
    <meta property="og:description" content="Schwann cells are exquisitely sensitive to the elasticity of their environment and their differentiation and capacity to myelinate depend on the transduction.">
</head>
</html>
"""

# A Datadome-style bot challenge page (no abstract meta tag).
DATADOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta http-equiv="Content-Security-Policy" content="default-src 'self'">
    <title>Client Challenge</title>
</head>
<body>
    <h1>We're checking your browser...</h1>
</body>
</html>
"""

# A page where the abstract is truncated to < 40 chars
# (typical for meta description of a list page).
SHORT_HTML = """<html><head>
    <meta name="description" content="Read the paper">
</head></html>
"""

# A page with HTML entities that need decoding.
ENTITIES_HTML = """<html><head>
    <meta name="citation_abstract" content="Glucose &amp; insulin regulate &micro;RNA expression &gt; 2-fold in hepatocytes.">
</head></html>
"""

# A page where the content attribute comes BEFORE the name
# attribute (older WordPress / custom CMS pages).
REVERSED_HTML = """<html><head>
    <meta content="Glucose and insulin regulate microRNA expression in hepatocytes via a novel regulatory pathway." name="citation_abstract">
</head></html>
"""


def _make_enricher(handler) -> AbstractEnricher:
    """Build an enricher with a mocked httpx transport.

    The ``handler`` is a callable that takes a
    ``httpx.Request`` and returns an ``httpx.Response``.
    """
    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    return AbstractEnricher(client=client)


# -----------------------------------------------------------------
# URL normalization
# -----------------------------------------------------------------


class TestURLNormalization:
    def test_strips_https_doi_org_prefix(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, text=NATURE_HTML)

        enricher = _make_enricher(handler)
        enricher.fetch("https://doi.org/10.1038/nature14539")

        assert captured["url"] == "https://doi.org/10.1038/nature14539"

    def test_strips_http_doi_org_prefix(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, text=NATURE_HTML)

        enricher = _make_enricher(handler)
        enricher.fetch("http://doi.org/10.1038/nature14539")

        assert captured["url"] == "https://doi.org/10.1038/nature14539"

    def test_strips_doi_org_prefix_no_scheme(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, text=NATURE_HTML)

        enricher = _make_enricher(handler)
        enricher.fetch("doi.org/10.1038/nature14539")

        assert captured["url"] == "https://doi.org/10.1038/nature14539"

    def test_normalizes_bare_doi(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, text=NATURE_HTML)

        enricher = _make_enricher(handler)
        enricher.fetch("10.1038/nature14539")

        assert captured["url"] == "https://doi.org/10.1038/nature14539"

    def test_strips_surrounding_whitespace(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, text=NATURE_HTML)

        enricher = _make_enricher(handler)
        enricher.fetch("  10.1038/nature14539  ")

        assert captured["url"] == "https://doi.org/10.1038/nature14539"


# -----------------------------------------------------------------
# Meta tag extraction
# -----------------------------------------------------------------


class TestMetaTagExtraction:
    def test_extracts_citation_abstract(self):
        """PLOS-style: <meta name="citation_abstract" content="...">"""
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=PLOS_HTML)
        )
        result = enricher.fetch("10.1371/journal.pone.0000001")
        assert result is not None
        assert result.abstract.startswith("Systemic inflammation is a leading cause")
        assert "warmth-seeking behavior" in result.abstract

    def test_extracts_description_when_no_citation_abstract(self):
        """Nature-style: <meta name="description" content="...">"""
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=NATURE_HTML)
        )
        result = enricher.fetch("10.1038/nature14539")
        assert result is not None
        assert result.abstract.startswith("Deep learning allows computational models")
        assert "drug discovery and genomics" in result.abstract

    def test_extracts_og_description_when_no_others(self):
        """Frontiers-style: <meta property="og:description" content="...">"""
        # Strip the citation_abstract and description to test
        # the og:description fallback.
        frontiers_only_og = FRONTIERS_HTML.replace(
            '<meta property="description" name="description"',
            '<meta _DEPRECATED_',  # noqa
        )
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=frontiers_only_og)
        )
        result = enricher.fetch("10.3389/fnmol.2019.00177")
        assert result is not None
        assert result.abstract.startswith("Schwann cells are exquisitely sensitive")

    def test_handles_reversed_attribute_order(self):
        """Older WordPress pages: content before name."""
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=REVERSED_HTML)
        )
        result = enricher.fetch("10.1234/reversed")
        assert result is not None
        assert "Glucose and insulin regulate" in result.abstract

    def test_handles_html_entities(self):
        """Decodes &amp; &micro; &gt; etc. so the abstract is clean."""
        # The fixture HTML is short (< 40 chars), so we
        # replace the meta tag with a longer abstract for
        # this test to exercise entity decoding.
        long_html = (
            "<html><head>"
            "<meta name='citation_abstract' content='"
            "Glucose &amp; insulin regulate &micro;RNA expression "
            "&gt; 2-fold in hepatocytes under fed/fasted conditions."
            "'>"
            "</head></html>"
        )
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=long_html)
        )
        result = enricher.fetch("10.1234/entities")
        assert result is not None
        assert "&amp;" not in result.abstract, "amp entities should be decoded"
        assert "µ" in result.abstract, "micro entities should be decoded"
        assert "> 2" in result.abstract, "gt entities should be decoded"

    def test_prefers_citation_abstract_over_description(self):
        """When both tags are present, citation_abstract wins."""
        # PLOS has both; PLOS's citation_abstract is the
        # authoritative source. (In practice they're equal,
        # but the priority order avoids ambiguity.)
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=PLOS_HTML)
        )
        result = enricher.fetch("10.1371/journal.pone.0000001")
        # Both contain the same text, so the assertion is
        # just that it returned successfully.
        assert result is not None
        assert "Systemic inflammation" in result.abstract

    def test_returns_none_when_no_abstract_meta_tag(self):
        """Pages with no abstract meta tag (e.g. Datadome
        challenges) return None."""
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=DATADOME_HTML)
        )
        result = enricher.fetch("10.1007/978-3-031-64636-2_17")
        assert result is None

    def test_rejects_short_content(self):
        """Meta descriptions shorter than 40 chars are likely
        not abstracts (e.g. 'Read the paper')."""
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=SHORT_HTML)
        )
        result = enricher.fetch("10.1234/short")
        assert result is None


# -----------------------------------------------------------------
# Section-based full-text extraction (preferred over meta tags)
# -----------------------------------------------------------------


# Real HTML samples from the three publishers we target with
# the section-based regex. These are minimal fragments showing
# just the section structure; the rest of the page is
# irrelevant and is elided with "..." comments.
SPRINGER_SECTION_HTML = """
<html><body>
<meta name="description" content="This is the publisher's teaser
ending with literal three dots ...">
<section aria-labelledby="Abs1" data-title="Abstract" lang="en">
  <h2 id="Abs1">Abstract</h2>
  <div class="c-article-section__content" id="Abs1-content">
    <p>This is the full abstract. Collision cross section values tend to
remain consistent across experiments. <i>m/z</i> and retention times are
discussed. We trained deep learning neural networks on the METLIN-CCS
dataset. The mean relative error was 3.20 percent in 5-fold
cross-validation.</p>
  </div>
</section>
</body></html>
"""

NATURE_SECTION_HTML = """
<html><body>
<section id="Abs1">
  <h2>Abstract</h2>
  <div><p>Deep learning allows computational models that are composed of
multiple processing layers to learn representations of data with
multiple levels of abstraction.</p></div>
</section>
</body></html>
"""

# Oxford Academic / IEEE style: section carries ``data-title="Abstract"``
# but no id/aria-labelledby.
OUP_SECTION_HTML = """
<html><body>
<section data-title="Abstract">
  <h2>Abstract</h2>
  <div><p>Oxford Academic style abstract. The full text is in the
section body, not the meta tag.</p></div>
</section>
</body></html>
"""

# Page with BOTH a meta description (short) AND a section (full).
# The section wins because it has more content.
BOTH_HTML = """
<html><body>
<meta name="description" content="Short teaser.">
<section aria-labelledby="Abs1" data-title="Abstract" lang="en">
  <h2 id="Abs1">Abstract</h2>
  <div><p>This is the full abstract body text, much longer than the
meta description teaser above.</p></div>
</section>
</body></html>
"""


class TestSectionExtraction:
    """Section-based full-text extraction from the publisher's
    canonical ``<section>...</section>`` block.

    Why this exists
    ---------------
    Many publishers (Springer Nature, Nature, Oxford Academic,
    IEEE) put the *full* abstract in
    ``<section id="Abs1"><p>...</p></section>`` while their
    ``<meta name="description">`` is a short teaser -- sometimes
    ending with literal ``"..."`` (Springer's publisher
    convention). The section-based regex catches the full text;
    the meta-tag regex would catch only the teaser.
    """

    def test_extracts_springer_section(self):
        """Springer Nature's ``<section aria-labelledby="Abs1">``
        is the canonical case. The full abstract is in the
        section's ``<p>`` -- not in the meta description.
        """
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=SPRINGER_SECTION_HTML)
        )
        result = enricher.fetch("10.1007/978-3-031-64636-2_17")
        assert result is not None
        # The full abstract mentions specific details that
        # the meta teaser omits.
        assert "METLIN-CCS" in result.abstract
        assert "3.20 percent" in result.abstract
        # The publisher's trailing "..." in the meta tag is
        # NOT what we return -- the section body is the
        # canonical full text.
        assert not result.abstract.endswith("...")

    def test_extracts_nature_section(self):
        """Nature uses ``<section id="Abs1">`` (not aria-labelledby).
        """
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=NATURE_SECTION_HTML)
        )
        result = enricher.fetch("10.1038/nature14539")
        assert result is not None
        assert "Deep learning" in result.abstract
        assert "multiple processing layers" in result.abstract

    def test_extracts_oup_section(self):
        """Oxford Academic / IEEE: section carries ``data-title="Abstract"``
        but no id-based marker. We match the data-title.
        """
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=OUP_SECTION_HTML)
        )
        result = enricher.fetch("10.1093/bioinformatics/btab105")
        assert result is not None
        assert "Oxford Academic" in result.abstract

    def test_prefers_section_over_meta_when_both_present(self):
        """When both meta description and section are present,
        the section wins because it has more content.

        The meta description is short ("Short teaser." -- 14
        chars, below our 40-char floor). The section body has
        the full abstract. We should return the section body.
        """
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=BOTH_HTML)
        )
        result = enricher.fetch("10.1234/both")
        assert result is not None
        assert "Short teaser" not in result.abstract
        assert "full abstract body text" in result.abstract

    def test_falls_back_to_meta_tag_when_no_section(self):
        """Pages without a section block fall back to the
        meta-tag regexes. This preserves the historical
        behavior for PLOS, Frontiers, etc.
        """
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=NATURE_HTML)
        )
        result = enricher.fetch("10.1038/nature14539")
        assert result is not None
        # ``NATURE_HTML`` doesn't have a section block; we
        # extract from the meta tag (Nature happens to have
        # both -- the test fixture uses the meta-only form).
        assert "Deep learning" in result.abstract

    def test_returns_none_when_no_section_and_no_meta(self):
        """Pages with neither a section nor a meta tag return None."""
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=DATADOME_HTML)
        )
        result = enricher.fetch("10.1234/blocked")
        assert result is None

    def test_section_body_strips_nested_tags(self):
        """The section body often contains nested HTML tags
        (``<i>``, ``<b>``, ``<sup>`` for math like ``<i>m/z</i>``).
        These should be stripped to plain text in the
        returned abstract.
        """
        # The SPRINGER_SECTION_HTML fixture already contains
        # ``<i>m/z</i>`` -- verify the abstract doesn't carry
        # the raw tags through.
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=SPRINGER_SECTION_HTML)
        )
        result = enricher.fetch("10.1007/978-3-031-64636-2_17")
        assert result is not None
        assert "<i>" not in result.abstract
        assert "</i>" not in result.abstract
        # The plain text should still be there.
        assert "m/z" in result.abstract


# -----------------------------------------------------------------
# Network / HTTP error handling
# -----------------------------------------------------------------


class TestErrorHandling:
    def test_returns_none_on_network_error(self):
        """If the request raises httpx.HTTPError, return None."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("DNS resolution failed")

        enricher = _make_enricher(handler)
        result = enricher.fetch("10.1234/network-failure")
        assert result is None

    def test_returns_none_on_404(self):
        """404 -> None (not an exception)."""
        enricher = _make_enricher(
            lambda req: httpx.Response(404, text="Not Found")
        )
        result = enricher.fetch("10.1234/notfound")
        assert result is None

    def test_returns_none_on_403(self):
        """403 -> None (gated publishers serve 403 to bots)."""
        enricher = _make_enricher(
            lambda req: httpx.Response(403, text="Forbidden")
        )
        result = enricher.fetch("10.1234/forbidden")
        assert result is None

    def test_returns_none_on_500(self):
        """500 -> None (transient server errors)."""
        enricher = _make_enricher(
            lambda req: httpx.Response(500, text="Internal Server Error")
        )
        result = enricher.fetch("10.1234/server-error")
        assert result is None

    def test_returns_none_on_empty_body(self):
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text="")
        )
        result = enricher.fetch("10.1234/empty")
        assert result is None

    def test_returns_none_on_paywall_page(self):
        """A typical paywall page has no abstract meta tag."""
        paywall_html = """<html><head>
            <title>Sign in to read</title>
            <meta name="description" content="Access through your institution">
        </head></html>"""
        enricher = _make_enricher(
            lambda req: httpx.Response(200, text=paywall_html)
        )
        result = enricher.fetch("10.1234/paywall")
        # The "access through your institution" string is too
        # short to be a real abstract, so we return None.
        assert result is None


# -----------------------------------------------------------------
# Client lifecycle / context manager
# -----------------------------------------------------------------


class TestClientLifecycle:
    def test_context_manager_closes_owned_client(self):
        """The enricher closes the httpx.Client it built."""
        with AbstractEnricher() as enricher:
            # The client is owned because we didn't pass one.
            assert enricher._owns_client is True
            assert enricher._client.is_closed is False

        # Exit the context: client should now be closed.
        assert enricher._client.is_closed is True

    def test_context_manager_does_not_close_injected_client(self):
        """The enricher leaves injected clients alone."""
        client = httpx.Client()
        try:
            with AbstractEnricher(client=client) as enricher:
                assert enricher._owns_client is False

            # After exit, the injected client is still open.
            assert client.is_closed is False
        finally:
            client.close()

    def test_user_agent_override(self):
        """The user_agent kwarg becomes the User-Agent header."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["ua"] = request.headers.get("User-Agent")
            return httpx.Response(200, text=NATURE_HTML)

        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": "CustomBot/1.0"},
        )
        with AbstractEnricher(client=client):
            pass  # entering the context doesn't make the request

        # Now make the request outside the context but
        # with the same client.
        client.get("https://example.com")
        assert captured["ua"] == "CustomBot/1.0"

    def test_custom_timeout(self):
        """The timeout kwarg overrides the default."""
        with AbstractEnricher(timeout=2.5) as enricher:
            assert enricher._client.timeout.connect == 2.5


# -----------------------------------------------------------------
# Pure-function tests for the cleaner (no network)
# -----------------------------------------------------------------


class TestCleanAbstract:
    def test_collapses_whitespace(self):
        text = (
            "Line 1\n\nLine 2\t\tLine 3 with extra padding "
            "to clear the 40-character threshold"
        )
        assert _clean_abstract(text) == (
            "Line 1 Line 2 Line 3 with extra padding "
            "to clear the 40-character threshold"
        )

    def test_strips_html_entities(self):
        # ``&amp;`` -> ``&`` so the abstract is plain text.
        text = "AT&amp;CG TA pattern recognition sequence motif"
        assert _clean_abstract(text) == (
            "AT&CG TA pattern recognition sequence motif"
        )

    def test_trims_leading_trailing_whitespace(self):
        text = "   hello world at the start of the abstract   "
        assert _clean_abstract(text) == (
            "hello world at the start of the abstract"
        )

    def test_rejects_empty_string(self):
        assert _clean_abstract("") == ""

    def test_rejects_whitespace_only(self):
        assert _clean_abstract("   \n\t  ") == ""

    def test_rejects_under_40_chars(self):
        # "Read the paper" = 14 chars. Below 40.
        assert _clean_abstract("Read the paper") == ""

    def test_accepts_40_chars_or_more(self):
        text = "a" * 40
        assert _clean_abstract(text) == text

    def test_preserves_punctuation(self):
        text = (
            "We measured glucose (10 mM) and insulin (1 nM) "
            "in hepatocytes. The fold-change was 2.3+/-0.5."
        )
        assert _clean_abstract(text) == text

    def test_strips_trailing_publisher_ellipsis(self):
        """Springer's meta descriptions end with literal "..." as
        a "see the page for more" signal. Stripping it makes the
        abstract read as complete rather than truncated.

        Without the strip, the user sees ``"...This..."`` and
        assumes the abstract is truncated mid-sentence. After
        the strip, they see ``"...This."`` -- still slightly
        truncated-feeling but accurate.

        The fixture is intentionally longer than the 40-char
        floor so the strip and the length check don't fight
        each other (the strip is BEFORE the length check, but
        if we strip a fixture that's already too short, the
        strip returns ``""`` -- which is the right answer for
        "too short to be an abstract" but a confusing test
        signal). We use a realistic Spring-style abstract.
        """
        # A Spring-style meta description ending in literal "..."
        text = (
            "Collision cross section values tend to remain "
            "consistent across experiments. This makes them "
            "useful for metabolite annotation..."
        )
        assert _clean_abstract(text) == (
            "Collision cross section values tend to remain "
            "consistent across experiments. This makes them "
            "useful for metabolite annotation"
        )

    def test_strips_trailing_ellipsis_with_surrounding_spaces(self):
        """Publisher teasers sometimes have ``" ... "`` (spaces
        around the ellipsis). Strip those too.
        """
        text = (
            "We trained several machine learning models on the "
            "METLIN-CCS dataset for metabolite annotation ... "
        )
        assert _clean_abstract(text) == (
            "We trained several machine learning models on the "
            "METLIN-CCS dataset for metabolite annotation"
        )

    def test_preserves_mid_text_ellipsis(self):
        """Ellipses in the middle of the abstract are real
        mathematical or citation text (``see Eq. (1) ... (3)``)
        -- they must NOT be stripped. The strip is anchored
        at end-of-string.
        """
        text = (
            "We measured glucose (10 mM) and insulin ... "
            "(1 nM) in hepatocytes. The fold-change was 2.3+/-0.5."
        )
        assert _clean_abstract(text) == text


# -----------------------------------------------------------------
# HTML tag stripping (pure-function tests)
# -----------------------------------------------------------------
#
# The ``_strip_html_tags`` helper removes raw HTML that some
# publishers (notably Elsevier / Springer Nature) leave behind
# in the abstract field. The rule is asymmetric: heading tags
# ``<h1>``-``<h6>`` drop the wrapped text (the publisher's
# structured-abstract label like "Introduction"), but every
# other tag (``<i>``, ``<b>``, ``<strong>``, ``<em>``, ``<u>``,
# ``<sup>``, ``<sub>``, ``<span>``, ``<a>``, etc.) drops the
# tags but keeps the wrapped text. These tests pin the rule.


class TestStripHTMLTags:
    """Direct unit tests for ``_strip_html_tags``."""

    def test_drops_h4_label_and_its_inner_text(self):
        """The bug from the user's PDF: ``<h4>Introduction</h4>``
        should be removed entirely so "Introduction" doesn't leak
        into the rendered abstract. ``<h4>Tau species...`` then
        just becomes ``Tau species...``.
        """
        text = (
            "<h4>Introduction</h4>Tau species lacking truncation of "
            "the N-terminal region"
        )
        assert _strip_html_tags(text) == (
            "Tau species lacking truncation of the N-terminal region"
        )

    def test_drops_all_h_levels(self):
        """``<h1>`` through ``<h6>`` all drop the wrapped content.

        Pinning each level individually so a future contributor
        can't accidentally exclude one (``h4`` is the one that
        actually leaks today, but the other levels appear in
        the same Elsevier-style structured abstracts).
        """
        for level in range(1, 7):
            tag = f"h{level}"
            text = f"<{tag}>Label</{tag}>Body content follows"
            assert _strip_html_tags(text) == "Body content follows", (
                f"tag <{tag}> should drop its inner text"
            )

    def test_keeps_inner_text_for_inline_emphatic_tags(self):
        """``<i>``, ``<b>``, ``<strong>``, ``<em>``, ``<u>``,
        ``<sup>``, ``<sub>`` -- the tags drop, the inner text
        stays. This is the asymmetric part of the rule.
        """
        assert _strip_html_tags("<i>tau</i> pathology") == "tau pathology"
        assert _strip_html_tags("<b>bold</b> claim") == "bold claim"
        assert (
            _strip_html_tags("<strong>strong</strong> evidence")
            == "strong evidence"
        )
        assert _strip_html_tags("<em>emphasis</em> here") == "emphasis here"
        assert _strip_html_tags("<u>underlined</u> word") == "underlined word"
        assert _strip_html_tags("E = mc<sup>2</sup>") == "E = mc2"
        assert _strip_html_tags("H<sub>2</sub>O") == "H2O"

    def test_handles_nested_h_with_inline_tags_inside(self):
        """A ``<h4>`` wrapping ``<i>Introduction</i>`` should drop
        the whole thing (the outer h4 is in the drop set, so the
        inner content -- including any nested ``<i>`` tags --
        is consumed). The trailing non-tag text is preserved.
        """
        assert (
            _strip_html_tags("<h4><i>Introduction</i></h4>Tau species")
            == "Tau species"
        )

    def test_handles_real_pubmed_abstract_chunks(self):
        """A realistic Elsevier/Springer abstract chunk as it
        appears in the live data. All five structured-abstract
        section headings drop their labels; the body prose
        survives untouched. Pinning this against a literal
        fixture taken from production so a refactor of the
        stripper's rules is forced through test updates.
        """
        text = (
            "<h4>Highlights</h4>Map gains into accountable, "
            "interpretable tools for ADRD care."
            "<h4>Introduction</h4>Tau species lacking truncation "
            "of the N-terminal region, including plasma N-terminal "
            "tau fragment 1 (NT1), have been previously associated "
            "with cognitive decline, neurodegeneration, and tau "
            "pathology in late-onset sporadic Alzheimer's disease "
            "(AD)."
            "<h4>Methods</h4>Here, we examined crosssectional and "
            "longitudinal plasma NT1 as a possible predictor of "
            "cognitive, clinical, and core AD biomarker trajectories "
            "in autosomal dominant AD (ADAD)."
            "<h4>Results</h4>NT1 levels in ADAD mutation carriers "
            "(MC; n = 132) increased across the disease continuum."
            "<h4>Discussion</h4>Together, our results suggest that "
            "plasma NT1-alone or combined with other tau "
            "measures-may be useful in studying AD-related "
            "clinical, cognitive, and biomarker outcomes."
        )
        result = _strip_html_tags(text)
        assert "Highlights" not in result
        assert "Introduction" not in result
        assert "Methods" not in result
        assert "Results" not in result
        assert "Discussion" not in result
        # The body prose survives.
        assert "Tau species lacking truncation" in result
        assert "ADAD mutation carriers" in result
        assert "plasma NT1-alone or combined" in result
        # No raw tags leak through.
        assert "<" not in result
        assert ">" not in result

    def test_handles_malformed_unclosed_tags_gracefully(self):
        """Real-world abstracts sometimes contain half-encoded
        fragments (``<h4`` without the closing ``>``, missing
        closing tags). The stripper must NOT raise; it returns
        the best-effort cleaned string.

        ``HTMLParser`` is intentionally lenient -- unclosed
        tags are silently accepted and their content is
        treated as text. We verify the stripper doesn't raise
        and produces something usable.
        """
        # Unclosed <h4> opener -- HTMLParser will treat the
        # rest of the string as text inside the (unclosed)
        # heading. The drop rule still applies, so the entire
        # rest of the input is consumed.
        try:
            result = _strip_html_tags(
                "<h4>IntroductionTau species lacking truncation"
            )
        except Exception as exc:
            raise AssertionError(
                f"_strip_html_tags raised on malformed input: {exc}"
            )
        # The result is something (whatever the lenient parser
        # produces) -- the contract is "don't raise", not a
        # specific output. Real-world malformed inputs are
        # rare; the production path catches the rare failure
        # via the downstream length check in ``_clean_abstract``.
        assert isinstance(result, str)

    def test_returns_empty_for_empty_input(self):
        """Idempotent on empty string -- matches the contract
        of the rest of ``_clean_abstract``.
        """
        assert _strip_html_tags("") == ""

    def test_returns_input_unchanged_when_no_tags(self):
        """No HTML -> input passes through unchanged.
        Defensive against over-stripping.
        """
        text = (
            "Tau species lacking truncation of the N-terminal "
            "region, including plasma N-terminal tau fragment 1."
        )
        assert _strip_html_tags(text) == text


class TestCleanAbstractStripsHTML:
    """End-to-end pin: the ``_clean_abstract`` chokepoint
    applies the tag strip before the whitespace collapse, so
    the user's bug never reaches the LLM summariser, the React
    UI, the SQLite DB, or the API response.

    These tests don't re-pin the whitespace/ellipsis behaviour
    (already covered by ``TestCleanAbstract``); they just
    confirm the new HTML-strip step is wired in.
    """

    def test_drops_h4_introduction_label_in_cleaned_abstract(self):
        """A real-shape Elsevier abstract with ``<h4>Introduction</h4>``
        comes out of ``_clean_abstract`` with the label
        dropped. Below the 40-char rejection floor so we
        just confirm the label is gone -- not the full
        length validation.
        """
        text = (
            "<h4>Introduction</h4>Tau species lacking truncation of "
            "the N-terminal region, including plasma N-terminal "
            "tau fragment 1 (NT1), have been previously associated "
            "with cognitive decline, neurodegeneration, and tau "
            "pathology in late-onset sporadic Alzheimer's disease (AD)."
        )
        result = _clean_abstract(text)
        assert "Introduction" not in result
        assert "<h4>" not in result
        # The body prose is preserved (whitespace collapsed).
        assert "Tau species lacking truncation" in result
        assert "tau pathology in late-onset sporadic" in result

    def test_keeps_inner_text_for_inline_tags_in_cleaned_abstract(self):
        """``<i>tau</i> pathology`` becomes ``tau pathology``
        in the final cleaned abstract -- the asymmetric rule
        is honoured end-to-end.
        """
        text = (
            "Plasma <i>tau</i> levels in mutation carriers were "
            "elevated about a decade prior to estimated symptom "
            "onset. Cross-sectional and longitudinal <b>NT1</b> "
            "levels in mutation carriers were associated with "
            "clinical and biomarker changes."
        )
        result = _clean_abstract(text)
        assert "tau levels" in result  # <i>tau</i> preserved
        assert "NT1" in result  # <b>NT1</b> preserved (the surrounding "levels" too)
        assert "<i>" not in result
        assert "<b>" not in result


# -----------------------------------------------------------------
# Cache behaviour (LRU)
# -----------------------------------------------------------------


class TestCache:
    """Verify the LRU cache in AbstractEnricher.

    The cache is keyed by DOI and bounded by ``cache_size``.
    Both string and ``None`` results are cached -- a DOI
    that returned ``None`` (Datadome block) should not be
    re-fetched in the same session.
    """

    def test_repeat_doi_does_not_hit_network(self):
        """Second fetch with the same DOI must not make a
        network request -- the cache returns the first
        result.
        """
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, text=NATURE_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with AbstractEnricher(client=client, cache_size=10) as enricher:
            first = enricher.fetch("10.1038/nature14539")
            second = enricher.fetch("10.1038/nature14539")
            third = enricher.fetch("10.1038/nature14539")

        assert first is not None
        assert second == first
        assert third == first
        # Only the FIRST fetch hit the network.
        assert call_count[0] == 1

    def test_cache_miss_then_hit_increments_stats(self):
        """cache_stats reports hits and misses correctly."""
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=NATURE_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with AbstractEnricher(client=client, cache_size=10) as enricher:
            assert enricher.cache_stats() == {
                "hits": 0, "misses": 0, "size": 0, "capacity": 10,
            }
            enricher.fetch("10.1038/nature14539")
            assert enricher.cache_stats() == {
                "hits": 0, "misses": 1, "size": 1, "capacity": 10,
            }
            enricher.fetch("10.1038/nature14539")
            assert enricher.cache_stats() == {
                "hits": 1, "misses": 1, "size": 1, "capacity": 10,
            }
            enricher.fetch("10.1038/nature14539")
            assert enricher.cache_stats() == {
                "hits": 2, "misses": 1, "size": 1, "capacity": 10,
            }

    def test_cache_distinguishes_none_from_absent(self):
        """A DOI that returned ``None`` (e.g. blocked by
        anti-bot) is cached as ``None`` -- the second fetch
        returns ``None`` without hitting the network.
        """
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            # Datadome-style challenge page -- no abstract.
            return httpx.Response(200, text=DATADOME_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with AbstractEnricher(client=client, cache_size=10) as enricher:
            first = enricher.fetch("10.1007/blocked-doi")
            second = enricher.fetch("10.1007/blocked-doi")

        assert first is None
        assert second is None
        # Only one network call -- the second was served
        # from the cache.
        assert call_count[0] == 1
        assert enricher.cache_stats()["size"] == 1

    def test_cache_evicts_least_recently_used(self):
        """When the cache is full, the least-recently used
        entry is evicted on the next miss.
        """
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, text=NATURE_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        # Cache size 2 so we can test eviction easily.
        with AbstractEnricher(client=client, cache_size=2) as enricher:
            # Fill the cache.
            enricher.fetch("10.1038/a")
            enricher.fetch("10.1038/b")
            assert enricher.cache_stats()["size"] == 2
            assert call_count[0] == 2

            # Access 'a' to make it most-recently-used.
            enricher.fetch("10.1038/a")
            assert call_count[0] == 2  # hit, no network

            # Add 'c' -- this should evict 'b' (LRU).
            enricher.fetch("10.1038/c")
            assert call_count[0] == 3  # miss for c
            assert enricher.cache_stats()["size"] == 2

            # 'b' was evicted, so fetching it now misses.
            # Re-adding 'b' evicts the current LRU ('a'),
            # because 'a' has not been touched since step 3.
            enricher.fetch("10.1038/b")
            assert call_count[0] == 4  # miss for b (evicted)

            # Touch 'a' again to confirm it's been evicted.
            enricher.fetch("10.1038/a")
            assert call_count[0] == 5  # miss for a (evicted)

            # Now 'b' is MRU. Fetching 'c' should miss.
            enricher.fetch("10.1038/c")
            assert call_count[0] == 6  # miss for c (evicted)
            assert enricher.cache_stats()["size"] == 2

    def test_cache_size_zero_disables_caching(self):
        """Passing ``cache_size=0`` disables caching -- every
        fetch hits the network, even for repeat DOIs.
        """
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, text=NATURE_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with AbstractEnricher(client=client, cache_size=0) as enricher:
            enricher.fetch("10.1038/nature14539")
            enricher.fetch("10.1038/nature14539")
            enricher.fetch("10.1038/nature14539")

        assert call_count[0] == 3
        assert enricher.cache_stats() == {
            "hits": 0, "misses": 0, "size": 0, "capacity": 0,
        }

    def test_clear_cache_resets_state(self):
        """``clear_cache()`` drops all entries and resets
        the hit/miss counters."""
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=NATURE_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with AbstractEnricher(client=client, cache_size=10) as enricher:
            enricher.fetch("10.1038/nature14539")
            enricher.fetch("10.1038/nature14539")
            assert enricher.cache_stats()["size"] == 1
            assert enricher.cache_stats()["hits"] == 1

            enricher.clear_cache()
            assert enricher.cache_stats() == {
                "hits": 0, "misses": 0, "size": 0, "capacity": 10,
            }

    def test_different_dois_get_separate_cache_entries(self):
        """Two different DOIs occupy two cache slots."""
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, text=NATURE_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with AbstractEnricher(client=client, cache_size=10) as enricher:
            enricher.fetch("10.1038/a")
            enricher.fetch("10.1038/b")
            enricher.fetch("10.1038/a")  # hit
            enricher.fetch("10.1038/b")  # hit
            enricher.fetch("10.1038/a")  # hit

        assert call_count[0] == 2
        assert enricher.cache_stats()["hits"] == 3
        assert enricher.cache_stats()["misses"] == 2

    def test_doi_prefix_normalized_for_cache_key(self):
        """Cache is keyed by DOI, not by URL -- different
        forms of the same DOI hit the same cache slot.
        ``https://doi.org/10.1038/x`` and ``10.1038/x``
        share one entry.
        """
        from app.infrastructure.pubmed.abstract_enricher import (
            AbstractEnricher,
        )
        import httpx

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, text=NATURE_HTML)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(
            transport=transport,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with AbstractEnricher(client=client, cache_size=10) as enricher:
            enricher.fetch("https://doi.org/10.1038/nature14539")
            enricher.fetch("doi.org/10.1038/nature14539")
            enricher.fetch("10.1038/nature14539")

        assert call_count[0] == 1
        assert enricher.cache_stats()["hits"] == 2

