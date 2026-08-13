"""
health.py

Application health monitoring endpoints.

Purpose
-------
Provides lightweight endpoints used to verify that the BioResearch AI
API is running correctly.

These endpoints intentionally avoid database, LLM, and external API
dependencies.

Author
------
Guillermo Ramajo Fernández
"""

from fastapi import APIRouter


router = APIRouter(
    tags=["System"],
)


@router.get(
    "/health",
    summary="Health check",
)
def health_check() -> dict[str, str]:
    """
    Verify API availability.

    Returns
    -------
    dict[str, str]
        Health status.
    """

    return {
        "status": "healthy",
    }