"""
test_llm_timeout_config.py

Tests for the shared ``TIMEOUT`` setting reaching the LLM providers.

``LLMSettings.timeout`` (the ``TIMEOUT`` environment variable) was
documented as the request timeout for LLM calls but never reached a
provider: ``LLMFactory.create()`` constructed providers with no
arguments, so every provider used its own hard-coded default and
the setting was dead config.

These tests pin the resolution rules:

1. ``TIMEOUT`` unset -> each provider keeps its own default
   (60s for the hosted HTTP APIs, 120s for the local Ollama
   provider). Nothing changes for an operator who never touched it.
2. ``TIMEOUT`` set -> it applies to every provider.
3. A provider-specific environment variable (``MINIMAX_TIMEOUT``,
   ``OLLAMA_TIMEOUT``) still wins, because it is the more specific
   configuration.
4. The factory never raises ``TypeError`` on a provider that does
   not accept a ``timeout`` argument.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import pytest

from app.config.llm import LLMSettings
from app.core.enums.llm_provider import LLMProviderEnum
from app.infrastructure.llm.llm_factory import LLMFactory


#: Providers whose constructor takes a ``timeout`` argument.
_HOSTED = [
    LLMProviderEnum.OPENAI,
    LLMProviderEnum.ANTHROPIC,
    LLMProviderEnum.GEMINI,
    LLMProviderEnum.MISTRAL,
    LLMProviderEnum.DEEPSEEK,
    LLMProviderEnum.MINIMAX,
]


@pytest.fixture(autouse=True)
def _isolate_from_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the providers from re-reading the repo's ``.env``.

    ``MinimaxProvider.__init__`` calls ``load_dotenv()``, which
    injects the developer's local ``MINIMAX_TIMEOUT`` into
    ``os.environ`` for the rest of the session. Without this fixture
    the tests would read the operator's local configuration instead
    of the values they set up.
    """
    monkeypatch.setattr(
        "app.infrastructure.llm.minimax_provider.load_dotenv",
        lambda *args, **kwargs: None,
    )
    # The OpenAI-compatible family's ``_load_env()`` loads the whole
    # repository ``.env`` into ``os.environ`` -- including
    # ``MINIMAX_TIMEOUT``, which then correctly outranks the shared
    # setting for that one provider. Neutralise it so these tests
    # measure the shared setting and not the developer's local file.
    monkeypatch.setattr(
        "app.infrastructure.llm._openai_compatible."
        "OpenAICompatibleProvider._load_env",
        lambda self: None,
    )
    # The MiniMax provider refuses to construct without a key. The
    # developer's local ``.env`` supplies one; a CI runner has no
    # ``.env`` at all. Give it a dummy so the test is hermetic.
    monkeypatch.setenv("MINIMAX_API_KEY", "dummy")


def _clear_timeout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every timeout variable that could leak between tests."""
    for name in (
        "TIMEOUT",
        "MINIMAX_TIMEOUT",
        "OLLAMA_TIMEOUT",
        "OPENAI_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)


def _client_timeout(provider) -> float:
    """Return the timeout a provider actually configured."""
    client = getattr(provider, "_client", None)
    if client is not None:
        timeout = client.timeout
        if isinstance(timeout, (int, float)):
            return float(timeout)
        read = timeout.read
        return float(read) if read is not None else 0.0
    # The OpenAI-compatible providers build their client lazily.
    return float(getattr(provider, "_timeout", 0.0))


def _provider_timeout(provider) -> float:
    """Return the timeout a provider stored, whatever its type."""
    return float(getattr(provider, "_timeout", 0.0))


# ---------------------------------------------------------------------------
# The setting itself
# ---------------------------------------------------------------------------


def test_timeout_unset_leaves_providers_on_their_own_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset ``TIMEOUT`` must not change any provider's behaviour.

    This is the important safety property: the shared setting only
    overrides a provider's default when the operator asks for it.
    """
    _clear_timeout_env(monkeypatch)
    settings = LLMSettings()

    assert settings.provider_timeout is None

    hosted = LLMFactory.create(LLMProviderEnum.OPENAI)
    assert _client_timeout(hosted) == 60.0

    ollama = LLMFactory.create(LLMProviderEnum.OLLAMA)
    assert _provider_timeout(ollama) == 120


