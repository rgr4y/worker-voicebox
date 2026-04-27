# Voicebox TTS Server
# CUDA 12.9 + Python 3.12 on Ubuntu 24.04
#
# Build:
#   DOCKER_BUILDKIT=1 docker build -t voicebox .
#   DOCKER_BUILDKIT=1 docker build --build-arg CUDA=0 -t voicebox-cpu .
#   DOCKER_BUILDKIT=1 docker build --build-arg SERVERLESS=1 -t voicebox-serverless .
#
# Run:
#   docker compose up -d
#
# syntax=docker/dockerfile:1.4

ARG CUDA=1
ARG SERVERLESS=0

# --- Base stage ---
FROM nvidia/cuda:12.9.1-runtime-ubuntu24.04 AS base-cuda
FROM ubuntu:24.04 AS base-cpu

# --- Pick base based on CUDA arg --
FROM base-cuda AS base-1
FROM base-cpu AS base-0
FROM base-${CUDA} AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HUB_ENABLE_HF_TRANSFER=1

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-dev \
    python3-pip \
    libsndfile1 \
    ffmpeg \
    curl \
    sox \
    zsh \
    && rm -rf /var/lib/apt/lists/*

# --- Dependencies stage (cached layer) ---
FROM base AS deps

ARG CUDA
ARG DEV_VENV=0
WORKDIR /app

# If DEV_VENV=1 (build arg), skip building /opt/venv entirely — the host venv at
# /app/backend/venv will be used instead (volume-mounted at runtime via docker-entrypoint.sh).
# If DEV_VENV=0 (default), build the full /opt/venv for production use.
COPY backend/requirements-linux.txt ./requirements-linux.txt

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    if [ "$DEV_VENV" = "0" ]; then \
        python3 -m venv /opt/venv && \
        /opt/venv/bin/pip install --upgrade pip && \
        if [ "$CUDA" = "1" ]; then \
            /opt/venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 && \
            /opt/venv/bin/pip install -r requirements-linux.txt --extra-index-url https://download.pytorch.org/whl/cu124; \
        else \
            /opt/venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
            /opt/venv/bin/pip install -r requirements-linux.txt --extra-index-url https://download.pytorch.org/whl/cpu; \
        fi; \
    else \
        echo "DEV_VENV=1: skipping /opt/venv build, host venv will be used at runtime"; \
    fi

# Copy entrypoint script (selects /opt/venv or host venv based on DEV_VENV env var)
COPY backend/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Source is volume-mounted at runtime (local dev) or COPYed below (serverless)
ENV HF_HOME=/app/data/huggingface

# Copy source into image for non-volume-mount deployments (e.g. RunPod)
COPY backend/ /app/backend/

# --- Normal mode: FastAPI server on port 17493 ---
FROM deps AS final-0
EXPOSE 17493
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:17493/health || exit 1
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python3", "-m", "backend.main", "--host", "0.0.0.0", "--port", "17493", "--data-dir", "/app/data"]

# --- Serverless mode: RunPod handler ---
FROM deps AS final-1
ENV SERVERLESS=1
HEALTHCHECK NONE
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD []

# --- Pick final stage based on SERVERLESS arg ---
ARG SERVERLESS
FROM final-${SERVERLESS} AS final
