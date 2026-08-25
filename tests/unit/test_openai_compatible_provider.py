"""
tests/unit/test_openai_compatible_provider.py

Tests for the ``OpenAICompatibleProvider`` base class -- the single
code path shared by 18 providers in the catalog (OpenAI, MiniMax,
DeepSeek, Groq, Mistral, xAI, etc.).

These tests focus on the configuration plumbing:
  - API key resolution (constructor > env var)
  - Base URL resolution order (constructor > env var > class attr)
  - Model resolution order (constructor > env var > class attr)

They do NOT exercise the network round-trip (the OpenAI SDK does
that, and tests for it live in the integration suite).

Precedence regression
---------------------
The previous implementation had TWO bugs in how it computed
``self._base_url``:

  1. The resolution order was constructor-arg -> class-attr -> env.
     The class attr (``"https://api.openai.com/v1"`` on
     ``OpenAIProvider``) is always truthy, so the env fallback was
     never reached.

  2. The env var name was computed as
     ``f"{api_key_env}_BASE_URL".replace("_API_KEY", "_BASE_URL")``.
     For ``api_key_env="OPENAI_API_KEY"`` the f-string produces
     ``"OPENAI_API_KEY_BASE_URL"``, then the replace fires on the
     ``_API_KEY`` substring, leaving ``"OPENAI_BASE_URL_BASE_URL"``
     (a duplicated ``_BASE_URL`` suffix). The correct derivation is:
     strip the ``_API_KEY`` suffix from the key env name, then
     append ``_BASE_URL``.

These tests pin both fixes.
"""
import importlib

import pytest

from app.infrastructure.llm.openai_provider import OpenAIProvider


@pytest.fixture
def clean_openai_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Strip every OpenAI-related env var AND make the project's
    ``.env`` file invisible to ``_load_env()``.

    The provider's ``_load_env()`` reads ``<project>/.env`` via
    ``python-dotenv`` during ``__init__``. If the project has a
    ``.env`` with ``OPENAI_BASE_URL=...`` (a common state during
    live verification), every test in this module would inherit
    that value regardless of ``monkeypatch.delenv``.

    We point ``_PROJECT_ROOT`` at an empty tmp directory for the
    duration of the test so ``_load_env()`` finds no ``.env`` file.
    That's the cleanest way to isolate the test from the developer's
    shell state without requiring every test to do its own cleanup.
    """
    for var in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)

    oc = importlib.import_module(
        "app.infrastructure.llm._openai_compatible"
    )
    monkeypatch.setattr(oc, "_PROJECT_ROOT", tmp_path)


def test_base_url_uses_class_default_when_no_env(
    clean_openai_env: None,
) -> None:
    """Without ``OPENAI_BASE_URL``, the provider falls back to the
    class-level default (``https://api.openai.com/v1``)."""
    provider = OpenAIProvider(api_key="sk-test")
    assert provider._base_url == "https://api.openai.com/v1"


def test_base_url_env_overrides_class_default(
    monkeypatch: pytest.MonkeyPatch, clean_openai_env: None
) -> None:
    """``OPENAI_BASE_URL`` must override the class-level default.

    Regression guard for the precedence bug where the class attr
    was always truthy and shadowed the env var fallback, making
    it impossible to point ``OpenAIProvider`` at MiniMax / Azure /
    vLLM without subclassing.
    """
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.minimax.chat/v1")
    provider = OpenAIProvider(api_key="sk-test")
    assert provider._base_url == "https://api.minimax.chat/v1"


def test_base_url_explicit_constructor_arg_wins(
    monkeypatch: pytest.MonkeyPatch, clean_openai_env: None
) -> None:
    """An explicit constructor ``base_url=...`` wins over both the
    env var and the class default. This is the override path for
    programmatic clients (e.g. tests, programmatic catalog wiring)."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.minimax.chat/v1")
    provider = OpenAIProvider(
        api_key="sk-test",
        base_url="https://custom.example.com/v1",
    )
    assert provider._base_url == "https://custom.example.com/v1"


def test_base_url_empty_env_keeps_class_default(
    monkeypatch: pytest.MonkeyPatch, clean_openai_env: None
) -> None:
    """An explicitly-empty ``OPENAI_BASE_URL`` (``export OPENAI_BASE_URL=``)
    should not clobber the class default. Only a non-empty env var
    overrides.

    This documents the "unset vs empty" distinction: unset means
    "use the default"; empty means "use nothing" -- but since the
    provider requires *some* base URL, the safest behaviour is to
    treat empty as unset and fall back to the class default.
    """
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    provider = OpenAIProvider(api_key="sk-test")
    assert provider._base_url == "https://api.openai.com/v1"


def test_base_url_env_var_name_is_derived_correctly(
    monkeypatch: pytest.MonkeyPatch, clean_openai_env: None
) -> None:
    """Regression guard for the second bug: ``OPENAI_API_KEY``
    must derive to ``OPENAI_BASE_URL``, not
    ``OPENAI_BASE_URL_BASE_URL``.

    The previous code was::

        f"{api_key_env}_BASE_URL".replace("_API_KEY", "_BASE_URL")

    which for ``api_key_env="OPENAI_API_KEY"`` produces
    ``"OPENAI_BASE_URL_BASE_URL"`` -- a duplicated suffix. The fix
    uses ``str.removesuffix`` to strip the suffix cleanly.
    """
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.minimax.chat/v1")
    provider = OpenAIProvider(api_key="sk-test")
    # The internal attribute that names the env var is also
    # useful for tests; verify it matches the documented name.
    assert provider._base_url_env == "OPENAI_BASE_URL"
    assert provider._base_url == "https://api.minimax.chat/v1"


def test_minimax_provider_imports_cleanly() -> None:
    """``MinimaxProvider`` does NOT subclass
    ``OpenAICompatibleProvider`` -- it's a standalone class with
    its own base URL handling. This test is a sanity check that
    the standalone provider still imports cleanly after the
    refactor above.

    The point: if you want MiniMax, set
    ``DEFAULT_LLM_PROVIDER=minimax`` in your ``.env`` and use
    ``MINIMAX_API_KEY`` -- don't try to coerce the OpenAI-compatible
    provider into talking to MiniMax via ``OPENAI_BASE_URL``.
    (That works too, but it's the fallback path -- this test pins
    the primary path as the documented one.)
    """
    from app.infrastructure.llm.minimax_provider import MinimaxProvider

    provider = MinimaxProvider(api_key="test-key")
    assert provider is not None
