#!/bin/bash
# Docker entrypoint for voicebox server.

PERSISTENT_STORAGE_DIR="/runpod-volume/voicebox"

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

# Serverless mode with no CMD: run RunPod handler via venv Python
if [ "${SERVERLESS:-0}" = "1" ] && [ "$#" -eq 0 ]; then
    export PATH="/opt/venv/bin:$PATH"
    set -- python3 -u -m backend.serverless_handler
fi

json_log "INFO" "cmd=$*"
exec "$@"
