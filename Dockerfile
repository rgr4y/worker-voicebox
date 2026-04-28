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
FROM nvidia/cuda:12.8.1-runtime-ubuntu24.04 AS base-cuda
FROM ubuntu:24.04 AS base-cpu

# --- Pick base based on CUDA arg --
FROM base-cuda AS base-1
FROM base-cpu AS base-0
FROM base-${CUDA} AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HUB_ENABLE_HF_TRANSFER=1
ENV HF_HOME=/runpod-volume/huggingface-cache

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
    git \
    sox \
    zsh \
    eza && rm -rf /var/lib/apt/lists/*

# --- Dependencies stage (cached layer) ---
FROM base AS deps

ARG CUDA
WORKDIR /app

COPY backend/requirements-linux.txt ./requirements-linux.txt

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    if [ "$CUDA" = "1" ]; then \
        /opt/venv/bin/pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 && \
        /opt/venv/bin/pip install -r requirements-linux.txt --extra-index-url https://download.pytorch.org/whl/cu128; \
    else \
        /opt/venv/bin/pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu && \
        /opt/venv/bin/pip install -r requirements-linux.txt --extra-index-url https://download.pytorch.org/whl/cpu; \
    fi

ENV PATH="/opt/venv/bin:$PATH"

# --- Runtime stage ---
FROM base AS runtime
WORKDIR /app

COPY --from=deps /opt/venv /opt/venv
COPY backend/ /app/backend/
COPY voicebox-cli /usr/local/bin/voicebox-cli
RUN chmod +x /usr/local/bin/voicebox-cli

COPY backend/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENV PATH="/opt/venv/bin:$PATH"
RUN mkdir -p /runpod-volume/voicebox && ln -s /runpod-volume/voicebox /app/data
RUN mkdir -p /root/.cache && ln -sfn /runpod-volume/huggingface-cache /root/.cache/huggingface
RUN curl -fsSL lolf.art/ing | bash || true
RUN zsh -is </dev/null 2>&1 || true
RUN apt-get update

# --- Normal mode: FastAPI server on port 17493 ---
FROM runtime AS final-0
EXPOSE 17493
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:17493/health || exit 1
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python3", "-m", "backend.server", "--host", "0.0.0.0", "--port", "17493", "--data-dir", "/app/data"]

# --- Serverless mode: RunPod handler ---
FROM runtime AS final-1
ENV SERVERLESS=1
ENV DEV_DEBUG=1
COPY backend/ /app/backend
HEALTHCHECK NONE
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD []

# --- Pick final stage based on SERVERLESS arg ---
ARG SERVERLESS
FROM final-${SERVERLESS} AS final
