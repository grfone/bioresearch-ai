"""
alibaba_provider.py

Alibaba Qwen implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Alibaba Qwen service exposes an OpenAI-compatible
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


class AlibabaProvider(OpenAICompatibleProvider):
    """
    Alibaba Qwen provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``DASHSCOPE_API_KEY``
        Required: Alibaba Qwen API key.
    ``ALIBABA_MODEL``
        Optional: model name override. Defaults to
        ``qwen-plus``.
    """

    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model = "qwen-plus"
    api_key_env = "DASHSCOPE_API_KEY"
    model_env = "ALIBABA_MODEL"
