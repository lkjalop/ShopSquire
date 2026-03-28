import os
import json
import time
import threading
import socket
import requests
import uvicorn
import pytest
import logging
import asyncio

# Skip the entire Playwright test suite unless explicitly enabled.
if os.getenv("DISABLE_PLAYWRIGHT_TESTS", "1").strip().lower() in ("1", "true", "yes"):
    pytest.skip("Playwright tests disabled (set DISABLE_PLAYWRIGHT_TESTS=0 to enable)", allow_module_level=True)

# Ensure Playwright can spawn subprocesses on Windows
try:
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
except Exception:
    pass


def _find_free_port(start: int = 8099) -> int:
    port = start
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1


@pytest.fixture(scope="module")
def test_server():
    """Start the FastAPI app with uvicorn in a background thread for browser tests."""
    requested_port = int(os.getenv("PLAYWRIGHT_TEST_PORT", "8099"))
    host = os.getenv("PLAYWRIGHT_TEST_HOST", "127.0.0.1")
    prev_skip_db_reset = os.environ.get("SKIP_DB_RESET")
    prev_skip_restore_db_engine = os.environ.get("SKIP_RESTORE_DB_ENGINE")
    prev_feature_flags_path = os.environ.get("FEATURE_FLAGS_PATH")
    # Ensure the test server uses the repo feature flags and test-friendly overrides
    # Use a Playwright-specific flags file so other tests can freely overwrite
    # `config/feature_flags.json` without affecting the long-running pw server.
    flags_path = os.path.join("tests", "playwright", "feature_flags_pw.json")
    os.makedirs(os.path.dirname(flags_path), exist_ok=True)
    base_flags = {
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "DECISION_LOG_WRITES_ENABLED": True,
        "DEGRADATION": {"enabled": False},
        "TEST_FORCE_BAD_SKU": False,
    }
    try:
        with open(flags_path, "w", encoding="utf-8") as f:
            json.dump(base_flags, f, ensure_ascii=False)
    except Exception:
        pass
    os.environ["FEATURE_FLAGS_PATH"] = flags_path
    os.environ.setdefault("TEST_BYPASS_POLICY_GATE", "1")
    os.environ.setdefault("TEST_TOLERANT_GET_ERRORS", "1")
    os.environ["TEST_FAST_HEALTH"] = "1"
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ.setdefault("CV_PROVIDER", "basic")
    os.environ["DISABLE_UI_ROUTES"] = "0"
    os.environ["RATE_LIMIT_PER_IP_PER_MIN"] = "0"
    os.environ["TEST_USE_DEMO_DECISION_TRACE"] = "0"
    # Ensure Playwright runs are deterministic and do not depend on any shared Redis state.
    # Point to an unreachable Redis so `get_redis()` falls back to DummyRedis.
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/15"
    try:
        import src.app.deps as deps

        deps._lazy_redis = None
    except Exception:
        pass
    # Use small deterministic fallback product set for Playwright storefront tests
    os.environ.setdefault("TEST_USE_FALLBACK_PRODUCTS", "1")
    # Prefer on-disk SQLite and disable tracing for faster startup and shared connections
    db_path = os.path.join("tests", "playwright", "smoke.sqlite")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
    # Force an isolated DB for Playwright so the app doesn't pick up a repo-level `.env` DATABASE_URL.
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    # Ensure global engine/session are pointed at this DB even if other tests imported the DB layer earlier.
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.app.models.db import set_engine

        eng = create_engine(
            os.environ["DATABASE_URL"],
            connect_args={"check_same_thread": False},
            future=True,
        )
        set_engine(eng)
        try:
            import src.app.models.db as dbmod

            dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
        except Exception:
            pass
    except Exception:
        pass
    os.environ.setdefault("DISABLE_TRACING", "1")
    os.environ.setdefault("SKIP_OBSERVER_ENDPOINTS", "/api/v1/orders")
    os.environ["SKIP_DB_RESET"] = "1"
    os.environ["SKIP_RESTORE_DB_ENGINE"] = "1"
    # Skip checkout dialog in Playwright widget tests by default to avoid hangs
    os.environ.setdefault("TEST_SKIP_CHECKOUT", "1")
    # Always allocate a free port for the test server.
    # This avoids the race where a connect probe succeeds but another process binds
    # the same port before uvicorn starts.
    port = _find_free_port(requested_port)
    # Import app after environment is prepared
    # Import app after environment is prepared. Wrap with logging for debug.
    try:
        print(f"[pw.conftest] Starting test server on {host}:{port} using DB={os.environ.get('DATABASE_URL')}")
        from src.app.main import create_app
        from src.app.models.init_db import ensure_metadata
        app = create_app()
        # Ensure schema exists before seeding
        try:
            ensure_metadata()
        except Exception:
            pass
    except Exception as e:
        print("[pw.conftest] Error importing or creating app:", e)
        raise
    config = uvicorn.Config(app=app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    print("[pw.conftest] uvicorn thread started")

    # Seed demo data using direct SQLite access (most reliable under mixed test-suite engine resets).
    try:
        import sqlite3

        con = sqlite3.connect(db_path)
        cur = con.cursor()
        specs1 = {"rating": 4.7, "shipping_days": 2, "ram_gb": 16, "storage": "512GB", "cpu": "Intel Core i7", "display": "14\" OLED", "graphics": "Intel Xe", "ports": ["USB-C", "HDMI"], "wifi": "Wi-Fi 6", "bluetooth": "5.2", "os": "Windows 11"}
        specs2 = {"rating": 4.5, "shipping_days": 3, "ram_gb": 16, "storage": "1TB", "cpu": "Apple M4", "display": "14\" Liquid Retina", "graphics": "Apple GPU", "ports": ["USB-C"], "wifi": "Wi-Fi 6E", "bluetooth": "5.3", "os": "macOS"}
        cur.execute("INSERT OR REPLACE INTO customers (id, email, name) VALUES (?,?,?)", ("cust_demo", "demo@example.com", "Demo User"))
        cur.execute("INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) VALUES (?,?,?,?,?,?,1)", ("p1", "XPS13PLUS", "Dell XPS 13 Plus", 129900, "USD", json.dumps(specs1)))
        cur.execute("INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) VALUES (?,?,?,?,?,?,1)", ("p2", "MBP14", "MacBook Pro 14", 209900, "USD", json.dumps(specs2)))
        cur.execute("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) VALUES (?,?,?,?)", ("inv1", "p1", 5, "default"))
        cur.execute("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) VALUES (?,?,?,?)", ("inv2", "p2", 3, "default"))
        con.commit()
        con.close()
    except Exception:
        pass

    # Wait for readiness (extended timeout). Print attempts for debugging.
    base_url = f"http://{host}:{port}"
    deadline = time.time() + 60
    ok = False
    last_err = None
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            print(f"[pw.conftest] health check attempt {attempt} -> {base_url}/health")
            r = requests.get(base_url + "/health", timeout=1)
            print(f"[pw.conftest] health status {r.status_code}")
            if r.status_code == 200:
                ok = True
                break
        except Exception as e:
            last_err = e
            print(f"[pw.conftest] health check failed: {e}")
        time.sleep(0.5)
    if not ok:
        msg = f"Server did not become ready for Playwright tests (last_err={last_err})"
        print("[pw.conftest] " + msg)
        raise RuntimeError(msg)

    yield {"base_url": base_url}
    # uvicorn Server respects should_exit flag. Use a configurable join timeout
    try:
        server.should_exit = True
    except Exception:
        pass
    join_timeout = int(os.getenv("PLAYWRIGHT_FIXTURE_JOIN_TIMEOUT", "10"))
    thread.join(timeout=join_timeout)
    if thread.is_alive():
        logging.getLogger("tests.pw.conftest").warning("Playwright test server thread did not exit within %s seconds", join_timeout)

    # Restore per-suite env overrides that can affect other tests.
    try:
        if prev_feature_flags_path is None:
            os.environ.pop("FEATURE_FLAGS_PATH", None)
        else:
            os.environ["FEATURE_FLAGS_PATH"] = prev_feature_flags_path
    except Exception:
        pass
    try:
        if prev_skip_db_reset is None:
            os.environ.pop("SKIP_DB_RESET", None)
        else:
            os.environ["SKIP_DB_RESET"] = prev_skip_db_reset
    except Exception:
        pass
    try:
        if prev_skip_restore_db_engine is None:
            os.environ.pop("SKIP_RESTORE_DB_ENGINE", None)
        else:
            os.environ["SKIP_RESTORE_DB_ENGINE"] = prev_skip_restore_db_engine
    except Exception:
        pass
