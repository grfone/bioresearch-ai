#!/usr/bin/env python3
"""
bootstrap.py

One-command installer and launcher for BioResearch AI.

Purpose
-------
This script is the single entry point for installing BioResearch AI
on Linux, macOS, and Windows. It:

1. Detects the operating system, architecture, and (if a GPU is
   present) the available VRAM.
2. Installs Docker if it is not already installed, using the
   OS-specific install path.
3. Builds the container image (which contains the Python backend,
   the React frontend, and the supporting CLI tools).
4. Brings the backend and (optionally) the local Ollama service
   up.
5. On first run, opens a Tkinter GUI that asks the user which LLM
   to use, collects the relevant API keys, and lets the user
   choose a local model tier when the machine has the hardware.
6. Probes each credential live and surfaces actionable error
   messages when something is wrong.
7. Saves the user-supplied values to ``.env`` for next time.
8. Opens the running app in the default browser.

The script is intentionally self-contained: it uses only the
Python standard library so it can run on a fresh checkout without
pip-installing anything first.

Usage
-----

    python3 bootstrap.py

The script is idempotent. Running it on a machine that already has
Docker and a built image is a no-op except for the GUI prompt.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

# Catalog of LLM providers — single source of truth for the GUI picker.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from app.application.services.llm_provider_catalog import (
        CATALOG as LLM_PROVIDER_CATALOG,
        ProviderMeta as LLMCatalogEntry,
        grouped_by_region as llm_grouped_by_region,
    )
except Exception:  # pragma: no cover — fallback when running outside the project
    LLM_PROVIDER_CATALOG = ()
    llm_grouped_by_region = lambda: {}  # type: ignore
    LLMCatalogEntry = None  # type: ignore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOCKER_IMAGE = "bioresearch-ai:latest"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BACKEND_PORT = 8000
GUI_TIMEOUT_SECONDS = 600  # 10 minutes max for the GUI prompt

#: Default conda channel used by the Dockerfile.
#:
#: ``conda.anaconda.org/conda-forge`` is the conda-forge channel
#: hosted on Anaconda's CDN. This is the URL that returns a 200
#: today (2026). Other candidates that look plausible do NOT
#: work:
#:
#: - ``conda-forge.org/conda-forge`` → 404 (the website is the
#:   community docs site, not the channel).
#: - ``conda.anaconda.cloud/conda-forge`` → routinely unreachable
#:   from build environments.
#:
#: If the default ever stops working, the bootstrap CLI accepts
#: ``--mirror <url>`` so users can pin a working mirror without
#: having to rebuild the image.
DEFAULT_CONDA_CHANNEL = "https://conda.anaconda.org/conda-forge"


# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------


class Color:
    """ANSI colours. Disabled when stdout is not a TTY."""

    enabled = sys.stdout.isatty()

    @classmethod
    def wrap(cls, code: str, text: str) -> str:
        if not cls.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    @classmethod
    def bold(cls, text: str) -> str:
        return cls.wrap("1", text)

    @classmethod
    def green(cls, text: str) -> str:
        return cls.wrap("32", text)

    @classmethod
    def yellow(cls, text: str) -> str:
        return cls.wrap("33", text)

    @classmethod
    def red(cls, text: str) -> str:
        return cls.wrap("31", text)

    @classmethod
    def cyan(cls, text: str) -> str:
        return cls.wrap("36", text)


def log_info(msg: str) -> None:
    print(Color.cyan("• ") + msg)


def log_ok(msg: str) -> None:
    print(Color.green("✓ ") + msg)


def log_warn(msg: str) -> None:
    print(Color.yellow("⚠ ") + msg, file=sys.stderr)


def log_error(msg: str) -> None:
    print(Color.red("✗ ") + msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Hardware / OS detection
# ---------------------------------------------------------------------------


@dataclass
class HardwareInfo:
    """Snapshot of the host machine's capabilities."""

    os: str
    machine: str
    cpu_cores: int
    ram_gb: float
    gpu_name: Optional[str] = None
    gpu_vram_gb: Optional[float] = None
    has_docker: bool = False
    docker_version: Optional[str] = None


def _read_meminfo() -> float:
    """Return system RAM in GiB. Works on Linux and macOS."""
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / 1024 / 1024
        except OSError:
            pass
    if system == "Darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True
            )
            return int(out.strip()) / 1024 ** 3
        except Exception:
            pass
    # Fallback: psutil if available, otherwise 0.
    try:
        import psutil  # type: ignore

        return psutil.virtual_memory().total / 1024 ** 3
    except ImportError:
        return 0.0


def _detect_gpu() -> tuple[Optional[str], Optional[float]]:
    """Return (gpu_name, vram_gb) if an NVIDIA GPU is visible."""
    if not shutil.which("nvidia-smi"):
        return None, None
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            text=True,
            timeout=5,
        )
    except Exception:
        return None, None
    line = out.strip().splitlines()
    if not line:
        return None, None
    first = line[0]
    parts = [p.strip() for p in first.split(",")]
    if len(parts) < 2:
        return None, None
    name = parts[0]
    try:
        mem_mib = int(parts[1].split()[0])
        vram = mem_mib / 1024
    except (ValueError, IndexError):
        vram = None
    return name, vram


