"""
citation.py

Domain entity representing a bibliographic citation.

A Citation encapsulates the logic required to transform a scientific paper
into a formatted reference according to a specific citation style (e.g. APA,
MLA, Vancouver).

The formatted citation is intentionally **not stored**. Instead, it is
generated on demand from the associated Paper entity. This prevents
inconsistencies between the paper metadata and the rendered citation.

Future versions may support additional citation styles and export formats
such as BibTeX, RIS, or EndNote.

Author
------
Guillermo Ramajo Fernández
"""

from dataclasses import dataclass

from app.core.enums.citation_style import CitationStyleEnum
from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper


# ---------------------------------------------------------------------------
# Citation formatting helpers
# ---------------------------------------------------------------------------
# Pure-function formatters, one per supported style. Each function takes
# the relevant pieces of Paper and returns a single-line citation segment.
# _format_citation is the dispatcher that picks the right style and
# stitches the segments together. We keep these here (rather than in a
# separate module) because they're used only by Citation.format() and
# don't need their own imports.
# ---------------------------------------------------------------------------


def _build_token(given):
    """Split the given name into per-INITIAL letters + separators.

    The internal representation stores initial letters (uppercase) and
    separators (``"-"`` between hyphenated parts within a name;
    ``" "`` between space-separated segments). Each initial letter
    carries an ``is_period`` flag that tells the caller whether the
    author already wrote a period after it (e.g. ``"D. S."`` produces
    ``("D", True), (" ", _), ("S", True)``). This is what lets us
    avoid the double-period bug.

    Parameters
    ----------
    given : str
        Author's given name. May be empty.

    Returns
    -------
    list[tuple[str, bool]]
        List of ``(letter_or_separator, is_period)`` tuples, e.g.
        ``[("J", False), ("-", _), ("M", True)]`` for
        ``"Jean-Michel"`` and
        ``[("D", True), (" ", _), ("S", True)]`` for ``"D. S."``.

        Empty list if no initials could be extracted.
    """
    if not given:
        return []
    tokens = []
    for s_idx, segment in enumerate(given.split()):
        if s_idx > 0:
            # Separator between space-separated segments. We
            # emit a single space; the per-period logic in the
            # caller adds the period after the previous initial.
            tokens.append((" ", False))
        # A segment is either a single name (``Jane``) or a
        # hyphenated name (``Jean-Michel``). Within a hyphenated
        # name, each part may already be abbreviated (``R. C.``)
        # or not (``Jane-Marie``).
        for h_idx, raw_part in enumerate(segment.split("-")):
            if h_idx > 0:
                # Separator between hyphenated parts.
                tokens.append(("-", False))
            # Strip any trailing period the author wrote so we
            # can decide whether to add one ourselves. We use
            # ``[:-1]`` if the part ends in ``.``, NOT
            # ``.rstrip(".")``: that's destructive on inputs
            # like ``"D. S."`` where the LAST ``.`` is in the
            # trailing ``S.`` and we just want to look at the
            # S, but ``rstrip`` would also strip the period
            # before the space (turning ``D. S.`` into ``D S``).
            if not raw_part or raw_part == ".":
                # Empty or lone period -- skip.
                continue
            if raw_part.endswith("."):
                part_letters = raw_part[:-1]
                already_ended_in_period = True
            else:
                part_letters = raw_part
                already_ended_in_period = False
            if not part_letters:
                continue
            tokens.append((part_letters[0].upper(), already_ended_in_period))
    return tokens


def _initial_to_letters(token):
    """Flatten the token stream to per-letter form, dropping separators.

    Returns ``list[str]`` of capital letters (e.g. ``['J', 'M']``
    for ``"John Michael"``). All separators (both ``-`` between
    hyphenated parts and `` `` between space-separated segments) are
    discarded.
    """
    return [t[0] for t in token if t[0] not in ("-", " ")]


