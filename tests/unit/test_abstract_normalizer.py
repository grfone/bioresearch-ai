"""
tests/unit/test_abstract_normalizer.py

Pure-function tests for ``normalize_abstract`` -- the
single-source-of-truth HTML stripper that runs on every
``Paper.abstract`` assignment across the codebase.

The user's bug
--------------
Paper abstracts from publisher structured-abstract pages
(Elsevier, Springer Nature) contain raw HTML tags like
``<h4>Introduction</h4>``. Some downstream consumers
(React paper cards, PDF generation, SQLite persistence)
rendered those tags literally. The fix is a single
``normalize_abstract`` call at every Paper-construction site.

Background
----------
The user's preference (recorded in this session's memory):

  - ``<h4>Introduction</h4>`` and other ``<h1>``-``<h6>``
    tags: drop the wrapping tags AND the inner text. The
    label is the publisher's navigation aid, not part of
    the abstract content.
  - ``<i>``, ``<b>``, ``<strong>``, ``<em>``, ``<sup>``,
    ``<sub>``, ``<u>``: drop the wrapping tags but preserve
    the inner text (``<sup>18</sup>F`` stays as ``18F``).
  - All other tags (``<span>``, ``<a>``, ``<p>`` etc.):
    default to "drop tag, keep text" -- the asymmetric
    rule for headings is the only exception.

These tests pin all three rules. They're also the contract
that every Paper-construction site (PubMed mapper, OpenAlex
client, biorxiv client, Europe PMC client, HTML enricher,
PDF structured extractor) relies on -- if you change the
rules here, you change the contract for every source.
"""
from __future__ import annotations

import pytest

from app.infrastructure.pubmed.abstract_normalizer import (
    _DROP_TAG_AND_CONTENT,  # noqa: F401  (used in test_constants)
    normalize_abstract,
)


class TestNormalizeAbstractDropRules:
    """Heading tags drop their inner text along with the
    wrappers (the user's preferred rule).
    """

    @pytest.mark.parametrize("level", ["h1", "h2", "h3", "h4", "h5", "h6"])
    def test_drops_h_level_label_and_inner_text(self, level):
        """``<h4>Introduction</h4>foo`` -> ``foo``. The label
        word (e.g. ``Introduction``) is dropped too -- the
        user's stated preference.
        """
        text = f"<{level}>Label</{level}>Body content follows"
        assert normalize_abstract(text) == "Body content follows"

    def test_drops_h4_introduction_real_pubmed_chunk(self):
        """A literal chunk of the user's bug report data:
        ``<h4>Introduction</h4>Tau species lacking truncation...``
        must drop the ``<h4>Introduction</h4>`` entirely.
        """
        text = (
            "<h4>Introduction</h4>Tau species lacking truncation "
            "of the N-terminal region, including plasma N-terminal "
            "tau fragment 1 (NT1), have been previously associated "
            "with cognitive decline, neurodegeneration, and tau "
            "pathology in late-onset sporadic Alzheimer's disease "
            "(AD)."
        )
        result = normalize_abstract(text)
        assert result == (
            "Tau species lacking truncation of the N-terminal "
            "region, including plasma N-terminal tau fragment 1 "
            "(NT1), have been previously associated with cognitive "
            "decline, neurodegeneration, and tau pathology in "
            "late-onset sporadic Alzheimer's disease (AD)."
        )
        assert "Introduction" not in result
        assert "<h4>" not in result
        assert "</h4>" not in result

    def test_drops_all_structured_abstract_section_labels(self):
        """Pin the full Elsevier structured-abstract pattern:
        ``<h4>Highlights</h4>``, ``<h4>Introduction</h4>``,
        ``<h4>Methods</h4>``, ``<h4>Results</h4>``,
        ``<h4>Discussion</h4>``. All five labels drop with
        their inner text; the prose body survives.
        """
        text = (
            "<h4>Highlights</h4>Map gains into accountable, "
            "interpretable tools for ADRD care."
            "<h4>Introduction</h4>Tau species lacking truncation "
            "of the N-terminal region, including plasma N-terminal "
            "tau fragment 1 (NT1), have been previously associated "
            "with cognitive decline."
            "<h4>Methods</h4>Here, we examined crosssectional and "
            "longitudinal plasma NT1 as a possible predictor of "
            "cognitive, clinical, and core AD biomarker trajectories."
            "<h4>Results</h4>NT1 levels in ADAD mutation carriers "
            "(MC; n = 132) increased across the disease continuum."
            "<h4>Discussion</h4>Together, our results suggest "
            "that plasma NT1-alone or combined with other tau "
            "measures-may be useful."
        )
        result = normalize_abstract(text)
        for label in ("Highlights", "Introduction", "Methods",
                      "Results", "Discussion"):
            assert label not in result, (
                f"<h4>{label}</h4> should drop but '{label}' "
                f"still in result"
            )
        # Body prose survives.
        assert "Tau species lacking truncation" in result
        assert "ADAD mutation carriers" in result
        # No raw tags leak.
        assert "<" not in result
        assert ">" not in result


