"""
_openai_compatible.py

Shared base class for OpenAI-compatible LLM providers.

Purpose
-------
The vast majority of modern LLM providers expose an OpenAI-compatible
``/chat/completions`` endpoint. This module implements the workhorse
adapter that talks to all of them through a single code path.

The infrastructure layer's concrete provider classes (e.g.
``AlibabaProvider``, ``DeepSeekProvider``, ``XaiProvider``) are thin
subclasses that simply pass a ``base_url``, ``model``, and
``api_key_env`` to ``OpenAICompatibleProvider``. The bootstrap
catalog (``app.application.services.llm_provider_catalog``) is
the single source of truth for what those values are.

The OpenAI Python client is used under the hood. We instantiate
it lazily so the provider can be imported even when the
``openai`` package is not installed in the dev environment
(it ships in the conda runtime).

Architectural choice
--------------------
Rather than writing 18 bespoke HTTP adapters, we capture the
common 80% of the contract — POST a JSON body with
``{model, messages, temperature, max_tokens}`` and parse
``{choices[0].message.content, usage}`` — and let the openai
client handle the rest. Providers that don't fit this contract
(Anthropic, MiniMax, AzureOpenAI) keep their bespoke classes.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt


# Where the .env file lives. We load it lazily so the provider is
# usable even when the bootstrap hasn't been run yet.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class OpenAICompatibleProvider(LLMProvider):
    """
    Provider for any LLM service that exposes an OpenAI-compatible
    ``/chat/completions`` endpoint.

    Concrete subclasses must at minimum set the class-level
    ``base_url`` and ``default_model`` attributes. The constructor
    picks up the API key from ``api_key_env`` (or accepts it
    explicitly).

    Parameters
    ----------
    api_key : str | None
        API key. If ``None`` it is read from the environment
        variable ``api_key_env``. ``bootstrap.py`` always passes
        the key explicitly so the GUI value is what wins.

    model : str | None
        Model name. Defaults to ``default_model`` or the
        ``<PROVIDER>_MODEL`` environment variable.

    timeout : float
        HTTP timeout in seconds.

    base_url : str | None
        Override the class-level base URL. Useful for
        user-defined custom endpoints (e.g. a self-hosted
        vLLM or a private Azure deployment).

    api_key_env : str | None
        Override the API key environment variable. Useful when
        the same provider class is reused across multiple
        environments.

    extra_headers : dict[str, str] | None
        Additional headers to set on every request. Some
        providers (e.g. Baidu Qianfan) need a custom header
        in addition to the Authorization header.
    """

    # Subclasses must override these.
    base_url: str = ""
    default_model: str = ""
    api_key_env: str = ""

    # Optional env var for the model name.
    model_env: str = ""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0,
        base_url: Optional[str] = None,
        api_key_env: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> None:
        # Lazily load the .env file so the provider is usable in
        # both dev and production. The bootstrap script writes
        # values to .env; users who set env vars directly do not
        # need the file.
        self._load_env()

        self._api_key = api_key or (
            os.getenv(api_key_env or self.api_key_env) if (api_key_env or self.api_key_env) else ""
        )
        self._model = model or os.getenv(
            self.model_env or "",
            self.default_model,
        )
        self._base_url = (
            base_url
            or self.base_url
            or os.getenv(f"{self.api_key_env}_BASE_URL".replace("_API_KEY", "_BASE_URL"), "")
        )
        self._extra_headers = dict(extra_headers or {})
        self._timeout = timeout
        self._client = None  # lazy

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_env(self) -> None:
        """Load the project .env file if it exists."""
        try:
            from dotenv import load_dotenv

            env_path = _PROJECT_ROOT / ".env"
            if env_path.exists():
                load_dotenv(env_path)
        except ImportError:
            # python-dotenv is not required; env vars may already
            # be in the environment.
            pass

    def _get_client(self):
        """Return the OpenAI client, instantiating on demand."""
        if self._client is None:
            from openai import OpenAI

            if not self._base_url:
                raise RuntimeError(
                    f"{type(self).__name__} has no base_url configured. "
                    "Set the class-level attribute or pass base_url=..."
                )
            self._client = OpenAI(
                api_key=self._api_key or "missing",
                base_url=self._base_url,
                timeout=self._timeout,
                default_headers=self._extra_headers or None,
            )
        return self._client

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    def generate(self, prompt: Prompt) -> LLMResponse:
        """
        Generate a completion using the OpenAI-compatible API.

        Parameters
        ----------
        prompt : Prompt
            Provider-independent prompt.

        Returns
        -------
        LLMResponse
            Normalized response.

        Raises
        ------
        RuntimeError
            On any upstream failure. The error message includes
            the provider slug and HTTP status so the bootstrap
            probe can show an actionable hint.
        """
        if not self._api_key:
            raise RuntimeError(
                f"{type(self).__name__} requires an API key. "
                f"Set it in the bootstrap GUI or pass api_key=..."
            )

        messages: list[dict[str, Any]] = []
        if prompt.system:
            messages.append({"role": "system", "content": prompt.system})
        user_content = prompt.user
        if prompt.context:
            user_content = f"{user_content}\n\n{prompt.context}"
        messages.append({"role": "user", "content": user_content})

        max_tokens = prompt.max_tokens or 2048
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": prompt.temperature,
            "max_tokens": max_tokens,
        }
        # Some providers reject stream options. We always send
        # stream=False explicitly so the response is predictable.
        payload["stream"] = False

        start = time.monotonic()
        try:
            response = self._get_client().chat.completions.create(**payload)
        except Exception as exc:
            raise RuntimeError(
                f"{type(self).__name__} request failed: {exc}"
            ) from exc
        latency = time.monotonic() - start

        if not response.choices:
            raise RuntimeError(
                f"{type(self).__name__} returned an empty response. "
                f"Raw: {response!r}"
            )

        content = response.choices[0].message.content or ""

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = (
            getattr(usage, "completion_tokens", 0) if usage else 0
        )
        total_tokens = (
            getattr(usage, "total_tokens", 0) if usage else 0
        )

        finish_reason = (
            response.choices[0].finish_reason
            if response.choices
            else "stop"
        )

        return LLMResponse(
            content=content,
            model=getattr(response, "model", self._model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason or "stop",
            latency_seconds=latency,
        )
