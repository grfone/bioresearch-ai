"""
iflytek_provider.py

iFlytek Spark implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The iFlytek Spark service exposes an OpenAI-compatible
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


class IflytekProvider(OpenAICompatibleProvider):
    """
    iFlytek Spark provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``IFLYTEK_API_KEY``
        Required: iFlytek Spark API key.
    ``IFLYTEK_MODEL``
        Optional: model name override. Defaults to
        ``generalv3.5``.
    """

    base_url = "https://spark-api-open.xf-yun.com/v1"
    default_model = "generalv3.5"
    api_key_env = "IFLYTEK_API_KEY"
    model_env = "IFLYTEK_MODEL"
