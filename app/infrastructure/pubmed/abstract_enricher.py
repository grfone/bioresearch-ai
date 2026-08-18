"""abstract_enricher.py

PMID-style fallback for missing abstracts.

When CrossRef and OpenAlex both fail to supply an abstract
(common for book chapters, conference proceedings, and
preprints), this module tries to fetch the abstract from the
publisher's HTML landing page via the DOI resolver.

The approach -- "code or even the LLM" -- was the user's
suggestion in the original feedback. Code is safer (no API
costs, no hallucination risk) but only works for open
publishers:

- Nature (10.1038) -- <meta name="description">
- PLOS (10.1371) -- <meta name="citation_abstract">
- Frontiers (10.3389) -- <meta property="og:description">
- Oxford Academic (10.1093) -- <meta name="citation_abstract">
- PNAS (10.1073) -- <meta name="description">
- Royal Society (10.1098) -- <meta name="description">
- CSH (10.1101) -- <meta name="description">

Gated publishers (Springer, Elsevier, Wiley, BMC) deploy
anti-bot (Datadome, reCAPTCHA) that blocks polite User-Agents.
For those, the enricher returns None and the resolver records
the paper as having no abstract.

Usage
-----
    from app.infrastructure.pubmed.abstract_enricher import (
        AbstractEnricher,
    )

    with AbstractEnricher() as enricher:
        abstract = enricher.fetch("10.1038/nature14539")
    if abstract:
        print(abstract[:80])

The enricher is a context manager -- it manages the underlying
``httpx.Client`` lifecycle. For long-running services, you
can inject a client instead:

    client = httpx.Client(timeout=10.0)
    enricher = AbstractEnricher(client=client)
    # Reuse the same client across many doi fetches.

Limitations
-----------
- Some publishers serve different HTML to bots vs browsers
  (we send a polite User-Agent with contact info and a
  realistic Accept header, but Datadome etc. still block).
- Some abstracts are truncated to ~200 chars in the meta tag
  (the actual paper may have more).
- The DOI redirect can land on a paywall page even for
  open-access papers if the publisher geo-blocks.
"""

from __future__ import annotations

import html
import logging
import re
from collections import OrderedDict

import httpx

logger = logging.getLogger(__name__)


# Polite User-Agent -- includes a contact email so the
# publisher can reach out if our request volume is
# problematic. Match the format used by the rest of the
# codebase (see CrossRef/OpenAlex clients).
DEFAULT_USER_AGENT = (
    "BioResearchAI/1.0 (mailto:bioresearch@example.org) "
    "python-httpx"
)

# Per-request timeout. Gated publishers sometimes hang for
# 30+ seconds on the redirect before the challenge page
# renders; 8 seconds is a reasonable cap that we've seen
# work for Nature, PLOS, and Frontiers.
DEFAULT_TIMEOUT = 8.0

# Default cache size. 256 entries is plenty for one
# session -- each entry is the abstract string (typically
# 100-3000 chars) keyed by DOI. Disable with
# ``cache_size=0`` for tests or memory-constrained envs.
DEFAULT_CACHE_SIZE = 256


