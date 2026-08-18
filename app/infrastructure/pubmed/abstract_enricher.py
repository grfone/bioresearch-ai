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
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        user_agent: str | None = None,
        timeout: float | None = None,
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

        Parameters
        ----------
        doi : str
            The DOI to resolve. Leading ``https://doi.org/``
            and ``doi.org/`` prefixes are stripped.
        """
        url = self._build_url(doi)
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            logger.info(
                "AbstractEnricher: HTTP error for %s: %s",
                doi, exc,
            )
            return None
        if response.status_code != 200:
            logger.info(
                "AbstractEnricher: HTTP %d for %s",
                response.status_code, doi,
            )
            return None
        return self._extract_abstract(response.text)

    @staticmethod
    def _build_url(doi: str) -> str:
        """Normalize the DOI to the canonical URL form.

        ``doi.org/<doi>`` (with ``https://``) is the official
        DOI resolver URL. The publisher's landing page is
        the redirect target.
        """
        cleaned = doi.strip()
        lowered = cleaned.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break
        return f"https://doi.org/{cleaned}"

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
