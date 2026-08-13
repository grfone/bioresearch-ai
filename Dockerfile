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

# syntax=docker/dockerfile:1.6
FROM mambaorg/micromamba:1.5.6

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
    && rm -rf /var/lib/apt/lists/*

# Create the application directory.
WORKDIR /app

# Install the conda environment first so Docker can cache the layer.
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yaml /app/environment.yaml
RUN micromamba install -y -n base -f /app/environment.yaml \
    && micromamba clean -a -y

# Prepend conda's bin so all subsequent commands see python/uvicorn.
ENV PATH=/opt/conda/bin:$PATH
ENV PYTHONUNBUFFERED=1
# Tell pydantic settings to read from /app/.env (mounted by compose).
ENV PYTHONPATH=/app

# Install Node deps and build the frontend.
COPY --chown=$MAMBA_USER:$MAMBA_USER frontend/package.json frontend/package-lock.json* /app/frontend/
WORKDIR /app/frontend
RUN npm install --no-audit --no-fund
COPY --chown=$MAMBA_USER:$MAMBA_USER frontend /app/frontend
RUN npm run build

# Copy the rest of the backend and install it.
WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
# pip install --no-deps so we don't reinstall what's already in conda.
RUN pip install --no-cache-dir --no-deps -e .

# Switch back to the micromamba user (uid 1000) so the running container
# is not root.
USER $MAMBA_USER

EXPOSE 8000

# Healthcheck is intentionally simple: uvicorn's / endpoint always
# returns 200 when the app is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/ || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
