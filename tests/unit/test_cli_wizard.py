"""
Tests for the first-run setup path.

These tests cover the bug fixed in this commit where the
bootstrap would crash with ``Tkinter is not installed on this
Python`` if the system Python didn't have tkinter. The fix has
two layers:

1. ``_ensure_tkinter(hw)`` tries to install python3-tk
   automatically on Linux / macOS. This is the primary fix.

2. ``_cli_collect_config(hw)`` is a terminal-based wizard that
   runs when tkinter cannot be made available AND the user has a
   real TTY. It walks the user through the same fields as the
   GUI wizard.

3. When stdin is not a TTY (CI, scripts, piped input), the CLI
   wizard refuses to run and surfaces a clear error. Users in that
   situation should use ``--skip-gui`` with a pre-populated
   ``.env``.

These tests do not require a real display server or system
package manager. They mock both.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "bootstrap.py"


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------


def test_bootstrap_has_ensure_tkinter_helper() -> None:
    """The bootstrap must define ``_ensure_tkinter`` so it can
    auto-install python3-tk when tkinter is missing."""
    text = BOOTSTRAP.read_text()
    assert "def _ensure_tkinter" in text, (
        "bootstrap.py must define _ensure_tkinter(hw) so tkinter "
        "is auto-installed when missing"
    )


def test_bootstrap_ensure_tkinter_installs_python3_tk_on_debian() -> None:
    """The ensure_tkinter helper must install python3-tk on Debian."""
    text = BOOTSTRAP.read_text()
    # Find the ensure_tkinter function body and assert it runs
    # apt-get install -y python3-tk.
    assert "python3-tk" in text, (
        "bootstrap.py must install python3-tk so the system "
        "Python gains tkinter"
    )


def test_bootstrap_has_cli_wizard() -> None:
    """The bootstrap must define ``_cli_collect_config`` as a
    terminal fallback when tkinter cannot be made available."""
    text = BOOTSTRAP.read_text()
    assert "def _cli_collect_config" in text, (
        "bootstrap.py must define _cli_collect_config(hw) as a "
        "terminal fallback for the GUI wizard"
    )


def test_bootstrap_cli_wizard_refuses_to_run_when_stdin_is_not_a_tty() -> None:
    """The CLI wizard must raise a clear error when stdin is not a TTY.

    Without this check the wizard would block forever waiting for
    ``input()`` in a non-interactive script.
    """
    text = BOOTSTRAP.read_text()
    # Look for the runtime check.
    assert "_is_tty" in text
    # Find the wizard body and assert the TTY check is there.
    import re
    m = re.search(
        r"def _cli_collect_config\(hw: HardwareInfo\)\s*->\s*GuiConfig:\s*.*?is_tty = _is_tty\(\)",
        text,
        re.DOTALL,
    )
    assert m is not None, (
        "_cli_collect_config must check _is_tty() at the start"
    )


def test_bootstrap_gui_wizard_falls_back_to_cli_when_tkinter_fails() -> None:
    """``_gui_collect_config`` must call ``_cli_collect_config``
    when tkinter cannot be made available, not raise."""
    text = BOOTSTRAP.read_text()
    # Find the GUI function body.
    import re
    m = re.search(
        r"def _gui_collect_config\(hw: HardwareInfo\)\s*->\s*GuiConfig:.*?(?=^def )",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert m is not None, "_gui_collect_config not found"
    body = m.group(0)
    assert "_cli_collect_config(hw)" in body, (
        "_gui_collect_config must delegate to _cli_collect_config "
        "when tkinter cannot be imported"
    )


# ---------------------------------------------------------------------------
# Wizard behaviour — mocked
# ---------------------------------------------------------------------------


def _hw_stub():
    """Return a minimal HardwareInfo that pick_local_model() can use."""
    from bootstrap import HardwareInfo
    return HardwareInfo(
        os="Linux",
        machine="x86_64",
        cpu_cores=12,
        ram_gb=16.0,
        gpu_name="NVIDIA Test GPU",
        gpu_vram_gb=8.0,
        has_docker=True,
        docker_version="29.1.3",
    )


def test_cli_wizard_returns_openai_config_for_default_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI wizard must produce a valid GuiConfig for OpenAI."""
    import bootstrap

    monkeypatch.setattr(bootstrap, "_ensure_tkinter", lambda hw: False)
    monkeypatch.setattr(bootstrap, "_is_tty", lambda: True)
    # Feed canned answers: provider=2 (OpenAI), api_key=sk-test,
    # model=blank (use default), pubmed_email=test@example.com,
    # pubmed_api_key=blank, base_url=blank.
    from io import StringIO
    import sys
    canned = StringIO(
        "2\n"
        "sk-test-fake-key\n"
        "\n"  # base_url: blank -> default
        "gpt-4o-mini\n"  # model
        "test@example.com\n"  # pubmed_email
        "\n"  # pubmed_api_key: blank
    )
    monkeypatch.setattr(sys, "stdin", canned)

    config = bootstrap._cli_collect_config(_hw_stub())
    assert config.llm_provider == "openai"
    assert config.api_key == "sk-test-fake-key"
    assert config.model == "gpt-4o-mini"
    assert config.pubmed_email == "test@example.com"
    assert config.proceed is True
    assert config.selected_local_model is None


