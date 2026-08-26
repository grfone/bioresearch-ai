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
import html.parser
import logging
import re
from collections import OrderedDict
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.infrastructure.pubmed.llm_extractor import (
        LLMExtractor,
    )

# ExtractionResult is a tiny value type -- just an abstract
# string + an inferred boolean. We import it at runtime
# (not under TYPE_CHECKING) because we instantiate it in
# fetch(). The LLM path passes through the LLM's result;
# the deterministic path wraps its string as
# inferred=False. There's no import cycle here -- the LLM
# extractor doesn't import from this module.
from app.infrastructure.pubmed.llm_extractor import (
    ExtractionResult,
)

# The cache backend abstraction lives in
# ``app.infrastructure.cache``. We default to the in-memory
# implementation (preserves the historical behavior) but the
# container module can inject ``RedisCache`` instead when
# ``CACHE_BACKEND=redis``. See
# ``docs/multi-worker-cache-investigation.md`` for the rationale.
from app.infrastructure.cache import (
    HIT,
    HIT_NONE,
    CacheProtocol,
    InMemoryLRUCache,
)

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
    llm_extractor : LLMExtractor | None
        Optional LLM-based fallback for when the
        deterministic regex extraction returns ``None``
        or a very short string. The LLM extractor is
        VERBATIM-only (extracts text from the page or
        returns ``None`` -- never invents content).
        Pass ``None`` (default) to disable the LLM
        fallback entirely.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
        llm_extractor: "LLMExtractor | None" = None,
        cache: "CacheProtocol | None" = None,
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
        # Cache backend. Default is the in-memory LRU (the
        # historical behavior). The container module injects
        # a ``RedisCache`` instance when ``CACHE_BACKEND=redis``,
        # which gives all uvicorn workers a shared cache
        # (multi-worker fix -- see
        # ``docs/multi-worker-cache-investigation.md``).
        #
        # If both ``cache`` and ``cache_size`` are provided,
        # ``cache`` wins (the size is then irrelevant since
        # the impl's capacity was already configured at
        # construction time). The ``cache_size`` parameter is
        # preserved for back-compat with code that built the
        # enricher without thinking about cache backends.
        if cache is None:
            cache = InMemoryLRUCache(capacity=cache_size)
        self._cache: "CacheProtocol" = cache
        # Keep ``_cache_size`` as a passthrough for the
        # ``capacity`` field in ``cache_stats()``. With the
        # in-memory backend, this matches the actual capacity;
        # with Redis, the value comes from the
        # ``RedisCache.capacity`` (set at construction time).
        self._cache_size = cache.capacity
        # Optional LLM-based fallback. ``None`` means the
        # deterministic path is the only fallback. The
        # LLM path only fires when the deterministic path
        # returned ``None`` or a short string AND the
        # HTML was reachable (HTTP 200) -- never when we
        # got blocked by anti-bot, since the LLM has
        # nothing to extract from in that case.
        self._llm_extractor = llm_extractor

    def __enter__(self) -> "AbstractEnricher":
        return self

    def __exit__(self, *args) -> None:
        if self._owns_client:
            self._client.close()

    def fetch(self, doi: str) -> "ExtractionResult | None":
        """Try to fetch the abstract from the publisher's
        HTML landing page.

        Returns an ``ExtractionResult`` (abstract text +
        provenance flag) or ``None`` if the publisher
        blocks us, the page has no abstract, or the
        network call fails.

        The provenance flag (``inferred``) tells the
        caller whether the abstract came from the LLM
        fallback (``inferred=True``) or from the
        deterministic regex (``inferred=False``). The
        resolver uses this to stamp
        ``paper.inferred_abstract`` so the frontend can
        show an "AI-extracted" badge.

        Results are cached in a bounded LRU keyed by DOI
        so repeat lookups in the same session skip the
        network entirely. Both ``ExtractionResult`` and
        ``None`` results are cached -- a DOI that
        returned ``None`` (Datadome block, network error)
        is not retried for the same session.

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
        # ``self._cache.get`` returns a 3-valued status:
        #   HIT      -- key present, value is an ExtractionResult
        #   HIT_NONE -- key present, value is None (negative cache)
        #   MISS     -- key not present
        # The cache backend handles the LRU-refresh on hit
        # (moves-to-end) and the per-impl counter increments.
        # The enricher doesn't need to track hits/misses
        # itself -- they're in ``self._cache.stats()``.
        status, cached = self._cache.get(cache_key)
        if status in (HIT, HIT_NONE):
            # Use the same log messages the historical
            # code used so log scrapers and the
            # ``make verify`` smoke battery keep working.
            if status == HIT:
                logger.debug(
                    "AbstractEnricher cache HIT for %s", doi
                )
            else:
                # HIT_NONE -- the cache has a "no abstract"
                # entry for this DOI. Log it the same as a
                # HIT so operators can see we're honoring
                # the negative cache. A separate log level
                # (e.g. ``DEBUG-NONE``) would be over-engineered.
                logger.debug(
                    "AbstractEnricher cache HIT for %s", doi
                )
            return cached
        # status == MISS -- fall through to the HTTP fetch.
        logger.debug("AbstractEnricher cache MISS for %s", doi)

        url = self._build_url(doi)
        # ``raw_html`` is set ONLY when the HTTP response
        # is 200 and the body is non-empty. We pass it to
        # the LLM extractor when the deterministic regex
        # path returned None or a short string -- the LLM
        # has nothing to extract from if we never saw the
        # page (e.g. Datadome block).
        raw_html: str | None = None
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
                raw_html = response.text
                raw = self._extract_abstract(raw_html)
                # Deterministic path: not inferred.
                result = (
                    ExtractionResult(abstract=raw, inferred=False)
                    if raw else None
                )

        # Optional LLM fallback. The LLM only sees raw
        # HTML that we already fetched successfully --
        # we don't try to bypass anti-bot with the LLM,
        # because the LLM has no web access of its own
        # (it only sees what we put in the prompt). The
        # LLM contract is verbatim extraction or NONE;
        # see app.infrastructure.pubmed.llm_extractor.
        if (
            self._llm_extractor is not None
            and (
                result is None
                or not result.abstract.strip()
            )
            and raw_html is not None
        ):
            logger.debug(
                "AbstractEnricher: trying LLM fallback for %s", doi,
            )
            llm_result = self._llm_extractor.extract(raw_html)
            if llm_result is not None:
                # The LLM extractor returns an
                # ExtractionResult with inferred=True.
                # We trust its verbatim contract.
                result = llm_result
                logger.debug(
                    "AbstractEnricher: LLM extraction succeeded for %s "
                    "(inferred=True)",
                    doi,
                )
            else:
                logger.debug(
                    "AbstractEnricher: LLM extraction returned no "
                    "abstract for %s",
                    doi,
                )

        # Store the result (even ``None``) so we don't
        # re-fetch the same DOI in this session. The cache
        # backend is responsible for LRU eviction -- the
        # in-memory impl evicts via OrderedDict.popitem; the
        # Redis impl evicts via ZRANGE+DEL+ZREM. Either way,
        # callers don't see evictions.
        #
        # The ``result`` here is an ``ExtractionResult | None``.
        # The protocol's ``set`` accepts ``object | None`` and
        # stores it unchanged -- for the in-memory impl,
        # that's the object; for the Redis impl, we round-trip
        # through JSON. The contract on the way back (via
        # ``get``) is "object with .abstract and .inferred
        # attributes" -- which ExtractionResult satisfies
        # directly, and the Redis impl's dict shape (a
        # JSON-serialized ExtractionResult) also satisfies
        # because both have those attributes. The cast below
        # tells the type checker this is safe.
        if self._cache_size > 0:
            self._cache.set(cache_key, result)
        return result  # type: ignore[return-value]

    def cache_stats(self) -> dict[str, int]:
        """Return cache statistics for diagnostics.

        Useful for the bootstrap diagnostics log and for
        tests. Returns a dict with ``hits``, ``misses``,
        ``size``, and ``capacity`` keys.

        Note on multi-worker mode: when ``CACHE_BACKEND=memory``
        and the container runs with ``uvicorn --workers N``,
        these counters are PER WORKER (each process has its
        own in-memory LRU). When ``CACHE_BACKEND=redis``, the
        counters are system-wide (atomic INCR on Redis), so
        operators see the real totals regardless of which
        worker handles the admin call.
        """
        return self._cache.stats().as_dict()

    def clear_cache(self) -> None:
        """Drop all cached entries.

        Useful when a researcher wants to force a refresh
        (e.g. they fixed a typo in their DOI) or for
        tests that need a clean slate between cases.

        Note on multi-worker mode: when ``CACHE_BACKEND=redis``,
        this is a system-wide operation (DEL on every key in
        the Redis namespace). When ``CACHE_BACKEND=memory``,
        this only clears the cache of the worker that handles
        the request -- operators with multi-worker deployments
        should set ``CACHE_BACKEND=redis`` if they need
        system-wide clears.
        """
        self._cache.clear()

    def invalidate(self, doi: str) -> bool:
        """
        Remove a single entry from the LRU cache.

        Returns True if an entry was removed, False if no
        entry existed for that DOI. Identifiers are
        normalized the same way as the cache key so
        ``"10.1038/x"``, ``"https://doi.org/10.1038/x"``,
        and ``"DOI.ORG/10.1038/x"`` all map to the same
        cached entry.

        Useful when:
        - A researcher fixes a typo in their DOI; cached
          None entries prevent re-lookup.
        - The publisher's metadata has changed (e.g.
          abstract added) and the cached version is stale.
        - An operator wants to debug a specific cached
          value without nuking the whole cache.

        Does NOT touch hit/miss counters -- those are
        process-wide aggregate counts and should not be
        reset by single-entry invalidation.

        Note on multi-worker mode: when ``CACHE_BACKEND=redis``,
        this is a system-wide invalidation (DEL on the entry
        in Redis -- other workers see the miss on their next
        read). When ``CACHE_BACKEND=memory``, this only
        invalidates the cache of the worker that handles the
        request -- 3 other workers' caches stay intact.
        Set ``CACHE_BACKEND=redis`` to get system-wide
        invalidation.
        """
        cache_key = self._normalize_doi(doi)
        return self._cache.delete(cache_key)

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

    # Section-based full-abstract extraction. Many publishers
    # (Springer Nature, Nature, IEEEXplore, Oxford Academic)
    # put the *full* abstract in a section identified by one
    # of two HTML conventions:
    #
    #   1. ``<section id="Abs1">...<p>FULL ABSTRACT</p>...</section>``
    #      (Nature, Oxford Academic, IEEE -- the section
    #      itself carries the id)
    #
    #   2. ``<section aria-labelledby="Abs1" data-title="Abstract">``
    #      ...<p>FULL ABSTRACT</p>...</section>``
    #      (Springer Nature -- the id is on the inner ``<h2>``,
    #      and the section references it via ``aria-labelledby``).
    #      The ``data-title="Abstract"`` attribute is an
    #      additional Springer-specific signal we can use as
    #      a fallback if neither id-based pattern matches.
    #
    # Both forms wrap the abstract in a ``<p>`` block inside
    # the section. We prefer the section over the meta-tag
    # fallback because it's the canonical full text -- Springer's
    # ``<meta name="description">`` is a 267-char teaser ending
    # in literal ``"..."`` while the section body has the full
    # abstract.
    #
    # The regex captures everything between the section open
    # tag (matched by id or aria-labelledby or data-title) and
    # the section close ``</section>``. Inside, we capture the
    # *first* ``<p>...</p>`` block (subsequent ``<p>``s are
    # usually acknowledgements, funding statements, or
    # "(c) ..." paragraphs).
    _SECTION_ABS_PATTERN: re.Pattern[str] = re.compile(
        # Pattern 1: section carries id="Abs[0-9]+"
        r'<section\b[^>]*\bid=["\']Abs\d+["\'][^>]*>'
        # Match up to 4 KB of content inside the section.
        # This is enough for the longest abstracts (~3-4 KB
        # chars) without backtracking on huge pages.
        r'(.{1,4096}?)'
        r'</section>'
        # Pattern 2: section references id via aria-labelledby
        # (the inner heading has the id="Abs[0-9]+")
        r'|'
        r'<section\b[^>]*aria-labelledby=["\']Abs\d+["\'][^>]*>'
        r'(.{1,4096}?)'
        r'</section>'
        # Pattern 3: Springer-style ``data-title="Abstract"``
        # attribute on the section itself. This is the most
        # generic fallback -- if the publisher tagged the
        # section with its semantic name, we use it.
        r'|'
        r'<section\b[^>]*data-title=["\']Abstract["\'][^>]*>'
        r'(.{1,4096}?)'
        r'</section>',
        re.IGNORECASE | re.DOTALL,
    )
    # First <p>...</p> inside the captured section. We
    # accept nested tags (``<i>``, ``<b>``, ``<sup>`` etc.)
    # but stop at the matching </p>. The non-greedy ``+?``
    # prevents crossing into a second paragraph.
    _SECTION_ABS_P_PATTERN: re.Pattern[str] = re.compile(
        r'<p\b[^>]*>(.+?)</p>',
        re.IGNORECASE | re.DOTALL,
    )

    def _extract_abstract(self, html_text: str) -> str | None:
        """Pull the abstract from the page.

        Two strategies, tried in order:

        1. **Section-based**: look for
           ``<section id="Abs[0-9]+">...</section>`` and
           extract the first ``<p>`` inside it. This is the
           canonical full-text path used by Springer
           Nature, Nature, and most Oxford Academic
           journals. Springer book chapters are the
           canonical example: their ``<meta
           name="description">`` is a 267-char teaser
           ending in literal ``"..."``, but the section
           body has the full abstract.
        2. **Meta-tag based**: fall back to the existing
           patterns (``citation_abstract``, ``description``,
           ``og:description``). Used by PLOS, Frontiers,
           and most open-access journals.

        Returns the first non-empty match, or ``None`` if
        neither strategy finds anything.

        HTML entity decoding and whitespace cleanup is
        delegated to ``_clean_abstract`` so the two
        responsibilities live in one place.
        """
        # 1. Section-based extraction (preferred).
        # The pattern has three alternatives with body groups
        # at positions 1, 3, 5. ``lastindex`` tells us which
        # alternative matched. We pull the body from whichever
        # group actually has content.
        section_match = self._SECTION_ABS_PATTERN.search(html_text)
        if (
            section_match is not None
            and section_match.lastindex is not None
        ):
            # ``lastindex`` is the highest group that
            # matched. The body group for each alternative is
            # at the same offset within that alternative
            # (always the *last* group in its alternative),
            # so we can read it directly as ``lastindex``.
            # Alternative 1: groups 1+2; body is 1. lastidx=1
            # Alternative 2: groups 3+4; body is 3. lastidx=3
            # Alternative 3: groups 5+6; body is 5. lastidx=5
            section_body = section_match.group(section_match.lastindex)
            p_match = self._SECTION_ABS_P_PATTERN.search(section_body)
            if p_match is not None:
                # Strip the nested tags from the <p> block
                # (``<i>``, ``<b>``, etc.) so the abstract
                # reads as plain text. The regex captures the
                # raw HTML; we strip tags here so the
                # downstream ``_clean_abstract`` can treat
                # the text uniformly regardless of whether
                # the source was a section or a meta tag.
                raw_html = p_match.group(1)
                plain = re.sub(r"<[^>]+>", " ", raw_html)
                cleaned = _clean_abstract(plain)
                if cleaned:
                    return cleaned
        # 2. Meta-tag extraction (fallback).
        for pattern in self._META_PATTERNS:
            match = pattern.search(html_text)
            if match is None:
                continue
            content = match.group(1)
            cleaned = _clean_abstract(content)
            if cleaned:
                return cleaned
        return None


# HTML tags whose entire wrapped content is dropped. The
# publisher's structured-abstract convention wraps a single
# label word in a heading tag (``<h4>Introduction</h4>``,
# ``<h4>Methods</h4>``, etc.). The label is the publisher's
# navigation aid, not part of the abstract's content --
# dropping it leaves a clean prose abstract and matches the
# user's preferred rendering. ``<h1>``-``<h6>`` cover all
# levels. We deliberately don't include ``<section>``,
# ``<div>``, ``<p>``, etc. here: those tend to wrap real
# content rather than labels, and the rule "drop tag, keep
# text" handles them correctly.
_DROP_TAG_AND_CONTENT = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


class _HTMLTagStripper(html.parser.HTMLParser):
    """Walk the text as a stream of (raw text, open tag,
    close tag, drop flag) and emit a cleaned string.

    Rules
    -----
    - For tags in ``_DROP_TAG_AND_CONTENT`` (``<h1>``-``<h6>``):
      the entire wrapped content is dropped along with the
      tags. ``<h4>Introduction</h4>Tau species...`` becomes
      ``Tau species...``.
    - For every other tag (``<i>``, ``<b>``, ``<strong>``,
      ``<em>``, ``<u>``, ``<sup>``, ``<sub>``, ``<span>``,
      ``<a>``, etc.): the tags are dropped but the wrapped
      text is preserved. ``<i>tau</i> pathology`` becomes
      ``tau pathology``.
    - HTML entities are already unescaped upstream
      (``html.unescape`` in ``_clean_abstract``), so
      ``handle_data`` sees plain text. We use the stdlib
      default ``convert_charrefs=True`` so any surviving
      entity (mostly malformed ``&CG``-style fragments)
      passes through ``handle_data`` unchanged -- preserving
      the byte-for-byte contract for already-unscaped text.
    - Malformed input is tolerated: ``HTMLParser`` is lenient
      and won't raise on partial / unclosed tags. The output
      may include extra spaces where tags were dropped; the
      downstream whitespace collapse folds those into
      single spaces.
    """

    def __init__(self) -> None:
        # ``convert_charrefs=True`` (the stdlib default) means
        # ``HTMLParser`` decodes entity refs (``&amp;``, ``&micro;``)
        # and numeric char refs (``&#NNN;``) into plain text and
        # delivers them via ``handle_data``. That's exactly what
        # we want: entities that survived upstream ``html.unescape``
        # are rare (mostly malformed ``&CG``-style fragments from
        # publishers who forgot the ``;``); with auto-conversion
        # they pass through as literal ``&CG`` text in
        # ``handle_data``, which is the correct preservation
        # behaviour. With ``convert_charrefs=False`` we'd have to
        # handle ``handle_entityref`` / ``handle_charref``
        # ourselves and reconstruct the original ``&name;`` text,
        # which is exactly the failure mode the
        # ``test_strips_html_entities`` regression caught.
        super().__init__()
        self._pieces: list[str] = []
        # Stack of "are we currently inside a drop-tag
        # region?". ``True`` means drop everything (text +
        # nested tags) until the matching close. Nesting
        # matters because a ``<h4>`` could in theory wrap a
        # ``<b>`` -- both should be dropped.
        self._drop_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _DROP_TAG_AND_CONTENT:
            self._drop_depth += 1
        # Other open tags are simply consumed (no output).

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TAG_AND_CONTENT and self._drop_depth > 0:
            self._drop_depth -= 1
        # Other close tags are simply consumed (no output).

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # Self-closing tags like ``<br/>``, ``<img .../>``:
        # no content to preserve, no impact on drop state.
        return

    def handle_data(self, data: str) -> None:
        if self._drop_depth == 0:
            self._pieces.append(data)


def _strip_html_tags(text: str) -> str:
    """Strip HTML tags from a raw abstract string.

    See :class:`_HTMLTagStripper` for the rules. This is the
    public-facing entry point; the class is an implementation
    detail.

    No external deps: ``html.parser`` is in the Python
    standard library. We deliberately avoid
    ``BeautifulSoup`` / ``lxml`` because the abstract
    pipeline is a single chokepoint and a 30-line
    ``HTMLParser`` subclass is enough.

    Note: ``HTMLParser`` is intentionally lenient -- it does
    NOT raise on malformed / unclosed / unrecognised tags.
    Real-world abstracts sometimes contain stray fragments
    (broken nested tags, half-encoded entities) and the
    parser silently accepts them. The downstream whitespace
    collapse in ``_clean_abstract`` folds any leftover
    spacing.
    """
    stripper = _HTMLTagStripper()
    stripper.feed(text)
    stripper.close()
    return "".join(stripper._pieces)


def _clean_abstract(text: str) -> str:
    """Normalize an abstract extracted from HTML.

    - Decode HTML entities (``&micro;`` -> ``µ``).
    - Collapse whitespace runs to single spaces.
    - Strip trailing whitespace and publisher's literal
      ``"..."`` truncation marker.
    - Drop the abstract if it's too short to be useful
      (some sites return just the title or a short
      summary).

    The trailing-ellipsis strip
    ----------------------------
    Some publishers (notably Springer Nature book
    chapters) put a literal ``"..."`` at the end of their
    short meta descriptions -- it's their way of signalling
    "more on the actual page". When we fall back to the
    meta description (because the section extraction missed),
    we don't want the user to see ``"This..."`` and think
    the abstract is truncated when it's actually complete.
    Stripping the trailing ``"..."`` (only when followed by
    end-of-string) gives us ``"This."`` -- still slightly
    truncated-feeling but accurate.

    We DON'T strip ellipses in the middle of the text --
    ``"see Eq. (1) ... (2) ... (3) for details"`` should
    pass through unchanged. The regex anchors on a literal
    trailing ellipsis only.
    """
    # Decode entities first so that, e.g., ``&micro;`` is
    # counted as a single character when measuring length.
    # We must use ``html.unescape`` here, not in
    # ``_extract_abstract``, so that the pure-function
    # behavior of ``_clean_abstract`` is self-contained.
    decoded = html.unescape(text)
    # Strip HTML tags some publishers leave behind in the
    # raw abstract text. We do this BEFORE the whitespace
    # collapse so any space gaps left behind by the strip
    # are folded into the normal ``\s+`` -> ``" "`` pass.
    # See ``_strip_html_tags`` for the rules.
    decoded = _strip_html_tags(decoded)
    # Collapse all whitespace (including newlines and
    # non-breaking spaces) to single spaces.
    normalized = re.sub(r"\s+", " ", decoded).strip()
    # Strip a trailing literal "..." (with or without
    # surrounding spaces) so publisher-supplied teasers
    # don't show "This..." as if the abstract is truncated
    # mid-sentence. Anchor at end-of-string so we don't
    # touch mid-text ellipses.
    #
    # IMPORTANT: this strip happens BEFORE the length check
    # so an abstract like ``"This is the abstract. ..."``
    # (27 visible chars + 3 dots) doesn't fall below the
    # 40-char floor. The dots are publisher boilerplate, not
    # content -- we strip them so the 40-char measurement
    # reflects the abstract's true length.
    normalized = re.sub(r"\s*\.{3}\s*$", "", normalized)
    if len(normalized) < 40:
        # Too short to be an abstract -- probably a meta
        # description like "Read the paper" or just the
        # title repeated.
        return ""
    return normalized
