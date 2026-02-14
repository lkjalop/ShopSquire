import os
import sys
import time
from pathlib import Path

# Force ProactorEventLoop on Windows early so pytest-playwright can spawn subprocesses.
try:
    import asyncio
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
except Exception:
    pass

# Optionally disable Playwright-driven e2e tests by injecting a minimal
# placeholder `playwright` module so test modules detect absence and skip.
if os.environ.get("DISABLE_PLAYWRIGHT_TESTS", "1").strip().lower() in ("1", "true", "yes"):
    try:
        import types

        # Insert a minimal module so `from playwright.sync_api import sync_playwright`
        # will raise in the test module and cause the skip path to run.
        if "playwright" not in sys.modules:
            sys.modules["playwright"] = types.ModuleType("playwright")
    except Exception:
        pass

import psycopg2
from sqlalchemy import text

# Ensure project root is on sys.path so imports like `src.*` and `tests.*` work
ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

try:
    import pytest  # noqa: F401
except Exception:
    pytest = None

_BASE_FLAGS_TEXT = None
_BASE_PLAYBOOKS_TEXT = None
_BASE_DB_ENGINE = None
_BASE_DB_SESSIONLOCAL = None

# Override pytest-playwright fixture to ensure Proactor loop on Windows.
try:
    from playwright.sync_api import sync_playwright  # type: ignore
except Exception:
    sync_playwright = None

if 'pytest' in globals() and pytest is not None:
    @pytest.fixture(scope="session")
    def playwright():
        if sync_playwright is None:
            pytest.skip("playwright not installed")
        try:
            import asyncio
            if sys.platform.startswith("win"):
                try:
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                except Exception:
                    pass
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                except Exception:
                    pass
        except Exception:
            pass
        with sync_playwright() as p:
            yield p

    @pytest.fixture(autouse=True)
    def restore_feature_flags():
        yield
        if _BASE_FLAGS_TEXT is None:
            return
        try:
            (ROOT / "config" / "feature_flags.json").write_text(_BASE_FLAGS_TEXT, encoding="utf-8")
        except Exception:
            pass

    @pytest.fixture(autouse=True)
    def restore_playbooks_config():
        yield
        if _BASE_PLAYBOOKS_TEXT is None:
            return
        try:
            p = ROOT / "config" / "security" / "cv_playbooks.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_BASE_PLAYBOOKS_TEXT, encoding="utf-8")
            try:
                from src.app.services.playbook_engine import load_playbook_config
                load_playbook_config(force_reload=True)
            except Exception:
                pass
        except Exception:
            pass

    @pytest.fixture(autouse=True)
    def restore_db_engine():
        if os.getenv("SKIP_RESTORE_DB_ENGINE", "0").lower() in ("1", "true", "yes"):
            yield
            return
        yield
        try:
            from src.app.models import db as dbmod
            if _BASE_DB_ENGINE is not None:
                dbmod.engine = _BASE_DB_ENGINE
            if _BASE_DB_SESSIONLOCAL is not None:
                dbmod.SessionLocal = _BASE_DB_SESSIONLOCAL
        except Exception:
            pass


DEFAULT_DB_URL = "postgresql+psycopg2://shopsquire:shopsquire@localhost:5433/shopsquire_test"


def _ensure_db_ready():
    # Derive connection params for psycopg2
    url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    # If using SQLite for tests, skip Postgres readiness checks
    if url.startswith("sqlite") or "sqlite" in url:
        return
    # Normalize driver prefix for psycopg2 (drop "+psycopg2")
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)

    # Basic wait-for-DB loop
    deadline = time.time() + 5
    last_err = None
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(url)
            conn.close()
            return
        except Exception as e:
            last_err = e
            time.sleep(2)
    # Fallback to SQLite for local test runs when Postgres isn't available
    os.environ["DATABASE_URL"] = "sqlite:///test.sqlite"
    return


def _apply_sql_file(url: str, sql_path: Path):
    # psycopg2 expects postgresql:// scheme
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    # If SQLite, apply SQL via SQLAlchemy engine execution
    if url.startswith("sqlite") or "sqlite" in url:
        from sqlalchemy import create_engine, text

        eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)
        sql = sql_path.read_text(encoding="utf-8")
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with eng.begin() as conn:
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
        return
    with psycopg2.connect(url) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            sql = sql_path.read_text(encoding="utf-8")
            cur.execute(sql)
            # Ensure search_path is applied for subsequent sessions during tests
            try:
                cur.execute("SET search_path TO oltp, audit, security, public")
            except Exception:
                pass


