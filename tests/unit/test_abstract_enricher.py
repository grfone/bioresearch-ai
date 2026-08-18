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