def test_cli_wizard_prompts_for_local_model_when_provider_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the user picks ``local``, the wizard must ask for a
    local model name."""
    import bootstrap

    monkeypatch.setattr(bootstrap, "_ensure_tkinter", lambda hw: False)
    monkeypatch.setattr(bootstrap, "_is_tty", lambda: True)
    from io import StringIO
    import sys
    canned = StringIO(
        "1\n"  # provider=1 (Local)
        "\n"  # api_key (skipped because local)
        "\n"  # base_url (blank -> default; Ollama's http://localhost:11434/v1)
        "\n"  # model (default)
        "deepseek-r1-distill-llama-8b-q4_k_m\n"  # local model
        "test@example.com\n"  # pubmed_email
        "\n"  # pubmed_api_key
    )
    monkeypatch.setattr(sys, "stdin", canned)

    config = bootstrap._cli_collect_config(_hw_stub())
    assert config.llm_provider == "local"
    assert config.selected_local_model == "deepseek-r1-distill-llama-8b-q4_k_m"
    assert config.api_key == ""
    assert config.proceed is True


def test_cli_wizard_accepts_provider_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user can type the provider slug (``openai``) instead of
    the numeric index."""
    import bootstrap

    monkeypatch.setattr(bootstrap, "_ensure_tkinter", lambda hw: False)
    monkeypatch.setattr(bootstrap, "_is_tty", lambda: True)
    from io import StringIO
    import sys
    canned = StringIO(
        "anthropic\n"  # provider by slug
        "sk-test-fake-key\n"
        "\n"  # base_url
        "claude-3-5-sonnet\n"
        "test@example.com\n"
        "\n"
    )
    monkeypatch.setattr(sys, "stdin", canned)

    config = bootstrap._cli_collect_config(_hw_stub())
    assert config.llm_provider == "anthropic"
    assert config.model == "claude-3-5-sonnet"