def _initials_apa(given):
    """APA 7th initials: ``John Michael`` -> ``J. M.``; ``Jean-Michel`` -> ``J.-M.``.

    Logic:
      - Every initial letter gets a trailing period (``D.``).
      - Hyphenated parts use a dash between initials (``J.``-``M.``).
      - Space-separated segments use a space between initials (``J. M.``).
      - Already-abbreviated inputs (e.g. ``"D. S."``) come out as
        ``"D. S."`` -- the trailing period the author already
        wrote is preserved rather than doubled up.

    Returns the empty string when no initials could be extracted.
    """
    if not given:
        return ""
    tokens = _build_token(given)
    if not tokens:
        return ""
    parts = []
    for letter, already_dot in tokens:
        if letter == "-":
            # Separator between hyphenated initials. The
            # previous letter already has its period (added or
            # preserved below); we don't add one on the dash.
            parts.append("-")
            continue
        if letter == " ":
            # Separator between space-separated initials. Same
            # logic -- no extra period on the space.
            parts.append(" ")
            continue
        # Real initial letter. Always emit a period after it
        # regardless of whether the author already wrote one.
        # The ``already_dot`` flag is preserved purely for
        # downstream consumers that want to detect already-
        # abbreviated sources; it doesn't change the output
        # since both cases want a period after the letter.
        parts.append(letter + ".")
    return "".join(parts)


def _initials_ieee(given):
    """IEEE initials: same format as APA, just named separately for clarity."""
    return _initials_apa(given)


def _initials_vancouver(given):
    """Vancouver (NLM/PubMed): no periods, dashes preserved for hyphenated initials.

    PubMed uses initials-with-no-period: ``Smith JA`` for Jane A.
    Smith; ``Knopman DS`` (if the source wrote it that way); ``J-M``
    for ``Jean-Michel``.

    Source-separated segments are NOT joined by a space -- the
    surname prefix in PubMed style is just the initials run
    together (e.g. ``"D. S. Knopman"`` -> ``"DS Knopman"`` at the
    call site). The dash between hyphenated initials IS preserved.
    """
    if not given:
        return ""
    tokens = _build_token(given)
    if not tokens:
        return ""
    parts = []
    for letter, _ in tokens:
        if letter == "-":
            parts.append("-")
            continue
        if letter == " ":
            # Surname prefix in PubMed is run together: no space.
            # The space is still rendered in APA / IEEE where the
            # surname comes AFTER the initials and is the natural
            # break. In Vancouver the prefix is glued.
            continue
        parts.append(letter)
    return "".join(parts)


def _format_authors_apa(authors):
    """APA 7th: ``Last, F. M., Last, F. M., & Last, F. M.``.

    Two authors: ``Last1, F. M., & Last2, F. M.``.
    One author: ``Last1, F. M.``.
    No authors: returns the empty string. The caller (``_format_citation``)
    handles the no-authors case by promoting the title to the lead
    position, which is what APA actually recommends for works
    authored by an organisation or with no named author
    (https://apastyle.apa.org/style-grammar-guidelines/citations/
    citing-a-work-with-no-author).
    """
    parts = []
    for author in authors:
        if not author.last_name or not author.first_name:
            # Fall back to whatever the family name is -- we don't
            # silently drop authors from a citation.
            parts.append(author.last_name or author.first_name or "Anonymous")
            continue
        initials = _initials_apa(author.first_name)
        if not initials:
            parts.append(author.last_name)
            continue
        parts.append(f"{author.last_name}, {initials}")
    if not parts:
        # No authors at all -- caller will promote the title.
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}, & {parts[1]}"
    # APA uses a comma before the final ``&`` when there are 3+ authors.
    return ", ".join(parts[:-1]) + f", & {parts[-1]}"


def _format_authors_mla(authors):
    """MLA 9th: ``Last, First`` for the first author, then ``First Last``.

    Three or more authors -> ``Last, First, et al.``.
    Two authors -> ``Last, First, and First Last``.
    """
    if not authors:
        return "Anonymous"
    first = authors[0]
    if first.last_name and first.first_name:
        head = f"{first.last_name}, {first.first_name}"
    else:
        head = first.last_name or first.first_name or "Anonymous"
    if len(authors) >= 3:
        return f"{head}, et al."
    if len(authors) == 1:
        return head
    rest = ", ".join(
        f"{a.first_name} {a.last_name}"
        if a.first_name and a.last_name
        else (a.last_name or a.first_name)
        for a in authors[1:]
    )
    return f"{head}, and {rest}"


