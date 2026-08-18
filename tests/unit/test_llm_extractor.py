"""
test_llm_extractor.py

Unit tests for ``LLMExtractor`` -- the LLM-based fallback
for the AbstractEnricher. The LLM contract is verbatim
extraction: it pulls the abstract from the page text or
returns ``None``. It must never invent content.

These tests use a fake ``LLMProvider`` so we can simulate
exactly what the LLM would return. The fake captures the
prompt so we can assert on what we sent (system prompt,
temperature, max_tokens, user message) -- this is the
contract the production code signs with the LLM.

What we cover:
- The LLM returns a real abstract -> extractor returns it
- The LLM returns "NONE" -> extractor returns None
- The LLM returns "There is no abstract on this page." ->
  extractor returns None (rejection pattern)
- The LLM returns a short sentence (e.g. "Not available")
  -> extractor returns None (below MIN_ABSTRACT_CHARS)
- The LLM returns something way too long (concatenated
  sections) -> extractor returns None (above
  MAX_ABSTRACT_CHARS)
- The LLM call raises LLMProviderError -> extractor
  returns None (network/rate-limit errors)
- The HTML is empty / script-only -> extractor skips
  the call entirely (returns None, no LLM call)
- The HTML is huge -> extractor truncates to
  max_input_chars before calling the LLM
- The system prompt contains the verbatim-extraction
  contract ("verbatim", "NONE", etc.) so a refactor
  can't accidentally drop it
- The temperature is 0 (deterministic extraction)
- max_tokens is bounded (don't blow the budget on a
  single DOI)
- Whitespace inside the LLM response is normalized
  (so a chatty "NONE  " is treated as NONE)
- The user message includes the page text wrapped in
  ```html fences so the LLM knows what's page vs
  what's prompt
"""

from __future__ import annotations

import re
from typing import List, Tuple

import pytest

from app.core.exceptions import LLMProviderError
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeLLMProvider(LLMProvider):
    """Fake LLM that records every call and returns a
    pre-configured sequence of responses."""

    def __init__(self, responses: List[str]) -> None:
        self.responses = list(responses)
        self.calls: List[Prompt] = []

    def generate(self, prompt: Prompt) -> LLMResponse:
        self.calls.append(prompt)
        if not self.responses:
            raise AssertionError(
                "FakeLLMProvider ran out of canned responses; "
                "configure more responses in the test fixture."
            )
        content = self.responses.pop(0)
        return LLMResponse(
            content=content,
            model="fake-llm",
            prompt_tokens=len(prompt.user) // 4,
            completion_tokens=len(content) // 4,
            total_tokens=(len(prompt.user) + len(content)) // 4,
            finish_reason="stop",
        )


class RaisingLLMProvider(LLMProvider):
    """Fake LLM that always raises (simulates network error,
    rate limit, server outage)."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or LLMProviderError("rate limited")
        self.calls = 0

    def generate(self, prompt: Prompt) -> LLMResponse:
        self.calls += 1
        raise self.error


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


REAL_ABSTRACT = (
    "Deep learning allows computational models that are "
    "composed of multiple processing layers to learn "
    "representations of data with multiple levels of "
    "abstraction. These methods have dramatically improved "
    "the state-of-the-art in speech recognition, visual "
    "object recognition, object detection and many other "
    "domains such as drug discovery and genomics."
)

NATURE_HTML = f"""<!DOCTYPE html>
<html>
<head>
    <title>Deep learning - Nature</title>
    <meta name="description" content="Other metadata here, not the abstract">
</head>
<body>
    <h1>Deep learning</h1>
    <p>{REAL_ABSTRACT}</p>
</body>
</html>"""

# Page where the abstract IS on the page but NOT in a
# <meta> tag -- a book-chapter landing page with the
# abstract rendered inside a CMS widget. The deterministic
# regex in AbstractEnricher would miss this; the LLM is the
# fallback that catches it.
BOOK_CHAPTER_HTML = f"""<!DOCTYPE html>
<html>
<head>
    <title>Chapter 17 - Training Deep Neural Networks</title>
</head>
<body>
    <div class="book-meta">
        <h1>Training Deep Neural Networks</h1>
        <p>Authors: A. Smith, B. Jones</p>
    </div>
    <section class="chapter-abstract">
        <h2>Abstract</h2>
        <p>{REAL_ABSTRACT}</p>
    </section>
    <div class="chapter-body">
        <p>The rest of the chapter...</p>
    </div>
