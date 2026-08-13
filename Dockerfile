# BioResearch AI — single-image build
#
# This Dockerfile produces a single image that contains:
# - The Python backend (FastAPI + uvicorn) installed via micromamba.
# - The React frontend prebuilt into frontend/dist.
# - The frontend is served by FastAPI itself at "/" so the entire app
#   is reachable on a single port (8000).
#
# The image is produced from the conda environment.yaml at the repo
# root so the runtime is reproducible across Linux, macOS, and Windows
# (when Docker Desktop is available).
#
# Network resilience
# ------------------
# Conda packages are downloaded from a configurable conda channel. The
# default is ``conda-forge.org/conda-forge`` (the channel's official
# host) which has a much better track record for international access
# than ``conda.anaconda.org``. Users on locked-down networks can pass
# a mirror at build time:
#
#     docker build --build-arg CONDA_CHANNEL=https://mirrors.tuna.tsinghua.edu.cn/conda-forge .
#     python3 bootstrap.py --mirror https://mirrors.tuna.tsinghua.edu.cn/conda-forge
#
# Popular mirrors:
# - https://conda-forge.org/conda-forge           (default; official)
# - https://mirrors.tuna.tsinghua.edu.cn/conda-forge   (China: TUNA)
# - https://mirrors.aliyun.com/conda-forge         (China: Aliyun)
# - https://conda.anaconda.org/conda-forge        (legacy fallback)
#
# The build also retries the solve up to three times with a back-off.
# The two conda steps are split so a transient failure of the solve
# does not require re-downloading the entire package set on the next run.

# syntax=docker/dockerfile:1.6
FROM mambaorg/micromamba:1.5.6

# Build-time channel configuration. Override with
# ``--build-arg CONDA_CHANNEL=<url>`` when you need a mirror.
ARG CONDA_CHANNEL=https://conda-forge.org/conda-forge

# Persist the channel choice into the runtime so any later commands
# (e.g. ``micromamba install`` at runtime) reuse the same mirror.
ENV CONDA_CHANNEL=${CONDA_CHANNEL}

# System packages we need beyond conda: Node.js for the frontend build,
# git for some pip packages, and curl for the credential probes.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
        procps \
        wget \
    && rm -rf /var/lib/apt/lists/*

# Create the application directory.
WORKDIR /app

# Tell micromamba to use the configured channel. The legacy behaviour
# of fetching ``repodata.json`` from the URL given here is what we want.
RUN mkdir -p /root/.conda && \
    echo "channels:" > /root/.conda/.condarc && \
    echo "  - ${CONDA_CHANNEL}" >> /root/.conda/.condarc && \
    echo "channel_priority: strict" >> /root/.conda/.condarc && \
    echo "show_channel_urls: true" >> /root/.conda/.condarc

# ---- Step 1: install only the heavy build-time deps first. ----
# This is split out so that if the network blips while downloading
# the first batch, the second batch doesn't have to re-download.
#
# The retry loop catches transient SSL / timeout errors that are
# common on slow or restrictive networks. The set +e / set -e dance
# lets us inspect the return code of micromamba while keeping the
# surrounding script's error handling off.
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yaml /app/environment.yaml
RUN set +e && \
    for attempt in 1 2 3; do \
        echo ">>> conda install attempt ${attempt}/3 from ${CONDA_CHANNEL}"; \
        micromamba install -y -n base \
            --channel "${CONDA_CHANNEL}" \
            --download-only \
            -f /app/environment.yaml && break; \
        rc=$?; \
        echo ">>> micromamba install failed with rc=${rc}"; \
        if [ "${attempt}" = "3" ]; then exit "${rc}"; fi; \
        echo ">>> sleeping 10s before retry..."; \
        sleep 10; \
    done

# ---- Step 2: actually link the packages into the environment. ----
# Linking is a local filesystem operation so it cannot fail with a
# network timeout. Splitting it from the download means a flaky
# network only ever re-downloads, never re-installs.
RUN set +e && \
    for attempt in 1 2 3; do \
        echo ">>> conda link attempt ${attempt}/3"; \
        micromamba install -y -n base \
            --offline \
            -f /app/environment.yaml && break; \
        rc=$?; \
        echo ">>> micromamba link failed with rc=${rc}"; \
        if [ "${attempt}" = "3" ]; then exit "${rc}"; fi; \
        sleep 5; \
    done && \
    micromamba clean -a -y

# Prepend conda's bin so all subsequent commands see python/uvicorn.
ENV PATH=/opt/conda/bin:$PATH
ENV PYTHONUNBUFFERED=1
# Tell pydantic settings to read from /app/.env (mounted by compose).
ENV PYTHONPATH=/app

# Install Node deps and build the frontend.
COPY --chown=$MAMBA_USER:$MAMBA_USER frontend/package.json frontend/package-lock.json* /app/frontend/
WORKDIR /app/frontend
# npm is also flaky on slow networks. Add a retry around the install.
RUN set +e && \
    for attempt in 1 2 3; do \
        echo ">>> npm install attempt ${attempt}/3"; \
        npm install --no-audit --no-fund && break; \
        rc=$?; \
        echo ">>> npm install failed with rc=${rc}"; \
        if [ "${attempt}" = "3" ]; then exit "${rc}"; fi; \
        sleep 5; \
    done
COPY --chown=$MAMBA_USER:$MAMBA_USER frontend /app/frontend
RUN npm run build

# Copy the rest of the backend and install it.
WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
# pip install --no-deps so we don't reinstall what's already in conda.
RUN pip install --no-cache-dir --no-deps -e .

# Switch back to the micromamba user (uid 1000) so the running
# container is not root.
USER $MAMBA_USER

EXPOSE 8000

# Healthcheck is intentionally simple: uvicorn's / endpoint always
# returns 200 when the app is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/ || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
