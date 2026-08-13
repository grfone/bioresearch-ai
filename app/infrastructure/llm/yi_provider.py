"""
yi_provider.py

01.AI Yi implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The 01.AI Yi service exposes an OpenAI-compatible
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


class YiProvider(OpenAICompatibleProvider):
    """
    01.AI Yi provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``YI_API_KEY``
        Required: 01.AI Yi API key.
    ``YI_MODEL``
        Optional: model name override. Defaults to
        ``yi-large``.
    """

    base_url = "https://api.01.ai/v1"
    default_model = "yi-large"
    api_key_env = "YI_API_KEY"
    model_env = "YI_MODEL"
