"""
Lightweight HTTP reverse proxy — runs as PID 1 to keep the container alive.
Forwards all requests to the backend on BACKEND_PORT. Returns 503 if backend is down.
Start/stop/restart the backend process independently without killing the container.
"""

import http.server
import json
import os
import signal
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

LISTEN_PORT = int(os.environ.get("PROXY_PORT", "17493"))
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "17494"))
BACKEND_HOST = "127.0.0.1"
BACKEND_CMD = os.environ.get("BACKEND_CMD", "").split() or None
DEV_DEBUG = os.environ.get("DEV_DEBUG", "0") == "1"

backend_process: subprocess.Popen | None = None
backend_lock = threading.Lock()


def start_backend():
    global backend_process
    with backend_lock:
        if backend_process and backend_process.poll() is None:
            return False, "backend already running"
        if not BACKEND_CMD:
            return False, "BACKEND_CMD not set"
        backend_process = subprocess.Popen(
            BACKEND_CMD,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        return True, f"started pid={backend_process.pid}"


def stop_backend():
    global backend_process
    with backend_lock:
        if not backend_process or backend_process.poll() is not None:
            return False, "backend not running"
        backend_process.terminate()
        try:
            backend_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            backend_process.kill()
            backend_process.wait()
        pid = backend_process.pid
        backend_process = None
        return True, f"stopped pid={pid}"


def backend_alive() -> bool:
    with backend_lock:
        return backend_process is not None and backend_process.poll() is None


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_request(self):
        # In dev debug mode, /health always reports healthy
        if DEV_DEBUG and self.path in ("/health", "/health/"):
            return self._json_response(200, {
                "status": "healthy",
                "dev_debug": True,
                "backend": "up" if backend_alive() else "down",
            })

        # Proxy control endpoints
        if self.path == "/_proxy/status":
            return self._json_response(200, {
                "proxy": "ok",
                "backend": "up" if backend_alive() else "down",
                "backend_port": BACKEND_PORT,
            })

        if self.path == "/_proxy/start":
            ok, msg = start_backend()
            return self._json_response(200 if ok else 409, {"result": msg})

        if self.path == "/_proxy/stop":
            ok, msg = stop_backend()
            return self._json_response(200 if ok else 409, {"result": msg})

        if self.path == "/_proxy/restart":
            stop_backend()
            time.sleep(0.5)
            ok, msg = start_backend()
            return self._json_response(200 if ok else 500, {"result": msg})

        # Forward to backend
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else None

        url = f"http://{BACKEND_HOST}:{BACKEND_PORT}{self.path}"
        req = urllib.request.Request(url, data=body, method=self.command)
        for key, val in self.headers.items():
            if key.lower() not in ("host", "content-length", "transfer-encoding"):
                req.add_header(key, val)

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    if key.lower() not in ("transfer-encoding",):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.URLError as e:
            if hasattr(e, "read"):
                resp_body = e.read()
                self.send_response(e.code)
                for key, val in e.headers.items():
                    if key.lower() not in ("transfer-encoding",):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(resp_body)
            else:
                self._json_response(503, {
                    "error": "backend unavailable",
                    "detail": str(e.reason),
                })
        except Exception as e:
            self._json_response(502, {"error": "proxy error", "detail": str(e)})

    do_GET = do_request
    do_POST = do_request
    do_PUT = do_request
    do_DELETE = do_request
    do_PATCH = do_request
    do_HEAD = do_request
    do_OPTIONS = do_request

    def _json_response(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        sys.stderr.write(f'{{"ts":"{ts}","logger":"proxy","message":"{format % args}"}}\n')


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    if BACKEND_CMD:
        ok, msg = start_backend()
        print(f'{{"ts":"{time.strftime("%Y-%m-%d %H:%M:%S")}","logger":"proxy","message":"backend: {msg}"}}')

    server = ThreadedServer(("0.0.0.0", LISTEN_PORT), ProxyHandler)
    print(f'{{"ts":"{time.strftime("%Y-%m-%d %H:%M:%S")}","logger":"proxy","message":"proxy listening on :{LISTEN_PORT} -> :{BACKEND_PORT}"}}')

    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        stop_backend()
        server.shutdown()


if __name__ == "__main__":
    main()
