"""
zhipu_provider.py

Zhipu GLM implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Zhipu GLM service exposes an OpenAI-compatible
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


class ZhipuProvider(OpenAICompatibleProvider):
    """
    Zhipu GLM provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``ZHIPU_API_KEY``
        Required: Zhipu GLM API key.
    ``ZHIPU_MODEL``
        Optional: model name override. Defaults to
        ``glm-4-plus``.
    """

    base_url = "https://open.bigmodel.cn/api/paas/v4"
    default_model = "glm-4-plus"
    api_key_env = "ZHIPU_API_KEY"
    model_env = "ZHIPU_MODEL"
