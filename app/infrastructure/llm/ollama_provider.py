"""
ollama_provider.py

Ollama implementation of the LLMProvider interface.

Purpose
-------
This module implements the adapter responsible for communicating with
locally hosted language models through Ollama. BioResearch AI uses
Ollama for the "Local" LLM option exposed by the bootstrap GUI —
no API key required, fully self-hosted, privacy-preserving.

The provider talks to Ollama's OpenAI-compatible endpoint at
``${OLLAMA_BASE_URL}/v1/chat/completions`` so the existing OpenAI
client library can be reused. This means the provider behaves
identically to the OpenAI provider from the application's point of
view; the only difference is the base URL and the absence of an
API key.

Configuration
-------------
The provider reads the following environment variables:

- ``OLLAMA_BASE_URL`` (default: ``http://localhost:11434``)
- ``OLLAMA_MODEL`` (default: ``deepseek-coder-v2-lite-instruct``)
- ``OLLAMA_TIMEOUT`` (default: ``120`` seconds — local models are
  slower than cloud APIs and the summarisation / comparison prompts
  push the token count)
- ``OLLAMA_NUM_GPU`` (default: ``-1`` meaning "use all available")

The bootstrap script detects hardware and sets ``OLLAMA_MODEL`` to
the appropriate quantized DeepSeek model.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import os
import time
from typing import Any

from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt
from app.infrastructure.llm.base_provider import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """
    Ollama implementation of the LLM provider interface.

    Communicates with a local Ollama daemon over the OpenAI-compatible
    chat completions endpoint. No API key is required.
    """

    def __init__(self) -> None:
        super().__init__()
        self._base_url = (
            os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")
        self._model = os.environ.get(
            "OLLAMA_MODEL", "deepseek-coder-v2-lite-instruct"
        )
        self._timeout = int(os.environ.get("OLLAMA_TIMEOUT", "120"))
        # Lazy import so the provider can be instantiated even when
        # the OpenAI client is not installed (it is shipped via the
        # ``openai`` package on conda).
        self._client = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        """Return the OpenAI-compatible client, instantiating on demand."""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=f"{self._base_url}/v1",
                api_key="ollama",  # any non-empty value; Ollama ignores it
                timeout=self._timeout,
            )
        return self._client

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: Prompt,
    ) -> LLMResponse:
        """
        Generate a completion using the local Ollama model.

        Parameters
        ----------
        prompt : Prompt
            Provider-independent prompt describing the task.

        Returns
        -------
        LLMResponse
            Normalized response.

        Raises
        ------
        RuntimeError
            If the Ollama daemon is unreachable, the model is missing,
            or the request fails for any other reason.
        """
        self.validate_prompt(prompt)

        user_content = prompt.user
        if prompt.context:
            user_content = f"{user_content}\n\n{prompt.context}"

        messages: list[dict[str, Any]] = []
        if prompt.system:
            messages.append({"role": "system", "content": prompt.system})
        messages.append({"role": "user", "content": user_content})

        start = time.monotonic()
        try:
            response = self._get_client().chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=prompt.temperature,
                max_tokens=prompt.max_tokens or 2048,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Local Ollama request failed: {exc}. "
                "Is the Ollama service running? "
                "Run `docker compose ps` to check."
            ) from exc

        latency = time.monotonic() - start

        # The OpenAI client returns a Pydantic object; normalise it
        # to the project's LLMResponse value type.
        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = (
            getattr(usage, "completion_tokens", 0) if usage else 0
        )
        total_tokens = (
            getattr(usage, "total_tokens", 0) if usage else 0
        )

        result = LLMResponse(
            content=content,
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=(
                response.choices[0].finish_reason
                if response.choices
                else "stop"
            ),
            latency_seconds=latency,
        )
        self.validate_response(result)
        return result
