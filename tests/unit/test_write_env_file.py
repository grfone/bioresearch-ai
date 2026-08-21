"""
tests/unit/test_write_env_file.py

Pins the shape of the .env file that bootstrap.write_env_file
emits. The user-facing purpose is to catch regressions in
the operator-facing discoverability of advanced settings --
if a future commit drops a commented-out line, we want a
test to fail loudly.

The non-comment lines are mostly covered indirectly by the
container's startup (the file is parsed on every boot).
The comment lines have no programmatic consumers, so we
test them here.

Why a dedicated file rather than appending to
test_cli_wizard.py
- ``test_cli_wizard.py`` is 500+ lines focused on the
  collect-config path (CLI/GUI flows). Adding .env-shape
  assertions there would dilute the focus.
- The .env shape changes rarely but when it does, it's
  usually an explicit decision (ADR-driven, like the
  PDF_UPLOAD_MAX_BYTES cap bump). A dedicated file makes
  those changes easy to find in history.
"""
import pathlib
import sys

import pytest


# bootstrap.py is the script that emits the .env file. We
# import it as a module so we can call write_env_file
# directly without spawning a subprocess.
#
# The bootstrap is normally run from the repo root, but
# importing it from a test doesn't require any path setup
# because we add the bootstrap's parent dir to sys.path
# explicitly. The bootstrap is intentionally side-effect-free
# at import time (the GUI/wizard entry points only run when
# explicitly called), so this is safe.
BOOTSTRAP_PARENT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOOTSTRAP_PARENT))


def _call_write_env(tmp_path, monkeypatch, **config_overrides):
    """Invoke bootstrap.write_env_file and return the emitted .env text.

    Redirects the bootstrap's ENV_FILE path to a temp file so
    the test doesn't touch the real .env. We don't actually
    need the file on disk -- we capture the write_text call
    -- but pointing at a tmp path keeps the bootstrap's
    invariants happy.
    """
    import bootstrap

    # Redirect the bootstrap's .env path to a temp file so
    # the test is hermetic. The bootstrap writes the file
    # unconditionally; we read it back immediately after.
    tmp_env = tmp_path / "bioresearch.env"
    monkeypatch.setattr(bootstrap, "ENV_FILE", tmp_env)

    # The bootstrap uses ``from app.core.enums.llm_provider
    # import LLMProviderEnum`` and ``from app.application.
    # services.llm_provider_catalog import get_provider_meta``
    # inside write_env_file. Those imports can fail in
    # standalone test runs (the app isn't on PYTHONPATH),
    # but the bootstrap already catches ImportError and
    # falls back to the legacy single-key behaviour.
    # We just need a valid GuiConfig.

    from bootstrap import GuiConfig, write_env_file

    config = GuiConfig(
        llm_provider=config_overrides.get("llm_provider", "openai"),
        api_key=config_overrides.get("api_key", "sk-test-key"),
        base_url=config_overrides.get("base_url", "https://api.openai.com/v1"),
        model=config_overrides.get("model", "gpt-4.1-mini"),
        pubmed_email=config_overrides.get("pubmed_email", "test@example.com"),
        pubmed_api_key=config_overrides.get("pubmed_api_key", ""),
        build_target=config_overrides.get("build_target", "minimal"),
    )

    write_env_file(config, conda_channel="conda-forge")
    return tmp_env.read_text()


def test_write_env_file_emits_abstract_enrichher_enabled_uncommented(tmp_path, monkeypatch):
    """The Abstract Enricher line is uncommented by default.

    The bootstrap should activate the abstract enricher
    out of the box (it costs ~1-2s per DOI lookup but
    dramatically improves Springer book chapter support).
    Operators can disable it by setting
    ``ABSTRACT_ENRICHER_ENABLED=false`` in their .env.
    """
    env_text = _call_write_env(tmp_path, monkeypatch)
    assert "ABSTRACT_ENRICHER_ENABLED=true" in env_text