class TestNormalizeAbstractKeepRules:
    """Inline tags drop their wrappers but preserve the inner
    text (the user's preferred rule).
    """

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("<i>tau</i> pathology", "tau pathology"),
            ("<b>bold</b> claim", "bold claim"),
            ("<strong>strong</strong> evidence", "strong evidence"),
            ("<em>emphasis</em> here", "emphasis here"),
            ("<u>underlined</u> word", "underlined word"),
            ("<mark>highlighted</mark> span", "highlighted span"),
            ("E = mc<sup>2</sup>", "E = mc2"),
            ("H<sub>2</sub>O", "H2O"),
            ("<span>spanned</span> text", "spanned text"),
            ("<a href='/x'>linked</a> word", "linked word"),
        ],
    )
    def test_keeps_inner_text_for_inline_tag(self, text, expected):
        """Each inline emphatic / superscript / subscript /
        formatting tag drops its wrappers but keeps the
        inner text.
        """
        assert normalize_abstract(text) == expected

    def test_keeps_pubmed_sup_tags_with_inner_text(self):
        """PubMed's structured abstracts wrap isotope
        notation in ``<sup>...</sup>``: the isotope label is
        real content (e.g. ``18F``, ``3H``). The user wants
        to keep the inner text, so ``[<sup>18</sup>F]`` should
        become ``[18F]``.
        """
        text = "[<sup>18</sup>F](S)-(2-methylpyrid-5-yl)-6-[<sup>3</sup>H]PiB"
        result = normalize_abstract(text)
        assert result == "[18F](S)-(2-methylpyrid-5-yl)-6-[3H]PiB"
        assert "<sup>" not in result

    def test_nested_sup_inside_sup_preserves_all_inner_text(self):
        """Defensive: if the publisher nests ``<sup>`` inside
        another ``<sup>`` (rare but possible), both wrappers
        drop and both inner texts stay. None of the wrappers
        is in ``_DROP_TAG_AND_CONTENT`` so they're all
        "drop-tag-keep-text".
        """
        text = "a<sup>1<sup>2</sup></sup>b"
        result = normalize_abstract(text)
        assert result == "a12b"


class TestNormalizeAbstractNesting:
    """The depth counter handles nested h-level tags."""

    def test_h4_wrapping_i_drops_the_i_outer_too(self):
        """``<h4><i>Introduction</i></h4>`` -- the ``<h4>``
        drops the entire wrapped region, including the
        nested ``<i>`` tag and its text.
        """
        text = "<h4><i>Introduction</i></h4>Tau species"
        assert normalize_abstract(text) == "Tau species"

    def test_h1_wrapping_h3_drops_both_levels(self):
        """``<h1><h3>Label</h3></h1>`` -- both levels are in
        ``_DROP_TAG_AND_CONTENT`` so both drop. Inner text
        ``Label`` is gone, body survives.
        """
        text = "<h1><h3>Label</h3></h1>Body content"
        assert normalize_abstract(text) == "Body content"

    def test_section_break_with_drop_followed_by_normal(self):
        """After a dropped ``<h4>...</h4>``, subsequent
        prose should render normally. The depth counter
        resets to 0 on the closing ``</h4>``.
        """
        text = (
            "<h4>Introduction</h4>"
            "Body after section one. "
            "<h4>Methods</h4>"
            "Body after section two."
        )
        assert normalize_abstract(text) == (
            "Body after section one. "
            "Body after section two."
        )


