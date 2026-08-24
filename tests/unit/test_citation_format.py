"""
tests/unit/test_citation_format.py

Tests for Citation.format() -- the formatter that turns a Paper
into a human-readable citation in the requested style.

The formatter must:
  - Use ``last_name, F. M.`` author format for APA
  - Use ``Last, First`` for the first author + ``et al.`` for 3+ in MLA
  - Use ``F. Last`` for IEEE
  - Use ``Last FM`` (NLM/PubMed) for Vancouver
  - Degrade gracefully when fields are missing -- never crash on a
    partial Paper
  - Always Include the paper title (never produce an empty string)
  - Cap multi-author lists sensibly
"""
from app.core.enums.citation_style import CitationStyleEnum
from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper


def _paper(**overrides) -> Paper:  # type: ignore[no-untyped-def]
    """Build a fully-populated Paper; override any field via kwargs."""
    defaults = dict(
        title="Alzheimer's disease biomarkers in 2024",
        authors=[
            Author(first_name="Jane", last_name="Smith"),
            Author(first_name="John", last_name="Doe"),
        ],
        journal=Journal(name="Nature", issn="0028-0836"),
        year=2024,
        abstract="",
        doi="10.1038/nature14539",
        pmid="12345678",
        keywords=[],
        url=None,
    )
    defaults.update(overrides)
    return Paper(**defaults)


# -- APA -----------------------------------------------------------------------------------------------------------------------------


def test_citation_apa_two_authors() -> None:
    paper = _paper()
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    # APA: ``Smith, J., & Doe, J.`` -- but with two authors the
    # style uses ``, &`` between them.
    assert "Smith, J." in formatted
    assert "Doe, J." in formatted
    assert "&" in formatted
    assert "(2024)" in formatted
    assert "Nature" in formatted
    assert "Alzheimer" in formatted
    assert "https://doi.org/10.1038/nature14539" in formatted


def test_citation_apa_single_author() -> None:
    paper = _paper(authors=[Author(first_name="Ada", last_name="Lovelace")])
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    assert formatted.startswith("Lovelace, A.")
    # Single author -- no ampersand.
    assert "&" not in formatted


def test_citation_apa_three_plus_authors_uses_comma_before_final_ampersand() -> None:
    paper = _paper(authors=[
        Author(first_name="A", last_name="One"),
        Author(first_name="B", last_name="Two"),
        Author(first_name="C", last_name="Three"),
    ])
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    # Three authors -> ``One, A., Two, B., & Three, C.``
    assert "One, A., Two, B., & Three, C." in formatted


def test_citation_apa_without_year_drops_year_bracket() -> None:
    paper = _paper(year=None)
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    assert "(None)" not in formatted
    assert "()" not in formatted


def test_citation_apa_without_doi_does_not_emit_doi_segment() -> None:
    paper = _paper(doi=None)
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    assert "doi.org" not in formatted
    assert "10.1038" not in formatted


def test_citation_apa_without_authors_starts_with_title() -> None:
    paper = _paper(authors=[])
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    # No authors -> the title becomes the lead segment.
    assert formatted.startswith("Alzheimer")


# -- MLA -----------------------------------------------------------------------------------------------------------------------------


def test_citation_mla_two_authors() -> None:
    paper = _paper()
    formatted = Citation(paper=paper, style=CitationStyleEnum.MLA).format()
    # MLA: ``Smith, Jane, and John Doe. Title. Nature, 2024.``
    assert "Smith, Jane" in formatted
    assert "John Doe" in formatted
    assert " and " in formatted
    assert "Nature, 2024" in formatted
    assert "https://doi.org/10.1038/nature14539" in formatted
    # MLA puts the year inside the journal segment, NOT in
    # an author prefix like APA's ``(2024)``.
    assert formatted.startswith("Smith, Jane, and John Doe.")


def test_citation_mla_three_plus_authors_uses_et_al() -> None:
    paper = _paper(authors=[
        Author(first_name="A", last_name="One"),
        Author(first_name="B", last_name="Two"),
        Author(first_name="C", last_name="Three"),
    ])
    formatted = Citation(paper=paper, style=CitationStyleEnum.MLA).format()
    assert "et al." in formatted


# -- IEEE ----------------------------------------------------------------------------------------------------------------------------


def test_citation_ieee() -> None:
    paper = _paper()
    formatted = Citation(paper=paper, style=CitationStyleEnum.IEEE).format()
    # IEEE: ``J. Smith and J. Doe, "Title," Nature, 2024.``
    assert '"Alzheimer' in formatted or '"Alzheimer\'s' in formatted or '"Alzheimer' in formatted
    assert "J. Smith" in formatted
    assert "and J. Doe" in formatted
    assert "Nature" in formatted
    assert "2024" in formatted


