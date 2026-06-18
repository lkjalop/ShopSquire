import os
import sys
import asyncio
import tempfile
import uuid
import threading
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared-app singleton — OOM prevention
# ---------------------------------------------------------------------------
# The full test suite imports ~160 test modules.  32 of them contain a
# module-level ``app = create_app()`` statement that executes at *collection*
# time, spawning 32 simultaneous FastAPI instances.  Combined with ~100 more
# per-function calls inside tests/api/, the peak working-set easily exceeded
# Windows virtual-memory limits in the March 2026 gap-closure run.
#
# Fix: patch ``src.app.main.create_app`` in ``pytest_configure`` (which runs
# before any test module is imported) to return a per-DATABASE_URL singleton.
# Tests that monkeypatch DATABASE_URL to a *different* path (e.g. load/chaos
# tests using "sqlite:///test.sqlite") get their own isolated instance, so
# cross-test DB contamination is avoided.  Tests at module level that share
# the session URL all reuse the same instance, collapsing 32 simultaneously
# live instances into one.
#
# Tests that need startup-time config changes (MAX_CONCURRENCY, CHAOS_ERROR_*,
# RATE_LIMIT_PER_IP_PER_MIN) must manipulate ``app.state`` directly — see
# tests/chaos/ for examples.
# ---------------------------------------------------------------------------

_SINGLETONS: dict[str, object] = {}
_SINGLETONS_LOCK = threading.Lock()


