"""
JSON logging configuration for voicebox backend.

Configures the root logger and all uvicorn/asyncio loggers to emit
structured JSON via python-json-logger. Call configure_json_logging()
as early as possible — before any other imports that might log.
"""

import datetime
import json
import logging
import os
import re
import sys

from pythonjsonlogger.json import JsonFormatter

# Uvicorn owns these logger names; we override them so nothing slips through as plain text.
_UVICORN_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "uvicorn.asgi",
    "fastapi",
)

# Tracebacks from uvloop/threading on shutdown that escape via raw stderr.
# These are cosmetic noise on clean Ctrl+C — swallow them.
# NOTE: Do NOT include "Traceback (most recent call last)" here — that would
# swallow real error tracebacks from third-party libraries like qwen_tts.
_STDERR_SWALLOW = (
    "uvloop/loop.pyx",
    "RuntimeError: Event loop is closed",
    "call_soon_threadsafe",
    "_check_closed",
    "_append_ready_handle",
    "_do_shutdown",
    "resource_tracker: There appear to be",
    "leaked semaphore objects to clean up",
)


class _JsonStdout:
    """Wraps stdout, wrapping bare print() output as JSON log lines."""

    def __init__(self, real):
        self._real = real

    def write(self, msg):
        if msg and msg.strip():
            line = json.dumps({
                "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3],
                "level": "INFO",
                "logger": "stdout",
                "message": msg.strip(),
            })
            self._real.write(line + "\n")
        elif msg == "\n":
            pass  # swallow bare newlines from print()

    def flush(self):
        self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


class _CleanJsonFormatter(JsonFormatter):
    """JsonFormatter that strips uvicorn's color_message field."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record.pop("color_message", None)


# Logger names whose every record gets subtype=tts automatically.
_TTS_LOGGER_PREFIXES = (
    "backend.backends.mlx_backend",
    "backend.backends.pytorch_backend",
)

# Message prefixes that imply subtype=tts regardless of logger name.
# Each entry is (prefix_to_strip, subtype_value).
_SUBTYPE_PREFIXES = (
    ("[TTS] ", "tts"),
    ("[IdleTimer] ", "tts"),
    ("[Queue] ", "queue"),
)


class _SubtypeFilter(logging.Filter):
    """Injects a ``subtype`` field on log records.

    ``subtype`` may be a string or a list of strings.  Rules:

    1. ``extra={"subtype": ...}`` set at the callsite → honour it; still strip
       any bracket prefix from the message.
    2. Message starts with a known bracket prefix → assign subtype from table,
       strip prefix.
    3. Logger name starts with a known backend prefix → subtype="tts".
    """

    @staticmethod
    def _as_list(value) -> list:
        """Normalise subtype to always be a list."""
        if isinstance(value, list):
            return value
        return [value]

    def filter(self, record: logging.LogRecord) -> bool:
        # Step 1: check for bracket prefix in message (sets subtype + strips prefix).
        if isinstance(record.msg, str):
            for msg_prefix, msg_subtype in _SUBTYPE_PREFIXES:
                if record.msg.startswith(msg_prefix):
                    record.msg = record.msg[len(msg_prefix):]
                    # Only assign if callsite didn't already provide subtype.
                    if not hasattr(record, "subtype"):
                        record.subtype = self._as_list(msg_subtype)
                    else:
                        record.subtype = self._as_list(record.subtype)
                    return True

        # Step 2: if callsite set subtype via extra=, normalise to list and we're done.
        if hasattr(record, "subtype"):
            record.subtype = self._as_list(record.subtype)
            return True

        # Step 3: logger name fallback.
        for prefix in _TTS_LOGGER_PREFIXES:
            if record.name.startswith(prefix):
                record.subtype = ["tts"]
                return True

        return True  # always pass — filter only annotates, never drops


class _AccessLogFilter(logging.Filter):
    """Unpacks uvicorn.access record.args into structured ``http`` fields.

    Adds to the record:
        http_client   — "127.0.0.1:52059"
        http_method   — "GET"
        http_path     — "/tasks/active"
        http_version  — "1.1"
        http_status   — 200  (int)
        subtype       — ["http"]
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            record.http = {
                "client":  args[0],
                "method":  args[1],
                "path":    args[2],
                "version": args[3],
                "status":  args[4],
            }
            record.subtype = ["http"]
            record.msg = "%s %s %s" % (args[1], args[2], args[4])
            record.args = None
        return True