def pytest_sessionstart(session):
    # Silence tracing noise in tests
    os.environ.setdefault("DISABLE_TRACING", "1")
    # Ensure a default event loop exists for Windows test runs
    try:
        import asyncio
        if sys.platform.startswith("win"):
            # Use the ProactorEventLoop on Windows to support subprocesses
            # (Playwright launches a driver subprocess which requires this).
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except Exception:
        pass
    # Force SQLite for deterministic local tests unless explicitly overridden
    if not os.getenv("DATABASE_URL") or os.getenv("FORCE_POSTGRES_TESTS", "0") not in ("1", "true", "yes"):
        os.environ["DATABASE_URL"] = "sqlite:///test.sqlite"

    # Test helpers: deterministic storefront product list and demo decision traces
    os.environ.setdefault("TEST_USE_FALLBACK_PRODUCTS", "1")
    os.environ.setdefault("TEST_USE_DEMO_DECISION_TRACE", "1")

    # Capture baseline feature flags for restoration between tests
    global _BASE_FLAGS_TEXT, _BASE_PLAYBOOKS_TEXT
    try:
        _BASE_FLAGS_TEXT = (ROOT / "config" / "feature_flags.json").read_text(encoding="utf-8")
    except Exception:
        _BASE_FLAGS_TEXT = None
    try:
        _BASE_PLAYBOOKS_TEXT = (ROOT / "config" / "security" / "cv_playbooks.json").read_text(encoding="utf-8")
    except Exception:
        _BASE_PLAYBOOKS_TEXT = None

    # Clean up any persisted sqlite test DB files to avoid uniqueness conflicts
    for path in ROOT.glob("*.sqlite"):
        try:
            path.unlink()
        except Exception:
            pass

    # If using Postgres, wait for it; for SQLite, skip readiness and apply SQL via SQLAlchemy
    url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    if not (url.startswith("sqlite") or "sqlite" in url):
        _ensure_db_ready()
        # Re-read URL in case readiness fell back to SQLite
        url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

    root = Path(__file__).resolve().parents[1]
    # Choose schema file based on DB URL
    is_pg = url.startswith("postgres") or "postgres" in url
    schema = root / "db" / ("schema_postgres.sql" if is_pg else "schema.sql")
    seed = root / "db" / "seed.sql"

    _apply_sql_file(url, schema)
    _apply_sql_file(url, seed)

    # Capture baseline DB engine/session for restoration between tests
    global _BASE_DB_ENGINE, _BASE_DB_SESSIONLOCAL
    try:
        from src.app.models import db as dbmod
        _BASE_DB_ENGINE = dbmod.engine
        _BASE_DB_SESSIONLOCAL = dbmod.SessionLocal
    except Exception:
        _BASE_DB_ENGINE = None
        _BASE_DB_SESSIONLOCAL = None

    # Make asyncio.run safe when an event loop may already be active (tests or background servers).
    try:
        import threading, queue
        _orig_asyncio_run = asyncio.run

        def _threaded_asyncio_run(coro):
            try:
                # If there's no running loop we can call the original directly
                asyncio.get_running_loop()
            except RuntimeError:
                return _orig_asyncio_run(coro)
            # Otherwise run the coroutine in a separate thread to avoid "asyncio.run() cannot be called from a running event loop"
            q = queue.Queue()

            def _target():
                try:
                    res = _orig_asyncio_run(coro)
                    q.put((True, res))
                except Exception as e:
                    q.put((False, e))

            t = threading.Thread(target=_target)
            t.start()
            ok, val = q.get()
            t.join()
            if ok:
                return val
            raise val

        asyncio.run = _threaded_asyncio_run
    except Exception:
        pass