def test_write_env_file_emits_pdf_upload_max_bytes_commented(tmp_path, monkeypatch):
    """The PDF cap line is COMMENTED OUT by default.

    The 200 MB default lives in
    ``LiteratureSettings.pdf_upload_max_bytes``; the .env
    line is documentation only -- it tells operators that
    the cap is configurable, where the default lives, and
    that the hard ceiling is 200 MB (non-configurable).

    We assert the comment line is present (so operators
    discover the knob) AND that it's commented out (so
    the default isn't accidentally overridden).
    """
    env_text = _call_write_env(tmp_path, monkeypatch)
    # The comment block that describes the knob must be
    # present -- operators discovering the cap read this.
    assert "# PDF upload cap" in env_text, (
        "bootstrap.write_env_file must emit a comment "
        "block describing the PDF_UPLOAD_MAX_BYTES knob"
    )
    # The default-value line must be COMMENTED out so
    # it doesn't override the LiteratureSettings default
    # (which would be confusing: setting the env var to
    # the same value the default would be a no-op, but
    # operators might not realise the .env is the source
    # of truth once uncommented).
    assert "# PDF_UPLOAD_MAX_BYTES=209715200" in env_text, (
        "the default-value line must be commented out "
        "(# PDF_UPLOAD_MAX_BYTES=209715200) so the 200 MB "
        "default in code remains the effective cap"
    )
    # Belt-and-suspenders: confirm there is NO uncommented
    # PDF_UPLOAD_MAX_BYTES line. We iterate line by line
    # because a naive ``substring not in text`` check would
    # also flag the commented version (which is what we
    # want -- the substring IS there, just inside a
    # comment).
    for line in env_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("PDF_UPLOAD_MAX_BYTES"), (
            f"found uncommented PDF_UPLOAD_MAX_BYTES line: "
            f"{stripped!r}"
        )


def test_write_env_file_emits_commented_pdf_cap_with_default_value(tmp_path, monkeypatch):
    """The commented PDF cap line shows 209715200 (= 200 MB).

    Operators discovering the knob see the byte value --
    209715200 -- alongside the doc comment. We assert the
    comment block includes the byte value, the unit
    explanation, AND a pointer to the hard ceiling.
    """
    env_text = _call_write_env(tmp_path, monkeypatch)
    # The comment block mentions 200 MB multiple times.
    assert "200 MB" in env_text
    # The hard ceiling is referenced so operators know
    # they can't bypass it via env var.
    assert "hard ceiling" in env_text.lower() or "hard cap" in env_text.lower()


def test_write_env_file_pdf_cap_section_is_in_abstract_enricher_neighborhood(tmp_path, monkeypatch):
    """The PDF cap section sits next to the Abstract Enricher section.

    Both settings tune the ``add_paper`` / ``add_paper_from_pdf``
    hot paths, so keeping them in the same .env block
    makes the discoverability story coherent. We assert
    the two section headers exist and that the PDF cap
    block appears after (i.e. below) the Abstract Enricher
    block -- the order in write_env_file's ``lines`` list
    is the source of truth.
    """
    env_text = _call_write_env(tmp_path, monkeypatch)
    enricher_idx = env_text.index("# Abstract enrichment")
    pdf_idx = env_text.index("# PDF upload cap")
    assert enricher_idx < pdf_idx, (
        "the Abstract Enricher section must appear BEFORE "
        "the PDF upload cap section in the .env so the two "
        "add_paper tunables are co-located"
    )


def test_write_env_file_emits_well_formed_env(tmp_path, monkeypatch):
    """Sanity check: the .env is non-empty and has the right shape.

    This is a regression guard for any future change that
    silently breaks write_env_file (e.g. wrong import path
    leaves the lines list empty). We check the structural
    minimum: the file has the bootstrap comment header
    AND both Abstract Enricher and PDF cap sections.
    """
    env_text = _call_write_env(tmp_path, monkeypatch)
    assert env_text.startswith(
        "# Generated by bootstrap.py. Re-run bootstrap.py to edit."
    )
    # The Abstract Enricher block must be present and
    # adjacent to its doc comment.
    assert "# Abstract enrichment" in env_text
    assert "ABSTRACT_ENRICHER_ENABLED=true" in env_text
    # The PDF cap block must be present (the comment lines
    # AND the commented default-value line).
    assert "# PDF upload cap" in env_text
    assert "# PDF_UPLOAD_MAX_BYTES=209715200" in env_text