class TestNormalizeAbstractPreservesEntities:
    """``HTMLParser`` with ``convert_charrefs=True`` (the
    stdlib default) decodes entity references like
    ``&amp;`` and ``&micro;`` into their character
    equivalents and emits them as ``handle_data``. The
    normaliser therefore preserves already-encoded text
    byte-for-byte -- the upstream ``html.unescape`` in
    ``_clean_abstract`` does the heavy lifting, but
    ``normalize_abstract`` itself must not corrupt
    entity references that survive to it.
    """

    def test_preserves_literal_ampersand_from_pubmed(self):
        """Real-world abstracts sometimes contain stray
        fragments like ``&CG`` where the publisher forgot
        the trailing ``;``. The normaliser must pass them
        through unchanged -- they are not HTML tags.
        """
        assert normalize_abstract("AT&CG TA pattern") == "AT&CG TA pattern"

    def test_decodes_stdlib_entities_via_handle_data(self):
        """``convert_charrefs=True`` means the parser decodes
        ``&amp;`` -> ``&`` and delivers it as ``handle_data``.
        The normaliser therefore emits the decoded
        character, not the entity literal.
        """
        # Note: this test pins the stdlib default
        # behaviour. Changing to ``convert_charrefs=False``
        # would change this contract -- see the module
        # docstring of abstract_normalizer.py for the
        # rationale.
        assert (
            normalize_abstract("AT&amp;CG TA pattern")
            == "AT&CG TA pattern"
        )

    def test_decodes_numeric_character_references(self):
        """``&#NNN;`` numeric character references are
        decoded by the stdlib HTMLParser into their
        Unicode character.
        """
        assert normalize_abstract("&#65;&#66;&#67;") == "ABC"


class TestNormalizeAbstractEdgeCases:
    """Defensive: empty input, no tags, malformed input."""

    def test_returns_empty_string_for_empty_input(self):
        """Idempotent on empty string. ``Paper.abstract = ""``
        is a valid state -- the normaliser must not crash
        on it.
        """
        assert normalize_abstract("") == ""

    def test_returns_input_unchanged_when_no_tags(self):
        """Defensive against over-stripping: a plain-text
        abstract (no HTML at all) passes through unchanged.
        """
        text = (
            "Tau species lacking truncation of the N-terminal "
            "region, including plasma N-terminal tau fragment 1."
        )
        assert normalize_abstract(text) == text

    def test_handles_malformed_unclosed_tags_gracefully(self):
        """Real-world abstracts sometimes contain
        half-encoded fragments (``<h4`` without the closing
        ``>``, missing closing tags). ``HTMLParser`` is
        intentionally lenient -- it does NOT raise on
        malformed input. The normaliser surfaces the
        best-effort cleaned string.
        """
        # Unclosed <h4> opener -- HTMLParser treats the rest
        # as text inside the (unclosed) heading. The drop
        # rule still applies, so the entire rest of the
        # input is consumed.
        try:
            result = normalize_abstract("<h4>Malformed fragment")
        except Exception as exc:
            raise AssertionError(
                f"normalize_abstract raised on malformed input: {exc}"
            )
        assert isinstance(result, str)

    def test_idempotent_under_double_pass(self):
        """Running the normaliser twice on the same text
        produces the same output as running it once. Pinning
        this so ``Paper.abstract = normalize_abstract(...)
        called twice in different code paths`` is safe and
        doesn't double-strip.
        """
        text = (
            "<h4>Introduction</h4>"
            "<i>tau</i> pathology "
            "[<sup>18</sup>F]"
        )
        once = normalize_abstract(text)
        twice = normalize_abstract(once)
        assert once == twice


class TestNormalizeAbstractContract:
    """Pin the global tag classification so a future
    contributor can't accidentally flip a tag's class.
    """

    def test_drop_classification_includes_h1_through_h6(self):
        """The classification list must cover all heading
        levels. Pinning explicitly because a typo
        (``{"h1", "h2", "h3", "h5", "h6"}`` -- missing ``h4``)
        would silently fail to drop the exact tag that's
        causing the user's bug.
        """
        for level in range(1, 7):
            tag = f"h{level}"
            assert tag in _DROP_TAG_AND_CONTENT, (
                f"_DROP_TAG_AND_CONTENT is missing '{tag}' -- "
                f"the heading classification is incomplete"
            )

    def test_drop_classification_does_not_include_inline_tags(self):
        """The classification list must NOT include
        inline emphatic tags (``i``, ``b``, ``strong``,
        ``em``, ``u``, ``sup``, ``sub``, ``mark``,
        ``span``, ``a``). These drop their wrappers but
        preserve the inner text -- putting them in
        ``_DROP_TAG_AND_CONTENT`` would silently lose
        ``<sup>18</sup>F`` -> ``F`` (wrong).
        """
        inline_tags = {
            "i", "b", "strong", "em", "u", "sup", "sub",
            "mark", "span", "a", "p", "div", "section",
        }
        for tag in inline_tags:
            assert tag not in _DROP_TAG_AND_CONTENT, (
                f"inline tag '{tag}' should NOT be in "
                f"_DROP_TAG_AND_CONTENT (would lose inner text)"
            )