class _FilteredStderr:
    """Wraps real stderr: swallows known noise, wraps everything else as JSON."""

    def __init__(self, real):
        self._real = real
        self._suppressing = False

    def write(self, msg):
        if any(pat in msg for pat in _STDERR_SWALLOW):
            self._suppressing = True
            return
        if self._suppressing:
            # Keep suppressing until we get a blank line (end of traceback block)
            if msg.strip():
                return
            self._suppressing = False
            return
        text = msg.strip()
        if not text:
            return
        # Already valid JSON (e.g. from our logging handler) — pass through raw.
        if text.startswith("{"):
            try:
                json.loads(text)
                self._real.write(text + "\n")
                return
            except json.JSONDecodeError:
                pass
        # Strip block-drawing chars and excess whitespace (tqdm progress bars)
        text = re.sub(r'[\u2580-\u259f\u2588-\u258f]+', '', text)  # block elements
        text = re.sub(r' {4,}', ' ', text).strip()  # collapse padding spaces
        if not text:
            return
        line = json.dumps({
            "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3],
            "level": "INFO",
            "logger": "stderr",
            "message": text,
        })
        self._real.write(line + "\n")

    def flush(self):
        self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


def configure_json_logging(log_level: str | None = None) -> None:
    """Install JSON formatter on all loggers and suppress uvicorn's own log config."""

    level_str = (log_level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_str, logging.INFO)

    formatter = _CleanJsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(_SubtypeFilter())

    # Root logger — catches everything not explicitly handled elsewhere
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Explicitly reconfigure uvicorn's loggers so they inherit our handler
    access_filter = _AccessLogFilter()
    for name in _UVICORN_LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.setLevel(level)
        lg.propagate = False  # prevent double-logging via root

    # Attach structured HTTP field extractor to access logger only
    logging.getLogger("uvicorn.access").addFilter(access_filter)

    # Silence noisy third-party loggers
    for noisy in (
        "torio._extension.utils",       # "Loading FFmpeg6" debug spam
        "qwen_tts.core.models.configuration_qwen3_tts",  # "talker_config is None" info spam
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Route unhandled thread exceptions through logging.
    # KeyboardInterrupt in threads during shutdown is normal — drop it silently.
    # Everything else is a real error and gets logged as ERROR with full traceback.
    import threading
    _thread_logger = logging.getLogger("threading")

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is KeyboardInterrupt:
            return
        _thread_logger.error(
            "Unhandled exception in thread %s",
            args.thread.name if args.thread else "<unknown>",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook

    # Wrap stdout so bare print() calls become JSON lines
    if not isinstance(sys.stdout, _JsonStdout):
        sys.stdout = _JsonStdout(sys.stdout)

    # Swallow raw stderr noise from uvloop shutdown tracebacks
    if not isinstance(sys.stderr, _FilteredStderr):
        sys.stderr = _FilteredStderr(sys.stderr)


def configure_log_file(path: str) -> None:
    """Attach a FileHandler to the root logger so all JSON logs also go to *path*.

    Call this after argparse (i.e. after ``configure_json_logging()`` has already
    set up the stderr handler).  The file gets the same JSON formatter used for
    stderr, so the output is identical and machine-parseable.
    """
    formatter = _CleanJsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(formatter)
    handler.addFilter(_SubtypeFilter())

    root = logging.getLogger()
    root.addHandler(handler)

    root.info("Log file opened: %s", path)
