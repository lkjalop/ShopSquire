import os
import asyncio
import tempfile
import uuid
import threading
from pathlib import Path

import pytest


_ORIG_ASYNCIO_RUN = asyncio.run


def _safe_asyncio_run(coro, *, debug=None):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return _ORIG_ASYNCIO_RUN(coro, debug=debug)

    result = {"value": None, "error": None}

    def _worker():
        try:
            result["value"] = _ORIG_ASYNCIO_RUN(coro, debug=debug)
        except Exception as exc:  # pragma: no cover - defensive
            result["error"] = exc

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout=30)
    if result.get("error") is not None:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")

# Patch at import time so all tests/modules see the safe wrapper.
asyncio.run = _safe_asyncio_run


def pytest_sessionstart(session):
    # Isolate test DB for this session so stateful API tests don't collide.
    db_file = os.path.join(tempfile.gettempdir(), f"shopsquire_test_{uuid.uuid4().hex}.sqlite")
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_file}"
    os.environ["DATABASE_URL_RO"] = f"sqlite+pysqlite:///{db_file}"

    # Keep full-suite tests deterministic by disabling background workers that
    # can create timing/port collisions during parallelized app startup.
    os.environ.setdefault("INVENTORY_WORKER_ENABLED", "0")
    os.environ.setdefault("RETENTION_CLEANUP_ENABLED", "0")
    os.environ.setdefault("WEBHOOK_DISPATCHER_WORKER_ENABLED", "0")
    os.environ.setdefault("DMARC_POLL_ENABLED", "0")
    os.environ.setdefault("FINGERPRINT_SCAN_WORKER_ENABLED", "0")
    os.environ.setdefault("PLAYBOOK_DLQ_REPROCESSOR_ENABLED", "0")
    os.environ.setdefault("PLAYBOOK_SCHEDULER_ENABLED", "0")
    os.environ.setdefault("PLAYBOOK_AUTORUN_ENABLED", "0")
    os.environ.setdefault("DISABLE_TRACING", "1")


@pytest.fixture(autouse=True)
def restore_feature_flags_file():
    flags_path = Path(os.environ.get("FEATURE_FLAGS_PATH", "config/feature_flags.json"))
    existed = flags_path.exists()
    original = flags_path.read_bytes() if existed else None
    yield
    try:
        if existed and original is not None:
            flags_path.parent.mkdir(parents=True, exist_ok=True)
            flags_path.write_bytes(original)
        elif not existed and flags_path.exists():
            flags_path.unlink()
    except Exception:
        pass
