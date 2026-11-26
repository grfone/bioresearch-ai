"""
test_minimax_timeout.py

Tests for the MiniMax provider's configurable request timeout.

The timeout used to be hard-coded to 60 seconds with no way to
change it, and nothing passed the ``TIMEOUT`` setting to the
provider (``LLMFactory.create()`` constructs providers with no
arguments). For a reasoning model such as ``MiniMax-M3.1-Flash``,
whose ``generate`` call summarises the entire workspace corpus in
one request, 60 seconds is not enough on a 20-paper corpus: the
request times out, the orchestrator records the failure, and the
workspace lands in ERROR.

These tests pin the resolution order so the knob cannot regress:

1. an explicit constructor argument wins;
2. otherwise ``MINIMAX_TIMEOUT`` is used;
3. otherwise the 60-second default;
4. a malformed or non-positive value falls back to the default
   rather than taking the application down.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import pytest

from app.infrastructure.llm.minimax_provider import (
    DEFAULT_TIMEOUT_SECONDS,
    MinimaxProvider,
    _timeout_from_env,
)


def _timeout_of(provider: MinimaxProvider) -> float:
    """Return the timeout actually configured on the HTTP client."""
    timeout = provider._client.timeout
    if isinstance(timeout, (int, float)):
        return float(timeout)
    # httpx wraps a structured timeout in a Timeout object; a scalar
    # timeout is stored as its ``read`` component.
    read = timeout.read
    return float(read) if read is not None else DEFAULT_TIMEOUT_SECONDS


def test_default_timeout_is_sixty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing configured, the timeout is the 60-second default."""
    monkeypatch.delenv("MINIMAX_TIMEOUT", raising=False)
    assert _timeout_from_env() == DEFAULT_TIMEOUT_SECONDS == 60.0


def test_timeout_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MINIMAX_TIMEOUT`` configures the request timeout."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "300")
    assert _timeout_from_env() == 300.0

    provider = MinimaxProvider(api_key="dummy")
    assert _timeout_of(provider) == 300.0


def test_explicit_argument_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A constructor argument wins over the environment variable."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "300")
    provider = MinimaxProvider(api_key="dummy", timeout=45.0)
    assert _timeout_of(provider) == 45.0


def test_malformed_timeout_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-numeric value must not take the application down."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "not-a-number")
    assert _timeout_from_env() == DEFAULT_TIMEOUT_SECONDS


def test_non_positive_timeout_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero or negative timeout is meaningless; fall back."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "0")
    assert _timeout_from_env() == DEFAULT_TIMEOUT_SECONDS

    monkeypatch.setenv("MINIMAX_TIMEOUT", "-5")
    assert _timeout_from_env() == DEFAULT_TIMEOUT_SECONDS


def test_empty_timeout_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty value is treated as unset."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "   ")
    assert _timeout_from_env() == DEFAULT_TIMEOUT_SECONDS


def test_fractional_timeout_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fractional timeout is a valid float and is honoured."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "90.5")
    assert _timeout_from_env() == 90.5


def test_the_client_uses_the_resolved_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP client is built with the resolved timeout, not the default.

    This is the assertion that would have caught the original bug: the
    provider accepted a ``timeout`` argument, but nothing ever set it
    and nothing read it from the environment, so the client was always
    built with 60 seconds.
    """
    monkeypatch.setenv("MINIMAX_TIMEOUT", "300")
    provider = MinimaxProvider(api_key="dummy")
    assert _timeout_of(provider) != DEFAULT_TIMEOUT_SECONDS
    assert _timeout_of(provider) == 300.0
