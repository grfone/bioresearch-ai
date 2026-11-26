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

Resolution order for the MiniMax timeout:

1. ``MINIMAX_TIMEOUT`` — the provider-specific environment variable.
   It wins over the constructor argument because it is the more
   specific configuration.
2. the ``timeout`` constructor argument — the *shared* ``TIMEOUT``
   setting, applied to every provider.
3. 60 seconds — this provider's own default.

A malformed or non-positive ``MINIMAX_TIMEOUT`` is ignored (with a
warning) rather than raising: a bad value must not take the whole
application down.

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


@pytest.fixture(autouse=True)
def _isolate_from_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the provider from re-reading the repo's ``.env``.

    ``MinimaxProvider.__init__`` calls ``load_dotenv()``, which
    injects ``MINIMAX_TIMEOUT`` from the developer's local ``.env``
    into ``os.environ`` -- permanently, for the rest of the test
    session. Without this fixture the "default timeout" test reads
    whatever the operator happens to have configured locally.
    """
    monkeypatch.setattr(
        "app.infrastructure.llm.minimax_provider.load_dotenv",
        lambda *args, **kwargs: None,
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
    assert _timeout_from_env() is None

    provider = MinimaxProvider(api_key="dummy")
    assert _timeout_of(provider) == DEFAULT_TIMEOUT_SECONDS == 60.0


def test_timeout_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MINIMAX_TIMEOUT`` configures the request timeout."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "300")
    assert _timeout_from_env() == 300.0

    provider = MinimaxProvider(api_key="dummy")
    assert _timeout_of(provider) == 300.0


def test_environment_beats_the_constructor_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider-specific variable wins over the shared setting.

    The constructor argument carries the shared ``TIMEOUT`` setting,
    which applies to every provider. ``MINIMAX_TIMEOUT`` is the more
    specific configuration, so it takes precedence.
    """
    monkeypatch.setenv("MINIMAX_TIMEOUT", "900")
    provider = MinimaxProvider(api_key="dummy", timeout=300.0)
    assert _timeout_of(provider) == 900.0


def test_constructor_argument_applies_without_a_specific_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared setting is used when no MiniMax-specific one exists."""
    monkeypatch.delenv("MINIMAX_TIMEOUT", raising=False)
    provider = MinimaxProvider(api_key="dummy", timeout=300.0)
    assert _timeout_of(provider) == 300.0


def test_malformed_timeout_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-numeric value must not take the application down."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "not-a-number")
    assert _timeout_from_env() is None

    provider = MinimaxProvider(api_key="dummy")
    assert _timeout_of(provider) == DEFAULT_TIMEOUT_SECONDS


def test_non_positive_timeout_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero or negative timeout is meaningless; fall back."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "0")
    assert _timeout_from_env() is None

    monkeypatch.setenv("MINIMAX_TIMEOUT", "-5")
    assert _timeout_from_env() is None


def test_empty_timeout_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty value is treated as unset."""
    monkeypatch.setenv("MINIMAX_TIMEOUT", "   ")
    assert _timeout_from_env() is None


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