def _format_authors_ieee(authors):
    """IEEE: ``F. Last``, comma-separated, ``and`` before the last."""
    parts = []
    for author in authors:
        if not author.last_name or not author.first_name:
            parts.append(author.last_name or author.first_name or "Anonymous")
            continue
        initials = _initials_ieee(author.first_name)
        if not initials:
            parts.append(author.last_name)
            continue
        parts.append(f"{initials} {author.last_name}")
    if not parts:
        return "Anonymous"
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _format_authors_vancouver(authors):
    """Vancouver (NLM/PubMed): ``Last FM``, comma-separated, no "and"."""
    parts = []
    for author in authors:
        if not author.last_name or not author.first_name:
            parts.append(author.last_name or author.first_name or "Anonymous")
            continue
        initials = _initials_vancouver(author.first_name)
        if not initials:
            parts.append(author.last_name)
            continue
        parts.append(f"{author.last_name} {initials}")
    return ", ".join(parts) if parts else "Anonymous"


def _journal_name(journal):
    """Best available journal name (full > abbreviated > title)."""
    if journal is None:
        return ""
    return journal.name or journal.abbreviation or journal.title or ""


def _format_citation(paper, style):
    """Dispatch helper. Returns the formatted citation for the requested style."""
    # Per-style author formatter. The journal / volume / pages /
    # DOI formatting is shared across all four styles -- only the
    # author-list format and the field-order separator differ.
    if style == CitationStyleEnum.APA:
        authors = _format_authors_apa(paper.authors)
    elif style == CitationStyleEnum.MLA:
        authors = _format_authors_mla(paper.authors)
    elif style == CitationStyleEnum.IEEE:
        authors = _format_authors_ieee(paper.authors)
    elif style == CitationStyleEnum.VANCOUVER:
        authors = _format_authors_vancouver(paper.authors)
    else:
        # Unknown style -- default to APA. The enum above is closed,
        # so this branch is defensive only.
        authors = _format_authors_apa(paper.authors)

    journal_name = _journal_name(paper.journal)
    year_str = str(paper.year) if paper.year is not None else ""
    doi_suffix = f" https://doi.org/{paper.doi}" if paper.doi else ""

    # Volume(Issue): Pages segment. The data model currently
    # doesn't carry these fields on Paper or Journal (the
    # retrievers populate volume / issue / pages inconsistently
    # across CrossRef, OpenAlex, PubMed). We emit whatever
    # attributes are present at runtime; missing ones are
    # silently skipped. This keeps the formatter forward-
    # compatible: when the data model grows these fields, the
    # citation output picks them up automatically.
    vi_page = ""
    if paper.journal is not None:
        v = getattr(paper.journal, "volume", None) or ""
        i = getattr(paper.journal, "issue", None) or ""
        p = getattr(paper.journal, "pages", None) or ""
        if v and i:
            vi_page = f"{v}({i})"
        elif v:
            vi_page = v
        elif i:
            vi_page = f"({i})"
        if p and vi_page:
            vi_page = f"{vi_page}: {p}"
        elif p and not vi_page:
            vi_page = p

    title = paper.title.strip() or "Untitled"

    if style in (CitationStyleEnum.APA, CitationStyleEnum.MLA):
        # APA / MLA: Authors (Year). Title. Journal, Volume(Issue): Pages. DOI.
        # MLA actually puts the year inline with the journal (e.g.
        # ``Nature, 2024``), so we share the journal_year block but
        # the year bracket stays only for APA. MLA picks the year up
        # inside the journal segment.
        # When ``authors`` is empty (no named author), we promote
        # the title to the lead position -- this is what APA
        # recommends for organisational authors / works without a
        # named individual.
        if style == CitationStyleEnum.APA:
            if authors:
                journal_year = ""
                if journal_name and year_str:
                    journal_year = f"{journal_name}, {year_str}"
                elif journal_name:
                    journal_year = journal_name
                elif year_str:
                    journal_year = year_str
                parts = [f"{authors}{(' (' + year_str + ')') if year_str else ''}. {title}."]
            else:
                # No authors -- title becomes the lead segment,
                # year follows as a parenthetical.
                parts = [f"{title}{(' (' + year_str + ')') if year_str else ''}."]
                journal_year = ""
                if journal_name:
                    journal_year = journal_name
                elif year_str:
                    journal_year = year_str
        else:
            # MLA: ``Authors. Title. Journal, Year.``
            if authors:
                parts = [f"{authors}. {title}."]
            else:
                parts = [f"{title}."]
            journal_year = ""
            if journal_name and year_str:
                journal_year = f"{journal_name}, {year_str}"
            elif journal_name:
                journal_year = journal_name
            elif year_str:
                journal_year = year_str
        if journal_year:
            parts.append(f"{journal_year}.")
        if vi_page:
            parts.append(f"{vi_page}.")
        if doi_suffix:
            parts.append(doi_suffix.strip())
        return " ".join(p for p in parts if p)
    if style == CitationStyleEnum.IEEE:
        # IEEE: Authors, "Title," Journal, vol(issue): pp., Year. DOI.
        seg = []
        if journal_name:
            seg.append(journal_name)
        if vi_page:
            seg.append(vi_page)
        if year_str:
            seg.append(year_str)
        journal_seg = ", ".join(seg)
        if authors:
            body = f'{authors}, "{title},"'
        else:
            body = f'"{title},"'
        if journal_seg:
            body = f"{body} {journal_seg},"
        if doi_suffix:
            body = f"{body}{doi_suffix}"
        return body.rstrip(",.").strip() + "."
    if style == CitationStyleEnum.VANCOUVER:
        # Vancouver: Authors. Title. Journal. Year;Volume(Issue):Pages. DOI.
        seg = []
        if journal_name:
            seg.append(f"{journal_name}.")
        if year_str:
            seg.append(f"{year_str};")
        if vi_page:
            seg.append(f"{vi_page}.")
        journal_seg = " ".join(seg)
        if authors:
            parts = [f"{authors}. {title}."]
        else:
            parts = [f"{title}."]
        if journal_seg:
            parts.append(journal_seg)
        if doi_suffix:
            parts.append(doi_suffix.strip())
        return " ".join(p for p in parts if p)
    # Fallback: APA-shaped with whatever we have.
    return f"{authors}. {title}.{doi_suffix}".strip()


