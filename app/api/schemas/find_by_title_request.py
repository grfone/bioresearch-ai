"""
find_by_title_request.py

Request schema for the title-driven paper discovery endpoint.

This endpoint exists primarily so users can recover from a PDF
upload that did not contain a recognisable DOI or PMID on the
first page. The flow is:

1. The user drags a PDF.
2. The backend's ``IdentifierResolver`` sweeps the first page
   for ``10.xxxx/yyyy`` (DOI) and ``PMID:`` patterns.
3. If nothing matches, the ``/papers/from-pdf`` endpoint
   returns ``422 no_identifiers_found`` with a small JSON body
   containing the first-page text.
4. The frontend catches that and surfaces an inline panel:
   "Type the paper title to search PubMed".
5. The user submits a title. This endpoint fires:
   ``POST /workspaces/{id}/papers/from-title``
6. The backend calls PubMed ESearch with the title, picks the
   best match, and adds it to the workspace — same flow as if
   the user had pasted the PMID directly.

The endpoint deliberately accepts only a free-text title, not a
question. The whole point is to recover from a PDF that yielded
no identifiers; the user already knows the paper exists and is
giving us its handle.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FindByTitleRequest(BaseModel):
    """Body of ``POST /workspaces/{id}/papers/from-title``.

    The ``title`` field is the only required value. Optional fields
    help us disambiguate when PubMed's ESearch returns multiple
    candidates.
    """

    title: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description=(
            "Paper title to search PubMed for. We feed it to "
            "PubMed's ESearch endpoint with relevance sort and "
            "pick the top match."
        ),
    )
    first_author: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Optional first-author surname. When provided we "
            "prefer PubMed matches whose first author matches "
            "this string (case-insensitive)."
        ),
    )
    journal: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Optional journal name. When provided we prefer "
            "PubMed matches published in this journal. Used to "
            "disambiguate popular titles that span decades."
        ),
    )
    year: int | None = Field(
        default=None,
        ge=1800,
        le=2100,
        description=(
            "Optional publication year. When provided we prefer "
            "PubMed matches published in this exact year. If the "
            "user's typed title is common and the journal year is "
            "known from the PDF front matter (e.g. copyright "
            "notice), this can pin the right paper."
        ),
    )
