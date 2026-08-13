"""
cohere_provider.py

Cohere implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Cohere service exposes an OpenAI-compatible
``/chat/completions`` endpoint so the only differences are the
base URL, the default model, and the environment variable that
holds the API key.

Author
------
Guillermo Ramajo Fernández
"""


from __future__ import annotations

from app.infrastructure.llm._openai_compatible import (
    OpenAICompatibleProvider,
)


class CohereProvider(OpenAICompatibleProvider):
    """
    Cohere provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``COHERE_API_KEY``
        Required: Cohere API key.
    ``COHERE_MODEL``
        Optional: model name override. Defaults to
        ``command-r-plus``.
    """

    base_url = "https://api.cohere.ai/compatibility/v1"
    default_model = "command-r-plus"
    api_key_env = "COHERE_API_KEY"
    model_env = "COHERE_MODEL"