def test_timeout_set_applies_to_every_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TIMEOUT`` reaches the hosted providers and the local one."""
    _clear_timeout_env(monkeypatch)
    monkeypatch.setenv("TIMEOUT", "300")
    settings = LLMSettings()

    assert settings.provider_timeout == 300.0

    for slug in _HOSTED:
        provider = LLMFactory.create(
            slug, timeout=settings.provider_timeout
        )
        assert _client_timeout(provider) == 300.0, (
            f"{slug.value} did not receive the shared timeout"
        )

    ollama = LLMFactory.create(
        LLMProviderEnum.OLLAMA, timeout=settings.provider_timeout
    )
    assert _provider_timeout(ollama) == 300


def test_provider_timeout_is_none_when_not_explicitly_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``provider_timeout`` is ``None`` when ``TIMEOUT`` is absent."""
    _clear_timeout_env(monkeypatch)
    assert LLMSettings().provider_timeout is None


# ---------------------------------------------------------------------------
# Precedence: the specific beats the general
# ---------------------------------------------------------------------------


def test_provider_specific_env_wins_over_the_shared_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MINIMAX_TIMEOUT`` beats the shared ``TIMEOUT``."""
    _clear_timeout_env(monkeypatch)
    monkeypatch.setenv("TIMEOUT", "300")
    monkeypatch.setenv("MINIMAX_TIMEOUT", "900")
    settings = LLMSettings()

    provider = LLMFactory.create(
        LLMProviderEnum.MINIMAX, timeout=settings.provider_timeout
    )
    assert _client_timeout(provider) == 900.0


def test_ollama_specific_env_wins_over_the_shared_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OLLAMA_TIMEOUT`` beats the shared ``TIMEOUT``."""
    _clear_timeout_env(monkeypatch)
    monkeypatch.setenv("TIMEOUT", "300")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "900")
    settings = LLMSettings()

    provider = LLMFactory.create(
        LLMProviderEnum.OLLAMA, timeout=settings.provider_timeout
    )
    assert _provider_timeout(provider) == 900


def test_shared_setting_applies_when_no_specific_env_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With only ``TIMEOUT`` set, MiniMax uses it."""
    _clear_timeout_env(monkeypatch)
    monkeypatch.setenv("TIMEOUT", "412")
    settings = LLMSettings()

    provider = LLMFactory.create(
        LLMProviderEnum.MINIMAX, timeout=settings.provider_timeout
    )
    assert _client_timeout(provider) == 412.0


# ---------------------------------------------------------------------------
# The factory is defensive
# ---------------------------------------------------------------------------


def test_factory_never_raises_on_a_provider_without_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider without a ``timeout`` parameter is skipped, not fatal."""

    class NoTimeoutProvider:
        def __init__(self) -> None:
            self.called = True

    monkeypatch.setitem(
        LLMFactory.PROVIDERS, LLMProviderEnum.OPENAI, NoTimeoutProvider
    )
    try:
        provider = LLMFactory.create(LLMProviderEnum.OPENAI, timeout=300.0)
        assert getattr(provider, "called", False) is True
    finally:
        LLMFactory.PROVIDERS.pop(LLMProviderEnum.OPENAI, None)


def test_factory_without_a_timeout_keeps_provider_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``timeout=None`` changes nothing."""
    _clear_timeout_env(monkeypatch)
    provider = LLMFactory.create(LLMProviderEnum.OPENAI)
    assert _client_timeout(provider) == 60.0


def test_every_catalog_provider_accepts_a_timeout() -> None:
    """Every provider in the catalog can be given a timeout.

    This is the anti-drift guard: a provider added later without a
    ``timeout`` parameter would silently keep its own default, so we
    assert the capability explicitly.
    """
    for slug, provider_class in LLMFactory.PROVIDERS.items():
        provider = provider_class()
        assert hasattr(provider, "_timeout"), (
            f"{slug.value} has no _timeout attribute"
        )


def test_openai_timeout_is_not_the_variable_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OPENAI_TIMEOUT`` has never been read; the alias is ``TIMEOUT``.

    ``.env.example`` documented ``OPENAI_TIMEOUT`` for years. The
    settings class sets no ``env_prefix``, so the literal variable
    name is ``TIMEOUT`` -- ``OPENAI_TIMEOUT`` did nothing.
    """
    _clear_timeout_env(monkeypatch)
    monkeypatch.setenv("OPENAI_TIMEOUT", "999")
    settings = LLMSettings()
    assert settings.timeout == 60, "OPENAI_TIMEOUT must not be read"
    assert settings.provider_timeout is None


# ---------------------------------------------------------------------------
# Every provider in the catalog
# ---------------------------------------------------------------------------
#
# The operator has API keys for MiniMax only, so the other providers
# cannot be exercised against their real endpoints. They can still be
# verified structurally, and that is what matters here: the timeout
# must land on the HTTP client that actually issues the request.
#
# Constructing a client makes no network call, so this is safe and
# fast.


