"""
markdown_text.py

Shared plain-text helpers for markdown fragments.

Why this exists
---------------
The report title is plain text: it is rendered as a heading in the
React UI and as a ReportLab paragraph in the PDF, and neither
renders markdown. The title is *derived from* the markdown body,
so the same markup has to be removed on both sides of any
comparison between them.

The PDF generator already needs such a comparison: the H1 fallback
prepends the body's opening sentence as the title, so the body
repeats it, and the generator strips the repeat. Before this
module the comparison was done on raw markdown against a clean
title, so a body line carrying ``**bold**`` never matched the
title it was derived from -- and the duplicate survived into the
PDF.

This module is the single place that knows how to strip inline
markdown. Two copies of that logic drift, and a drifting copy
silently stops matching.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import re

#: Inline markup markers that must not appear in plain text.
#:
#: Only unambiguous markers are removed: ``**bold**`` and
#: ``` `code` ```. A single ``*`` or ``_`` is left alone -- those
#: occur in ordinary text ("p-tau217", "3 * 4", "snake_case") and
#: stripping them would mangle the content.
_INLINE_MARKUP_RE = re.compile(r"\*\*|`")

_WHITESPACE_RE = re.compile(r"\s+")


def strip_inline_markdown(text: str) -> str:
    """
    Remove inline markdown markers and collapse whitespace.

    Parameters
    ----------
    text : str
        A markdown fragment.

    Returns
    -------
    str
        The fragment with ``**`` and ``` ` ``` markers removed and
        runs of whitespace collapsed to single spaces.

    Examples
    --------
    >>> strip_inline_markdown("**plasma** N-terminal tau")
    'plasma N-terminal tau'
    >>> strip_inline_markdown("a  `code`  span")
    'a code span'
    >>> strip_inline_markdown("p-tau217 and 3 * 4")
    'p-tau217 and 3 * 4'
    """
    cleaned = _INLINE_MARKUP_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()
