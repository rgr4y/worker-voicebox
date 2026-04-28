"""
RunPod Serverless handler for voicebox TTS server.

Starts the FastAPI/uvicorn server in a background thread and proxies
RunPod job requests as HTTP calls to the local server.

Usage (RunPod serverless):
    CMD ["python3", "-u", "-m", "backend.serverless_handler"]

Local testing:
    python3 -m backend.serverless_handler --rp_serve_api
"""

import os

# Must be set before any backend imports so backends disable idle timers at module load time
os.environ["SERVERLESS"] = "1"

import time
import logging
import threading
import base64

import httpx
import runpod
import uvicorn

# Set up JSON logging FIRST, before any backend imports that might log
from backend.utils.logging_config import configure_json_logging
configure_json_logging()
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────
from backend.constants import (
    build_base_url,
    DATA_DIR,
    ENV_SERVERLESS,
    HEALTH_PATH,
    SERVERLESS_BINARY_CONTENT_TYPES,
    SERVERLESS_HEALTHCHECK_TIMEOUT_SECONDS,
    SERVERLESS_HTTP_METHOD_DEFAULT,
    SERVERLESS_JSON_METHODS,
    SERVERLESS_MISSING_PATH_MESSAGE,
    SERVERLESS_REQUEST_TIMEOUT_SECONDS,
    SERVERLESS_STARTUP_POLL_SECONDS,
    SERVERLESS_STARTUP_TIMEOUT_SECONDS,
    VOICEBOX_PORT,
    WILDCARD_HOST,
)

_HOST = WILDCARD_HOST
_PORT = VOICEBOX_PORT
_BASE_URL = build_base_url(_HOST, _PORT)
_STARTUP_TIMEOUT = SERVERLESS_STARTUP_TIMEOUT_SECONDS
_STARTUP_POLL = SERVERLESS_STARTUP_POLL_SECONDS

# ── Server lifecycle ──────────────────────────────────────────
_server_ready = threading.Event()
_server_thread: threading.Thread | None = None


def _start_server():
    """Start the FastAPI/uvicorn server in a background thread."""
    global _server_thread

    if _server_thread is not None and _server_thread.is_alive():
        return

    _server_ready.clear()

    from backend import config
    from backend.main import app

    config.set_data_dir(DATA_DIR)

    def _run():
        uvicorn.run(app, host=_HOST, port=_PORT, log_level="info", log_config=None)

    _server_thread = threading.Thread(target=_run, daemon=True)
    _server_thread.start()


def _wait_for_server():
    """Block until /health responds 200 or timeout."""
    if _server_ready.is_set():
        return

    deadline = time.time() + _STARTUP_TIMEOUT
    while time.time() < deadline:
        try:
            r = httpx.get(f"{_BASE_URL}{HEALTH_PATH}", timeout=5)
            if r.status_code == 200:
                logger.info("Voicebox server is ready")
                _server_ready.set()
                return
        except httpx.RequestError:
            pass
        time.sleep(_STARTUP_POLL)

    raise RuntimeError(
        f"Voicebox server did not become healthy within {_STARTUP_TIMEOUT}s"
    )


# ── RunPod handler ────────────────────────────────────────────

def handler(job: dict) -> dict:
    """
    RunPod serverless handler.

    Expected job["input"]:
        method  (str)  — HTTP method, default "POST"
        path    (str)  — required, e.g. "/generate"
        body    (dict) — optional, JSON body for POST/PUT
        params  (dict) — optional, query params
        headers (dict) — optional
    """
    _start_server()
    _wait_for_server()

    inp = job.get("input", {})

    path = inp.get("path")
    if not path:
        return {"error": SERVERLESS_MISSING_PATH_MESSAGE}

    method = inp.get("method", SERVERLESS_HTTP_METHOD_DEFAULT).upper()
    body = inp.get("body")
    params = inp.get("params")
    headers = inp.get("headers", {})

    url = f"{_BASE_URL}{path}"

    try:
        with httpx.Client(timeout=SERVERLESS_REQUEST_TIMEOUT_SECONDS) as client:
            response = client.request(
                method=method,
                url=url,
                json=body if method in SERVERLESS_JSON_METHODS else None,
                params=params,
                headers=headers,
            )

        content_type = response.headers.get("content-type", "")
        is_binary = any(ct in content_type for ct in SERVERLESS_BINARY_CONTENT_TYPES)

        if is_binary:
            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body_base64": base64.b64encode(response.content).decode("ascii"),
                "is_binary": True,
            }

        try:
            result = response.json()
        except Exception:
            result = response.text

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": result,
        }

    except httpx.TimeoutException:
        return {"error": f"Request to voicebox server timed out ({SERVERLESS_REQUEST_TIMEOUT_SECONDS}s)"}
    except Exception as e:
        return {"error": f"Request failed: {e}"}


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