def _get_or_create_app_for_url() -> object:
    """Return a singleton app keyed on the current DATABASE_URL.

    Module-level callers (32 files) all use the session URL → one shared instance.
    Callers inside monkeypatched tests that change DATABASE_URL get an isolated
    instance for that URL, preserving the original per-test DB isolation.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    with _SINGLETONS_LOCK:
        if db_url not in _SINGLETONS:
            import src.app.main as _m  # noqa: PLC0415
            _SINGLETONS[db_url] = _m._original_create_app()
        return _SINGLETONS[db_url]


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    """Install the per-URL singleton factory before any test module is imported."""
    # ── Guard: ensure KILL_SWITCH is False before any module is collected ────
    # A previous crashed run may leave config/feature_flags.json with
    # KILL_SWITCH: True.  test_rollout_and_killswitch.py captures _ORIGINAL_FLAGS
    # at module-import time (collection), so it would "restore" to the corrupted
    # kill-switch-on state for every test in the suite.  Reset it here, before
    # any module is imported, so _ORIGINAL_FLAGS always captures a clean state.
    try:
        import json as _json

        _fpath = Path("config/feature_flags.json")
        _fpath.parent.mkdir(parents=True, exist_ok=True)

        # Canonical flags baseline — written whenever the file is missing,
        # empty, or missing required keys (handles truncated-file cascade).
        _BASELINE_FLAGS: dict = {
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {
                "recommend": {"enabled": True, "rollout_percent": 100},
                "pricing": {"enabled": True, "rollout_percent": 100},
            },
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
            "SEASONAL_CONTEXT": {
                "active_season": None,
                "boosts": {
                    "back_to_school": {
                        "student": 1.3,
                        "content_creation": 1.15,
                        "software_development": 1.1,
                    },
                    "gaming_season": {
                        "gaming": 1.4,
                        "rtx": 1.25,
                        "high_performance": 1.2,
                    },
                    "holiday": {
                        "gaming": 1.35,
                        "content_creation": 1.2,
                        "premium": 1.15,
                    },
                    "new_year_refresh": {
                        "business": 1.2,
                        "student": 1.15,
                        "value": 1.1,
                    },
                },
            },
        }

        # Read current file; fall back to baseline on empty / invalid JSON
        _fdata: dict = {}
        if _fpath.exists():
            try:
                _raw = _fpath.read_text("utf-8").strip()
                _fdata = _json.loads(_raw) if _raw else {}
            except Exception:
                _fdata = {}

        _dirty = False
        if not _fdata:
            # Empty or unreadable — restore full baseline
            _fdata = dict(_BASELINE_FLAGS)
            _dirty = True
        else:
            # Selective repairs on an otherwise valid file
            if _fdata.get("KILL_SWITCH"):
                _fdata["KILL_SWITCH"] = False
                _dirty = True
            if "SEASONAL_CONTEXT" not in _fdata:
                _fdata["SEASONAL_CONTEXT"] = _BASELINE_FLAGS["SEASONAL_CONTEXT"]
                _dirty = True

        if _dirty:
            _fpath.write_text(
                _json.dumps(_fdata, indent=2, ensure_ascii=False), "utf-8"
            )
    except Exception:
        pass

    # ── Prevent Ollama from hanging collection-time create_app() calls ───────
    # Module-level `app = create_app()` in ~32 test files runs at collection
    # time, before pytest_sessionstart.  Without this, ManagedCVProvider will
    # block up to 20 s × 6 model candidates = 120 s every time /cv/analyze is
    # hit in TestCVAnalyzeWithRealImages (and similar) when Ollama is offline.
    os.environ.setdefault("CV_VISION_ENABLED", "0")
    os.environ.setdefault("CV_VISION_TIMEOUT_SEC", "1")
    os.environ.setdefault("CV_DAMAGE_YOLO_MODEL", "")
    os.environ.setdefault("CV_DETECTOR_MODEL", "")
    # Prevent _summarize_results from calling live Ollama during tests.
    # Tests that need LLM summary behavior monkeypatch recommend_router._summarize_results directly.
    os.environ.setdefault("USE_LLM_SUMMARY", "0")
    os.environ.setdefault("USE_LLM_RERANK", "0")
    os.environ.setdefault("USE_OLLAMA_INTENT", "0")
    # Tesseract calls pytesseract.image_to_string() without a timeout by default,
    # which can hang indefinitely when tesseract.exe is not on PATH or unresponsive.
    # In tests without a real tesseract binary, set a short timeout (3 s) so the
    # OCR fallback path triggers quickly instead of hanging the test suite.
    os.environ.setdefault("CV_OCR_TIMEOUT_SEC", "3")
    # Disable the OCR provider in tests that don't explicitly need it.
    # Tests that require OCR set monkeypatch.setenv("CV_OCR_PROVIDER", "embedded")
    # which overrides this default.  With "disabled", _tesseract_text() returns
    # immediately from Stage A (empty), skipping the expensive Stage B
    # multi-contrast deep OCR pass that can add 5-30 s per image.
    os.environ.setdefault("CV_OCR_PROVIDER", "disabled")
    # Bound the total wall-clock time for the three parallel cv/analyze tasks
    # (tier2, consistency, QR decode) so tests never hang indefinitely when
    # YOLO/Ollama/tesseract are unavailable in the test environment.
    os.environ.setdefault("CV_ANALYZE_TIMEOUT_SEC", "8")

    # ── Cap xdist worker count to 2 ─────────────────────────────────────────
    # Running ``pytest -n auto`` on this machine can spike memory to >20 GB
    # (N workers × ~1 GB app singleton + YOLOv8 models per worker).  Cap at 2
    # so that if someone adds ``-n auto`` to their local run it never exceeds a
    # safe ceiling.  The check is a no-op when pytest-xdist is not installed.
    try:
        n = getattr(config.option, "numprocesses", None)
        if isinstance(n, int) and n > 2:
            config.option.numprocesses = 2
    except AttributeError:
        pass

    try:
        import src.app.main as _m  # noqa: PLC0415
    except Exception:  # pragma: no cover — src not importable yet
        return
    if hasattr(_m, "_original_create_app"):
        return  # already patched (re-entrant call guard)
    _m._original_create_app = _m.create_app  # type: ignore[attr-defined]
    _m.create_app = _get_or_create_app_for_url  # type: ignore[attr-defined]


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
    session_db_url = f"sqlite+pysqlite:///{db_file}"
    os.environ["DATABASE_URL"] = session_db_url
    os.environ["DATABASE_URL_RO"] = session_db_url

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

    # ── Block accidental YOLO model loads ───────────────────────────────────
    # ultralytics IS installed in this venv.  If CV_DAMAGE_YOLO_MODEL or
    # CV_DETECTOR_MODEL leak in from a prior demo/server run, every
    # DamageClassifier / CVObjectDetector instantiation inside a test (inc.
    # per-request app code) would load a 200-600 MB .pt file — once per HTTP
    # request for tests that hit /api/v1/cv/*.  Set to empty to disable;
    # tests that explicitly need YOLO should use the session-scoped
    # yolo_object_detector / yolo_damage_classifier fixtures below.
    os.environ.setdefault("CV_DAMAGE_YOLO_MODEL", "")
    os.environ.setdefault("CV_DETECTOR_MODEL", "")

    # Prevent Ollama vision calls from hanging the test suite.
    # With no Ollama server, urllib.request.urlopen tries N model candidates
    # at CV_VISION_TIMEOUT_SEC each (default 20s × up to 6 = 120 s hang per call).
    # Setting 1 s means the graceful fallback path is taken in <6 s.
    os.environ.setdefault("CV_VISION_TIMEOUT_SEC", "1")

    # Align the module-level engine with the session DATABASE_URL.
    # During collection some test modules call create_app() before
    # pytest_sessionstart has set DATABASE_URL, which creates a stale
    # singleton (keyed on "") backed by sqlite:///test.sqlite and sets the
    # module-level engine to that stale file.  The _restore_db_engine
    # autouse fixture then snapshots that stale engine and, after the first
    # real test creates the session singleton (which calls set_engine with the
    # session engine), incorrectly restores the stale engine — making all
    # subsequent db_session() calls outside a request write to the wrong DB.
    # Calling set_engine() here ensures the module-level engine points at the
    # session DB before any test fixture snapshot is taken.
    try:
        from sqlalchemy import create_engine as _create_engine
        from src.app.models.db import set_engine as _set_engine
        _session_eng = _create_engine(session_db_url, pool_pre_ping=True, future=True)
        _set_engine(_session_eng)
        # Pre-populate the singleton for the session URL so the first
        # create_app() call reuses this engine rather than creating a new one.
        with _SINGLETONS_LOCK:
            if session_db_url not in _SINGLETONS:
                import src.app.main as _m  # noqa: PLC0415
                _SINGLETONS[session_db_url] = _m._original_create_app()
        # Align ALL singleton apps' app.state.engine so that db_session()
        # inside request handlers uses the session DB engine.
        # Tests with their own module-specific engines (e.g. StaticPool) should
        # override app.state.engine in their own test bodies and restore it when done.
        with _SINGLETONS_LOCK:
            for _app_inst in _SINGLETONS.values():
                try:
                    _app_inst.state.engine = _session_eng
                except Exception:
                    pass
        # Also ensure the schema exists in the session DB (the stale singleton's
        # ensure_metadata() may have run against a different engine).
        try:
            from src.app.models.db import _ensure_minimal_sqlite_tables  # noqa: PLC0415
            _ensure_minimal_sqlite_tables(_session_eng)
        except Exception:
            pass
        try:
            from src.app.models.orm import Base  # noqa: PLC0415
            Base.metadata.create_all(_session_eng)
        except Exception:
            pass
    except Exception:
        pass


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Clean up session-scoped resources after the test run.

    1. Remove the temp SQLite DB file (+ WAL/SHM journal files) created by
       ``pytest_sessionstart``.  Without this, every run leaves behind a
       2-10 MB file in %TEMP%, which accumulates across many daily runs.
    2. Clear the ``_SINGLETONS`` dict so CPython can GC the app instances,
       connection pools, thread pools, and middleware chains they hold before
       any remaining teardown hooks run.
    """
    # 1 — temp DB cleanup
    try:
        db_url = os.environ.get("DATABASE_URL", "")
        if "shopsquire_test_" in db_url:
            db_path = db_url.split("///")[-1]
            for suffix in ("", "-wal", "-shm"):
                p = Path(db_path + suffix)
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    # 2 — release all singleton app references so GC can reclaim memory
    with _SINGLETONS_LOCK:
        _SINGLETONS.clear()


