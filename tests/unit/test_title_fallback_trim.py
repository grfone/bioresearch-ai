"""
Tests for the ``_trim_to_last_content_word`` helper
introduced in this commit.

The helper refines the title derivation by trimming
trailing function words (articles, conjunctions,
prepositions, auxiliaries) so titles don't end in "and",
"of", "the", etc. This is a separate module-level
function so the test file lives alongside
``test_title_fallback.py`` and reuses the same
``from app.infrastructure.llm.title_fallback import``
import path.

Background
----------
The user complaint: titles derived from the LLM's first
sentence were sometimes truncated mid-phrase, leaving
dangling function words:

    "...central to the biological diagnosis and"   (BAD)
    "...central to the biological diagnosis"        (GOOD)

The ``_trim_to_last_content_word`` function back-tracks
from the end of the truncated word list until it finds a
non-function word, then returns everything up to that
word.
"""


from app.infrastructure.llm.title_fallback import (
    _trim_to_last_content_word,
)


class TestTrimToLastContentWord:
    """Pin the trim behaviour against the user's
    reported case and several edge cases."""

    def test_user_reported_dangling_and(self):
        """The exact pattern from the user's report: a
        12-word truncation that landed on "and". The
        helper trims "and" so the title ends on the
        previous content word.
        """
        words = [
            "Tau", "biomarkers", "have", "become",
            "central", "to", "the", "biological",
            "diagnosis", "and",
        ]
        out = _trim_to_last_content_word(words)
        # The trailing "and" is gone; "diagnosis" is now
        # the last word.
        assert out.endswith(" diagnosis")
        assert "and" not in out.split()
        # Total word count drops by one.
        assert len(out.split()) == 9

    def test_trims_trailing_preposition(self):
        """Trailing prepositions like "for", "of", "in"
        are trimmed because titles ending in a preposition
        are mid-phrase (e.g. "the role of").
        """
        words = ["the", "role", "of", "biomarker", "for"]
        out = _trim_to_last_content_word(words)
        # "for" is a preposition in our function-word set
        # (and also a conjunction), so it's trimmed.
        # Walking back: "biomarker" is content -- stop.
        assert out == "the role of biomarker"

    def test_trims_trailing_article(self):
        """Trailing "the", "a", "an" are trimmed."""
        words = ["this", "is", "the", "title", "a"]
        out = _trim_to_last_content_word(words)
        # "a" is an article -- trim. "title" is content --
        # stop.
        assert out == "this is the title"

    def test_trims_trailing_auxiliary_verb(self):
        """Auxiliary verbs like "is", "are", "was" don't
        end phrases by themselves."""
        words = ["the", "test", "is"]
        out = _trim_to_last_content_word(words)
        # "is" is an auxiliary -- trim. "test" is content.
        assert out == "the test"

    def test_no_trim_when_last_word_is_content(self):
        """A list ending in a content word passes
        through unchanged.
        """
        words = [
            "long", "term", "memory", "storage",
            "for", "cross", "session", "learning",
        ]
        out = _trim_to_last_content_word(words)
        assert out == " ".join(words)

    def test_empty_list_returns_empty(self):
        assert _trim_to_last_content_word([]) == ""

    def test_single_word_content_returns_unchanged(self):
        """A one-word title (content word) can't be
        trimmed -- there's nothing to back off to.
        """
        assert _trim_to_last_content_word(["biomarkers"]) == "biomarkers"

    def test_single_word_function_returns_unchanged(self):
        """A one-word title (function word) also can't be
        trimmed -- the loop requires ``last_idx > 0``
        to enter, so a single-word input is returned
        as-is regardless of whether it's a function word.
        This is intentional: returning the function
        word is no worse than returning an empty string,
        and gives the caller something to render rather
        than a blank.
        """
        assert _trim_to_last_content_word(["the"]) == "the"
        assert _trim_to_last_content_word(["and"]) == "and"

    def test_all_function_words_returns_first_word(self):
        """A pathological all-function-words list (e.g.
        something the LLM might produce from a
        fragment) -- the loop walks back to ``last_idx > 0``,
        so we end up with the first word of the list.
        Acceptable behaviour: no clean cut is possible,
        and the caller can fall back to the default label.
        """
        words = ["the", "a", "of", "in"]
        out = _trim_to_last_content_word(words)
        # Walking back: 3->"in" function, 2->"of" function,
        # 1->"a" function, loop exits because last_idx > 0
        # condition fails (last_idx becomes 1, then loop
        # checks words[1]="a" which IS function, decrement
        # to 0, loop condition last_idx > 0 fails, exit).
        # Result: words[:1] = ["the"]
        assert out == "the"

    def test_case_insensitive_match(self):
        """Function-word matching is case-insensitive
        because the regex captures sentences as the LLM
        emitted them, and biomedical titles may carry
        Title Case or ALL CAPS.
        """
        # Mixed case: "And" at end (capitalised).
        words = ["the", "title", "And"]
        out = _trim_to_last_content_word(words)
        assert out == "the title"

    def test_combined_trim_and_content_preservation(self):
        """A realistic truncation case: 12-word slice
        ends with a conjunction that should be trimmed
        to land on the previous content word.
        """
        words = [
            "Plasma", "p-tau217", "is", "a", "sensitive",
            "and", "specific", "marker", "for", "AD",
            "diagnosis", "and",
        ]
        out = _trim_to_last_content_word(words)
        # Trims trailing "and", giving us 11 words ending
        # on "diagnosis".
        assert out.endswith(" diagnosis")
        assert not out.endswith(" and")


