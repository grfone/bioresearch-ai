"""
search_source.py

Enumeration of supported scientific literature sources.

Purpose
-------
BioResearch AI is designed to retrieve scientific publications from
multiple sources.

Although PubMed will be the first implementation, the architecture
supports additional providers without modifying the application layer.

This enumeration identifies the supported literature sources.

Author
------
Guillermo Ramajo Fernández
"""

from enum import StrEnum


class SearchSourceEnum(StrEnum):
    """
    Supported scientific literature sources.
    """

    PUBMED = "pubmed"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    EUROPE_PMC = "europe_pmc"
    BIORXIV = "biorxiv"