@pytest.fixture(autouse=True)
def _restore_feature_flags_file():
    """Prevent cross-test pollution of config/feature_flags.json.

    Several tests write minimal payloads (e.g. only DECISION_LOG_WRITES_ENABLED),
    which can erase required keys for later tests if not restored.
    """
    flags_path = Path("config/feature_flags.json")
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


@pytest.fixture(autouse=True)
def _reset_store_profile_cache():
    """Clear the StoreProfile lru_cache (and the profile-derived taxonomy/vocab caches)
    between tests so a profile loaded under one vertical (e.g. pharmacy) can't leak into the
    next test's reads. PROVABLY SAFE and NON-masking: it reloads identical static JSON, so it
    can never change a test's verdict (unlike the catalog/Redis clears that masked NQE — see
    docs/DETERMINISM.md)."""
    def _reset_all():
        for mod, fn in (
            ("src.app.platform.store_profile", "reset_cache"),
            ("src.app.services.product_classifier", "reset_cache"),
            ("src.app.services.product_claim_guard", "reset_vocab_cache"),
        ):
            try:
                getattr(__import__(mod, fromlist=[fn]), fn)()
            except Exception:
                pass
    _reset_all()
    yield
    _reset_all()


@pytest.fixture(autouse=True)
def _restore_db_engine():
    """Snapshot and restore the module-level DB engine after each test.

    Tests that call ``set_engine()`` to configure an isolated DB (e.g.
    in-memory SQLite for `test_db_upsert`) would otherwise leak their engine
    into subsequent tests via the singleton app — because the old code relied
    on each ``create_app()`` call to reset the engine, which no longer happens
    with the per-URL singleton.

    This fixture is zero-overhead for the common case where no test changes
    the engine (just a reference comparison at teardown).
    """
    try:
        from src.app.models.db import get_engine, set_engine  # noqa: PLC0415
        original_engine = get_engine()
    except Exception:
        yield
        return
    yield
    try:
        from src.app.models.db import get_engine, set_engine  # noqa: PLC0415
        if get_engine() is not original_engine:
            set_engine(original_engine)
            # Re-align all singleton app.state.engine so that request handlers
            # use the same engine as db_session() after restoration.
            with _SINGLETONS_LOCK:
                for _app_inst in _SINGLETONS.values():
                    try:
                        _app_inst.state.engine = original_engine
                    except Exception:
                        pass
            # Reset one-time table-ready flags so they re-create tables on the
            # restored engine.  This prevents "no such table" errors when a test
            # used an in-memory or isolated engine and these flags stayed True.
            try:
                import src.app.security.security_event_ingest as _sei  # noqa: PLC0415
                _sei._SECURITY_EVENT_TABLE_READY = False
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session-scoped YOLO fixtures — load each model ONCE per test session
# ---------------------------------------------------------------------------
# ultralytics is installed.  Tests must NOT construct DamageClassifier or
# CVObjectDetector with real model paths in their own bodies because that
# would load a 200-600 MB .pt file once per test function.  Instead, request
# one of these fixtures; pytest guarantees session scope = single load.
# In the default test config (CV_*_MODEL="") both return no-op instances.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def yolo_object_detector():
    """Session-scoped CVObjectDetector — YOLO model loaded at most once.

    Returns ``CVObjectDetector(model_path=None)`` (heuristic-only) when
    ``CV_DETECTOR_MODEL`` is blank, which is the default test configuration.
    Set ``CV_DETECTOR_MODEL=yolov8n.pt`` to enable real inference in a run.
    """
    from src.app.services.cv_object_detector import CVObjectDetector  # noqa: PLC0415
    model_path = os.environ.get("CV_DETECTOR_MODEL") or None
    return CVObjectDetector(model_path=model_path)


