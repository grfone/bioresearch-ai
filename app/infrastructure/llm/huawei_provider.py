"""
huawei_provider.py

Huawei Pangu implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Huawei Pangu service exposes an OpenAI-compatible
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


class HuaweiProvider(OpenAICompatibleProvider):
    """
    Huawei Pangu provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``HUAWEI_PANGU_API_KEY``
        Required: Huawei Pangu API key.
    ``HUAWEI_MODEL``
        Optional: model name override. Defaults to
        ``pangu-4``.
    """

    base_url = "https://pangu.ap-southeast-1.myhuaweicloud.com/v1"
    default_model = "pangu-4"
    api_key_env = "HUAWEI_PANGU_API_KEY"
    model_env = "HUAWEI_MODEL"
