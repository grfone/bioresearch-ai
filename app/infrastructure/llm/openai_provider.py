"""
openai_provider.py

OpenAI implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The OpenAI service exposes an OpenAI-compatible
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


class OpenAIProvider(OpenAICompatibleProvider):
    """
    OpenAI provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``OPENAI_API_KEY``
        Required: OpenAI API key.
    ``OPENAI_MODEL``
        Optional: model name override. Defaults to
        ``gpt-4.1-mini``.
    """

    base_url = "https://api.openai.com/v1"
    default_model = "gpt-4.1-mini"
    api_key_env = "OPENAI_API_KEY"
    model_env = "OPENAI_MODEL"