@pytest.fixture(scope="session")
def yolo_damage_classifier():
    """Session-scoped DamageClassifier — YOLO model loaded at most once.

    Returns a heuristic-only classifier when ``CV_DAMAGE_YOLO_MODEL`` is
    blank (the default).  Pass ``CV_DAMAGE_YOLO_MODEL=yolov8s.pt`` to
    enable the full YOLO damage detection path.
    """
    from src.app.services.cv_damage_classifier import DamageClassifier  # noqa: PLC0415
    yolo_path = os.environ.get("CV_DAMAGE_YOLO_MODEL") or None
    return DamageClassifier(model_path=None, yolo_model_path=yolo_path)


# ---------------------------------------------------------------------------
# Per-test RSS guard
# ---------------------------------------------------------------------------
# Emits a stderr warning (visible even with -p no:warnings) when a single
# test grows the Python process RSS by > 300 MB.  This catches model loads,
# large fixture leaks, and SQLAlchemy connection-pool explosions early.
# psutil 7.2.2 is available in the project venv.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _rss_guard():
    """Warn to stderr when a test grows process RSS by > 300 MB."""
    try:
        import psutil  # noqa: PLC0415
        proc = psutil.Process(os.getpid())
        rss_before = proc.memory_info().rss
    except Exception:
        yield
        return
    yield
    try:
        import psutil  # noqa: PLC0415
        rss_after = psutil.Process(os.getpid()).memory_info().rss
        delta_mb = (rss_after - rss_before) / 1_048_576
        if delta_mb > 300:
            sys.stderr.write(
                f"\n[OOM-GUARD] {delta_mb:.0f} MB RSS spike in this test "
                f"(before={rss_before // 1_048_576} MB, "
                f"after={rss_after // 1_048_576} MB). "
                "Check for ML model loads, large fixtures, or unclosed connections.\n"
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Skip @pytest.mark.slow tests unless --run-slow is given
# ---------------------------------------------------------------------------
# CV pipeline / large-image-inference tests take 60–120 s due to YOLOv8
# model loading.  They are marked ``@pytest.mark.slow`` and skipped by
# default.  Pass ``--run-slow`` on the CLI to include them.
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Include @pytest.mark.slow tests (skipped by default).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    if config.getoption("--run-slow", default=False):
        return  # run everything
    skip_slow = pytest.mark.skip(reason="slow test — pass --run-slow to enable")
    for item in items:
        if item.get_closest_marker("slow"):
            item.add_marker(skip_slow)
