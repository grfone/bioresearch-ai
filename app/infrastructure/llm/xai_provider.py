"""
xai_provider.py

xAI Grok implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The xAI Grok service exposes an OpenAI-compatible
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


class XaiProvider(OpenAICompatibleProvider):
    """
    xAI Grok provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``XAI_API_KEY``
        Required: xAI Grok API key.
    ``XAI_MODEL``
        Optional: model name override. Defaults to
        ``grok-3-mini``.
    """

    base_url = "https://api.x.ai/v1"
    default_model = "grok-3-mini"
    api_key_env = "XAI_API_KEY"
    model_env = "XAI_MODEL"
