"""
client.py

Low-level client for communicating with the PubMed (NCBI Entrez) API.

Purpose
-------
This module implements the infrastructure adapter responsible for
communicating with the PubMed (NCBI Entrez) API.

Following Clean Architecture principles, this class is the only
component responsible for performing network communication with the
NCBI services. It deliberately returns raw PubMed records rather than
domain entities, leaving the translation into domain objects to the
PubMedMapper.

Architecture
------------

Application
      │
      ▼
PubMedProvider
      │
      ▼
PubMedClient
      │
      ▼
NCBI Entrez API

Responsibilities
----------------
- Execute PubMed search queries.
- Retrieve publication metadata.
- Configure the Entrez client.
- Handle infrastructure-level communication.
- Return raw PubMed records.

Non-responsibilities
--------------------
This class does NOT:

- Create domain entities.
- Parse publication metadata.
- Rank search results.
- Summarize literature.
- Generate reports.
- Perform scientific reasoning.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.error import HTTPError, URLError

from Bio import Entrez


class PubMedClient:
    """
    Low-level client for the PubMed API.

    This class wraps Biopython's Entrez module while exposing a clean,
    provider-independent interface to the rest of the infrastructure
    layer.

    Notes
    -----
    The client intentionally returns raw PubMed records. Conversion into
    domain entities is delegated to the PubMedMapper.
    """

    def __init__(
        self,
        email: str,
        api_key: str | None = None,
    ) -> None:
        """
        Initialize the PubMed client.

        Parameters
        ----------
        email
            E-mail address required by the NCBI Entrez API.

        api_key
            Optional PubMed API key used to increase rate limits.
        """

        self._email = email
        self._api_key = api_key

        self._configure_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[str]:
        """
        Search PubMed for publications matching a query.

        Parameters
        ----------
        query
            PubMed-compatible search query.

        limit
            Maximum number of PMIDs to retrieve.

        Returns
        -------
        list[str]
            List of PubMed identifiers.

        Raises
        ------
        ValueError
            If the query is empty or the limit is invalid.

        RuntimeError
            If the PubMed request fails.
        """

        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if limit <= 0:
            raise ValueError("Limit must be greater than zero.")

        self._configure_client()

        try:
            with Entrez.esearch(
                db="pubmed",
                term=query,
                retmax=limit,
                sort="relevance",
            ) as handle:
                response = Entrez.read(handle)

            return response["IdList"]

        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError(
                "Failed to search PubMed."
            ) from exc

    def fetch(
        self,
        identifiers: Sequence[str],
    ) -> list[dict[str, Any]]:
        """
        Retrieve publication metadata from PubMed.

        Parameters
        ----------
        identifiers
            Collection of PubMed identifiers (PMIDs).

        Returns
        -------
        list[dict[str, Any]]
            Raw publication records returned by PubMed.

        Raises
        ------
        RuntimeError
            If the metadata request fails.
        """

        if not identifiers:
            return []

        self._configure_client()

        try:
            with Entrez.efetch(
                db="pubmed",
                id=",".join(identifiers),
                rettype="abstract",
                retmode="xml",
            ) as handle:
                records = Entrez.read(handle)

            return records["PubmedArticle"]

        except (HTTPError, URLError, OSError) as exc:
            raise RuntimeError(
                "Failed to retrieve publications from PubMed."
            ) from exc

    def health_check(self) -> bool:
        """
        Verify connectivity with the PubMed service.

        Returns
        -------
        bool
            True if PubMed is reachable, otherwise False.
        """

        try:
            self.search("cancer", limit=1)
            return True

        except RuntimeError:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _configure_client(self) -> None:
        """
        Configure the underlying Biopython Entrez client.

        Notes
        -----
        Entrez stores its configuration in module-level global variables.
        This method is intentionally idempotent and is invoked before each
        request to ensure the client remains correctly configured even if
        another component modifies the global state.
        """

        Entrez.email = self._email

        if self._api_key:
            Entrez.api_key = self._api_key