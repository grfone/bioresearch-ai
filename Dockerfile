# syntax=docker/dockerfile:1.6
#
# Build arguments
# ---------------
# BUILD_TARGET selects which target of this multi-stage build to use.
# Values: "minimal" (default) or "local".
#
# CONDA_CHANNEL is preserved as a build-arg for backwards
# compatibility. The current implementation does NOT use conda
# at all: pip pulls the wheels directly from PyPI. The flag is
# kept so ``bootstrap.py --mirror <url>`` still works, but it
# does not change the source.
ARG BUILD_TARGET=minimal
ARG CONDA_CHANNEL=https://conda.anaconda.org/conda-forge
# When the user has an NVIDIA GPU, the bootstrap sets this to the
# CUDA wheel index (e.g. https://download.pytorch.org/whl/cu121)
# so torch installs with GPU support. Empty -> CPU-only wheels.
ARG TORCH_INDEX_URL=

# ---------------------------------------------------------------------------
# Stage 1: build the React frontend
# ---------------------------------------------------------------------------
# This stage runs only at build time. It installs Node, runs npm
# install, builds the Vite bundle, and discards the entire
# node_modules (171 MB). The final image only contains the 2.4 MB
# dist/ directory.
FROM node:20-bookworm-slim AS frontend

WORKDIR /app/frontend

# Copy only the manifests first so this layer is cached when only
# source files change.
COPY frontend/package.json frontend/package-lock.json* ./

# npm is flaky on slow networks (chunks don't always finish). Retry
# up to three times.
RUN set -e && \
    for attempt in 1 2 3; do \
        echo ">>> npm ci attempt ${attempt}/3"; \
        npm ci --no-audit --no-fund && break; \
        echo ">>> npm ci failed, retrying..."; \
        sleep 5; \
    done

COPY frontend ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: minimal backend (default — no ML deps)
# ---------------------------------------------------------------------------
# Slim Python 3.12 base + pip install of the minimal backend
# requirements. Total image size: ~250 MB. This is the default for
# users who pick any cloud LLM (OpenAI, Anthropic, xAI, etc.).
FROM python:3.12-slim AS backend-minimal

# System packages we need beyond Python: curl for the credential
# probes and healthcheck, and build-essential for any wheels that
# need to compile (e.g. greenlet on some platforms).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the minimal backend deps. This is the hot path for the
# common case (cloud LLMs only).
COPY requirements/minimal-requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy only what the backend needs at runtime.
COPY --chown=app:app app /app/app
COPY --chown=app:app main.py pyproject.toml /app/
# The minimal requirements file is the only one we install from
# the slim image.
COPY --chown=app:app requirements/minimal-requirements.txt /app/requirements.txt

# Copy the prebuilt frontend bundle from the frontend stage.
COPY --from=frontend --chown=app:app /app/frontend/dist /app/frontend/dist

EXPOSE 8000

# Switch to a non-root user for runtime safety.
RUN useradd --create-home --shell /bin/bash app
USER app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------------------------------------------------------------------------
# Stage 3: local backend (heavy ML deps via pip — NO conda)
# ---------------------------------------------------------------------------
# This stage is only built when the user picks ``local`` in the
# bootstrap GUI. It installs the heavy ML deps (torch, transformers,
# scikit-learn, rdkit, etc.) via pip on top of the same slim
# Python 3.12 base. NO conda is used: we save ~2 GB of image
# weight and avoid the conda solver's slow downloads.
#
# Why no conda?
# ------------
# - conda + the conda-forge solver is slow and bandwidth-heavy.
# - PyTorch ships manylinux wheels on PyPI that work on
#   python:3.12-slim without compilation. No conda needed.
# - Ollama itself is a separate sidecar container with its own
#   binary; the BioResearch backend only talks to it via HTTP.
#   We don't need PyTorch at all to talk to Ollama — Ollama
#   handles the GPU runtime inside its own container.
#
# - For users who DO want their research scripts to work inside
#   the container (torch, transformers, rdkit, scikit-learn),
#   we install them via pip on the slim base. This makes the
#   local image about 1.2 GB (vs. 3 GB for the previous conda
#   build) and avoids the 404-prone conda channel entirely.
FROM python:3.12-slim AS backend-local

# System packages: build-essential for compiling numpy/pandas/scipy
# wheels from source when no wheel is available, curl for the
# credential probes and healthcheck, git for some pip packages
# (e.g. transformers), and tini for clean signal handling of the
# long-running pip install.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the minimal backend deps first, then layer the heavy ML
# deps on top. The install is split so a cache invalidation of one
# layer doesn't force re-download of the other.
# When TORCH_INDEX_URL is set (e.g. to the CUDA wheel index for
# GPU machines) we use it to install torch. When unset we fall
# back to the default PyPI CPU wheels.
ARG TORCH_INDEX_URL=

COPY requirements/minimal-requirements.txt /app/requirements.txt
COPY requirements/local-requirements.txt /app/local-requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && \
    if [ -n "${TORCH_INDEX_URL}" ]; then \
        pip install --no-cache-dir --index-url "${TORCH_INDEX_URL}" \
            torch torchvision; \
    else \
        pip install --no-cache-dir -r /app/local-requirements.txt; \
    fi

# Copy only what the backend needs at runtime.
COPY --chown=app:app app /app/app
COPY --chown=app:app main.py pyproject.toml /app/
COPY --chown=app:app requirements/minimal-requirements.txt /app/requirements.txt

# Copy the prebuilt frontend bundle from the frontend stage.
COPY --from=frontend --chown=app:app /app/frontend/dist /app/frontend/dist

EXPOSE 8000

# Switch to a non-root user for runtime safety.
RUN useradd --create-home --shell /bin/bash app
USER app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------
# The default target is the slim backend. The bootstrap script also
# accepts ``--local`` which builds the heavy backend-local target.
FROM backend-${BUILD_TARGET} AS final