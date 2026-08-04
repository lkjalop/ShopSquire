from __future__ import annotations

import logging
import os
import uuid
from contextvars import ContextVar

from opentelemetry import trace

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger
    _HAS_JSON_LOGGER = True
except ImportError:
    _jsonlogger = None  # type: ignore[assignment]
    _HAS_JSON_LOGGER = False


_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def bind_request_id(value: str):
    _request_id.set(value or "-")


def get_request_id() -> str:
    return _request_id.get() or "-"


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            span = trace.get_current_span()
            ctx = span.get_span_context()
            trace_id = ctx.trace_id
            span_id = ctx.span_id
            record.trace_id = f"{trace_id:032x}" if trace_id else "-"
            record.span_id = f"{span_id:016x}" if span_id else "-"
        except Exception:
            record.trace_id = "-"
            record.span_id = "-"
        record.request_id = get_request_id()
        return True


class RedactionFilter(logging.Filter):
    """Redact sensitive patterns from log messages (best-effort)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = str(record.getMessage())
            # Patterns: email, phone, API keys, credit-card-ish numbers
            import re
            patterns = [
                (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED:email]"),
                (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[REDACTED:phone]"),
                (r"\bsk_(live|test)_[A-Za-z0-9]{24}\b", "[REDACTED:key]"),
                (r"\bghp_[A-Za-z0-9]{36}\b", "[REDACTED:key]"),
                (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED:key]"),
                (r"\b\d{13,16}\b", "[REDACTED:cc]"),
            ]
            redacted = msg
            for pat, repl in patterns:
                redacted = re.sub(pat, repl, redacted)
            # Update record.msg preserving formatting args
            record.msg = redacted
        except Exception:
            pass
        return True


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        for attr in ("request_id", "trace_id", "span_id"):
            if not hasattr(record, attr):
                setattr(record, attr, "-")
        return super().format(record)


class _SafeJsonFormatter(_jsonlogger.JsonFormatter if _HAS_JSON_LOGGER else logging.Formatter):  # type: ignore[misc]
    """JsonFormatter that guarantees trace context fields are present and applies redaction."""

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:  # type: ignore[override]
        super().add_fields(log_record, record, message_dict)  # type: ignore[arg-type]
        log_record["timestamp"] = log_record.pop("asctime", None) or record.asctime if hasattr(record, "asctime") else None
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        for field in ("request_id", "trace_id", "span_id"):
            log_record.setdefault(field, getattr(record, field, "-"))

    def format(self, record: logging.LogRecord) -> str:
        for attr in ("request_id", "trace_id", "span_id"):
            if not hasattr(record, attr):
                setattr(record, attr, "-")
        return super().format(record)


def _build_formatter(level: int, json_mode: bool) -> logging.Formatter:
    if json_mode and _HAS_JSON_LOGGER:
        return _SafeJsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(request_id)s %(trace_id)s %(span_id)s %(message)s"
        )
    fmt = "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s trace_id=%(trace_id)s span_id=%(span_id)s %(message)s"
    return SafeFormatter(fmt)


def init_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    # LOG_FORMAT=json → structured JSON output for container log shippers.
    # LOG_JSON=1 is an alias for backward compatibility.
    json_mode = os.getenv("LOG_FORMAT", "").lower() == "json" or os.getenv("LOG_JSON", "0") in ("1", "true")
    formatter = _build_formatter(level, json_mode)
    logging.basicConfig(level=level)
    log_file = os.getenv("LOG_FILE")
    if log_file:
        try:
            import os as _os
            _os.makedirs(_os.path.dirname(log_file), exist_ok=True)
            fh = logging.FileHandler(log_file)
            fh.setLevel(level)
            fh.setFormatter(formatter)
            logging.getLogger().addHandler(fh)
            logging.getLogger("shopsquire.http").addHandler(fh)
        except Exception:
            pass
    root = logging.getLogger()
    root.addFilter(TraceContextFilter())
    root.addFilter(RedactionFilter())
    for h in root.handlers:
        try:
            h.setFormatter(formatter)
        except Exception:
            pass


def new_request_id(header_val: str | None = None) -> str:
    return (header_val or "").strip() or str(uuid.uuid4())


def log_request_line(method: str, path: str, status: int, duration_seconds: float) -> None:
    log_file = os.getenv("LOG_FILE")
    if not log_file:
        return
    try:
        from datetime import datetime

        span = trace.get_current_span()
        ctx = span.get_span_context()
        trace_id = f"{ctx.trace_id:032x}" if ctx.trace_id else "-"
        span_id = f"{ctx.span_id:016x}" if ctx.span_id else "-"
        line = (
            f"{datetime.utcnow().isoformat()} "
            f"request_id={get_request_id()} trace_id={trace_id} span_id={span_id} "
            f"{method} {path} {status} {duration_seconds:.3f}s\n"
        )
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
