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


# ---------------------------------------------------------------------------
# Phase 2 — Build the image
# ---------------------------------------------------------------------------


def build_image() -> None:
    """Build the bioresearch-ai image. Skips if the image already exists."""
    log_info("Building the BioResearch AI Docker image (this can take a few minutes)…")
    last_pct = -1
    rc = run_streaming(
        ["docker", "build", "-t", DOCKER_IMAGE, "."],
        cwd=REPO_ROOT,
        check=False,
    )
    if rc != 0:
        raise RuntimeError("Docker build failed; check the output above.")
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

    # LLM provider
    row = 2
    ttk.Label(root, text="LLM provider").grid(row=row, column=0, sticky="w", **pad)
    provider_var = tk.StringVar(value="openai")
    provider_combo = ttk.Combobox(
        root,
        textvariable=provider_var,
        values=("openai", "local"),
        state="readonly",
        width=20,
    )
    provider_combo.grid(row=row, column=1, sticky="ew", **pad)

    # API key
    row += 1
    ttk.Label(root, text="API key").grid(row=row, column=0, sticky="w", **pad)
    api_key_var = tk.StringVar()
    api_key_entry = ttk.Entry(root, textvariable=api_key_var, show="*", width=40)
    api_key_entry.grid(row=row, column=1, sticky="ew", **pad)

    # Base URL
    row += 1
    ttk.Label(root, text="Base URL").grid(row=row, column=0, sticky="w", **pad)
    base_url_var = tk.StringVar(value="https://api.openai.com/v1")
    ttk.Entry(root, textvariable=base_url_var).grid(
        row=row, column=1, sticky="ew", **pad
    )

    # Model
    row += 1
    ttk.Label(root, text="Model").grid(row=row, column=0, sticky="w", **pad)
    model_var = tk.StringVar(value="gpt-4.1-mini")
    model_combo = ttk.Combobox(
        root,
        textvariable=model_var,
        values=("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o",
                "claude-3-5-sonnet", "deepseek-chat"),
        width=40,
    )
    model_combo.grid(row=row, column=1, sticky="ew", **pad)

    # Local model
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
        is_local = provider_var.get() == "local"
        if is_local:
            api_key_entry.configure(state="disabled")
            base_url_var.set("http://host.docker.internal:11434/v1")
            model_var.set("local")
            model_combo.configure(state="disabled")
            local_model_combo.configure(state="readonly")
        else:
            api_key_entry.configure(state="normal")
            model_combo.configure(state="normal")
            local_model_combo.configure(state="disabled")

    provider_combo.bind("<<ComboboxSelected>>", on_provider_change)

    def on_test():
        status_var.set("Probing…")
        probe_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "probe_credentials.py"),
            "--llm",
            "local" if provider_var.get() == "local" else "openai",
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
        if provider_var.get() == "local":
            env["OLLAMA_BASE_URL"] = base_url_var.get().replace("/v1", "")
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
        if provider_var.get() == "openai" and not api_key_var.get().strip():
            messagebox.showerror(
                "Required", "API key is required for the OpenAI provider."
            )
            return
        config.llm_provider = provider_var.get()
        config.api_key = api_key_var.get().strip()
        config.base_url = base_url_var.get().strip()
        config.model = model_var.get().strip()
        config.pubmed_email = pubmed_email_var.get().strip()
        config.pubmed_api_key = pubmed_api_key_var.get().strip()
        config.selected_local_model = (
            local_model_var.get().strip()
            if provider_var.get() == "local"
            else None
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


def write_env_file(config: GuiConfig) -> None:
    """Persist the configuration to .env so next runs are silent."""
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
        "# PubMed",
        f"PUBMED_EMAIL={config.pubmed_email}",
        f"PUBMED_API_KEY={config.pubmed_api_key}",
        "",
        "# Database",
        "DATABASE_URL=sqlite:///./bioresearch.db",
        "",
    ]
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

    # 3. Build the image
    build_image()
    print()

    # 4. First-run GUI (unless --skip-gui)
    have_env = ENV_FILE.is_file()
    if args.skip_gui and have_env:
        log_info(f"Using existing {ENV_FILE}")
        config = GuiConfig()
        # Parse the existing .env so we know what to log.
        for raw in ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if k == "DEFAULT_LLM_PROVIDER":
                config.llm_provider = v
            elif k == "API_KEY":
                config.api_key = v
            elif k == "BASE_URL":
                config.base_url = v
            elif k == "DEFAULT_LLM_MODEL":
                config.model = v
            elif k == "PUBMED_EMAIL":
                config.pubmed_email = v
            elif k == "PUBMED_API_KEY":
                config.pubmed_api_key = v
            elif k == "OLLAMA_MODEL":
                config.selected_local_model = v
    else:
        config = _gui_collect_config(hw)
        write_env_file(config)
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
