"""
search_literature.py

Application Use Case
--------------------

This module contains the SearchLiteratureUseCase, responsible for retrieving
scientific publications relevant to a user's research question.

The use case coordinates the application's business logic while remaining
independent of any specific literature provider (e.g. PubMed, Europe PMC,
Semantic Scholar).

By depending only on the LiteratureSearcher interface, different search
implementations can be introduced without modifying this use case.

Responsibilities
----------------
- Validate the incoming research question.
- Delegate the search operation to a LiteratureSearcher.
- Return the retrieved Paper entities.

This class intentionally contains very little logic. Complex retrieval
strategies (query expansion, ranking, retries, hybrid search, etc.) belong
inside the concrete search implementation or dedicated services.

Author
------
Guillermo Ramajo Fernández
"""

from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.interfaces.literature_searcher import LiteratureSearcher


class SearchLiteratureUseCase:
    """
    Retrieve scientific literature for a research question.

    This use case represents the first step in the BioResearch AI pipeline.

        Research Question
                │
                ▼
        SearchLiteratureUseCase
                │
                ▼
        LiteratureSearcher
                │
                ▼
           List[Paper]

    Notes
    -----
    The use case depends exclusively on the LiteratureSearcher abstraction.

    This means it can work with any search backend implementing the interface,
    including:

    - PubMed
    - Europe PMC
    - Semantic Scholar
    - Local document collections
    - Vector databases
    - Future MCP-based search providers

    The application layer never knows which implementation is being used.
    """

    def __init__(self, literature_searcher: LiteratureSearcher) -> None:
        """
        Initialize the use case.

        Parameters
        ----------
        literature_searcher : LiteratureSearcher
            Concrete implementation responsible for retrieving scientific
            publications.
        """
        self._literature_searcher = literature_searcher

    def execute(self, question: ResearchQuestion) -> list[Paper]:
        """
        Search scientific literature related to a research question.

        Parameters
        ----------
        question : ResearchQuestion
            User's scientific question.

        Returns
        -------
        list[Paper]
            List of retrieved scientific publications.

        Raises
        ------
        ValueError
            If the research question is empty.

        Notes
        -----
        At this stage the use case simply delegates the search operation.

        Future versions may include:

        - Query validation
        - Automatic keyword extraction
        - Query expansion
        - Search caching
        - Multi-source federation
        - Ranking and filtering
        - Telemetry and logging
        """

        if not question.question.strip():
            raise ValueError("Research question cannot be empty.")

        return self._literature_searcher.search(question)