</body>
</html>"""

# Page with NO abstract on it (a homepage, a table of
# contents, a paywall page).
NO_ABSTRACT_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Chapter Listing - Publisher</title>
</head>
<body>
    <h1>Table of Contents</h1>
    <ul>
        <li>Chapter 1: Introduction</li>
        <li>Chapter 2: Background</li>
        <li>Chapter 3: Methods</li>
    </ul>
    <p>To read the full chapter, please log in or purchase access.</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestExtractionSuccess:
    """The LLM correctly identifies and returns the abstract."""

    def test_returns_real_abstract_verbatim(self):
        """When the LLM returns a real abstract, the extractor
        returns it unchanged (whitespace-normalized only)."""
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract(BOOK_CHAPTER_HTML)

        assert result is not None
        assert result.abstract == REAL_ABSTRACT
        # The provenance flag must always be True -- that's
        # the whole point of the ExtractionResult wrapper.
        assert result.inferred is True

    def test_strips_script_content_before_sending(self):
        """The page text we send to the LLM should not include
        JavaScript -- the LLM has no use for client-side
        code and it would waste tokens.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        extractor.extract(BOOK_CHAPTER_HTML)

        assert len(fake.calls) == 1
        sent_text = fake.calls[0].user
        # The user prompt contains the page text wrapped in
        # fences. It should NOT contain any JS source.
        assert "var x = 1" not in sent_text
        assert "function () {" not in sent_text
        assert "alert(" not in sent_text

    def test_includes_page_text_in_user_prompt(self):
        """The user prompt is the page text wrapped in
        ```html fences -- this is the contract the LLM
        sees.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        extractor.extract(BOOK_CHAPTER_HTML)

        sent = fake.calls[0].user
        assert "```html" in sent
        assert "```" in sent
        # The page text should contain the abstract.
        assert REAL_ABSTRACT[:80] in sent


class TestRejectionPatterns:
    """The LLM correctly says 'no abstract' -- the extractor
    must treat these as None, not invent content."""

    def test_literal_NONE_returns_none(self):
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider(["NONE"])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract(NO_ABSTRACT_HTML)

        assert result is None

    def test_NONE_with_whitespace_returns_none(self):
        """The LLM is chatty -- it might return 'NONE ' or
        '\\nNONE\\n'. We treat all of these as None.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        for variant in ["NONE", " NONE", "NONE ", "\nNONE\n", "none"]:
            fake = FakeLLMProvider([variant])
            extractor = LLMExtractor(llm_provider=fake)
            assert extractor.extract(NO_ABSTRACT_HTML) is None, (
                f"variant {variant!r} should be rejected"
            )

    def test_preamble_about_no_abstract_returns_none(self):
        """When the LLM drifts and explains why there's no
        abstract (e.g. 'There is no abstract on this page.')
        instead of returning the literal NONE, we still
        treat it as None.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        for variant in [
            "There is no abstract on this page.",
            "No abstract available.",
            "Abstract not found.",
            "Abstract not provided.",
            "Not available.",
            "N/A",
        ]:
            fake = FakeLLMProvider([variant])
            extractor = LLMExtractor(llm_provider=fake)
            assert extractor.extract(NO_ABSTRACT_HTML) is None, (
                f"variant {variant!r} should be rejected"
            )


class TestLengthValidation:
    """Length-based rejections -- the LLM is chatty and
    sometimes returns text that's too short or too long."""

    def test_short_response_returns_none(self):
        """Anything shorter than MIN_ABSTRACT_CHARS (40) is
        rejected. Even if it doesn't match a rejection
        pattern, we don't trust it.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        # 35 chars -- below the 40-char floor.
        fake = FakeLLMProvider(["Just a short blurb, not abstract."])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract(NO_ABSTRACT_HTML)
        assert result is None

    def test_long_response_returns_none(self):
        """Anything longer than MAX_ABSTRACT_CHARS (8000) is
        rejected -- the LLM probably concatenated sections.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        too_long = "x" * 8001
        fake = FakeLLMProvider([too_long])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract(BOOK_CHAPTER_HTML)
        assert result is None


class TestEmptyHTML:
    """Edge cases where the HTML is empty / script-only."""

    def test_empty_html_returns_none_without_calling_llm(self):
        """Don't waste an LLM call on empty HTML -- we know
        there's no abstract to extract.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract("")

        assert result is None
        assert fake.calls == [], (
            "Extractor called the LLM for empty HTML"
        )

    def test_script_only_html_returns_none_without_calling_llm(self):
        """A page that's just JavaScript has no abstract.
        Strip the script first, then check if the
        remainder is empty.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract(
            "<html><head><script>var x = 1;</script></head></html>"
        )

        assert result is None
        assert fake.calls == [], (
            "Extractor called the LLM for script-only HTML"
        )


