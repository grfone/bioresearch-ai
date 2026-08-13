"""
gemini_provider.py

Google Gemini implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Google Gemini service exposes an OpenAI-compatible
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


class GeminiProvider(OpenAICompatibleProvider):
    """
    Google Gemini provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``GEMINI_API_KEY``
        Required: Google Gemini API key.
    ``GEMINI_MODEL``
        Optional: model name override. Defaults to
        ``gemini-2.0-flash``.
    """

    base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    default_model = "gemini-2.0-flash"
    api_key_env = "GEMINI_API_KEY"
    model_env = "GEMINI_MODEL"
