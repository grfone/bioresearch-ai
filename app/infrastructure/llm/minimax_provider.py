"""
minimax_provider.py

Infrastructure implementation of the LLMProvider interface for Minimax.

This module adapts the external Minimax API to the internal application
LLM abstraction. The application layer interacts only with the
LLMProvider interface and remains independent of vendor-specific
details.

Responsibilities
----------------
- Minimax API authentication
- HTTP communication
- Request formatting
- Response parsing and normalization
- Provider-specific error handling

It is intentionally unaware of:
- Research workflows
- Prompt engineering logic
- Scientific domain rules

Architecture
------------
Application Layer → LLMProvider Interface → MinimaxProvider → Minimax API

Configuration
-------------
Environment variables (loaded from .env):

MINIMAX_API_KEY
    Required: MiniMax API authentication token.

MINIMAX_MODEL
    Optional: Model name. Defaults to MiniMax-Text-01
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.models.llm_response import LLMResponse
from app.domain.models.prompt import Prompt


logger = logging.getLogger(__name__)

#: Default HTTP timeout in seconds when ``MINIMAX_TIMEOUT`` is unset.
DEFAULT_TIMEOUT_SECONDS = 60.0


def _timeout_from_env() -> float | None:
    """
    Read the request timeout from ``MINIMAX_TIMEOUT``.

    Returns
    -------
    float | None
        The timeout in seconds, or ``None`` when the variable is
        unset — the caller then falls back to the shared ``TIMEOUT``
        setting or the provider's own default.

        A malformed or non-positive value logs a warning and returns
        ``None`` rather than raising: a bad value must not take the
        whole application down at import time.
    """
    raw = os.getenv("MINIMAX_TIMEOUT")
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "MINIMAX_TIMEOUT=%r is not a number; ignoring it.",
            raw,
        )
        return None
    if value <= 0:
        logger.warning(
            "MINIMAX_TIMEOUT=%r is not positive; ignoring it.",
            raw,
        )
        return None
    return value


class MinimaxProvider(LLMProvider):
    """
    Concrete implementation of the LLMProvider interface using Minimax.

    This class encapsulates all Minimax-specific details and provides
    a clean contract to the rest of the application.
    """
    BaseURL = "https://api.minimax.io/anthropic"
    ChatPath = "/v1/messages"

    ENDPOINT = BaseURL + ChatPath
    # MiniMax-M3.1-Flash replaces the retired MiniMax-M3: cheaper per token
    # ($0.15/$0.60 vs $0.30/$1.20 per 1M) and a flat rate at any prompt
    # length, whereas M3's rate doubles above 512K input. The MINIMAX_MODEL
    # env var overrides this default when set.
    DEFAULT_MODEL = "MiniMax-M3.1-Flash"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """
        Initialize the Minimax provider.

        Parameters
        ----------
        api_key : str | None
            MiniMax API key. If not provided, it will be loaded from
            the MINIMAX_API_KEY environment variable (including .env file).
        model : str | None
            Model identifier. Falls back to MINIMAX_MODEL env var or default.
        timeout : float | None
            HTTP request timeout in seconds. When omitted, the
            ``MINIMAX_TIMEOUT`` environment variable is used
            (default: 60 seconds).

            The timeout needs to be generous for this provider:
            ``MiniMax-M3.1-Flash`` is a *reasoning* model — it emits
            a ``thinking`` block before the answer — and the
            ``generate`` pipeline summarises the whole workspace
            corpus in one call. A 20-paper corpus routinely exceeds
            the 60-second default, and the resulting
            ``httpx.ReadTimeout`` surfaces as "Unable to connect to
            the MiniMax API", which sends the workspace to ERROR.

        Raises
        ------
        ValueError
            If no API key is found.
        """
        # Get the directory where THIS file (minimax_provider.py) is located
        current_file_dir = Path(__file__).resolve().parent  # .../app/infrastructure/llm/
        # Go up 3 levels to reach the project root
        project_root = current_file_dir.parent.parent.parent  # .../bioresearch-ai/
        # Define the path to .env
        env_path = project_root / '.env'
        # Load the specific .env file
        load_dotenv(dotenv_path=env_path)

        self._api_key = api_key or os.getenv("MINIMAX_API_KEY")

        if not self._api_key:
            raise ValueError(
                f"MINIMAX_API_KEY environment variable is missing. "
                f"Tried to load .env from: {env_path}. "
                "Please check your .env file."
            )

        self._model = model or os.getenv("MINIMAX_MODEL", self.DEFAULT_MODEL)

        # The timeout is configurable via ``MINIMAX_TIMEOUT`` (the
        # provider-specific environment variable, which mirrors the
        # ``OLLAMA_TIMEOUT`` convention already used by the Ollama
        # provider). It exists because the 60-second default is too
        # short for the corpus-summarisation call.
        #
        # Resolution order: the provider-specific environment
        # variable wins over the explicit constructor argument,
        # because it is the more specific configuration. The
        # constructor argument is the shared ``TIMEOUT`` setting,
        # which applies to every provider.
        env_timeout = _timeout_from_env()
        if env_timeout is not None:
            self._timeout = env_timeout
        elif timeout is not None:
            self._timeout = float(timeout)
        else:
            self._timeout = DEFAULT_TIMEOUT_SECONDS

        self._client = httpx.Client(
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    def generate(self, prompt: Prompt) -> LLMResponse:
        """
        Generate a completion using the MiniMax Messages API.

        Parameters
        ----------
        prompt
            Structured prompt.

        Returns
        -------
        LLMResponse
            Normalized language model response.

        Raises
        ------
        RuntimeError
            If the request fails or the response cannot be parsed.
        """

        payload: dict[str, Any] = {
            "model": self._model,
            "system": prompt.system,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"{prompt.user}\n\n"
                        f"{prompt.context}"
                    ),
                }
            ],
            "temperature": prompt.temperature,
        }

        start = time.perf_counter()

        try:
            response = self._client.post(
                self.ENDPOINT,
                json=payload,
            )

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"MiniMax returned HTTP {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc

        except httpx.RequestError as exc:
            raise RuntimeError(
                "Unable to connect to the MiniMax API."
            ) from exc

        latency = time.perf_counter() - start

        data: dict[str, Any] = response.json()

        try:

            content_blocks = data["content"]

            text = "\n".join(
                block["text"]
                for block in content_blocks
                if block.get("type") == "text"
            )

            usage = data.get("usage", {})

            prompt_tokens = usage.get(
                "input_tokens",
                0,
            )

            completion_tokens = usage.get(
                "output_tokens",
                0,
            )

            total_tokens = (
                prompt_tokens +
                completion_tokens
            )

            finish_reason = data.get(
                "stop_reason",
                "end_turn",
            )

        except Exception as exc:
            raise RuntimeError(
                "Unexpected response received from MiniMax.\n\n"
                f"{data}"
            ) from exc

        return LLMResponse(
            content=text,
            model=data.get("model", self._model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
            latency_seconds=latency,
        )

    def close(self) -> None:
        """
        Release the underlying HTTP resources.
        """

        self._client.close()