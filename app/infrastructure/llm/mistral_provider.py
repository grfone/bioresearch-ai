"""
mistral_provider.py

Mistral AI implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Mistral AI service exposes an OpenAI-compatible
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


class MistralProvider(OpenAICompatibleProvider):
    """
    Mistral AI provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``MISTRAL_API_KEY``
        Required: Mistral AI API key.
    ``MISTRAL_MODEL``
        Optional: model name override. Defaults to
        ``mistral-large-latest``.
    """

    base_url = "https://api.mistral.ai/v1"
    default_model = "mistral-large-latest"
    api_key_env = "MISTRAL_API_KEY"
    model_env = "MISTRAL_MODEL"