class TestErrorHandling:
    """Network/rate-limit errors don't crash the extractor."""

    def test_llm_provider_error_returns_none(self):
        """If the LLM call raises LLMProviderError, the
        extractor returns None silently. The caller (the
        AbstractEnricher) will record 'no abstract found'.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = RaisingLLMProvider(
            LLMProviderError("rate limit exceeded")
        )
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract(BOOK_CHAPTER_HTML)

        assert result is None
        assert fake.calls == 1, (
            "Extractor should have called the LLM once before "
            "falling back to None on error"
        )


class TestPromptContract:
    """Pin the prompt structure so refactors don't drop the
    verbatim-extraction contract."""

    def test_system_prompt_contains_verbatim_contract(self):
        """The system prompt must tell the LLM to extract
        verbatim and return NONE if there's no abstract.
        If a future refactor drops these phrases, the LLM
        would silently start inventing content.
        """
        from app.infrastructure.pubmed.llm_extractor import (
            SYSTEM_PROMPT,
        )

        assert "verbatim" in SYSTEM_PROMPT.lower(), (
            "System prompt must say 'verbatim' -- without it "
            "the LLM might summarize instead of extract"
        )
        assert "NONE" in SYSTEM_PROMPT, (
            "System prompt must mention NONE as the "
            "no-abstract signal"
        )
        # Anti-hallucination defenses:
        assert "invent" in SYSTEM_PROMPT.lower(), (
            "System prompt must say 'do not invent'"
        )
        assert "paraphrase" in SYSTEM_PROMPT.lower(), (
            "System prompt must say 'do not paraphrase'"
        )
        assert "summarize" in SYSTEM_PROMPT.lower(), (
            "System prompt must say 'do not summarize'"
        )

    def test_temperature_is_zero(self):
        """Extraction is deterministic -- we don't want the
        LLM picking a different verb on each call.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        extractor.extract(BOOK_CHAPTER_HTML)

        assert fake.calls[0].temperature == 0.0

    def test_max_tokens_is_bounded(self):
        """The max_tokens limit must be set so a runaway
        generation can't blow the budget on one DOI.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        extractor.extract(BOOK_CHAPTER_HTML)

        max_tokens = fake.calls[0].max_tokens
        # Must be a positive integer and reasonable.
        assert isinstance(max_tokens, int)
        assert max_tokens > 0
        # Generous enough for a 3KB abstract with overhead,
        # but bounded so the LLM can't go crazy.
        assert max_tokens <= 5000


class TestInputTruncation:
    """Large pages get truncated to the budget."""

    def test_huge_html_is_truncated_before_sending(self):
        """A page with 100KB of HTML should be truncated to
        max_input_chars before being sent to the LLM --
        we don't want to send entire landing pages when
        the abstract is in the first 30KB.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        # Build a page with lots of padding text.
        padding = "<p>Lorem ipsum dolor sit amet. </p>" * 5000
        huge_html = (
            "<html><body>"
            + padding
            + f"<p>{REAL_ABSTRACT}</p>"
            + padding
            + "</body></html>"
        )

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(
            llm_provider=fake, max_input_chars=5000,
        )
        extractor.extract(huge_html)

        # The text we sent to the LLM should be at most
        # ~5000 chars + fences/prompt overhead.
        sent = fake.calls[0].user
        # The stripped page text is shorter than the raw HTML
        # because <p> tags collapse to whitespace.
        # Allow some slack for fences and prompt scaffolding.
        assert len(sent) < 8000, (
            f"Expected truncated prompt, but sent {len(sent)} chars"
        )