def _http_timeout(client) -> float:
    """Return the timeout an HTTP client will actually use."""
    timeout = client.timeout
    if isinstance(timeout, (int, float)):
        return float(timeout)
    read = timeout.read
    return float(read) if read is not None else 0.0


def _construct(provider_class, timeout: float):
    """
    Build a provider with a dummy key and the given timeout.

    The constructor arguments differ across the catalog -- the local
    Ollama provider takes no API key, Azure forwards everything
    through ``**kwargs`` -- so the arguments are chosen by asking
    the class rather than by hard-coding a list.
    """
    import inspect

    parameters = inspect.signature(provider_class.__init__).parameters
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in parameters.values()
    )

    kwargs: dict = {}
    if "api_key" in parameters or accepts_kwargs:
        kwargs["api_key"] = "dummy-key-not-used-offline"
    if "timeout" in parameters or accepts_kwargs:
        kwargs["timeout"] = timeout
    return provider_class(**kwargs)


def _client_of(provider):
    """
    Return the HTTP client a provider will issue its request through.

    The OpenAI-compatible family builds its client lazily, so the
    accessor is called to materialise it. That constructs an SDK
    client; it does not send anything.
    """
    getter = getattr(provider, "_get_client", None)
    if getter is not None:
        return getter()
    client = getattr(provider, "_client", None)
    if client is None:
        raise AssertionError(
            f"{type(provider).__name__} exposes no HTTP client"
        )
    return client


def test_every_provider_puts_the_timeout_on_its_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every provider in the catalog applies the timeout to its client.

    This is the check that does not need an API key: it asserts that
    the timeout reaches the object that makes the HTTP request, for
    every provider, without contacting any endpoint.
    """
    import os

    _clear_timeout_env(monkeypatch)
    # Azure resolves its base URL from the environment; without it the
    # client cannot be built.
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.invalid")

    failures: list[str] = []
    for slug, provider_class in sorted(
        LLMFactory.PROVIDERS.items(), key=lambda kv: kv[0].value
    ):
        try:
            provider = _construct(provider_class, 137.0)
            actual = _http_timeout(_client_of(provider))
        except Exception as exc:  # pragma: no cover - reported below
            failures.append(f"{slug.value}: {type(exc).__name__}: {exc}")
            continue
        if actual != 137.0:
            failures.append(
                f"{slug.value}: HTTP client timeout is {actual}, "
                f"expected 137.0"
            )

    assert not failures, (
        "providers whose HTTP client did not receive the timeout:\n  "
        + "\n  ".join(failures)
    )


def test_every_provider_gets_the_shared_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TIMEOUT`` reaches the HTTP client of every provider."""
    import os

    _clear_timeout_env(monkeypatch)
    monkeypatch.setenv("TIMEOUT", "137")
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.invalid")

    settings = LLMSettings()
    assert settings.provider_timeout == 137.0

    failures: list[str] = []
    for slug, provider_class in sorted(
        LLMFactory.PROVIDERS.items(), key=lambda kv: kv[0].value
    ):
        try:
            provider = _construct(provider_class, settings.provider_timeout)
            actual = _http_timeout(_client_of(provider))
        except Exception as exc:  # pragma: no cover - reported below
            failures.append(f"{slug.value}: {type(exc).__name__}: {exc}")
            continue
        if actual != 137.0:
            failures.append(
                f"{slug.value}: HTTP client timeout is {actual}, "
                f"expected 137.0"
            )

    assert not failures, (
        "providers that did not receive the shared TIMEOUT:\n  "
        + "\n  ".join(failures)
    )


def test_the_shared_setting_reaches_every_provider_through_the_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory path wires ``TIMEOUT`` into every provider.

    The same end-to-end check, but through ``LLMFactory.create`` --
    the path the application actually uses.
    """
    import os

    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
    _clear_timeout_env(monkeypatch)
    monkeypatch.setenv("TIMEOUT", "137")
    settings = LLMSettings()

    failures: list[str] = []
    for slug in sorted(LLMFactory.PROVIDERS, key=lambda s: s.value):
        try:
            provider = LLMFactory.create(
                slug, timeout=settings.provider_timeout
            )
            actual = _http_timeout(_client_of(provider))
        except Exception as exc:  # pragma: no cover - reported below
            failures.append(f"{slug.value}: {type(exc).__name__}: {exc}")
            continue
        if actual != 137.0:
            failures.append(
                f"{slug.value}: HTTP client timeout is {actual}, "
                f"expected 137.0"
            )

    assert not failures, (
        "providers the factory did not wire the shared TIMEOUT into:\n  "
        + "\n  ".join(failures)
    )