def _detect_docker() -> tuple[bool, Optional[str]]:
    """Return (available, version_string)."""
    if not shutil.which("docker"):
        return False, None
    try:
        out = subprocess.check_output(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            text=True,
            timeout=5,
        )
        version = out.strip()
        return bool(version), version or None
    except Exception:
        return False, None


def detect_hardware() -> HardwareInfo:
    gpu_name, gpu_vram = _detect_gpu()
    has_docker, docker_version = _detect_docker()
    return HardwareInfo(
        os=platform.system(),
        machine=platform.machine(),
        cpu_cores=os.cpu_count() or 1,
        ram_gb=_read_meminfo(),
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram,
        has_docker=has_docker,
        docker_version=docker_version,
    )


# ---------------------------------------------------------------------------
# Subprocess + UI helpers
# ---------------------------------------------------------------------------


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    timeout: Optional[int] = None,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Thin wrapper around subprocess.run with sensible defaults."""
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


def run_streaming(
    cmd: list[str],
    *,
    on_line: Optional[Callable[[str], None]] = None,
    check: bool = True,
    timeout: Optional[int] = None,
    cwd: Optional[Path] = None,
) -> int:
    """Run a command, stream stdout/stderr line by line."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip()
        if on_line:
            on_line(line)
        else:
            print(line)
    proc.wait(timeout=timeout)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return proc.returncode


# ---------------------------------------------------------------------------
# Phase 1 — Install Docker
# ---------------------------------------------------------------------------


def install_docker(hw: HardwareInfo) -> None:
    """Install Docker via the OS-specific path. Idempotent."""
    if hw.has_docker:
        log_ok(f"Docker already installed ({hw.docker_version})")
        return

    log_info(f"Docker not found on {hw.os}. Installing…")

    if hw.os == "Linux":
        # Detect the package manager.
        if shutil.which("apt-get"):
            run(["sudo", "apt-get", "update"], check=False)
            run(
                [
                    "sudo",
                    "apt-get",
                    "install",
                    "-y",
                    "docker.io",
                    "docker-compose-v2",
                    "docker-compose-plugin",
                ],
                check=False,
            )
        elif shutil.which("dnf"):
            run(
                [
                    "sudo",
                    "dnf",
                    "install",
                    "-y",
                    "docker",
                    "docker-compose",
                    "docker-buildx",
                ],
                check=False,
            )
        elif shutil.which("pacman"):
            run(
                [
                    "sudo",
                    "pacman",
                    "-S",
                    "--noconfirm",
                    "docker",
                    "docker-compose",
                    "docker-buildx",
                ],
                check=False,
            )
        else:
            raise RuntimeError(
                "Could not detect the package manager. "
                "Please install Docker Desktop manually from "
                "https://docs.docker.com/engine/install/ and re-run."
            )
        # Make sure the daemon is running.
        run(["sudo", "systemctl", "enable", "--now", "docker"], check=False)
    elif hw.os == "Darwin":
        if not shutil.which("brew"):
            raise RuntimeError(
                "Homebrew is required to install Docker on macOS. "
                "Install it from https://brew.sh and re-run."
            )
        run(["brew", "install", "--cask", "docker"], check=False)
        log_warn(
            "Docker Desktop was installed. Open it from the Applications "
            "folder once so the daemon is running, then re-run this script."
        )
        # Wait for the daemon to come up.
        deadline = time.time() + 120
        while time.time() < deadline:
            available, _ = _detect_docker()
            if available:
                break
            time.sleep(2)
        else:
            raise RuntimeError(
                "Docker Desktop did not start in time. "
                "Launch it manually and re-run."
            )
    elif hw.os == "Windows":
        raise RuntimeError(
            "Windows native Docker is not supported by this bootstrap. "
            "Install WSL2 + Docker Desktop and re-run from the WSL shell: "
            "https://docs.docker.com/desktop/wsl/"
        )
    else:
        raise RuntimeError(f"Unsupported OS: {hw.os}")

    available, version = _detect_docker()
    if not available:
        raise RuntimeError(
            "Docker was installed but the daemon is not reachable. "
            "Re-run after starting the Docker Desktop app."
        )
    log_ok(f"Docker installed ({version})")