class TestHTMLStripping:
    """The HTML preprocessor turns messy page markup into
    clean text the LLM can actually read."""

    def test_strips_script_blocks(self):
        from app.infrastructure.pubmed.llm_extractor import (
            _strip_html,
        )

        html = (
            "<html><body>"
            "<script>alert('xss');</script>"
            "<p>Real content here.</p>"
            "</body></html>"
        )
        cleaned = _strip_html(html)
        assert "alert" not in cleaned
        assert "Real content here." in cleaned

    def test_strips_style_blocks(self):
        from app.infrastructure.pubmed.llm_extractor import (
            _strip_html,
        )

        html = (
            "<html><body>"
            "<style>.foo { color: red; }</style>"
            "<p>Visible content.</p>"
            "</body></html>"
        )
        cleaned = _strip_html(html)
        assert "color: red" not in cleaned
        assert "Visible content." in cleaned

    def test_strips_html_comments(self):
        from app.infrastructure.pubmed.llm_extractor import (
            _strip_html,
        )

        html = (
            "<html><body>"
            "<!-- This is a comment -->"
            "<p>Visible content.</p>"
            "</body></html>"
        )
        cleaned = _strip_html(html)
        assert "comment" not in cleaned
        assert "Visible content." in cleaned

    def test_decodes_common_entities(self):
        from app.infrastructure.pubmed.llm_extractor import (
            _strip_html,
        )

        html = (
            "<html><body>"
            "<p>AT&amp;CG &micro;RNA &gt; 2-fold in "
            "hepatocytes.</p>"
            "</body></html>"
        )
        cleaned = _strip_html(html)
        assert "&amp;" not in cleaned
        assert "AT&CG" in cleaned
        assert "µRNA" in cleaned
        assert "> 2" in cleaned

    def test_collapses_whitespace_runs(self):
        from app.infrastructure.pubmed.llm_extractor import (
            _strip_html,
        )

        html = (
            "<html><body>"
            "<p>Line 1\n\nLine 2\t\tLine 3</p>"
            "</body></html>"
        )
        cleaned = _strip_html(html)
        # All whitespace runs become single spaces.
        assert "\n" not in cleaned
        assert "\t" not in cleaned
        assert "  " not in cleaned


class TestExtractFromDOI:
    """The convenience wrapper passes through to extract()."""

    def test_extract_from_doi_delegates_to_extract(self):
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        fake = FakeLLMProvider([REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract_from_doi(
            "10.1234/test", BOOK_CHAPTER_HTML,
        )
        assert result is not None
        assert result.abstract == REAL_ABSTRACT
        assert result.inferred is True
        assert len(fake.calls) == 1


class TestWhitespaceNormalization:
    """The LLM is chatty with whitespace -- normalize it."""

    def test_internal_whitespace_collapsed(self):
        """If the LLM returns 'Abstract.    More text.', we
        normalize to 'Abstract. More text.' -- but we
        don't change the wording.
        """
        from app.infrastructure.pubmed.llm_extractor import LLMExtractor

        chatty = REAL_ABSTRACT.replace(" ", "   ")
        fake = FakeLLMProvider([chatty])
        extractor = LLMExtractor(llm_provider=fake)
        result = extractor.extract(BOOK_CHAPTER_HTML)

        assert result is not None
        # All internal whitespace should be single spaces.
        assert "  " not in result.abstract
        assert result.abstract == REAL_ABSTRACT


class TestExtractionResultContract:
    """Pin the ExtractionResult wrapper contract.

    These tests exist so a future refactor can't
    accidentally:
    - Drop the wrapper and return a bare string
    - Set inferred=False on LLM-extracted results
    - Return an ExtractionResult with an empty abstract
      when the LLM said NONE
    """

    def test_extraction_result_is_always_marked_inferred(self):
        """Every successful LLMExtractor result has
        inferred=True. This is the contract -- the
        whole point of the wrapper is to carry the
        provenance flag.
        """
        from app.infrastructure.pubmed.llm_extractor import (
            LLMExtractor,
        )
        from app.infrastructure.pubmed.llm_extractor import (
            ExtractionResult,
        )

        fake = FakeLLMProvider([REAL_ABSTRACT, REAL_ABSTRACT])
        extractor = LLMExtractor(llm_provider=fake)
        r1 = extractor.extract(BOOK_CHAPTER_HTML)
        r2 = extractor.extract(BOOK_CHAPTER_HTML)
        assert isinstance(r1, ExtractionResult)
        assert isinstance(r2, ExtractionResult)
        assert r1.inferred is True
        assert r2.inferred is True

    def test_extraction_failure_returns_none_not_empty_result(self):
        """When the LLM says NONE or the response is too
        short or too long, the extractor returns None,
        NOT an ExtractionResult with an empty abstract.
        The ``None`` sentinel is the contract for "no
        abstract available".
        """
        from app.infrastructure.pubmed.llm_extractor import (
            LLMExtractor,
        )

        for variant in [
            "NONE",
            "No abstract.",
            "",  # empty
        ]:
            fake = FakeLLMProvider([variant])
            extractor = LLMExtractor(llm_provider=fake)
            assert extractor.extract(NO_ABSTRACT_HTML) is None

        # Too long -- still None, not an empty result.
        fake = FakeLLMProvider(["x" * 8001])
        extractor = LLMExtractor(llm_provider=fake)
        assert extractor.extract(BOOK_CHAPTER_HTML) is None

