#!/bin/bash
# Docker entrypoint for voicebox server.

PERSISTENT_STORAGE_DIR="/runpod-volume/voicebox"
BAKED_MODELS_DIR="/opt/models"

if [ "${SERVERLESS:-0}" = "1" ]; then
    export VOICEBOX_DATA_DIR="${VOICEBOX_DATA_DIR:-$PERSISTENT_STORAGE_DIR}"
else
    export VOICEBOX_DATA_DIR="${VOICEBOX_DATA_DIR:-/app/data}"
fi

export HF_HOME="${HF_HOME:-$VOICEBOX_DATA_DIR/huggingface}"
mkdir -p "$VOICEBOX_DATA_DIR" "$HF_HOME"

[[ -n "${HF_TOKEN:-}" ]] && echo -n "$HF_TOKEN" > "$HF_HOME/token"

json_log() {
    local level="$1"; local msg="$2"
    local ts; ts=$(date '+%Y-%m-%d %H:%M:%S,000')
    printf '{"ts":"%s","level":"%s","logger":"entrypoint","message":"%s"}\n' "$ts" "$level" "$msg" | tee -a /app/app.log
}

# Sync baked-in models to HF_HOME (skip if same path)
if [ -d "$BAKED_MODELS_DIR" ] && [ "$BAKED_MODELS_DIR" != "$HF_HOME" ]; then
    json_log "INFO" "syncing baked models from $BAKED_MODELS_DIR to $HF_HOME"
    rsync -a --ignore-existing "$BAKED_MODELS_DIR/" "$HF_HOME/"
    json_log "INFO" "model sync complete"
fi

# Serverless mode with no CMD: run RunPod handler via venv Python
if [ "${SERVERLESS:-0}" = "1" ] && [ "$#" -eq 0 ]; then
    export PATH="/opt/venv/bin:$PATH"
    set -- python3 -u -m backend.serverless_handler
fi

json_log "INFO" "cmd=$*"

# Dev debug mode: proxy is PID 1, backend runs behind it
# /health always returns 200 so RunPod keeps the pod alive
# Use /_proxy/stop, /_proxy/start, /_proxy/restart to manage backend
if [ "${DEV_DEBUG:-0}" = "1" ]; then
    json_log "INFO" "dev debug mode — proxy on :17493, backend on :17494"
    export PROXY_PORT=17493
    export BACKEND_PORT=17494
    # Rewrite port in CMD args so backend listens on 17494
    REWRITTEN_CMD=$(echo "$*" | sed 's/--port 17493/--port 17494/g')
    export BACKEND_CMD="$REWRITTEN_CMD"
    # Also override for serverless handler's hardcoded port
    export VOICEBOX_PORT=17494
    exec python3 -u -m backend.proxy
fi

exec "$@"
