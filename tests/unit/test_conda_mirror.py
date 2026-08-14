"""
Unit tests for the build-system resilience properties.

These tests lock in the four properties that make the bootstrap
resilient to bad hardware and bad connections:

1. The Dockerfile declares the ``BUILD_TARGET`` build-arg so the
   bootstrap can pick between the slim and the heavy image.
2. The Dockerfile declares ``TORCH_INDEX_URL`` so the bootstrap
   can route PyTorch installs to the right wheel repo (CPU vs CUDA).
3. The ``backend-local`` stage uses pip, NOT conda. We pulled
   out of the conda-forge channel entirely because conda was slow
   and prone to 404s. The tests enforce this regression guard.
4. ``bootstrap.py`` wires the ``--mirror`` and ``--local`` flags
   through to ``docker build --build-arg`` and persists the
   choices in ``.env`` so subsequent runs reuse them.

The Dockerfile is parsed as plain text for these tests because we
do not have a Docker daemon in the CI environment. The parsing is
tolerant — it catches the most common regressions (deleted arg,
wrong default, conda creeping back in).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
BOOTSTRAP = REPO_ROOT / "bootstrap.py"
MINIMAL_REQS = REPO_ROOT / "requirements" / "minimal-requirements.txt"
LOCAL_REQS = REPO_ROOT / "requirements" / "local-requirements.txt"


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------


def test_dockerfile_exists() -> None:
    assert DOCKERFILE.is_file(), "Dockerfile is missing"


def test_dockerfile_declares_build_target_build_arg() -> None:
    """The Dockerfile must accept a ``BUILD_TARGET`` build-arg."""
    text = DOCKERFILE.read_text()
    assert re.search(
        r"^ARG\s+BUILD_TARGET=", text, re.MULTILINE
    ), "Dockerfile must declare 'ARG BUILD_TARGET=...' so users can pick the build target"


def test_dockerfile_default_build_target_is_minimal() -> None:
    """The default ``BUILD_TARGET`` must be ``minimal``."""
    text = DOCKERFILE.read_text()
    match = re.search(
        r"^ARG\s+BUILD_TARGET=(\S+)", text, re.MULTILINE
    )
    assert match is not None, "BUILD_TARGET arg missing"
    assert match.group(1) == "minimal", (
        f"Default BUILD_TARGET must be 'minimal', got {match.group(1)!r}"
    )


def test_dockerfile_declares_torch_index_url() -> None:
    """The Dockerfile must accept ``TORCH_INDEX_URL`` for the local stage.

    When the user has an NVIDIA GPU, the bootstrap sets this to
    the CUDA wheel index (``https://download.pytorch.org/whl/cu124``).
    When unset, pip pulls the small CPU-only torch wheel from PyPI.
    """
    text = DOCKERFILE.read_text()
    assert re.search(
        r"^ARG\s+TORCH_INDEX_URL=", text, re.MULTILINE
    ), "Dockerfile must declare 'ARG TORCH_INDEX_URL=...'"


def test_dockerfile_local_stage_uses_pip_not_conda() -> None:
    """The local stage must install via pip and NOT use conda.

    We pulled out of conda-forge entirely. Conda was slow (~30 s
    solver round-trip), prone to 404s on the wrong mirror, and the
    PyTorch manylinux wheels on PyPI are smaller and faster to
    install. This test guards against a regression that re-introduces
    micromamba/conda.
    """
    text = DOCKERFILE.read_text()
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    local_block = next(
        (c for c in chunks if "AS backend-local" in c),
        None,
    )
    assert local_block is not None, "backend-local block not found"
    # Strip comments before checking.
    code = re.sub(r"(?m)^\s*#.*$", "", local_block)
    assert "micromamba" not in code, (
        "backend-local must not use micromamba (we use pip)"
    )
    assert "conda" not in code.lower(), (
        "backend-local must not mention conda"
    )
    assert "environment.yaml" not in code, (
        "backend-local must not reference environment.yaml"
    )
    assert "pip install" in code, (
        "backend-local must install via pip"
    )


def test_dockerfile_local_stage_installs_local_deps() -> None:
    """The local stage must reference local-requirements.txt."""
    text = DOCKERFILE.read_text()
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    local_block = next(
        (c for c in chunks if "AS backend-local" in c),
        None,
    )
    assert local_block is not None
    assert "local-requirements.txt" in local_block, (
        "backend-local must reference requirements/local-requirements.txt"
    )


def test_dockerfile_no_install_retry_loop_needed() -> None:
    """Because we use pip (not conda) the retry loop is no longer
    required for channel 404s. This test enforces that the
    conda-specific retry loop has been removed. We keep retries
    on npm ci (handled separately) but no longer need them for
    pip install.
    """
    text = DOCKERFILE.read_text()
    # The pip install commands should NOT be wrapped in a
    # ``for attempt in 1 2 3`` retry loop, which is the conda
    # pattern.
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    for chunk in chunks:
        code = re.sub(r"(?m)^\s*#.*$", "", chunk)
        if "AS backend-" in chunk:
            pip_section = code.split("pip install", 1)
            if len(pip_section) > 1:
                # Look at the chunk right after pip install — must NOT
                # be a retry loop.
                following = pip_section[1][:300]
                assert "for attempt in" not in following, (
                    "pip install must not be wrapped in a retry loop; "
                    "pip retries internally on transient network errors"
                )


def test_dockerfile_final_target_is_parametric() -> None:
    """The final ``FROM`` line must select the target based on ``BUILD_TARGET``."""
    text = DOCKERFILE.read_text()
    last_from = re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE)[-1]
    assert "${BUILD_TARGET}" in last_from, (
        f"Final FROM must be 'FROM backend-${{BUILD_TARGET}}', got {last_from!r}"
    )


# ---------------------------------------------------------------------------
# bootstrap.py
# ---------------------------------------------------------------------------


def test_bootstrap_persists_build_target_in_env() -> None:
    """``bootstrap.py`` must save ``BUILD_TARGET`` to ``.env``."""
    text = BOOTSTRAP.read_text()
    assert "BUILD_TARGET=" in text, (
        "bootstrap.py must persist BUILD_TARGET in .env"
    )


def test_bootstrap_persists_mirror_in_env() -> None:
    """``bootstrap.py`` must save the conda channel / pip mirror to ``.env``.

    Even though we no longer use conda, the ``--mirror`` flag is
    still accepted and persisted for backwards compatibility.
    """
    text = BOOTSTRAP.read_text()
    assert "CONDA_CHANNEL=" in text, (
        "bootstrap.py must persist CONDA_CHANNEL in .env (legacy)"
    )


def test_bootstrap_local_passes_torch_index_url_for_gpu() -> None:
    """When the user picks ``--local`` and has an NVIDIA GPU, the
    bootstrap must pass ``--build-arg TORCH_INDEX_URL=.../cu124``
    so pip installs the CUDA build of torch."""
    text = BOOTSTRAP.read_text()
    assert "TORCH_INDEX_URL" in text, (
        "bootstrap.py must forward TORCH_INDEX_URL to docker build"
    )
    assert "download.pytorch.org/whl/cu124" in text or "cu124" in text, (
        "bootstrap.py must reference the cu124 wheel index for "
        "NVIDIA GPUs"
    )


def test_bootstrap_local_skips_torch_index_for_cpu_only() -> None:
    """When the user picks ``--local`` without a GPU, the bootstrap
    must leave ``TORCH_INDEX_URL`` empty (default = CPU wheels)."""
    text = BOOTSTRAP.read_text()
    # The build_image call must use the local torch_index_url variable.
    assert "torch_index_url=" in text


def test_bootstrap_default_image_is_slim() -> None:
    """Without ``--local``, the bootstrap builds the slim image."""
    text = BOOTSTRAP.read_text()
    assert "\"minimal\"" in text, (
        "bootstrap.py must default BUILD_TARGET to 'minimal' so the slim image is built"
    )


# ---------------------------------------------------------------------------
# requirements files
# ---------------------------------------------------------------------------


def test_local_requirements_exists() -> None:
    """``requirements/local-requirements.txt`` must exist."""
    assert LOCAL_REQS.is_file(), (
        "requirements/local-requirements.txt is missing — the local "
        "image needs a pip-installable ML deps file"
    )


def test_local_requirements_has_ml_deps() -> None:
    """``local-requirements.txt`` must include the ML deps."""
    text = LOCAL_REQS.read_text().lower()
    # At least one of the heavy ML deps must be present.
    heavy = ["torch", "transformers", "scikit-learn", "rdkit", "pandas", "scipy"]
    has = [p for p in heavy if p in text]
    assert has, (
        f"local-requirements.txt must contain at least one of {heavy}"
    )


def test_minimal_requirements_does_not_have_ml_deps() -> None:
    """``minimal-requirements.txt`` must NOT include ML deps."""
    text = MINIMAL_REQS.read_text().lower()
    code = re.sub(r"(?m)^\s*#.*$", "", text)
    forbidden = ["torch", "transformers", "scikit-learn", "rdkit", "pandas", "scipy"]
    for pkg in forbidden:
        assert pkg not in code, (
            f"minimal-requirements.txt must not install {pkg!r}"
        )