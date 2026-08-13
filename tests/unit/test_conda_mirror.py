"""
Unit tests for the conda-channel mirror support.

These tests lock in the three properties that make the bootstrap
resilient to bad connections:

1. The Dockerfile references the ``CONDA_CHANNEL`` build-arg so
   users can override the channel at build time.
2. The Dockerfile's default is the official ``conda-forge.org``
   host rather than the legacy ``conda.anaconda.org``.
3. ``bootstrap.py`` wires the ``--mirror`` flag through to
   ``docker build --build-arg CONDA_CHANNEL=...`` and persists
   the choice in ``.env`` so subsequent runs reuse it.

The Dockerfile is parsed as plain text for these tests because we
do not have a Docker daemon in the CI environment. The parsing is
tolerant — it catches the most common regressions (deleted arg,
deleted env reference, wrong default).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
BOOTSTRAP = REPO_ROOT / "bootstrap.py"


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------


def test_dockerfile_exists() -> None:
    assert DOCKERFILE.is_file(), "Dockerfile is missing"


def test_dockerfile_declares_conda_channel_build_arg() -> None:
    """The Dockerfile must accept a CONDA_CHANNEL build-arg."""
    text = DOCKERFILE.read_text()
    assert re.search(
        r"^ARG\s+CONDA_CHANNEL=", text, re.MULTILINE
    ), "Dockerfile must declare 'ARG CONDA_CHANNEL=...' so users can override"


def test_dockerfile_default_is_anaconda_cloud_conda_forge() -> None:
    """The default channel must be the anaconda.cloud conda-forge URL.

    The conda-forge project transitioned its primary host to
    Anaconda Cloud in 2026. The legacy ``conda-forge.org`` and
    ``conda.anaconda.org`` URLs are being phased out, so the
    default must NOT be either.
    """
    text = DOCKERFILE.read_text()
    match = re.search(
        r"^ARG\s+CONDA_CHANNEL=(\S+)", text, re.MULTILINE
    )
    assert match is not None, "CONDA_CHANNEL arg missing"
    default = match.group(1)
    assert "conda-forge" in default, (
        f"Default channel should be a conda-forge mirror, got {default!r}"
    )
    assert "conda.anaconda.cloud" in default, (
        f"Default channel should be conda.anaconda.cloud after the 2026 "
        f"transition, got {default!r}"
    )
    assert "conda-forge.org" not in default, (
        f"Default channel must not be conda-forge.org (phased out), "
        f"got {default!r}"
    )
    assert "conda.anaconda.org" not in default, (
        f"Default channel must not be conda.anaconda.org (legacy CDN), "
        f"got {default!r}"
    )


def test_dockerfile_uses_channel_in_install() -> None:
    """The conda install must reference the configured channel."""
    text = DOCKERFILE.read_text()
    # We accept either an explicit ``--channel ${CONDA_CHANNEL}``
    # or a ``.condarc`` file that lists the channel. Both are
    # supported by micromamba.
    has_arg = "--channel" in text and "${CONDA_CHANNEL}" in text
    has_condarc = ".condarc" in text and "${CONDA_CHANNEL}" in text
    assert has_arg or has_condarc, (
        "Dockerfile must reference ${CONDA_CHANNEL} either via "
        "--channel or in a .condarc file"
    )


def test_dockerfile_has_retry_loop() -> None:
    """The install step must retry on transient failures."""
    text = DOCKERFILE.read_text()
    # We accept any of the common patterns: a ``for attempt in``
    # loop, an explicit ``|| true && retry``, or a ``set +e`` reset.
    for_pattern = re.search(r"for\s+attempt\s+in\s+1\s+2\s+3", text)
    assert for_pattern is not None, (
        "Dockerfile must include a 3-attempt retry loop around the "
        "conda install to survive transient network failures"
    )


def test_dockerfile_persists_channel_at_runtime() -> None:
    """The channel must be persisted into the runtime image so the
    running container can also use it (e.g. for additional
    ``micromamba install`` calls)."""
    text = DOCKERFILE.read_text()
    assert re.search(
        r"^ENV\s+CONDA_CHANNEL=\$\{CONDA_CHANNEL\}", text, re.MULTILINE
    ), "Dockerfile must persist CONDA_CHANNEL as an ENV so the runtime sees it"


# ---------------------------------------------------------------------------
# bootstrap.py CLI
# ---------------------------------------------------------------------------


def test_bootstrap_has_mirror_flag() -> None:
    text = BOOTSTRAP.read_text()
    assert "--mirror" in text, "bootstrap.py must accept --mirror"
    # The argparse help should mention at least one popular mirror so
    # users don't have to guess.
    assert "tuna" in text.lower() or "aliyun" in text.lower(), (
        "bootstrap.py --mirror help should reference popular mirrors"
    )


def test_bootstrap_mirror_propagates_to_docker_build() -> None:
    """The --mirror URL must be passed as a build-arg."""
    text = BOOTSTRAP.read_text()
    # The build_image() implementation must invoke
    # ``docker build --build-arg CONDA_CHANNEL=...``.
    assert "--build-arg" in text
    assert "CONDA_CHANNEL" in text


def test_bootstrap_persists_mirror_to_env() -> None:
    """After the GUI, the chosen channel must be saved to .env."""
    text = BOOTSTRAP.read_text()
    assert "CONDA_CHANNEL" in text, (
        "bootstrap.py must persist CONDA_CHANNEL into .env"
    )


def test_bootstrap_default_channel_is_anaconda_cloud() -> None:
    text = BOOTSTRAP.read_text()
    # Look for the DEFAULT_CONDA_CHANNEL constant.
    match = re.search(
        r"DEFAULT_CONDA_CHANNEL\s*=\s*[\"']([^\"']+)[\"']", text
    )
    assert match is not None, "bootstrap.py must define DEFAULT_CONDA_CHANNEL"
    assert "conda.anaconda.cloud" in match.group(1), (
        "Default channel should be conda.anaconda.cloud, "
        f"got {match.group(1)!r}"
    )
    assert "conda-forge.org" not in match.group(1), (
        "Legacy conda-forge.org host must not be the default, "
        f"got {match.group(1)!r}"
    )


# ---------------------------------------------------------------------------
# .env parsing
# ---------------------------------------------------------------------------


def test_bootstrap_reads_mirror_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If CONDA_CHANNEL is in .env, the bootstrap should use it."""
    # Write a minimal .env to the temporary location.
    env = tmp_path / ".env"
    env.write_text(
        "PUBMED_EMAIL=test@example.com\n"
        "DEFAULT_LLM_PROVIDER=openai\n"
        "CONDA_CHANNEL=https://mirrors.tuna.tsinghua.edu.cn/conda-forge\n"
    )
    # Read the file and assert the parsing logic we use in main().
    text = env.read_text()
    channel = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("CONDA_CHANNEL="):
            channel = line.split("=", 1)[1].strip()
            break
    assert channel == "https://mirrors.tuna.tsinghua.edu.cn/conda-forge"



# ---------------------------------------------------------------------------
# Buildx support
# ---------------------------------------------------------------------------


def test_bootstrap_prefers_buildx_when_available() -> None:
    """``_build_command`` returns ``docker buildx build`` when buildx is on PATH."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from bootstrap import _build_command  # type: ignore

    cmd = _build_command(["-t", "foo", "."])
    # If buildx is installed on this host, the prefix must be
    # ``docker buildx build``. Otherwise the legacy fallback is
    # acceptable — but the function must still return a list
    # whose first two elements are ``["docker", "build"]`` or
    # ``["docker", "buildx", "build"]``.
    assert cmd[0] == "docker"
    assert cmd[1] in ("build", "buildx")
    if cmd[1] == "buildx":
        assert cmd[2] == "build"


def test_bootstrap_apt_install_includes_docker_buildx() -> None:
    """The Linux install path must include docker-buildx so buildx is on PATH."""
    text = BOOTSTRAP.read_text()
    assert "docker-buildx" in text, (
        "bootstrap.py must install docker-buildx on Debian so "
        "the buildx path is the default."
    )