# -- Vancouver ------------------------------------------------------------------------------------------------------------------------


def test_citation_vancouver() -> None:
    paper = _paper()
    formatted = Citation(paper=paper, style=CitationStyleEnum.VANCOUVER).format()
    # Vancouver: ``Smith J, Doe J. Title. Nature. 2024.``
    assert "Smith J" in formatted
    assert "Doe J" in formatted
    assert "Nature" in formatted
    assert "2024" in formatted


def test_citation_vancouver_does_not_use_and() -> None:
    paper = _paper(authors=[
        Author(first_name="A", last_name="One"),
        Author(first_name="B", last_name="Two"),
    ])
    formatted = Citation(paper=paper, style=CitationStyleEnum.VANCOUVER).format()
    # Vancouver does not use "and" between authors -- it's a comma list.
    assert " and " not in formatted.split(".")[0]


# -- Cross-style edge cases -----------------------------------------------------------------------------------------------------------


def test_citation_never_returns_empty_string() -> None:
    # Even with the most minimal Paper (no authors, no journal,
    # no year, no DOI), the formatter must return at least the
    # title so the citation list in the UI never has blank rows.
    paper = Paper(
        title="Minimal paper",
        authors=[],
        journal=None,
        year=None,
        abstract="",
        doi=None,
        pmid=None,
    )
    for style in CitationStyleEnum:
        formatted = Citation(paper=paper, style=style).format()
        assert formatted.strip(), f"{style.value} returned empty"
        assert "Minimal paper" in formatted


def test_citation_handles_author_missing_first_name() -> None:
    # Some papers list authors by last name only ("Anonymous"
    # in medieval texts, or institutional authors like
    # ``World Health Organization``). The formatter must
    # degrade to using the last_name as the whole author label.
    paper = _paper(authors=[Author(first_name="", last_name="World Health Organization")])
    for style in CitationStyleEnum:
        formatted = Citation(paper=paper, style=style).format()
        assert "World Health Organization" in formatted, f"{style.value} dropped the author"


def test_citation_handles_hyphenated_given_names() -> None:
    # ``Jean-Michel`` should produce ``J.-M.`` initials, not
    # split awkwardly across authors.
    paper = _paper(authors=[Author(first_name="Jean-Michel", last_name="Dupont")])
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    # APA uses ``J.-M.`` -- check that the initials section
    # captured both halves.
    assert "J.-M." in formatted


def test_citation_handles_first_name_only() -> None:
    # Edge case: an author with only a given name (e.g. a
    # mononym like ``Plato`` or ``Aristotle``). The formatter
    # must not crash and must surface the name.
    paper = _paper(authors=[Author(first_name="Plato", last_name="")])
    formatted = Citation(paper=paper, style=CitationStyleEnum.APA).format()
    assert "Plato" in formatted


def test_citation_no_double_period_for_already_abbreviated_initials() -> None:
    # Regression guard for the ``Knopman, D.. S.`` bug we hit in
    # production. Author metadata from PubMed/CrossRef often
    # arrives with initials already written as ``"D. S."`` -- the
    # formatter must NOT add a second period after each initial
    # (which would give ``"D.. S."``). APA preserves the
    # author-written form; Vancouver drops the periods to give
    # ``"DS"`` (PubMed style).
    paper = _paper(
        authors=[Author(first_name="D. S.", last_name="Knopman")],
    )
    formatted_apa = Citation(
        paper=paper, style=CitationStyleEnum.APA
    ).format()
    formatted_vanc = Citation(
        paper=paper, style=CitationStyleEnum.VANCOUVER
    ).format()
    assert "D.." not in formatted_apa, (
        "APA citation should NOT contain ``D..``: "
        f"{formatted_apa!r}"
    )
    assert "D. S." in formatted_apa, (
        "APA should preserve the author-written ``D. S.``: "
        f"{formatted_apa!r}"
    )
    assert "DS" in formatted_vanc, (
        "Vancouver strips periods: "
        f"{formatted_vanc!r}"
    )


def test_citation_str_uses_format() -> None:
    # ``__str__`` must mirror ``format()`` -- the API layer
    # serialises citations via ``str(citation)``.
    paper = _paper()
    for style in CitationStyleEnum:
        citation = Citation(paper=paper, style=style)
        assert str(citation) == citation.format()


def test_citation_to_markdown_emits_bullet() -> None:
    paper = _paper()
    md = Citation(paper=paper, style=CitationStyleEnum.APA).to_markdown()
    assert md.startswith("- ")
    assert "Alzheimer" in md