if 'pytest' in globals() and pytest is not None:
    @pytest.fixture(autouse=True)
    def _reset_sqlite_db_per_test():
        # Avoid deleting sqlite files while servers are running; instead clear tables.
        # File deletion can break engines that keep an open handle to the DB.
        if os.getenv("SKIP_DB_RESET", "0").lower() in ("1", "true", "yes"):
            yield
            return
        try:
            import src.app.models.db as dbmod
            eng = getattr(dbmod, 'engine', None)
            if eng is not None:
                with eng.begin() as conn:
                    for tbl in [
                        'products', 'inventory', 'orders', 'security_events',
                        'incidents', 'decision_logs'
                    ]:
                        try:
                            conn.execute(text(f"DELETE FROM {tbl}"))
                        except Exception:
                            pass
        except Exception:
            pass
        yield

    @pytest.fixture(autouse=True)
    def _mock_ollama(monkeypatch):
        """Autouse fixture to mock Ollama /api/generate for tests to avoid external calls.

        Mocks both async (`httpx.AsyncClient.post`) and sync (`httpx.Client.post`) usage.
        """
        # Allow disabling global httpx mocking when tests need real client behavior.
        try:
            if os.getenv("DISABLE_GLOBAL_HTTPX_MOCK", "0").lower() in ("1", "true", "yes"):
                yield
                return
        except Exception:
            pass
        try:
            import httpx
        except Exception:
            httpx = None

        if httpx is None:
            yield
            return

        class DummyResp:
            def __init__(self, payload):
                import json as _json
                self._payload = payload
                # Provide common response attributes used by callers/tests
                self.status_code = 200
                try:
                    self.text = _json.dumps(payload)
                    self.content = self.text.encode("utf-8")
                except Exception:
                    self.text = str(payload)
                    self.content = self.text.encode("utf-8")

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        async def _async_post(self, url, *args, **kwargs):
            # Preserve TestClient/internal httpx behavior: do not inject/override kwargs like `json=None`.
            if url and "/api/generate" not in str(url):
                return await _orig_async_post(self, url, *args, **kwargs)
            if url and "/api/generate" in str(url):
                return DummyResp({"response": "mocked response"})
            return DummyResp({})

        def _sync_post(self, url, *args, **kwargs):
            if url and "/api/generate" not in str(url):
                return _orig_sync_post(self, url, *args, **kwargs)
            if url and "/api/generate" in str(url):
                return DummyResp({"response": "mocked response"})
            return DummyResp({})

        # Preserve originals so TestClient and internal HTTP calls keep working
        try:
            _orig_async_post = httpx.AsyncClient.post
        except Exception:
            _orig_async_post = None
        try:
            _orig_sync_post = httpx.Client.post
        except Exception:
            _orig_sync_post = None

        # Patch httpx clients used across the codebase
        try:
            monkeypatch.setattr(httpx.AsyncClient, 'post', _async_post, raising=False)
        except Exception:
            pass
        try:
            monkeypatch.setattr(httpx.Client, 'post', _sync_post, raising=False)
        except Exception:
            pass

        yield

    @pytest.fixture(autouse=True)
    def _mock_heavy_services(monkeypatch):
        """Mock heavy CV and reverse search services to speed up tests and avoid external calls."""
        # Allow disabling heavy service mocks for targeted integration tests.
        try:
            if os.getenv("DISABLE_HEAVY_SERVICE_MOCK", "0").lower() in ("1", "true", "yes"):
                yield
                return
        except Exception:
            pass
        try:
            from src.app.services.cv_provider import ManagedCVProvider
        except Exception:
            ManagedCVProvider = None
        try:
            from src.app.services.reverse_image_search import ReverseImageSearch
        except Exception:
            ReverseImageSearch = None

        # Mock ManagedCVProvider.get_labels_and_text (support async and sync)
        async def _async_get_labels_and_text(self, image_bytes):
            return (["mock_label"], "mocked extracted text")

        def _sync_get_labels_and_text(self, image_bytes):
            return (["mock_label"], "mocked extracted text")

        if ManagedCVProvider is not None:
            try:
                monkeypatch.setattr(ManagedCVProvider, 'get_labels_and_text', _async_get_labels_and_text, raising=False)
            except Exception:
                try:
                    monkeypatch.setattr(ManagedCVProvider, 'get_labels_and_text', _sync_get_labels_and_text, raising=False)
                except Exception:
                    pass

        # Mock ReverseImageSearch.find_similar
        if ReverseImageSearch is not None:
            def _find_similar(self, phash, max_distance=8, limit=5):
                return []
            try:
                monkeypatch.setattr(ReverseImageSearch, 'find_similar', _find_similar, raising=False)
            except Exception:
                pass

        yield