@dataclass
class Citation:
    """Represents a bibliographic citation for a scientific publication.

    Parameters
    ----------
    paper : Paper
        Scientific publication to be cited.

    style : CitationStyleEnum, default=CitationStyleEnum.APA
        Citation format to use.

    Notes
    -----
    This class belongs to the Domain layer and therefore contains no
    dependency on external citation libraries.

    Formatting logic should remain lightweight. If more sophisticated
    formatting becomes necessary, this class can delegate the work to a
    dedicated CitationFormatter service in the Application layer.
    """

    paper: Paper
    style: CitationStyleEnum = CitationStyleEnum.APA

    def format(self) -> str:
        """Generate a formatted citation.

        Returns a string formatted in the requested citation style
        (``self.style``). All four supported styles use the same
        paper metadata (``self.paper.title``, ``self.paper.authors``,
        ``self.paper.journal``, ``self.paper.year``, ``self.paper.doi``)
        and degrade gracefully when fields are missing -- e.g. a paper
        without a DOI omits the DOI segment, a paper without authors
        starts with the title.

        Returns
        -------
        str
            The formatted citation. Always non-empty -- at minimum we
            return the paper title.

        Notes
        -----
        This implementation is intentionally lightweight -- we use string
        formatting rather than pulling in a heavy citation library
        (e.g. ``citeproc-py``) because the BioResearch AI deployment is a
        single Docker container and we want zero extra runtime
        dependencies. The output follows the dominant formatting style
        for each style but does not handle edge cases like corporate
        authors, non-Latin scripts, or hierarchical DOIs.
        """
        return _format_citation(self.paper, self.style)

    def to_markdown(self) -> str:
        """Return the citation formatted for Markdown documents.

        Returns
        -------
        str
            Markdown representation of the citation.
        """
        return f"- {self.format()}"

    def to_dict(self) -> dict:
        """Serialize the citation into a dictionary.

        Returns
        -------
        dict
            Serializable representation of the citation.
        """
        return {
            "style": self.style.value,
            "paper_title": self.paper.title,
            "doi": self.paper.doi,
            "pmid": self.paper.pmid,
        }

    def __str__(self) -> str:
        """Return the formatted citation.

        Returns
        -------
        str
            Human-readable citation.
        """
        return self.format()