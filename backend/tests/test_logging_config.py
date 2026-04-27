"""
Tests for configure_json_logging().

Run from voicebox/backend/:
    python -m pytest tests/test_logging_config.py -v
or standalone:
    python tests/test_logging_config.py
"""

import io
import json
import logging
import sys
import traceback
import types
import unittest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _install_logging(level: str = "DEBUG") -> io.StringIO:
    """
    Call configure_json_logging() with a StringIO stderr so we can
    inspect the output.  Returns the buffer.

    We monkey-patch sys.stderr before calling configure so the
    StreamHandler binds to our buffer.
    """
    buf = io.StringIO()

    # Temporarily replace stderr so the handler binds to our buffer.
    real_stderr = sys.stderr
    sys.stderr = buf
    try:
        # Re-import to reset module-level state each test
        import importlib
        import backend.utils.logging_config as lc
        importlib.reload(lc)
        lc.configure_json_logging(log_level=level)
    finally:
        sys.stderr = real_stderr

    return buf


def _lines(buf: io.StringIO) -> list[dict]:
    """Return all non-empty lines from buf as parsed JSON dicts."""
    out = []
    for line in buf.getvalue().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise AssertionError(f"Non-JSON output line: {line!r}") from e
    return out


def _last(buf: io.StringIO) -> dict:
    lines = _lines(buf)
    assert lines, "No log output produced"
    return lines[-1]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestJsonLoggingConfig(unittest.TestCase):

    def setUp(self):
        """Fresh logging state before each test."""
        # Wipe all handlers so configure_json_logging starts clean
        root = logging.getLogger()
        root.handlers.clear()
        for name in list(logging.Logger.manager.loggerDict):
            lg = logging.Logger.manager.loggerDict[name]
            if isinstance(lg, logging.Logger):
                lg.handlers.clear()

    # ------------------------------------------------------------------
    # 1. Basic message fields
    # ------------------------------------------------------------------

    def test_basic_message_is_valid_json(self):
        buf = _install_logging()
        logger = logging.getLogger("test.basic")
        logger.info("hello world")
        row = _last(buf)
        self.assertEqual(row["message"], "hello world")
        self.assertEqual(row["level"], "INFO")
        self.assertIn("ts", row)
        self.assertIn("logger", row)

    def test_level_field_matches_severity(self):
        buf = _install_logging()
        logger = logging.getLogger("test.levels")
        logger.debug("dbg")
        logger.warning("wrn")
        logger.error("err")
        rows = _lines(buf)
        levels = [r["level"] for r in rows]
        self.assertIn("DEBUG",   levels)
        self.assertIn("WARNING", levels)
        self.assertIn("ERROR",   levels)

    # ------------------------------------------------------------------
    # 2. Exception capture (the big one — multi-line tracebacks)
    # ------------------------------------------------------------------

    def test_exception_via_exc_info(self):
        """logger.exception / exc_info=True must produce exc_info in JSON."""
        buf = _install_logging()
        logger = logging.getLogger("test.exc")
        try:
            raise ValueError("something exploded")
        except ValueError:
            logger.exception("caught it")

        row = _last(buf)
        self.assertEqual(row["message"], "caught it")
        self.assertIn("exc_info", row)
        self.assertIn("ValueError", row["exc_info"])
        self.assertIn("something exploded", row["exc_info"])
        # Must NOT contain a bare newline that would break JSON parsing
        raw = buf.getvalue().splitlines()
        json_lines = [l for l in raw if l.strip()]
        for line in json_lines:
            json.loads(line)  # raises if multi-line bleed-through

    def test_nested_exception_chain(self):
        """Exception chains (raise X from Y) are fully captured."""
        buf = _install_logging()
        logger = logging.getLogger("test.chain")
        try:
            try:
                raise RuntimeError("root cause")
            except RuntimeError as e:
                raise KeyError("secondary") from e
        except KeyError:
            logger.exception("chained exc")

        row = _last(buf)
        exc = row.get("exc_info", "")
        self.assertIn("RuntimeError", exc)
        self.assertIn("KeyError", exc)

    def test_deep_traceback(self):
        """Deeply nested call stack is fully serialised in one JSON line."""
        buf = _install_logging()
        logger = logging.getLogger("test.deep")

        def level3():
            raise TypeError("deep error")

        def level2():
            level3()

        def level1():
            level2()

        try:
            level1()
        except TypeError:
            logger.exception("deep tb")

        row = _last(buf)
        exc = row.get("exc_info", "")
        self.assertIn("level3", exc)
        self.assertIn("level2", exc)
        self.assertIn("level1", exc)
        self.assertIn("TypeError", exc)

    def test_exception_with_extra_fields(self):
        """Extra fields survive alongside exc_info."""
        buf = _install_logging()
        logger = logging.getLogger("test.extra_exc")
        try:
            raise OSError("disk full")
        except OSError:
            logger.error("storage error", exc_info=True, extra={"job_id": "abc-123"})

        row = _last(buf)
        self.assertIn("exc_info", row)
        self.assertEqual(row.get("job_id"), "abc-123")

    def test_bare_exception_object_as_message(self):
        """Logging an exception object directly (not via exc_info)."""
        buf = _install_logging()
        logger = logging.getLogger("test.bare_exc")
        err = RuntimeError("bare object")
        logger.error(str(err))

        row = _last(buf)
        self.assertIn("bare object", row["message"])

    def test_syntaxerror_with_lineno(self):
        """SyntaxError has extra attributes — still must be valid JSON."""
        buf = _install_logging()
        logger = logging.getLogger("test.syntax")
        try:
            compile("def f(:\n    pass", "<string>", "exec")
        except SyntaxError:
            logger.exception("syntax error caught")

        row = _last(buf)
        self.assertIn("SyntaxError", row.get("exc_info", ""))

    # ------------------------------------------------------------------
    # 3. Subtype injection via _SubtypeFilter
    # ------------------------------------------------------------------

    def test_subtype_from_bracket_prefix_tts(self):
        buf = _install_logging()
        logger = logging.getLogger("test.prefix")
        logger.info("[TTS] model loaded")
        row = _last(buf)
        self.assertEqual(row.get("subtype"), ["tts"])
        self.assertEqual(row["message"], "model loaded")   # prefix stripped

    def test_subtype_from_bracket_prefix_queue(self):
        buf = _install_logging()
        logger = logging.getLogger("test.prefix")
        logger.info("[Queue] job started")
        row = _last(buf)
        self.assertEqual(row.get("subtype"), ["queue"])
        self.assertEqual(row["message"], "job started")

    def test_subtype_from_logger_name_backend(self):
        buf = _install_logging()
        logger = logging.getLogger("backend.backends.pytorch_backend")
        logger.info("loading weights")
        row = _last(buf)
        self.assertEqual(row.get("subtype"), ["tts"])

    def test_subtype_from_extra_overrides_prefix(self):
        """Explicit extra={"subtype": ...} at callsite should be honoured."""
        buf = _install_logging()
        logger = logging.getLogger("test.extra_subtype")
        logger.info("[TTS] something", extra={"subtype": "custom"})
        row = _last(buf)
        # callsite wins; prefix is still stripped
        self.assertEqual(row.get("subtype"), ["custom"])
        self.assertEqual(row["message"], "something")

    def test_subtype_normalised_to_list(self):
        """Single string subtype is normalised to a list."""
        buf = _install_logging()
        logger = logging.getLogger("test.norm")
        logger.info("msg", extra={"subtype": "tts"})
        row = _last(buf)
        self.assertIsInstance(row.get("subtype"), list)

    # ------------------------------------------------------------------
    # 3b. Access log (uvicorn.access) — message is always populated
    # ------------------------------------------------------------------

    def test_access_log_message_populated(self):
        """uvicorn.access records must have a non-empty message field.

        The _AccessLogFilter unpacks the 5-tuple args into an ``http``
        field AND formats a human-readable message string so consumers
        (like the frontend log viewer) never see a blank message.
        """
        buf = _install_logging()
        access_logger = logging.getLogger("uvicorn.access")

        # Simulate what uvicorn does: msg with %-format args as a 5-tuple
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:54321",
            "GET",
            "/health",
            "1.1",
            200,
        )

        row = _last(buf)
        # message must not be empty
        self.assertTrue(row.get("message"), "Access log message must not be blank")
        self.assertIn("GET", row["message"])
        self.assertIn("/health", row["message"])
        self.assertIn("200", row["message"])

        # http field must still be present with structured data
        http = row.get("http")
        self.assertIsNotNone(http, "Access log must have http field")
        self.assertEqual(http["method"], "GET")
        self.assertEqual(http["path"], "/health")
        self.assertEqual(http["status"], 200)
        self.assertEqual(row.get("subtype"), ["http"])

    # ------------------------------------------------------------------
    # 4. print() → stdout wrapper
    # ------------------------------------------------------------------

    def test_print_becomes_json(self):
        """print() on the wrapped stdout should emit a valid JSON line."""
        buf_out = io.StringIO()
        real_stdout = sys.stdout

        _install_logging()  # installs _JsonStdout wrapper
        # Redirect the real stdout under the wrapper to our buffer
        import backend.utils.logging_config as lc
        real_inner = lc._JsonStdout.__init__  # keep original

        # Simpler: patch the _real inside the already-installed wrapper
        if isinstance(sys.stdout, lc._JsonStdout):
            sys.stdout._real = buf_out

        try:
            print("hello from print")
        finally:
            sys.stdout = real_stdout

        output = buf_out.getvalue().strip()
        if output:
            row = json.loads(output)
            self.assertIn("hello from print", row["message"])
            self.assertEqual(row["logger"], "stdout")

    def test_tqdm_cr_prefix_stripped(self):
        """tqdm writes \\r-prefixed progress bars to stdout; \\r must not appear in message."""
        buf_out = io.StringIO()
        real_stdout = sys.stdout

        _install_logging()
        import backend.utils.logging_config as lc
        if isinstance(sys.stdout, lc._JsonStdout):
            sys.stdout._real = buf_out

        try:
            sys.stdout.write("\rDownloading model.safetensors:  42%|████      | 123M/2.33G [00:05<01:10, 30.5MB/s]")
        finally:
            sys.stdout = real_stdout

        output = buf_out.getvalue().strip()
        self.assertTrue(output, "Expected JSON output from tqdm-style write")
        row = json.loads(output)
        self.assertNotIn("\r", row["message"])
        self.assertIn("Downloading", row["message"])
        self.assertEqual(row["logger"], "stdout")

    # ------------------------------------------------------------------
    # 5. stderr noise suppression
    # ------------------------------------------------------------------

    def test_uvloop_noise_suppressed(self):
        """Lines matching _STDERR_SWALLOW patterns must not reach real stderr."""
        _install_logging()
        import backend.utils.logging_config as lc

        capture = io.StringIO()
        if isinstance(sys.stderr, lc._FilteredStderr):
            real_real = sys.stderr._real
            sys.stderr._real = capture

        try:
            sys.stderr.write("uvloop/loop.pyx in run_forever\n")
            sys.stderr.write("RuntimeError: Event loop is closed\n")
        finally:
            if isinstance(sys.stderr, lc._FilteredStderr):
                sys.stderr._real = real_real

        self.assertEqual(capture.getvalue(), "")

    def test_real_errors_not_suppressed(self):
        """Genuine error output must still pass through filtered stderr.

        We test the _FilteredStderr.write() logic directly rather than
        routing through sys.stderr so pytest's own capture doesn't interfere.
        """
        import backend.utils.logging_config as lc

        capture = io.StringIO()
        filtered = lc._FilteredStderr(capture)

        filtered.write("REAL ERROR: something bad happened\n")
        self.assertIn("REAL ERROR", capture.getvalue())

    # ------------------------------------------------------------------
    # 6. Extra fields pass through cleanly
    # ------------------------------------------------------------------

    def test_extra_fields_in_output(self):
        buf = _install_logging()
        logger = logging.getLogger("test.extra")
        logger.info("structured event", extra={"job_id": "xyz", "model": "1.7B"})
        row = _last(buf)
        self.assertEqual(row.get("job_id"), "xyz")
        self.assertEqual(row.get("model"), "1.7B")

    def test_color_message_stripped(self):
        """uvicorn injects color_message; _CleanJsonFormatter must drop it."""
        buf = _install_logging()
        record = logging.LogRecord(
            name="uvicorn", level=logging.INFO,
            pathname="", lineno=0,
            msg="started", args=(), exc_info=None,
        )
        record.color_message = "\x1b[32mstarted\x1b[0m"
        logging.getLogger("uvicorn").handle(record)
        row = _last(buf)
        self.assertNotIn("color_message", row)

    # ------------------------------------------------------------------
    # 6b. threading.excepthook
    # ------------------------------------------------------------------

    def test_thread_exception_captured_as_json(self):
        """Unhandled thread exceptions must be routed through logging, not raw stderr."""
        import threading
        buf = _install_logging()

        exc = RuntimeError("thread blew up")
        args = threading.ExceptHookArgs(
            (type(exc), exc, exc.__traceback__, threading.current_thread())
        )
        threading.excepthook(args)

        rows = _lines(buf)
        error_rows = [r for r in rows if r.get("level") == "ERROR"]
        self.assertTrue(error_rows, "Expected an ERROR log line from thread exception")
        self.assertIn("thread blew up", error_rows[-1].get("exc_info", "") + error_rows[-1].get("message", ""))

    def test_thread_keyboard_interrupt_suppressed(self):
        """KeyboardInterrupt in threads must be silently dropped — not logged."""
        import threading
        buf = _install_logging()

        args = threading.ExceptHookArgs(
            (KeyboardInterrupt, KeyboardInterrupt(), None, threading.current_thread())
        )
        threading.excepthook(args)

        rows = _lines(buf)
        self.assertFalse(
            any(r.get("level") == "ERROR" for r in rows),
            "KeyboardInterrupt in thread must not produce an ERROR log line",
        )

    # ------------------------------------------------------------------
    # 7. configure_log_file()
    # ------------------------------------------------------------------

    def test_log_file_creates_file_and_writes_json(self):
        """configure_log_file() should append a FileHandler that writes valid JSON."""
        import tempfile
        import os

        buf = _install_logging()
        logger = logging.getLogger("test.logfile")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            from backend.utils.logging_config import configure_log_file
            configure_log_file(log_path)

            logger.info("file log entry")
            logger.warning("file warning", extra={"key": "val"})

            # Flush all handlers
            for h in logging.getLogger().handlers:
                h.flush()

            with open(log_path) as f:
                lines = [l.strip() for l in f if l.strip()]

            self.assertGreaterEqual(len(lines), 2, "Expected at least 2 lines in log file")
            for line in lines:
                row = json.loads(line)
                self.assertIn("ts", row)
                self.assertIn("level", row)
                self.assertIn("message", row)

            # Verify our specific messages made it
            messages = [json.loads(l)["message"] for l in lines]
            self.assertTrue(any("file log entry" in m for m in messages))
            self.assertTrue(any("file warning" in m for m in messages))

            # Verify extra fields pass through to file handler
            warning_rows = [json.loads(l) for l in lines if "file warning" in l]
            self.assertTrue(warning_rows)
            self.assertEqual(warning_rows[0].get("key"), "val")
        finally:
            os.unlink(log_path)

    def test_log_file_also_writes_to_stderr(self):
        """Adding a file handler must not break the existing stderr handler."""
        import tempfile
        import os

        buf = _install_logging()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            from backend.utils.logging_config import configure_log_file
            configure_log_file(log_path)

            logger = logging.getLogger("test.dual")
            logger.info("dual output test")

            # Should appear in stderr buffer too
            row = _last(buf)
            self.assertIn("dual output test", row.get("message", ""))
        finally:
            os.unlink(log_path)

    def test_log_file_subtype_filter_applied(self):
        """The file handler should also get subtype annotations."""
        import tempfile
        import os

        _install_logging()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            from backend.utils.logging_config import configure_log_file
            configure_log_file(log_path)

            logger = logging.getLogger("test.file_subtype")
            logger.info("[TTS] model loaded via file")

            for h in logging.getLogger().handlers:
                h.flush()

            with open(log_path) as f:
                lines = [l.strip() for l in f if l.strip()]

            tts_rows = [json.loads(l) for l in lines if "model loaded via file" in l]
            self.assertTrue(tts_rows, "Expected TTS log line in file")
            self.assertEqual(tts_rows[0].get("subtype"), ["tts"])
            # Prefix should be stripped
            self.assertEqual(tts_rows[0]["message"], "model loaded via file")
        finally:
            os.unlink(log_path)

    # ------------------------------------------------------------------
    # 8. Timestamp format — must be parseable by the frontend
    # ------------------------------------------------------------------

    def test_ts_format_parseable_by_javascript(self):
        """The 'ts' field must be in a format the frontend can parse.

        Python logging emits "2026-02-19 12:34:56,789" (comma before ms).
        The frontend normalises comma→dot before parsing.  Verify the
        format is consistent across both the JSON formatter and the
        _JsonStdout wrapper so the viewer never shows "Invalid Date".
        """
        import re

        # Expected pattern: YYYY-MM-DD HH:MM:SS,mmm
        ts_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}$")

        # 1) Standard logger → _CleanJsonFormatter
        buf = _install_logging()
        logger = logging.getLogger("test.ts_format")
        logger.info("ts check")
        row = _last(buf)
        ts = row.get("ts", "")
        self.assertRegex(ts, ts_re,
            f"Formatter ts {ts!r} doesn't match YYYY-MM-DD HH:MM:SS,mmm")

        # Verify comma→dot normalisation produces a valid ISO-ish datetime
        normalised = ts.replace(",", ".")
        from datetime import datetime as dt
        parsed = dt.strptime(normalised, "%Y-%m-%d %H:%M:%S.%f")
        self.assertIsNotNone(parsed)

        # 2) _JsonStdout wrapper (print → JSON)
        import backend.utils.logging_config as lc
        buf_out = io.StringIO()
        real_stdout = sys.stdout
        if isinstance(sys.stdout, lc._JsonStdout):
            sys.stdout._real = buf_out
        try:
            print("stdout ts check")
        finally:
            sys.stdout = real_stdout

        output = buf_out.getvalue().strip()
        if output:
            stdout_row = json.loads(output)
            stdout_ts = stdout_row.get("ts", "")
            self.assertRegex(stdout_ts, ts_re,
                f"_JsonStdout ts {stdout_ts!r} doesn't match YYYY-MM-DD HH:MM:SS,mmm")

    # ------------------------------------------------------------------
    # 9. Every output line is valid JSON (smoke test)
    # ------------------------------------------------------------------

    def test_all_output_is_valid_json(self):
        """Fire a bunch of varied log calls; every output line must parse."""
        buf = _install_logging()
        logger = logging.getLogger("test.smoke")
        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warn msg with unicode: 😀")
        logger.error("error msg")
        try:
            1 / 0
        except ZeroDivisionError:
            logger.exception("division error")
        logger.info("[TTS] tts msg")
        logger.info("[Queue] queue msg")
        logger.info("extra fields", extra={"foo": "bar", "n": 42})

        rows = _lines(buf)
        self.assertGreater(len(rows), 0)
        # Every row must have the three mandatory fields
        for row in rows:
            self.assertIn("ts",      row, f"Missing 'ts' in: {row}")
            self.assertIn("level",   row, f"Missing 'level' in: {row}")
            self.assertIn("message", row, f"Missing 'message' in: {row}")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