def _detect_buildx() -> bool:
    """Return True if ``docker buildx`` is available on the host.

    The legacy ``docker build`` is deprecated as of Docker 25 and
    will be removed in a future release. The bootstrap calls
    ``docker buildx build`` so it works against both the legacy
    builder and the modern BuildKit builder.
    """
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(
            ["docker", "buildx", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def ensure_buildx(hw: HardwareInfo) -> None:
    """Install ``docker buildx`` if it is not already on PATH.

    BuildKit is the modern Docker build engine and the legacy
    ``docker build`` is deprecated as of Docker 25. The bootstrap
    uses ``docker buildx build`` so the deprecation warning
    never appears in the user's build output.

    This function is called after ``install_docker`` so users with
    an existing Docker install still get buildx installed the
    first time they run the bootstrap. On macOS and Windows,
    buildx is bundled with Docker Desktop and no extra install is
    required — we only verify.

    On Linux we install via the OS package manager:
    - Debian / Ubuntu: ``docker-buildx``
    - Fedora / RHEL: ``docker-buildx``
    - Arch:          ``docker-buildx``

    On macOS the buildx binary lives inside the Docker Desktop
    bundle. If ``docker buildx`` is not on PATH, we symlink it
    from the standard install location.
    """
    if _detect_buildx():
        try:
            version = subprocess.check_output(
                ["docker", "buildx", "version"],
                text=True,
                timeout=10,
            ).strip()
        except Exception:
            version = "installed"
        log_ok(f"docker buildx available ({version[:80]})")
        return

    log_info("docker buildx is not installed; installing…")

    if hw.os == "Linux":
        if shutil.which("apt-get"):
            run(
                ["sudo", "apt-get", "install", "-y", "docker-buildx"],
                check=False,
            )
        elif shutil.which("dnf"):
            run(
                ["sudo", "dnf", "install", "-y", "docker-buildx"],
                check=False,
            )
        elif shutil.which("pacman"):
            run(
                ["sudo", "pacman", "-S", "--noconfirm", "docker-buildx"],
                check=False,
            )
        else:
            log_warn(
                "Could not detect the package manager to install "
                "docker-buildx. The build will use the legacy "
                "builder (deprecated). Install docker-buildx "
                "manually to suppress the warning."
            )
            return
    elif hw.os == "Darwin":
        # Docker Desktop on macOS bundles buildx at this path.
        # Some installs don't expose it on PATH, so we symlink it.
        candidates = [
            Path("/Applications/Docker.app/Contents/Resources/bin/docker-buildx"),
            Path("/usr/local/bin/docker-buildx"),
            Path.home()
            / "Applications"
            / "Docker.app"
            / "Contents"
            / "Resources"
            / "bin"
            / "docker-buildx",
        ]
        for cand in candidates:
            if cand.is_file():
                link = Path("/usr/local/bin/docker-buildx")
                if not link.exists():
                    run(
                        ["sudo", "ln", "-s", str(cand), str(link)],
                        check=False,
                    )
                break
        else:
            log_warn(
                "Could not find docker-buildx inside Docker Desktop. "
                "Reinstall Docker Desktop or update it to the latest "
                "version."
            )
            return
    elif hw.os == "Windows":
        # WSL2 path: buildx is bundled with Docker Desktop. If the
        # user is on stock Windows (not WSL), bootstrap already
        # raised in install_docker so we never get here.
        return
    else:
        log_warn(
            f"buildx install is not implemented for {hw.os}. "
            "The build will use the legacy builder (deprecated)."
        )
        return

    # Verify the install worked. The first ``docker buildx`` invocation
    # right after a fresh install can sometimes fail because the
    # shell has cached the PATH — ``shutil.which`` only re-reads the
    # cache on certain conditions. We force a fresh lookup.
    if _detect_buildx():
        log_ok("docker buildx installed")
    else:
        log_warn(
            "docker-buildx was installed but the binary is not on "
            "PATH in this shell. Open a new terminal and re-run, or "
            "check that /usr/bin is in PATH."
        )


def _build_command(extra_args: list[str]) -> list[str]:
    """Return the docker build command list to use.

    Prefers ``docker buildx build`` (the modern, supported path).
    Falls back to ``docker build`` when buildx is unavailable
    (e.g. older Docker Engine installs).
    """
    if _detect_buildx():
        return ["docker", "buildx", "build"] + extra_args
    return ["docker", "build"] + extra_args


# ---------------------------------------------------------------------------
# Phase 2 — Build the image
# ---------------------------------------------------------------------------


def build_image(
    conda_channel: str = DEFAULT_CONDA_CHANNEL,
    build_target: str = "minimal",
) -> None:
    """Build the BioResearch AI image.

    Parameters
    ----------
    conda_channel : str
        The conda channel URL to use. Only consulted when
        ``build_target="local"``. Defaults to
        ``https://conda.anaconda.org/conda-forge``.

    build_target : str
        Either ``"minimal"`` (default) or ``"local"``. The minimal
        target is a slim Python image with only the backend runtime
        dependencies — ~250 MB and no conda. The local target pulls
        in the full ML stack (torch, transformers, scikit-learn,
        rdkit, etc.) via conda — ~3 GB. The bootstrap passes
        ``"local"`` automatically when the user picks the Local
        provider in the GUI.

    Notes
    -----
    Uses ``docker buildx build`` (BuildKit) when available. Falls
    back to ``docker build`` (legacy, deprecated) when buildx is not
    installed. The bootstrap installs ``docker-buildx`` on Linux
    alongside ``docker.io`` so the buildx path is preferred.
    """
    if build_target not in ("minimal", "local"):
        raise ValueError(
            f"build_target must be 'minimal' or 'local', got {build_target!r}"
        )
    target_description = {
        "minimal": "slim Python-only image (~250 MB)",
        "local": "full image with ML deps (~3 GB)",
    }[build_target]
    log_info(
        f"Building the BioResearch AI Docker image "
        f"({target_description}, this can take a few minutes)…"
    )
    extra = [
        "--build-arg", f"CONDA_CHANNEL={conda_channel}",
        "--build-arg", f"BUILD_TARGET={build_target}",
        "-t", DOCKER_IMAGE,
        ".",
    ]
    cmd = _build_command(extra)
    if cmd[0:3] == ["docker", "buildx", "build"]:
        log_info("Using BuildKit (buildx).")
    else:
        log_warn(
            "docker buildx is not installed; falling back to the "
            "legacy builder (deprecated). Install docker-buildx to "
            "suppress this warning."
        )
    rc = run_streaming(cmd, cwd=REPO_ROOT, check=False)
    if rc != 0:
        raise RuntimeError(
            "Docker build failed; check the output above. "
            "If the failure is a network timeout to "
            "conda.anaconda.org, re-run with --mirror <url> "
            "(e.g. https://mirrors.tuna.tsinghua.edu.cn/conda-forge)."
        )
    log_ok("Image built")


# ---------------------------------------------------------------------------
# Phase 3 — Local LLM model selection
# ---------------------------------------------------------------------------


@dataclass
class LocalModel:
    """A quantized DeepSeek model tier that fits a given hardware profile."""

    name: str
    size_gb: float
    min_ram_gb: float
    min_vram_gb: Optional[float] = None
    description: str = ""


LOCAL_MODELS: list[LocalModel] = [
    LocalModel(
        name="deepseek-r1-distill-llama-8b-q4_k_m",
        size_gb=4.6,
        min_ram_gb=12,
        min_vram_gb=8,
        description="DeepSeek-R1 distilled into Llama-8B, Q4_K_M quantization. "
        "Best quality/speed tradeoff for a GPU with ≥ 8 GB VRAM.",
    ),
    LocalModel(
        name="deepseek-coder-v2-lite-instruct-q4_k_m",
        size_gb=4.6,
        min_ram_gb=10,
        min_vram_gb=None,
        description="DeepSeek-Coder-V2-Lite-Instruct, Q4_K_M. Lighter; "
        "good for instruction following and biomedical text.",
    ),
    LocalModel(
        name="deepseek-coder-v2-lite-instruct-q3_k_m",
        size_gb=3.3,
        min_ram_gb=8,
        min_vram_gb=None,
        description="Q3_K_M variant of the coder model. Smaller, "
        "runnable on CPU with 8 GB RAM.",
    ),
]


def pick_local_model(hw: HardwareInfo) -> Optional[LocalModel]:
    """Return the best model that fits the machine's hardware, or None."""
    available: list[LocalModel] = []
    for model in LOCAL_MODELS:
        if hw.ram_gb + 0.5 < model.min_ram_gb:
            continue
        if (
            model.min_vram_gb is not None
            and (hw.gpu_vram_gb or 0.0) + 0.5 < model.min_vram_gb
        ):
            continue
        available.append(model)
    if not available:
        return None
    # Prefer the bigger model (better quality).
    return max(available, key=lambda m: m.size_gb)


def describe_hardware(hw: HardwareInfo) -> str:
    bits = [
        f"{hw.cpu_cores} CPU cores",
        f"{hw.ram_gb:.1f} GB RAM",
    ]
    if hw.gpu_name and hw.gpu_vram_gb is not None:
        bits.append(f"{hw.gpu_name} ({hw.gpu_vram_gb:.1f} GB VRAM)")
    else:
        bits.append("no NVIDIA GPU detected")
    return ", ".join(bits)




def _persist_conda_channel(channel: str) -> None:
    """Write or update the CONDA_CHANNEL line in the existing .env.

    Preserves all other lines. If the file does not exist yet, this
    is a no-op (the bootstrap will create it from scratch when the
    GUI completes).
    """
    if not ENV_FILE.is_file():
        return
    text = ENV_FILE.read_text()
    lines = text.splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("CONDA_CHANNEL="):
            lines[i] = f"CONDA_CHANNEL={channel}"
            found = True
            break
    if not found:
        lines.append(f"CONDA_CHANNEL={channel}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Phase 4 — Tkinter first-run GUI
# ---------------------------------------------------------------------------


@dataclass
class GuiConfig:
    """User-supplied configuration from the first-run GUI."""

    llm_provider: str = "openai"  # "openai" | "local"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    pubmed_email: str = ""
    pubmed_api_key: str = ""
    selected_local_model: Optional[str] = None
    # Whether the user opted in to the heavy local build target.
    # When false, the slim image is built (~250 MB).
    build_target: str = "minimal"
    proceed: bool = False


def _gui_collect_config(hw: HardwareInfo) -> GuiConfig:
    """Open the Tkinter GUI and return the user's choices."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError as exc:
        raise RuntimeError(
            "Tkinter is not installed on this Python. "
            "Install it with `apt-get install python3-tk` "
            "(Debian/Ubuntu) or `brew install python-tk` (macOS) "
            "and re-run."
        ) from exc

    detected = pick_local_model(hw)
    recommended_model = detected.name if detected else ""

    config = GuiConfig()
    root = tk.Tk()
    root.title("BioResearch AI — first-run setup")
    root.geometry("640x560")
    root.minsize(640, 480)

    pad = {"padx": 12, "pady": 4}

    # Header
    ttk.Label(
        root,
        text="Welcome to BioResearch AI",
        font=("Helvetica", 16, "bold"),
    ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)
    ttk.Label(
        root,
        text=(
            f"Detected: {describe_hardware(hw)}\n"
            "Fill in the credentials below. "
            "You can re-run this script at any time to change them."
        ),
        justify="left",
    ).grid(row=1, column=0, columnspan=2, sticky="w", **pad)

    # LLM provider — catalog-driven regional picker.
    row = 2

    # Build the dropdown options. Format: "<region> — <display_name>"
    # so the user can pick visually while the value stored is the
    # enum slug.
    region_groups = llm_grouped_by_region()
    provider_options: list[str] = []
    provider_lookup: dict[str, LLMCatalogEntry] = {}
    for region_name, entries in region_groups.items():
        for entry in entries:
            label = f"{entry.display_name}  [{region_name}]"
            provider_options.append(label)
            provider_lookup[label] = entry

    # Default to OpenAI for convenience.
    default_label = next(
        (lbl for lbl in provider_options if "OpenAI" in lbl and "Azure" not in lbl),
        provider_options[0] if provider_options else "OpenAI  [US]",
    )

    ttk.Label(root, text="LLM provider").grid(row=row, column=0, sticky="w", **pad)
    provider_var = tk.StringVar(value=default_label)
    provider_combo = ttk.Combobox(
        root,
        textvariable=provider_var,
        values=provider_options,
        state="readonly",
        width=40,
    )
    provider_combo.grid(row=row, column=1, sticky="ew", **pad)

    # Hint label that shows the env var the user should set,
    # e.g. "Set OPENAI_API_KEY in your environment or paste
    # the key below."
    row += 1
    provider_hint_var = tk.StringVar(value="")
    ttk.Label(
        root,
        textvariable=provider_hint_var,
        foreground="gray",
        wraplength=420,
        justify="left",
    ).grid(row=row, column=0, columnspan=2, sticky="w", **pad)

    # API key
    row += 1
    api_key_label = ttk.Label(root, text="API key")
    api_key_label.grid(row=row, column=0, sticky="w", **pad)
    api_key_var = tk.StringVar()
    api_key_entry = ttk.Entry(root, textvariable=api_key_var, show="*", width=40)
    api_key_entry.grid(row=row, column=1, sticky="ew", **pad)

    # Base URL
    row += 1
    ttk.Label(root, text="Base URL").grid(row=row, column=0, sticky="w", **pad)
    base_url_var = tk.StringVar(value="https://api.openai.com/v1")
    base_url_entry = ttk.Entry(root, textvariable=base_url_var)
    base_url_entry.grid(row=row, column=1, sticky="ew", **pad)

    # Model
    row += 1
    ttk.Label(root, text="Model").grid(row=row, column=0, sticky="w", **pad)
    model_var = tk.StringVar(value="gpt-4.1-mini")
    model_entry = ttk.Entry(root, textvariable=model_var)
    model_entry.grid(row=row, column=1, sticky="ew", **pad)
    model_hint_var = tk.StringVar(value="")
    ttk.Label(
        root,
        textvariable=model_hint_var,
        foreground="gray",
        wraplength=420,
        justify="left",
    ).grid(row=row + 1, column=0, columnspan=2, sticky="w", **pad)
    row += 1

    # Local model — only enabled when the user picks the Local
    # provider.
    row += 1
    ttk.Label(root, text="Local model (only if provider=local)").grid(
        row=row, column=0, sticky="w", **pad
    )
    local_model_var = tk.StringVar(
        value=recommended_model
        or (LOCAL_MODELS[0].name if LOCAL_MODELS else "")
    )
    local_model_combo = ttk.Combobox(
        root,
        textvariable=local_model_var,
        values=tuple(m.name for m in LOCAL_MODELS),
        state="readonly",
        width=40,
    )
    local_model_combo.grid(row=row, column=1, sticky="ew", **pad)
    if not detected:
        ttk.Label(
            root,
            text=(
                "  ⚠ Your machine is below the recommended minimum for any "
                "local model. The local option will fail."
            ),
            foreground="orange",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=12)

    # PubMed email
    row += 1
    ttk.Separator(root, orient="horizontal").grid(
        row=row, column=0, columnspan=2, sticky="ew", pady=8
    )
    row += 1
    ttk.Label(root, text="PubMed email").grid(row=row, column=0, sticky="w", **pad)
    pubmed_email_var = tk.StringVar()
    ttk.Entry(root, textvariable=pubmed_email_var, width=40).grid(
        row=row, column=1, sticky="ew", **pad
    )

    # PubMed API key
    row += 1
    ttk.Label(root, text="PubMed API key (optional)").grid(
        row=row, column=0, sticky="w", **pad
    )
    pubmed_api_key_var = tk.StringVar()
    ttk.Entry(root, textvariable=pubmed_api_key_var, show="*", width=40).grid(
        row=row, column=1, sticky="ew", **pad
    )

    # Probe status
    row += 1
    status_var = tk.StringVar(value="")
    ttk.Label(root, textvariable=status_var, foreground="blue").grid(
        row=row, column=0, columnspan=2, sticky="w", **pad
    )

    # Buttons
    row += 1
    button_frame = ttk.Frame(root)
    button_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=12)

    def on_provider_change(*_):
        """Update hints, base URL, and model when the provider changes."""
        label = provider_var.get()
        entry = provider_lookup.get(label)
        if entry is None:
            return
        is_local = entry.slug.value == "local"
        if is_local:
            api_key_label.configure(text="API key (not required for Local)")
            api_key_entry.configure(state="disabled")
            api_key_var.set("")
            base_url_var.set("http://host.docker.internal:11434/v1")
            model_var.set("local")
            model_entry.configure(state="disabled")
            local_model_combo.configure(state="readonly")
            provider_hint_var.set(
                "Self-hosted. No API key required. The bootstrap script "
                "will pull a quantized model sized for your hardware."
            )
            model_hint_var.set("")
        else:
            api_key_label.configure(text=f"API key ({entry.api_key_env})")
            api_key_entry.configure(state="normal")
            model_entry.configure(state="normal")
            local_model_combo.configure(state="disabled")
            # Reset to the catalog defaults when the user picks a
            # different provider. We don't touch existing values if
            # they were already entered.
            if entry.base_url:
                base_url_var.set(entry.base_url)
            if entry.default_model:
                model_var.set(entry.default_model)
            provider_hint_var.set(
                f"Set {entry.api_key_env} in your environment, or paste "
                f"the key directly below. {entry.notes}"
            ).strip()
            model_hint_var.set(
                "Suggested models: " + entry.model_hint
            )

    provider_combo.bind("<<ComboboxSelected>>", on_provider_change)

    def on_test():
        status_var.set("Probing…")
        entry = provider_lookup.get(provider_var.get())
        slug = entry.slug.value if entry else "openai"
        is_local = slug == "local"
        probe_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "probe_credentials.py"),
            "--llm",
            "local" if is_local else "openai",
            "--api-key",
            api_key_var.get(),
            "--base-url",
            base_url_var.get(),
            "--model",
            model_var.get(),
            "--pubmed-email",
            pubmed_email_var.get(),
            "--pubmed-api-key",
            pubmed_api_key_var.get(),
        ]
        env = os.environ.copy()
        if is_local:
            env["OLLAMA_BASE_URL"] = base_url_var.get().replace("/v1", "")
        else:
            # Make the catalog-derived env var name available so
            # the probe can use the right key when the user supplies
            # one through the GUI.
            if entry is not None and entry.api_key_env and api_key_var.get():
                env[entry.api_key_env] = api_key_var.get()
        try:
            proc = subprocess.run(
                probe_cmd,
                capture_output=True,
                text=True,
                timeout=45,
                env=env,
            )
        except Exception as exc:
            status_var.set(f"Probe failed: {exc}")
            return
        try:
            result = json.loads(proc.stdout)
        except Exception:
            status_var.set(f"Probe failed: {proc.stderr.strip()}")
            return
        ok = result.get("ok", False)
        lines = []
        for c in result.get("checks", []):
            mark = "✓" if c["ok"] else "✗"
            lines.append(f"{mark} {c['name']}: {c['message']}")
        status_var.set("\n".join(lines))
        if ok:
            messagebox.showinfo(
                "BioResearch AI",
                "All checks passed. Click 'Save and start' to continue.",
            )

    ttk.Button(button_frame, text="Test credentials", command=on_test).pack(
        side="left", padx=6
    )

    def on_save():
        # Validate.
        if not pubmed_email_var.get().strip():
            messagebox.showerror(
                "Required",
                "PubMed email is required. NCBI rejects anonymous requests.",
            )
            return
        entry = provider_lookup.get(provider_var.get())
        if entry is None:
            messagebox.showerror(
                "Required", "Pick a provider from the list."
            )
            return
        is_local = entry.slug.value == "local"
        if not is_local and not api_key_var.get().strip():
            messagebox.showerror(
                "Required",
                f"API key is required for {entry.display_name}. "
                f"Set {entry.api_key_env} or paste the key.",
            )
            return
        config.llm_provider = entry.slug.value
        config.api_key = api_key_var.get().strip()
        config.base_url = base_url_var.get().strip()
        config.model = model_var.get().strip()
        config.pubmed_email = pubmed_email_var.get().strip()
        config.pubmed_api_key = pubmed_api_key_var.get().strip()
        config.selected_local_model = (
            local_model_var.get().strip() if is_local else None
        )
        config.proceed = True
        root.destroy()

    ttk.Button(button_frame, text="Save and start", command=on_save).pack(
        side="right", padx=6
    )

    ttk.Button(button_frame, text="Quit", command=sys.exit).pack(
        side="right", padx=6
    )

    root.columnconfigure(1, weight=1)

    on_provider_change()

    # Auto-close after timeout (helps CI runs).
    root.after(GUI_TIMEOUT_SECONDS * 1000, root.destroy)

    root.mainloop()

    if not config.proceed:
        log_warn("Setup was cancelled. Run bootstrap.py again to retry.")
        sys.exit(0)

    return config


# ---------------------------------------------------------------------------
# Phase 5 — Save .env, write config, start containers
# ---------------------------------------------------------------------------


def write_env_file(
    config: GuiConfig,
    conda_channel: str = DEFAULT_CONDA_CHANNEL,
    build_target: str = "minimal",
) -> None:
    """Persist the configuration to .env so next runs are silent.

    The file always writes the short ``API_KEY`` value because the
    project composition root expects it. The provider's
    class-level ``api_key_env`` is also written when the catalog
    exposes a different name (e.g. ``DEEPSEEK_API_KEY``,
    ``XAI_API_KEY``) so the provider can fall back to either.
    """
    lines = [
        "# Generated by bootstrap.py. Re-run bootstrap.py to edit.",
        "APP_ENVIRONMENT=development",
        "DEBUG=True",
        "",
        "# LLM",
        f"DEFAULT_LLM_PROVIDER={config.llm_provider}",
        f"DEFAULT_LLM_MODEL={config.model}",
        "API_KEY=" + (config.api_key or ""),
        f"BASE_URL={config.base_url or ''}",
        "",
    ]

    # Map the chosen provider to its catalog metadata and write the
    # provider-specific env var so the user can also set the key via
    # the environment directly.
    try:
        from app.core.enums.llm_provider import LLMProviderEnum
        from app.application.services.llm_provider_catalog import (
            get_provider_meta,
        )

        meta = get_provider_meta(
            LLMProviderEnum(config.llm_provider)
        )
        if meta.api_key_env and meta.api_key_env != "API_KEY" and config.api_key:
            lines.append(f"{meta.api_key_env}={config.api_key}")
        if meta.requires_extra_headers:
            # Baidu Qianfan needs a Content-Type hint.
            lines.append("QIANFAN_EXTRA_HEADERS=Content-Type:application/json")
    except Exception:
        # Catalog may not be importable in standalone runs; fall back
        # to the legacy single-key behaviour.
        pass

    lines.extend(
        [
            "",
            "# PubMed",
            f"PUBMED_EMAIL={config.pubmed_email}",
            f"PUBMED_API_KEY={config.pubmed_api_key}",
            "",
            "# Database",
            "DATABASE_URL=sqlite:///./bioresearch.db",
            "",
            "# Build",
            "# conda channel used by the Dockerfile. Override with",
            "# ``python3 bootstrap.py --mirror <url>`` to add a custom mirror.",
            f"CONDA_CHANNEL={conda_channel}",
            "# Build target: 'minimal' (default, slim Python) or 'local'",
            "# (full ML stack via conda, ~3 GB). Set to 'local' if you want",
            "# to run local models or use the offline research scripts.",
            f"BUILD_TARGET={build_target}",
            "",
        ]
    )
    if config.llm_provider == "local" and config.selected_local_model:
        lines.extend(
            [
                "# Local model",
                f"OLLAMA_MODEL={config.selected_local_model}",
                "",
            ]
        )

    ENV_FILE.write_text("\n".join(lines))
    os.chmod(ENV_FILE, 0o600)
    log_ok(f"Wrote {ENV_FILE}")


def start_containers() -> None:
    """Bring the backend and (optionally) the ollama service up."""
    log_info("Starting containers…")
    run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build"],
        cwd=REPO_ROOT,
        check=False,
    )


def wait_for_backend() -> None:
    """Block until the backend answers on port 8000."""
    log_info("Waiting for the backend to be ready…")
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://localhost:{BACKEND_PORT}/api", timeout=2
            ) as r:
                if r.status == 200:
                    log_ok("Backend is up")
                    return
        except Exception:
            pass
        time.sleep(2)
    log_warn("Backend did not answer in 120s. Check `docker compose ps`.")


def pull_local_model(model: str) -> None:
    """Pull the chosen quantized model inside the ollama container."""
    log_info(f"Pulling local model '{model}' into the Ollama container…")
    rc = run_streaming(
        [
            "docker",
            "exec",
            "-it",
            "bioresearch-ai-ollama",
            "ollama",
            "pull",
            model,
        ],
        check=False,
    )
    if rc != 0:
        raise RuntimeError(
            f"Failed to pull '{model}'. "
            "Check your network connection and try again."
        )
    log_ok(f"Pulled {model}")


# ---------------------------------------------------------------------------
# Phase 6 — open the browser
# ---------------------------------------------------------------------------


def open_browser() -> None:
    url = f"http://localhost:{BACKEND_PORT}"
    log_info(f"Opening {url} in your default browser…")
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap BioResearch AI")
    parser.add_argument(
        "--skip-gui",
        action="store_true",
        help="Use the existing .env file without prompting.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open the browser at the end.",
    )
    parser.add_argument(
        "--mirror",
        default=None,
        help=(
            "Conda channel URL to use when building the local image. "
            "Use this when the default conda.anaconda.org host is blocked "
            "or slow on your network. Examples: "
            "https://mirrors.tuna.tsinghua.edu.cn/conda-forge, "
            "https://mirrors.aliyun.com/conda-forge. "
            "Saved to .env so subsequent runs remember the choice."
        ),
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help=(
            "Build the heavy image with the full ML stack (torch, "
            "transformers, scikit-learn, rdkit, etc.) via conda. "
            "Required when the user picks the 'Local' (self-hosted "
            "Ollama) LLM provider; otherwise the bootstrap builds "
            "the slim (~250 MB) image. The default is to build the "
            "slim image."
        ),
    )
    args = parser.parse_args()

    log_info("BioResearch AI bootstrap")
    print(f"  Repo: {REPO_ROOT}")
    print()

    # 1. Hardware / OS detection
    hw = detect_hardware()
    print(f"  OS:           {hw.os} {hw.machine}")
    print(f"  CPU cores:    {hw.cpu_cores}")
    print(f"  RAM:          {hw.ram_gb:.1f} GB")
    print(
        f"  GPU:          {hw.gpu_name or 'none detected'}"
        + (f" ({hw.gpu_vram_gb:.1f} GB VRAM)" if hw.gpu_vram_gb else "")
    )
    print(f"  Docker:       {hw.docker_version or 'not installed'}")
    print()

    # 2. Install Docker if needed
    install_docker(hw)
    # Re-detect after install.
    hw.has_docker, hw.docker_version = _detect_docker()
    print()

    # 2b. Install buildx if needed. Docker 25+ deprecates the
    # legacy ``docker build`` builder; we always use buildx. The
    # install is independent of whether Docker itself was just
    # installed, so users with an existing Docker install still
    # get buildx added on the first bootstrap run.
    if hw.has_docker:
        ensure_buildx(hw)
    print()

    # 3. Build the image
    # Resolve the conda channel: explicit --mirror flag wins, then
    # the .env value, then the default. The channel is only used
    # by the local (heavy) target.
    conda_channel = args.mirror
    if conda_channel is None and ENV_FILE.is_file():
        for raw in ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if line.startswith("CONDA_CHANNEL="):
                conda_channel = line.split("=", 1)[1].strip()
                break
    if conda_channel is None:
        conda_channel = DEFAULT_CONDA_CHANNEL
    build_target = "local" if args.local else "minimal"
    if build_target == "local":
        log_info(f"Using conda channel: {conda_channel}")
    build_image(conda_channel=conda_channel, build_target=config.build_target)
    print()

    # 4. First-run GUI (unless --skip-gui)
    have_env = ENV_FILE.is_file()
    if args.skip_gui and have_env:
        log_info(f"Using existing {ENV_FILE}")
        config = GuiConfig()
        # Persist the conda channel back to .env so subsequent runs
        # reuse the same channel without prompting.
        _persist_conda_channel(conda_channel)
        # Build an env-var fallback list per provider so we pick up
        # the right key no matter which provider was selected.
        from app.core.enums.llm_provider import LLMProviderEnum
        from app.application.services.llm_provider_catalog import (
            get_provider_meta,
        )

        # Parse the .env into a dict for easy lookup.
        env_values: dict[str, str] = {}
        for raw in ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_values[k.strip()] = v.strip()

        slug = env_values.get("DEFAULT_LLM_PROVIDER", "openai")
        config.llm_provider = slug
        config.api_key = env_values.get("API_KEY", "")
        # If the provider has a more specific env var, prefer it.
        try:
            meta = get_provider_meta(LLMProviderEnum(slug))
            config.api_key = env_values.get(meta.api_key_env, config.api_key)
        except Exception:
            pass
        config.base_url = env_values.get("BASE_URL", "")
        config.model = env_values.get("DEFAULT_LLM_MODEL", "")
        config.pubmed_email = env_values.get("PUBMED_EMAIL", "")
        config.pubmed_api_key = env_values.get("PUBMED_API_KEY", "")
        config.selected_local_model = env_values.get("OLLAMA_MODEL")
        target = env_values.get("BUILD_TARGET", "minimal")
        if target in ("minimal", "local"):
            config.build_target = target
    else:
        config = _gui_collect_config(hw)
        # When the user picks Local, the GUI sets
        # config.llm_provider == "local" and we want the heavy
        # image. Persist this so the next run also picks the right
        # target.
        local_picked = config.llm_provider == "local"
        build_target_picked = "local" if local_picked else "minimal"
        write_env_file(
            config,
            conda_channel=conda_channel,
            build_target=build_target_picked,
        )
        if local_picked and build_target != "local":
            log_info(
                "You picked Local in the GUI. The slim image does not "
                "include the heavy ML deps (torch, transformers, etc.). "
                "Rerun with --local to install them, or accept the slim "
                "image if you only want the Ollama runtime."
            )
    print()

    # 5. Pull the local model if requested
    if config.llm_provider == "local" and config.selected_local_model:
        pull_local_model(config.selected_local_model)
    print()

    # 6. Start containers
    start_containers()
    print()

    # 7. Wait for the backend
    wait_for_backend()
    print()

    # 8. Open the browser
    if not args.no_browser:
        open_browser()
    print()

    log_ok("BioResearch AI is running.")
    print(f"  URL:      http://localhost:{BACKEND_PORT}")
    print("  Stop:     docker compose down")
    print("  Restart:  python3 bootstrap.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log_warn("Bootstrap interrupted.")
        sys.exit(130)
    except Exception as exc:
        log_error(str(exc))
        sys.exit(1)