class AbstractEnricher:
    """Fetch missing abstracts from publisher HTML pages.

    The class is a context manager so the underlying
    ``httpx.Client`` is closed automatically. Tests can
    inject a pre-built client (with a MockTransport) to
    avoid hitting the network.

    Parameters
    ----------
    client : httpx.Client | None
        Pre-built client. If ``None``, the enricher builds
        its own client with the default timeout and
        User-Agent. The enricher is the owner of any client
        it creates (the ``__exit__`` closes it) but does not
        close injected clients.
    user_agent : str | None
        Override the User-Agent header. Useful for testing
        or for letting researchers identify their instance.
    timeout : float | None
        Override the per-request timeout in seconds.
    cache_size : int
        Maximum number of DOI -> abstract entries to keep
        in the in-memory LRU cache. Set to ``0`` to
        disable caching entirely (useful for tests and
        memory-constrained deployments). Default
        ``DEFAULT_CACHE_SIZE`` (256).
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout or DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent or DEFAULT_USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/"
                    "xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        # LRU cache: most-recently-fetched DOI is at the
        # back. When the cache is full, the least-recently
        # used entry is evicted. ``OrderedDict.move_to_end``
        # is the standard LRU pattern.
        #
        # Both string and ``None`` results are cached -- a
        # DOI that returned ``None`` (Datadome block, etc.)
        # should not be re-fetched within the same session.
        self._cache: OrderedDict[str, str | None] = OrderedDict()
        self._cache_size = max(0, int(cache_size))
        self._cache_hits = 0
        self._cache_misses = 0

    def __enter__(self) -> "AbstractEnricher":
        return self

    def __exit__(self, *args) -> None:
        if self._owns_client:
            self._client.close()

    def fetch(self, doi: str) -> str | None:
        """Try to fetch the abstract from the publisher's
        HTML landing page.

        Returns the abstract string (typically 100-3000
        characters) or ``None`` if the publisher blocks
        us, the page has no abstract meta tag, or the
        network call fails.

        Results are cached in a bounded LRU keyed by DOI
        so repeat lookups in the same session skip the
        network entirely. Both string and ``None`` results
        are cached -- a DOI that returned ``None``
        (Datadome block, network error) is not retried
        for the same session.

        Parameters
        ----------
        doi : str
            The DOI to resolve. Leading ``https://doi.org/``
            and ``doi.org/`` prefixes are stripped.
        """
        # Normalize the DOI for the cache key. Two forms
        # of the same DOI (e.g. "10.1038/x" and
        # "https://doi.org/10.1038/x") should share one
        # cache slot, otherwise a researcher who pastes
        # the DOI with a prefix and without would cause
        # two network requests.
        cache_key = self._normalize_doi(doi)
        if self._cache_size > 0 and cache_key in self._cache:
            # Cache hit. ``move_to_end`` marks this entry
            # as most-recently-used so it doesn't get
            # evicted on the next miss.
            self._cache.move_to_end(cache_key)
            self._cache_hits += 1
            return self._cache[cache_key]
        if self._cache_size > 0:
            self._cache_misses += 1

        url = self._build_url(doi)
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            logger.info(
                "AbstractEnricher: HTTP error for %s: %s",
                doi, exc,
            )
            result = None
        else:
            if response.status_code != 200:
                logger.info(
                    "AbstractEnricher: HTTP %d for %s",
                    response.status_code, doi,
                )
                result = None
            else:
                result = self._extract_abstract(response.text)

        # Store the result (even ``None``) so we don't
        # re-fetch the same DOI in this session. Evict
        # the oldest entry if the cache is full.
        if self._cache_size > 0:
            if cache_key in self._cache:
                # Shouldn't happen (the cache check at the
                # top would have returned), but defensively
                # move it to the end if the value changed.
                self._cache.move_to_end(cache_key)
                self._cache[cache_key] = result
            else:
                self._cache[cache_key] = result
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return result

    def cache_stats(self) -> dict[str, int]:
        """Return cache statistics for diagnostics.

        Useful for the bootstrap diagnostics log and for
        tests. Returns a dict with ``hits``, ``misses``,
        ``size``, and ``capacity`` keys.
        """
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": len(self._cache),
            "capacity": self._cache_size,
        }

    def clear_cache(self) -> None:
        """Drop all cached entries.

        Useful when a researcher wants to force a refresh
        (e.g. they fixed a typo in their DOI) or for
        tests that need a clean slate between cases.
        """
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    @staticmethod
    def _build_url(doi: str) -> str:
        """Normalize the DOI to the canonical URL form.

        ``doi.org/<doi>`` (with ``https://``) is the official
        DOI resolver URL. The publisher's landing page is
        the redirect target.
        """
        cleaned = AbstractEnricher._normalize_doi(doi)
        return f"https://doi.org/{cleaned}"

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        """Return the canonical DOI form (no prefix, stripped).

        Used for both cache keys and URL construction so
        ``"10.1038/x"`` and ``"https://doi.org/10.1038/x"``
        are treated as the same identifier.
        """
        cleaned = doi.strip()
        lowered = cleaned.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break
        return cleaned

    # Meta-tag patterns. We try a few formats because
    # publishers vary:
    # 1. citation_abstract -- HighWire / Google Scholar
    #    standard, used by PLOS, Oxford Academic, etc.
    # 2. description -- The most general-purpose meta tag.
    #    Used by Nature, PNAS, Royal Society, etc.
    # 3. og:description -- Open Graph, used by Frontiers.
    #
    # The patterns are deliberately permissive about
    # attribute order (name before content and vice versa)
    # and about quote styles (single vs double). The
    # Doctrine, Frontiers, and older Nature pages all have
    # slightly different attribute orders.
    _META_PATTERNS: tuple[re.Pattern[str], ...] = (
        # <meta name="citation_abstract" content="...">
        re.compile(
            r'<meta\s+[^>]*name=["\']citation_abstract["\']'
            r'[^>]*content=["\']([^"\']+)["\']',
            re.IGNORECASE | re.DOTALL,
        ),
        # <meta content="..." name="citation_abstract">
        re.compile(
            r'<meta\s+[^>]*content=["\']([^"\']+)["\']'
            r'[^>]*name=["\']citation_abstract["\']',
            re.IGNORECASE | re.DOTALL,
        ),
        # <meta name="description" content="...">
        re.compile(
            r'<meta\s+[^>]*name=["\']description["\']'
            r'[^>]*content=["\']([^"\']+)["\']',
            re.IGNORECASE | re.DOTALL,
        ),
        # <meta content="..." name="description">
        re.compile(
            r'<meta\s+[^>]*content=["\']([^"\']+)["\']'
            r'[^>]*name=["\']description["\']',
            re.IGNORECASE | re.DOTALL,
        ),
        # <meta property="og:description" content="...">
        re.compile(
            r'<meta\s+[^>]*property=["\']og:description["\']'
            r'[^>]*content=["\']([^"\']+)["\']',
            re.IGNORECASE | re.DOTALL,
        ),
        # <meta content="..." property="og:description">
        re.compile(
            r'<meta\s+[^>]*content=["\']([^"\']+)["\']'
            r'[^>]*property=["\']og:description["\']',
            re.IGNORECASE | re.DOTALL,
        ),
    )

    def _extract_abstract(self, html_text: str) -> str | None:
        """Pull the abstract from one of the known meta tags.

        Returns the first non-empty match, or ``None`` if
        none of the meta tags are present.

        HTML entity decoding and whitespace cleanup is
        delegated to ``_clean_abstract`` so the two
        responsibilities live in one place.
        """
        for pattern in self._META_PATTERNS:
            match = pattern.search(html_text)
            if match is None:
                continue
            content = match.group(1)
            cleaned = _clean_abstract(content)
            if cleaned:
                return cleaned
        return None


def _clean_abstract(text: str) -> str:
    """Normalize an abstract extracted from HTML.

    - Decode HTML entities (``&micro;`` -> ``µ``).
    - Collapse whitespace runs to single spaces.
    - Strip trailing whitespace.
    - Drop the abstract if it's too short to be useful
      (some sites return just the title or a short
      summary).
    """
    # Decode entities first so that, e.g., ``&micro;`` is
    # counted as a single character when measuring length.
    # We must use ``html.unescape`` here, not in
    # ``_extract_abstract``, so that the pure-function
    # behavior of ``_clean_abstract`` is self-contained.
    decoded = html.unescape(text)
    # Collapse all whitespace (including newlines and
    # non-breaking spaces) to single spaces.
    normalized = re.sub(r"\s+", " ", decoded).strip()
    if len(normalized) < 40:
        # Too short to be an abstract -- probably a meta
        # description like "Read the paper" or just the
        # title repeated.
        return ""
    return normalized
