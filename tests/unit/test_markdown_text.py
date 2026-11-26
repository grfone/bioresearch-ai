"""
Tests for ``app/core/markdown_text.py``.

The shared stripper is the single place that knows how to remove
inline markdown. Two copies of that logic drift, and a drifting
copy silently stops matching -- which is exactly what happened
when the PDF compared a clean title against a body line that
still carried ``**bold**``.
"""

from app.core.markdown_text import strip_inline_markdown


class TestStripInlineMarkdown:
    def test_removes_bold_markers(self) -> None:
        assert strip_inline_markdown(
            "**plasma** N-terminal tau"
        ) == "plasma N-terminal tau"

    def test_removes_code_markers(self) -> None:
        assert strip_inline_markdown("a `code` span") == "a code span"

    def test_leaves_a_single_asterisk_alone(self) -> None:
        # "p-tau217", "3 * 4", "snake_case" -- stripping these
        # would mangle ordinary scientific text.
        assert strip_inline_markdown("p-tau217 and 3 * 4") == (
            "p-tau217 and 3 * 4"
        )

    def test_leaves_a_single_underscore_alone(self) -> None:
        assert strip_inline_markdown("snake_case_name") == "snake_case_name"

    def test_collapses_whitespace(self) -> None:
        assert strip_inline_markdown("a   b\n\nc") == "a b c"

    def test_strips_the_markers_not_the_text(self) -> None:
        assert strip_inline_markdown("**bold**") == "bold"

    def test_handles_an_empty_string(self) -> None:
        assert strip_inline_markdown("") == ""

    def test_a_title_derived_from_a_body_line_matches_it(self) -> None:
        """The property the PDF's duplicate guard depends on."""
        from app.infrastructure.llm.title_fallback import (
            derive_title_from_first_sentence,
        )

        body = (
            "Among the supplied studies, **plasma N-terminal tau "
            "fragment 1** (p-tau217) emerged as the marker."
        )
        title = derive_title_from_first_sentence(body)
        assert strip_inline_markdown(body).startswith(title)
