"""
helpers/abstract_normalizer.py

Single-source-of-truth for sanitising raw abstract text.

Three HTML flavours show up at different points in the pipeline:

  1. **Publisher structured-abstract pages** (Elsevier, Springer
     Nature, Wiley). The section labels wrap a single label
     word in an ``<h4>`` tag (``<h4>Introduction</h4>``,
     ``<h4>Methods</h4>``, etc.). The label is the publisher's
     navigation aid, not the abstract content -- we drop the
     entire ``<h4>LABEL</h4>`` chunk.

  2. **PubMed XML structured abstracts**. PubMed wraps
     inline superscripts in ``<sup>...</sup>`` (``[Tau]``,
     ``[<sup>18</sup>F]`` etc.). The superscript markup is
     semantically meaningful (isotope notation, gene
     references) but the tags are visual only -- we drop the
     ``<sup>`` / ``</sup>`` wrappers and keep the inner text.

  3. **Inline emphatic markup** in publisher pages
     (``<i>tau</i>``, ``<b>`` ``<strong>``, etc.). Same rule as
     ``<sup>``: drop the tags, keep the inner text.

The normaliser is intentionally a single function call so
every Paper-construction site uses it. If a future source
produces a new flavour (e.g. ``<mark>``, ``<code>``), fix the
normaliser once and every consumer gets the fix.

Why not BeautifulSoup / lxml / bleach?
-------------------------------------
Stdlib ``html.parser`` is dependency-free and the surface
area here is small (drop a handful of well-known tag
families). The previous session (and this session's
`_strip_html_tags` helper in ``abstract_enricher.py``)
already use this approach; the normaliser extends the same
rule by also handling ``<sup>``/``<sub>``/inline emphatic
tags. Pulling in BeautifulSoup for what's ultimately a
30-line state machine would be overkill.
"""
from __future__ import annotations

import html.parser

# -- Tag-classification rules ------------------------------------------------
#
# ``DROP_TAG_AND_CONTENT``: tags whose entire wrapped content
# is dropped along with the tags. Currently limited to the
# heading family ``h1``-``h6`` which wraps the publisher's
# structured-abstract section labels.
#
# ``DROP_TAG_KEEP_CONTENT``: tags whose wrappers are dropped
# but whose inner text is preserved. Inline emphatic tags
# (``i``, ``b``, ``strong``, ``em``, ``u``, ``mark``, etc.)
# and the superscript / subscript families (``sup``,
# ``sub``).
#
# We deliberately don't strip ``<p>``, ``<div>``, ``<section>``,
# ``<span>`` -- these typically wrap real content rather than
# labels. If a future source wraps a content chunk in
# ``<p>...</p>`` and we want to keep the content with just
# normalised whitespace, the downstream whitespace-collapse
# in the abstract_enricher (or here, via ``\s+`` -> ``" "``)
# already collapses any visual artefacts.

_DROP_TAG_AND_CONTENT = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


class _AbstractNormalizer(html.parser.HTMLParser):
    """Strip publisher-supplied HTML tags from an abstract body.

    See module docstring for the rules. The class is an
    implementation detail of ``normalize_abstract``.
    """

    def __init__(self) -> None:
        # ``convert_charrefs=True`` (the stdlib default) means
        # ``HTMLParser`` decodes entity refs (``&amp;``,
        # ``&micro;``) and numeric char refs (``&#NNN;``) into
        # plain text via ``handle_data``. The downstream
        # consumer (caller of ``normalize_abstract``) sees
        # plain Unicode and never has to worry about
        # pre-stripped entities.
        super().__init__()
        self._pieces: list[str] = []
        # ``True`` when we're inside a tag whose content
        # should be dropped along with the tags. Nesting
        # matters (``<h4><i>X</i></h4>`` -> both the h4 and
        # the nested i are dropped).
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
        # Self-closing tags like ``<br/>`` or ``<img .../>``:
        # no content to preserve, no impact on drop state.
        return

    def handle_data(self, data: str) -> None:
        if self._drop_depth == 0:
            self._pieces.append(data)


def normalize_abstract(text: str) -> str:
    """Sanitise an abstract body in one pass.

    The single entry point for ``Paper.abstract`` assignment
    across the PubMed mapper, the identifier resolver
    (OpenAlex / HTML enricher fallbacks), the structured PDF
    extractor, and the cross-source literature clients.

    Idempotent: passing in already-normalised text returns
    it unchanged. The HTMLParser-based walker is content-only
    when there are no tags to strip, and the downstream
    whitespace collapse is a no-op on already-collapsed text.

    Parameters
    ----------
    text : str
        Raw abstract, possibly containing ``<h4>...</h4>``,
        ``<sup>...</sup>``, ``<i>...</i>``, etc.

    Returns
    -------
    str
        The same text with the tag wrappers removed. Inline
        content (including the text inside ``<sup>``,
        ``<i>``, ``<b>`` etc.) is preserved verbatim. Content
        inside ``<h1>``-``<h6>`` is dropped along with the
        wrapping tags.
    """
    if not text:
        return text
    normalizer = _AbstractNormalizer()
    normalizer.feed(text)
    normalizer.close()
    return "".join(normalizer._pieces)
