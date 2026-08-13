"""
Unit tests for the slim + local image split.

These tests lock in the property that BioResearch AI ships two
build targets:

- ``bioresearch-ai:latest`` (the default): a slim Python 3.12 image
  with only the backend runtime dependencies. No conda, no ML
  libraries, no Node.js. ~250 MB total.

- ``bioresearch-ai:local``: the full image with the heavy ML
  dependencies (torch, transformers, scikit-learn, rdkit, etc.)
  installed via conda. ~3 GB. Only built when the user passes
  ``--local`` to bootstrap.py or picks the Local LLM provider in
  the GUI.

The split is enforced by ``BUILD_TARGET`` build-arg in the Dockerfile
and the ``--local`` flag in bootstrap.py. The tests below make sure
neither regresses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
BOOTSTRAP = REPO_ROOT / "bootstrap.py"
MINIMAL_REQS = REPO_ROOT / "requirements" / "minimal-requirements.txt"
ENVIRONMENT_YAML = REPO_ROOT / "environment.yaml"


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------


def test_dockerfile_declares_build_target_build_arg() -> None:
    """The Dockerfile must accept BUILD_TARGET so docker build can pick a target."""
    text = DOCKERFILE.read_text()
    assert re.search(
        r"^ARG\s+BUILD_TARGET=", text, re.MULTILINE
    ), "Dockerfile must declare 'ARG BUILD_TARGET=...' so users can pick the build target"


def test_dockerfile_default_target_is_minimal() -> None:
    """The default BUILD_TARGET must be 'minimal' so users get the slim image."""
    text = DOCKERFILE.read_text()
    match = re.search(
        r"^ARG\s+BUILD_TARGET=(\S+)", text, re.MULTILINE
    )
    assert match is not None, "BUILD_TARGET arg missing"
    assert match.group(1) == "minimal", (
        f"Default BUILD_TARGET must be 'minimal', got {match.group(1)!r}"
    )


def test_dockerfile_has_minimal_stage() -> None:
    """The Dockerfile must define a slim backend-minimal stage."""
    text = DOCKERFILE.read_text()
    assert "AS backend-minimal" in text, (
        "Dockerfile must define a backend-minimal stage for the slim image"
    )


def test_dockerfile_has_local_stage() -> None:
    """The Dockerfile must define a backend-local stage for the heavy image."""
    text = DOCKERFILE.read_text()
    assert "AS backend-local" in text, (
        "Dockerfile must define a backend-local stage for the heavy image"
    )


def test_dockerfile_minimal_stage_uses_slim_python() -> None:
    """The slim stage must use python:3.12-slim, not micromamba."""
    text = DOCKERFILE.read_text()
    # Find the backend-minimal stage.
    match = re.search(
        r"FROM\s+(\S+)\s+AS\s+backend-minimal", text
    )
    assert match is not None, "backend-minimal stage not found"
    base = match.group(1)
    assert "python" in base, (
        f"backend-minimal must use a python base image, got {base!r}"
    )
    assert "slim" in base, (
        f"backend-minimal must use a slim variant, got {base!r}"
    )
    assert "micromamba" not in base, (
        f"backend-minimal must not use micromamba, got {base!r}"
    )


def test_dockerfile_minimal_stage_does_not_install_conda_env() -> None:
    """The slim stage must not run ``micromamba install`` or COPY environment.yaml."""
    text = DOCKERFILE.read_text()
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    minimal_block = next(
        (c for c in chunks if c.lstrip().startswith("python") and "AS backend-minimal" in c),
        None,
    )
    assert minimal_block is not None, "backend-minimal block not found"
    # Strip comments before checking — the slim stage may discuss
    # ``environment.yaml`` in a comment without actually using it.
    code = re.sub(r"(?m)^\s*#.*$", "", minimal_block)
    assert "micromamba" not in code, (
        "backend-minimal must not run micromamba"
    )
    assert "environment.yaml" not in code, (
        "backend-minimal must not COPY environment.yaml"
    )


def test_dockerfile_minimal_stage_uses_pip() -> None:
    """The slim stage must install deps via pip, not conda."""
    text = DOCKERFILE.read_text()
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    minimal_block = next(
        (c for c in chunks if c.lstrip().startswith("python") and "AS backend-minimal" in c),
        None,
    )
    assert minimal_block is not None
    assert "pip install" in minimal_block, (
        "backend-minimal must use pip install for the backend deps"
    )


def test_dockerfile_minimal_stage_uses_minimal_requirements() -> None:
    """The slim stage must use requirements/minimal-requirements.txt."""
    text = DOCKERFILE.read_text()
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    minimal_block = next(
        (c for c in chunks if c.lstrip().startswith("python") and "AS backend-minimal" in c),
        None,
    )
    assert minimal_block is not None
    assert "requirements/minimal-requirements.txt" in minimal_block, (
        "backend-minimal must COPY requirements/minimal-requirements.txt"
    )


def test_dockerfile_minimal_stage_does_not_include_node() -> None:
    """The slim stage must not install Node.js (the frontend is prebuilt)."""
    text = DOCKERFILE.read_text()
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    minimal_block = next(
        (c for c in chunks if c.lstrip().startswith("python") and "AS backend-minimal" in c),
        None,
    )
    assert minimal_block is not None
    # The minimal stage should not run npm install. The frontend
    # stage already builds the bundle.
    assert "npm install" not in minimal_block, (
        "backend-minimal must not run npm install (the frontend is prebuilt)"
    )


def test_dockerfile_local_stage_uses_environment_yaml() -> None:
    """The local stage must install environment.yaml via conda."""
    text = DOCKERFILE.read_text()
    chunks = re.split(r"^FROM\s+", text, flags=re.MULTILINE)
    local_block = next(
        (c for c in chunks if "AS backend-local" in c),
        None,
    )
    assert local_block is not None, "backend-local block not found"
    assert "environment.yaml" in local_block, (
        "backend-local must reference environment.yaml"
    )
    assert "micromamba install" in local_block, (
        "backend-local must install the conda env via micromamba"
    )


def test_dockerfile_final_target_is_parametric() -> None:
    """The final FROM line must select the target based on BUILD_TARGET."""
    text = DOCKERFILE.read_text()
    # We expect the last ``FROM`` to be ``FROM backend-${BUILD_TARGET}``.
    last_from = re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE)[-1]
    assert "${BUILD_TARGET}" in last_from, (
        f"Final FROM must be 'FROM backend-${{BUILD_TARGET}}', got {last_from!r}"
    )


# ---------------------------------------------------------------------------
# requirements/minimal-requirements.txt
# ---------------------------------------------------------------------------


def test_minimal_requirements_file_exists() -> None:
    assert MINIMAL_REQS.is_file(), (
        "requirements/minimal-requirements.txt is missing — the slim image "
        "needs a pin list of the backend runtime deps"
    )


def test_minimal_requirements_no_ml_deps() -> None:
    """The minimal requirements must not install torch, transformers, scikit-learn, etc."""
    text = MINIMAL_REQS.read_text()
    # Strip comments so the test does not match on words in a
    # comment line.
    code = re.sub(r"(?m)^\s*#.*$", "", text).lower()
    forbidden = ["torch", "transformers", "scikit-learn", "rdkit", "pandas", "scipy", "numpy"]
    for pkg in forbidden:
        assert pkg not in code, (
            f"requirements/minimal-requirements.txt must not install {pkg!r}"
        )


def test_minimal_requirements_has_backend_runtime() -> None:
    """The minimal requirements must include the backend runtime deps."""
    text = MINIMAL_REQS.read_text().lower()
    required = ["fastapi", "uvicorn", "pydantic", "httpx", "python-dotenv", "biopython", "openai"]
    for pkg in required:
        assert pkg in text, (
            f"requirements/minimal-requirements.txt must include {pkg!r}"
        )


def test_environment_yaml_has_ml_deps() -> None:
    """environment.yaml should still contain the ML deps (the local target uses them)."""
    text = ENVIRONMENT_YAML.read_text().lower()
    # At least one of the heavy ML deps must be present.
    heavy = ["torch", "transformers", "scikit-learn", "rdkit"]
    has = [p for p in heavy if p in text]
    assert has, (
        f"environment.yaml must contain at least one of {heavy} for the local target"
    )


# ---------------------------------------------------------------------------
# bootstrap.py
# ---------------------------------------------------------------------------


def test_bootstrap_has_local_flag() -> None:
    """bootstrap.py must accept --local."""
    text = BOOTSTRAP.read_text()
    assert "--local" in text.split("def main()")[1], (
        "bootstrap.py must define --local so users can build the heavy image"
    )


def test_bootstrap_local_flag_passes_build_target() -> None:
    """The --local flag must result in ``--build-arg BUILD_TARGET=local``."""
    text = BOOTSTRAP.read_text()
    # The DEFAULT target is "minimal"; the --local flag sets it to "local".
    assert "BUILD_TARGET=build_target" in text or "BUILD_TARGET=build_target".lower() in text, (
        "bootstrap.py must pass BUILD_TARGET=<value> to docker build"
    )
    # The build_target arg must flow through to docker build.
    assert '"--build-arg"' in text
    assert "BUILD_TARGET" in text


def test_bootstrap_default_target_is_minimal() -> None:
    """Without --local, the build target must be 'minimal' (the slim image)."""
    text = BOOTSTRAP.read_text()
    assert '"minimal"' in text, (
        "bootstrap.py must default BUILD_TARGET to 'minimal' so the slim image is built"
    )


def test_bootstrap_persists_build_target_in_env() -> None:
    """When the user picks Local, the target must be saved to .env."""
    text = BOOTSTRAP.read_text()
    # The write_env_file function must write BUILD_TARGET.
    assert "BUILD_TARGET=" in text, (
        "bootstrap.py must persist BUILD_TARGET in .env"
    )
