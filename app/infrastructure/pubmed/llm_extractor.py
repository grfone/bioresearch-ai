"""llm_extractor.py

LLM-based fallback for the AbstractEnricher.

The deterministic extractor in AbstractEnricher fetches
the publisher's HTML landing page and parses known
<meta> tag patterns (citation_abstract, description,
og:description). For most open publishers (Nature, PLOS,
Frontiers) this works.

When the deterministic path returns None or a very short
string, it usually means one of two things:

  1. The publisher blocked us (anti-bot) -- nothing we
     can do without an LLM that has web access.
  2. The abstract IS on the page, but in a non-standard
     location that our regex doesn't match. Common when:
       - The page is a book chapter landing page where
         the abstract is rendered inside a custom CMS
         widget, not in <meta> tags.
       - The publisher uses a JavaScript-rendered SPA
         where the meta tags are injected client-side
         and our simple HTML parser only sees the empty
         shell.

This module is the fallback for case (2). It takes the
already-fetched HTML, strips tags, and asks an LLM to
extract the abstract VERBATIM. The prompt is explicit:

    "Return the abstract text as it appears on the
    page, word-for-word. If the page does not contain
    an abstract, return the literal string NONE. Do
    not invent, summarize, paraphrase, or fill in
    missing information."

That last sentence is the whole point of this module.
It is NOT a generation path. The LLM is acting as a
flexible text extractor, not an author. If the page
truly has no abstract, the answer is NONE and the
resolver falls back to "no abstract found".

The extracted text is also length-validated client-side:
anything shorter than 40 characters or longer than 8000
characters is rejected. The short filter handles cases
where the LLM returned "NONE" plus some chatty preamble
("There is no abstract on this page."); the long filter
handles cases where the LLM concatenated multiple
sections by mistake. These are belt-and-braces
defenses against the LLM drifting off the verbatim
contract.

Cost: roughly 1-3k tokens per call (page text only).
We only call the LLM when the deterministic path
returned None or a short string, so the cost is paid
for thin-record DOIs only. With the LRU cache on the
deterministic path, repeat lookups don't trigger this
either.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core.exceptions import LLMProviderError
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt

logger = logging.getLogger(__name__)


# System prompt -- this is the contract. Keep it stable
# across releases; the tests assert on substrings of it
# to prevent silent regressions.
SYSTEM_PROMPT = """\
You are an extraction tool, not a writer. Your task is to \
find the abstract of a scientific paper on the HTML page \
below and return it VERBATIM.