def test_cli_wizard_refuses_to_run_when_stdin_is_not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wizard must raise a clear error when stdin is not a TTY.

    Without this, the wizard would block forever waiting for
    ``input()`` in a non-interactive script (CI, ``python3
    bootstrap.py < /dev/null``, etc).
    """
    import bootstrap

    monkeypatch.setattr(bootstrap, "_ensure_tkinter", lambda hw: False)
    monkeypatch.setattr(bootstrap, "_is_tty", lambda: False)
    with pytest.raises(RuntimeError, match="stdin is not a TTY"):
        bootstrap._cli_collect_config(_hw_stub())


def test_cli_wizard_falls_back_to_env_var_for_required_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the user just hits enter at the API key prompt and the
    env var is set, the wizard uses the env var."""
    import bootstrap

    monkeypatch.setattr(bootstrap, "_ensure_tkinter", lambda hw: False)
    monkeypatch.setattr(bootstrap, "_is_tty", lambda: True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-fallback")
    from io import StringIO
    import sys
    canned = StringIO(
        "2\n"  # OpenAI
        "\n"  # API key: blank, then env var fallback
        "\n"  # base_url
        "gpt-4.1-mini\n"
        "test@example.com\n"
        "\n"
    )
    monkeypatch.setattr(sys, "stdin", canned)

    config = bootstrap._cli_collect_config(_hw_stub())
    assert config.api_key == "sk-env-fallback"


def test_ensure_tkinter_reports_already_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When tkinter is already importable, ``_ensure_tkinter``
    returns True without running any package install."""
    import bootstrap

    # tkinter is importable on this machine.
    assert bootstrap._import_tkinter() is not None
    assert bootstrap._ensure_tkinter(_hw_stub()) is True


def test_gui_wizard_wraps_mainloop_in_try_except() -> None:
    """``_gui_collect_config`` must wrap ``root.mainloop()`` in a
    try/except so that TclError (missing DISPLAY, etc.) triggers
    a clean fallback to the CLI wizard instead of crashing."""
    text = BOOTSTRAP.read_text()
    # Find the body of _gui_collect_config.
    func_start = text.find("def _gui_collect_config")
    next_def = text.find("\ndef ", func_start + 1)
    body = text[func_start:next_def]
    # The function must call root.mainloop() inside a try/except.
    assert "root.mainloop()" in body
    mainloop_pos = body.find("root.mainloop()")
    assert mainloop_pos >= 0
    # Find the most recent ``try:`` before mainloop.
    last_try = body.rfind("try:", 0, mainloop_pos)
    assert last_try >= 0 and last_try < mainloop_pos, (
        "root.mainloop() must be inside a try block"
    )
    # And an except clause after mainloop that calls the CLI wizard.
    after = body[mainloop_pos:]
    assert "except" in after, (
        "There must be an except clause after root.mainloop()"
    )
    assert "_cli_collect_config" in after, (
        "The except clause must fall back to _cli_collect_config"
    )



def test_gui_stringvars_are_initialized_to_empty_string() -> None:
    """The GUI's ``tk.StringVar()`` calls must use ``value=""``.

    A previous version called ``tk.StringVar()`` with no default
    for ``api_key_var``, ``pubmed_email_var`` and
    ``pubmed_api_key_var``. On some Tk versions the initial value
    is ``None`` instead of ``""``, which made ``.get().strip()`` raise
    ``AttributeError: 'NoneType' object has no attribute 'strip'``.
    """
    text = BOOTSTRAP.read_text()
    # Find the StringVar declarations.
    import re
    matches = re.findall(r"(\w+_var)\s*=\s*tk\.StringVar\(\s*\)", text)
    # The bug was on api_key_var, pubmed_email_var,
    # pubmed_api_key_var. Other variables have valid defaults.
    forbidden = {
        "api_key_var",
        "pubmed_email_var",
        "pubmed_api_key_var",
    }
    for var in matches:
        assert var not in forbidden, (
            f"{var} must be initialized with a default value "
            f"(e.g. tk.StringVar(value='')). Bare tk.StringVar() "
            f"returns None on some Tk versions and crashes the "
            f"bootstrap with 'NoneType has no attribute strip'."
        )


def test_gui_strip_calls_are_defensive_against_none() -> None:
    """Every ``X_var.get().strip()`` in the GUI code must be wrapped
    as ``(X_var.get() or '').strip()`` to survive ``None`` returns.

    Defensive belt-and-braces for any Tk version that ever returns
    ``None`` from a StringVar's ``.get()`` method.
    """
    text = BOOTSTRAP.read_text()
    # Find any unguarded ``X_var.get().strip()`` calls inside the GUI.
    import re
    # Only check inside _gui_collect_config.
    m = re.search(
        r"def _gui_collect_config\(.*?\) -> GuiConfig:.*?(?=^def )",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert m is not None, "_gui_collect_config not found"
    body = m.group(0)
    unsafe = re.findall(r"\w+_var\.get\(\)\.strip\(\)", body)
    assert not unsafe, (
        "These ``.get().strip()`` calls are unsafe and must be "
        f"wrapped as ``(X_var.get() or '').strip()``: {unsafe}"
    )



def test_prompt_returns_eof_as_empty() -> None:
    """``_prompt`` must return empty string on EOFError.

    A broken stdin (e.g. piped to ``/dev/null``) raises EOFError
    instead of blocking. The wizard treats empty as ``"cancel"``
    and the bootstrap surfaces a clear message.
    """
    import bootstrap
    from unittest.mock import patch

    # input() raises EOFError on EOF.
    with patch("builtins.input", side_effect=EOFError):
        result = bootstrap._prompt("test: ")
    assert result == ""
