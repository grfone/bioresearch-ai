# syntax=docker/dockerfile:1.6
#
# Build arguments
# ---------------
# BUILD_TARGET selects which target of this multi-stage build to use.
# Values: "minimal" (default) or "local".
ARG BUILD_TARGET=minimal
# CONDA_CHANNEL is preserved for backwards compatibility but only
# consulted when BUILD_TARGET=local. The minimal target does not use
# conda at all.
ARG CONDA_CHANNEL=https://conda.anaconda.org/conda-forge

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
# Stage 2: minimal backend (default — no conda, no ML deps)
# ---------------------------------------------------------------------------
# Slim Python 3.12 base + pip install of the minimal backend
# requirements. Total image size: ~250 MB.
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
# the slim image — environment.yaml stays in the build context
# for the local target but is not copied into the slim image.
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
# Stage 3: local backend (heavy ML deps for offline use)
# ---------------------------------------------------------------------------
# This stage is only built when the user picks ``local`` in the
# bootstrap GUI. It uses the conda env to pull in torch, transformers,
# scikit-learn, rdkit, etc. — the deps that the user's research
# scripts and the local Ollama validation need.
FROM mambaorg/micromamba:1.5.6 AS backend-local

# Pull in the user's choice of mirror.
ARG CONDA_CHANNEL
ENV CONDA_CHANNEL=${CONDA_CHANNEL}

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
        procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set up the conda channel. The retry loop here is the same as before
# — bail out on 404 because that means the channel URL is wrong,
# not a transient failure.
RUN mkdir -p /root/.conda && \
    echo "channels:" > /root/.conda/.condarc && \
    echo "  - ${CONDA_CHANNEL}" >> /root/.conda/.condarc && \
    echo "channel_priority: strict" >> /root/.conda/.condarc

COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yaml /app/environment.yaml
RUN set +e && \
    for attempt in 1 2 3; do \
        echo ">>> conda install attempt ${attempt}/3 from ${CONDA_CHANNEL}"; \
        if micromamba install -y -n base \
                --channel "${CONDA_CHANNEL}" \
                --download-only \
                -f /app/environment.yaml; then break; fi; \
        echo ">>> micromamba download failed"; \
        if curl -sIL --max-time 10 "${CONDA_CHANNEL}/noarch/repodata.json" | grep -q " 404 "; then \
            echo ">>> FATAL: channel ${CONDA_CHANNEL} returned 404"; \
            exit 1; \
        fi; \
        if [ "${attempt}" = "3" ]; then exit 1; fi; \
        sleep 10; \
    done && \
    micromamba install -y -n base --offline -f /app/environment.yaml && \
    micromamba clean -a -y

# Frontend build (local image rebuilds; we still want no node_modules
# in the runtime layer).
COPY --chown=$MAMBA_USER:$MAMBA_USER frontend/package.json frontend/package-lock.json* /app/frontend/
WORKDIR /app/frontend
RUN set +e && \
    for attempt in 1 2 3; do \
        echo ">>> npm ci attempt ${attempt}/3"; \
        (cd /app/frontend && npm ci --no-audit --no-fund) && break; \
        sleep 5; \
    done
COPY --chown=$MAMBA_USER:$MAMBA_USER frontend /app/frontend
RUN npm run build

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
RUN pip install --no-cache-dir --no-deps -e .

ENV PATH=/opt/conda/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

USER $MAMBA_USER

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------
# The default target is the slim backend. The bootstrap script also
# accepts ``--local`` which builds the heavy backend-local target.
FROM backend-${BUILD_TARGET} AS final