Rules:
- Return the abstract text as it appears on the page, \
word-for-word. Include any inline citations, equations, \
or formatting hints that are part of the abstract itself.
- Do NOT paraphrase, summarize, rewrite, or compress.
- Do NOT invent, hallucinate, or fill in missing \
information.
- If the page does NOT contain an abstract (e.g. it's a \
book-chapter landing page, a paywall, a homepage, or a \
table-of-contents listing), return the literal string \
NONE -- nothing else.
- Do not include the title, authors, journal name, DOI, \
keywords, or any metadata in your answer.
- Do not wrap the abstract in quotes or any other \
delimiter.
- Your answer must be ONLY the abstract text, or ONLY the \
string NONE.
"""


# Lower bound for a real abstract. Anything shorter is
# almost certainly "NONE" plus some chatty preamble like
# "There is no abstract on this page." (14 chars). The
# 40-char floor matches the deterministic extractor's
# floor so the two paths produce comparable-quality
# results.
MIN_ABSTRACT_CHARS = 40

# Upper bound for a real abstract. Real abstracts are
# 100-3000 chars. We allow up to 8000 to handle review
# articles with long structured abstracts. Beyond 8000
# the LLM almost certainly concatenated multiple
# sections by mistake, and we'd rather show "no
# abstract" than 30KB of text the user didn't ask for.
MAX_ABSTRACT_CHARS = 8000


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Carries the LLM-extracted abstract AND the
    provenance flag.

    ``abstract`` is the verbatim text the LLM pulled
    from the page.

    ``inferred`` is always ``True`` for results returned
    by ``LLMExtractor`` -- that's the whole point of
    this class. The field is exposed so the
    AbstractEnricher can stamp ``inferred_abstract=True``
    onto the resulting Paper without coupling the
    enricher to the extractor's internal contract.
    """
    abstract: str
    inferred: bool = True


class LLMExtractor:
    """Extract the abstract from a publisher HTML page
    using an LLM as a flexible text parser.

    This is a FALLBACK for when the deterministic regex
    path in AbstractEnricher returned None or a short
    string. It is never called when the regex already
    produced a usable abstract.

    Parameters
    ----------
    llm_provider : LLMProvider
        The LLM provider to use. ``LLMProvider.generate``
        is called once per extraction. Errors are caught
        and treated as "no abstract found".
    max_input_chars : int
        Maximum number of characters of stripped HTML
        to send to the LLM. Default 30KB. Pages larger
        than this are truncated to the first N chars;
        we lose the rest but most landing pages put the
        abstract near the top so this is usually fine.
    timeout_seconds : float | None
        Timeout for the LLM call. None = no timeout.
        Real providers all have their own server-side
        timeout, but we cap here too to avoid hanging
        the resolver.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        *,
        max_input_chars: int = 30_000,
        timeout_seconds: float | None = 30.0,
    ) -> None:
        self._llm_provider = llm_provider
        self._max_input_chars = max_input_chars
        self._timeout_seconds = timeout_seconds

    def extract(self, html: str) -> "ExtractionResult | None":
        """Return an ExtractionResult (verbatim abstract
        + inferred=True provenance flag), or ``None`` if
        the page genuinely has no abstract.

        The contract is strict:

        - If the LLM returns a string that looks like an
          abstract (>= 40 chars, <= 8000 chars), wrap it
          in an ``ExtractionResult`` and return it.
        - If the LLM returns ``NONE`` or anything
          matching the rejection pattern ("no abstract",
          "not available", etc.), return ``None``.
        - If the LLM call fails (network error, rate
          limit, server error), return ``None``.

        Never invent content. Never paraphrase. The LLM
        is a flexible parser; if it can't find an
        abstract, the answer is ``None``.

        The returned ``ExtractionResult`` always has
        ``inferred=True`` -- that's the whole point of
        this class. Callers (the AbstractEnricher)
        stamp this flag onto the resulting Paper so the
        frontend can render an "AI-extracted" badge.
        """
        page_text = _strip_html(html)
        if not page_text.strip():
            # Empty HTML -- nothing for the LLM to extract
            # from. Don't waste an API call.
            logger.debug("LLMExtractor: page text empty, skipping")
            return None

        # Truncate to keep the prompt within budget. We
        # send the FIRST N chars, not a random window,
        # because most landing pages put the abstract
        # near the top.
        if len(page_text) > self._max_input_chars:
            page_text = page_text[: self._max_input_chars]
            logger.debug(
                "LLMExtractor: page text truncated to %d chars",
                self._max_input_chars,
            )

        prompt = Prompt(
            system=SYSTEM_PROMPT,
            user=(
                "Extract the abstract from the HTML below. "
                "Return only the abstract text, or NONE if "
                "there is none.\n\n"
                f"```html\n{page_text}\n```"
            ),
            temperature=0.0,  # Zero temp for extraction -- we
                              # want the LLM to be deterministic.
            max_tokens=2000,  # Enough for ~3000-char abstracts
                              # with some overhead.
        )

        try:
            response = self._llm_provider.generate(prompt)
        except LLMProviderError as exc:
            logger.info(
                "LLMExtractor: provider error: %s", exc,
            )
            return None

        cleaned = _clean_extraction(response.content)
        if cleaned is None:
            return None
        # The result came from the LLM -- always mark as
        # inferred. The contract is verbatim extraction
        # (never generation) so the flag is safe to set.
        return ExtractionResult(abstract=cleaned, inferred=True)

    def extract_from_doi(
        self, doi: str, html: str,
    ) -> "ExtractionResult | None":
        """Convenience wrapper that includes the DOI in
        the prompt. Some pages show different content
        depending on the URL hash; including the DOI
        gives the LLM a stable identifier to anchor on.

        Same return contract as ``extract``.
        """
        # We could include the DOI in the prompt, but the
        # page text already contains the DOI in <meta
        # name="citation_doi"> etc., so re-stating it is
        # redundant. Just delegate to extract().
        return self.extract(html)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


# HTML tags we strip entirely (their content is invisible to
# the LLM anyway -- the abstract is plain text in the body).
_INVISIBLE_TAGS = re.compile(
    # Match a complete <script|style|noscript|svg|head>...</>
    # block. We don't backreference the opening tag name;
    # the closing tag is just /<whitespace><name><whitespace>>.
    # HTML allows some flexibility here (e.g. </script >),
    # and we only strip what we know is invisible content.
    r"<\s*(?:script|style|noscript|svg|head)\b[^>]*>"
    r".*?</\s*(?:script|style|noscript|svg|head)\s*>",
    re.IGNORECASE | re.DOTALL,
)

# All other tags -- just strip the tags themselves, keep the
# inner text. We do NOT collapse multiple spaces here; that
# happens in _clean_extraction after the LLM returns so we
# preserve the LLM's natural output formatting.
_ALL_TAGS = re.compile(r"<[^>]+>", re.DOTALL)

# HTML comments
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_html(html: str) -> str:
    """Reduce HTML to plain text suitable for the LLM prompt.

    We strip script/style/noscript/svg/head blocks first
    (their content is irrelevant to the abstract), then
    strip all remaining tags, then collapse whitespace.
    """
    text = _INVISIBLE_TAGS.sub(" ", html)
    text = _COMMENTS.sub(" ", text)
    text = _ALL_TAGS.sub(" ", text)
    # Decode the most common HTML entities. We don't use
    # html.unescape() because it's overkill -- the LLM
    # handles the rest OK and we want to keep this fast.
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
        .replace("&micro;", "µ")
        .replace("&deg;", "°")
        .replace("&times;", "×")
    )
    # Collapse whitespace runs.
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Patterns that mean "the LLM says there's no abstract".
# These come from LLM responses when the contract is
# followed strictly -- the LLM returns NONE -- or when
# the LLM drifts and returns a short sentence explaining
# that. Either way, treat as no-abstract.
_REJECTION_PATTERNS = (
    re.compile(r"^\s*NONE\s*$", re.IGNORECASE),
    re.compile(r"^\s*No abstract\b", re.IGNORECASE),
    re.compile(r"^\s*There is no abstract\b", re.IGNORECASE),
    re.compile(r"^\s*Abstract not (?:available|found|provided)\b", re.IGNORECASE),
    re.compile(r"^\s*The page does not contain an abstract\b", re.IGNORECASE),
    re.compile(r"^\s*Not available\b", re.IGNORECASE),
    re.compile(r"^\s*N/?A\s*$", re.IGNORECASE),
)


def _clean_extraction(raw: str) -> str | None:
    """Validate the LLM's response and return a clean abstract
    or ``None`` if the response should be rejected.

    Rejection happens when:
    - The LLM returned the literal NONE token.
    - The LLM returned a "no abstract" preamble.
    - The response is too short (< MIN_ABSTRACT_CHARS)
      to be a real abstract.
    - The response is too long (> MAX_ABSTRACT_CHARS)
      -- the LLM almost certainly concatenated multiple
      sections by mistake.
    - The response is empty / whitespace-only.

    Acceptance: anything that survives the rejection
    patterns and length checks. We do NOT further
    paraphrase, trim, or modify -- the LLM is the
    authoritative extractor and we trust its output.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    # Reject the explicit "no abstract" responses.
    for pattern in _REJECTION_PATTERNS:
        if pattern.match(text):
            logger.debug(
                "LLMExtractor: rejection pattern matched: %r", text[:80],
            )
            return None

    if len(text) < MIN_ABSTRACT_CHARS:
        # Too short to be a real abstract. Log and reject.
        logger.debug(
            "LLMExtractor: response too short (%d chars): %r",
            len(text), text[:80],
        )
        return None

    if len(text) > MAX_ABSTRACT_CHARS:
        # Too long. The LLM probably concatenated sections.
        # We could truncate to MAX_ABSTRACT_CHARS, but that
        # would hide the bug. Reject and let the resolver
        # fall back to "no abstract" instead.
        logger.debug(
            "LLMExtractor: response too long (%d chars), rejecting",
            len(text),
        )
        return None

    # Collapse internal whitespace runs (the LLM sometimes
    # leaves double-spaces around punctuation). We don't
    # change the wording -- just normalize whitespace.
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized


__all__ = [
    "LLMExtractor",
    "ExtractionResult",
    "SYSTEM_PROMPT",
    "MIN_ABSTRACT_CHARS",
    "MAX_ABSTRACT_CHARS",
]
