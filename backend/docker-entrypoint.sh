#!/bin/bash
set -x
# Docker entrypoint for voicebox server.

# Remote syslog — start ASAP so all subsequent output is captured
if [[ -n "${RSYSLOG_HOST:-}" ]]; then
    RSYSLOG_PORT="${RSYSLOG_PORT:-514}"
    cat > /etc/rsyslog.d/50-remote.conf <<RSYSLOG
*.* @@${RSYSLOG_HOST}:${RSYSLOG_PORT}
RSYSLOG
    rsyslogd
    # Redirect stdout/stderr through syslog via logger
    exec > >(logger -t voicebox -p local0.info) 2> >(logger -t voicebox -p local0.err)
    echo "rsyslog forwarding to ${RSYSLOG_HOST}:${RSYSLOG_PORT}"
fi

eval "$(
python3 - <<'PY'
from backend.constants import APP_LOG_FILENAME, DATA_DIR, HF_HOME, PROXY_PORT, VOICEBOX_PORT

print(f'export VOICEBOX_DATA_DIR="${{VOICEBOX_DATA_DIR:-{DATA_DIR}}}"')
print(f'export HF_HOME="${{HF_HOME:-{HF_HOME}}}"')
print(f'export VOICEBOX_PORT="${{VOICEBOX_PORT:-{VOICEBOX_PORT}}}"')
print(f'export PROXY_PORT="${{PROXY_PORT:-{PROXY_PORT}}}"')
print(f'export BACKEND_PORT="${{BACKEND_PORT:-{VOICEBOX_PORT}}}"')
print(f'export APP_LOG_PATH="{DATA_DIR}/{APP_LOG_FILENAME}"')
PY
)"
mkdir -p "$VOICEBOX_DATA_DIR" "$HF_HOME"

[[ -n "${HF_TOKEN:-}" ]] && echo -n "$HF_TOKEN" > "$HF_HOME/token"

json_log() {
    local level="$1"; local msg="$2"
    local ts; ts=$(date '+%Y-%m-%d %H:%M:%S,000')
    printf '{"ts":"%s","level":"%s","logger":"entrypoint","message":"%s"}\n' "$ts" "$level" "$msg" | tee -a "$APP_LOG_PATH"
}

# Serverless mode with no CMD: run RunPod handler via venv Python
if [ "${SERVERLESS:-0}" = "1" ] && [ "$#" -eq 0 ]; then
    export PATH="/opt/venv/bin:$PATH"
    set -- python3 -u -m backend.serverless_handler
fi

json_log "INFO" "HF_HOME=$HF_HOME"
json_log "INFO" "VOICEBOX_DATA_DIR=$VOICEBOX_DATA_DIR"
json_log "INFO" "DEV_DEBUG=${DEV_DEBUG:-0} SERVERLESS=${SERVERLESS:-0}"
json_log "INFO" "cmd=$*"

# Dev debug mode: proxy is PID 1, backend runs behind it
# /health always returns 200 so RunPod keeps the pod alive
# Use /_proxy/stop, /_proxy/start, /_proxy/restart to manage backend
if [ "${DEV_DEBUG:-0}" = "1" ]; then
    export BACKEND_CMD="$*"
    json_log "INFO" "dev debug mode — proxy on :$PROXY_PORT, backend on :$BACKEND_PORT"
    exec python3 -u -m backend.proxy
fi

exec "$@"