class TestTrimIntegratedWithDeriveTitle:
    """Integration: the trim is called from
    ``derive_title_from_first_sentence``. The user's
    specific complaint case is now solved end-to-end.
    """

    def test_users_complaint_case(self):
        """The exact body from the user's complaint --
        "Tau biomarkers have become central to the
        biological diagnosis and staging of Alzheimer
        disease." -- now produces a title that ends on
        a content word, not a dangling "and".
        """
        from app.infrastructure.llm.title_fallback import (
            derive_title_from_first_sentence,
        )

        body = (
            "Tau biomarkers have become central to the "
            "biological diagnosis and staging of "
            "Alzheimer disease."
        )
        out = derive_title_from_first_sentence(body)
        # The title MUST NOT end in a function word from
        # our closed vocabulary (the most common dangling
        # ones: and, of, the, for, in, etc.).
        last_word = out.split()[-1].lower()
        assert last_word not in {
            "and", "or", "but", "of", "in", "on", "at",
            "to", "by", "with", "from", "for", "as",
            "the", "a", "an",
        }, (
            f"title should not end on a function word; "
            f"got {out!r} (last word: {last_word!r})"
        )

    def test_short_sentence_unchanged(self):
        """Sentences that fit within the word cap
        pass through unchanged (no truncation happens,
        no trimming happens).
        """
        from app.infrastructure.llm.title_fallback import (
            derive_title_from_first_sentence,
        )

        body = "Plasma p-tau217 is a sensitive marker."
        out = derive_title_from_first_sentence(body)
        # 6 words, fits the cap, ends on "marker" (content).
        assert out == "Plasma p-tau217 is a sensitive marker"

    def test_title_ends_on_content_word_for_long_input(self):
        """A long input that's forced to truncate
        produces a title ending on a content word, not
        a dangling function word.
        """
        from app.infrastructure.llm.title_fallback import (
            derive_title_from_first_sentence,
        )

        body = (
            "The integration of plasma biomarkers in "
            "clinical practice for the diagnosis of "
            "Alzheimer disease and related dementias "
            "is now widely recommended by international "
            "guidelines and expert consensus statements."
        )
        out = derive_title_from_first_sentence(body)
        last_word = out.split()[-1].lower()
        # The last word is whichever content word the
        # truncation landed on. The trim should have
        # back-tracked past any function word.
        assert last_word not in {
            "and", "or", "but", "of", "in", "on", "at",
            "to", "by", "with", "from", "for", "as",
            "the", "a", "an", "is", "are", "was", "were",
            "be", "been",
        }, (
            f"long-input title should end on a content "
            f"word, not a function word; got {out!r} "
            f"(last: {last_word!r})"
        )