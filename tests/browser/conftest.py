import os
import time
import threading

import pytest
import requests
import uvicorn
import socket
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

# Skip the entire browser test suite when playwright is not installed.
# Install with: pip install pytest-playwright && playwright install chromium
try:
    import playwright  # noqa: F401
except ImportError:
    pytest.skip("playwright not installed — run 'pip install pytest-playwright && playwright install'",
                allow_module_level=True)

# A fixed repository-local SQLite file leaked locks and state between browser
# runs. Give every pytest process an isolated database; the session fixture
# removes it (and SQLite sidecars) after the server exits.
BROWSER_DB_PATH = str(
    Path(tempfile.gettempdir()) / f"shopsquire-browser-{os.getpid()}.sqlite"
)

# Compute a dynamic base URL early so test modules that read env at import time
# will pick up the correct value instead of the default 8080.
_host = os.getenv("E2E_HOST", "127.0.0.1")
_env_port = os.getenv("E2E_PORT", "")
try:
    _port = int(_env_port) if _env_port else 0
except Exception:
    _port = 0
if not _port:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as _s:
        _s.bind((_host, 0))
        _s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _port = _s.getsockname()[1]
os.environ["E2E_PORT"] = str(_port)
os.environ["E2E_BASE_URL"] = f"http://{_host}:{_port}"


@pytest.fixture(scope="session", autouse=True)
def browser_test_server():
    host = os.getenv("E2E_HOST", "127.0.0.1")
    env_port = os.getenv("E2E_PORT", "")
    try:
        port = int(env_port) if env_port else 0
    except Exception:
        port = 0
    if not port:
        # Find a free ephemeral port
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind((host, 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            port = s.getsockname()[1]
        os.environ["E2E_PORT"] = str(port)
    prev_env = {k: os.environ.get(k) for k in [
        "E2E_BASE_URL",
        "FEATURE_FLAGS_PATH",
        "TEST_BYPASS_POLICY_GATE",
        "TEST_TOLERANT_GET_ERRORS",
        "CV_PROVIDER",
        "DATABASE_URL",
        "APP_ENV",
        "DECISION_LOG_PREWARM_ON_START",
        "ROUTER_PREWARM_ON_START",
    ]}
    os.environ["E2E_BASE_URL"] = f"http://{host}:{port}"
    flags_path = os.path.join("tests", "browser", "flags.json")
    os.environ.setdefault("FEATURE_FLAGS_PATH", flags_path)
    os.environ["APP_ENV"] = "testing"
    os.environ["DECISION_LOG_PREWARM_ON_START"] = "0"
    os.environ["ROUTER_PREWARM_ON_START"] = "0"
    os.environ["DISABLE_UI_ROUTES"] = "0"
    os.environ.setdefault("TEST_BYPASS_POLICY_GATE", "1")
    os.environ.setdefault("TEST_TOLERANT_GET_ERRORS", "1")
    os.environ.setdefault("CV_PROVIDER", "basic")
    os.environ.setdefault("RATE_LIMIT_PER_IP_PER_MIN", "0")
    os.makedirs(os.path.dirname(BROWSER_DB_PATH), exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{BROWSER_DB_PATH}"

    # Browser tests exercise production-shaped startup. Apply the actual
    # migration chain before starting Uvicorn so background seeders do not
    # repeatedly probe tables that do not exist.
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    alembic_command.upgrade(AlembicConfig("alembic.ini"), "head")

    from src.app.main import create_app
    from src.app.models.init_db import ensure_metadata

    print(f"[browser.conftest] Starting server on {host}:{port}")
    app = create_app()
    try:
        ensure_metadata()
    except Exception:
        pass
    config = uvicorn.Config(app=app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://{host}:{port}"
    deadline = time.time() + 30
    ok = False
    while time.time() < deadline:
        try:
            r = requests.get(base_url + "/healthz", timeout=1)
            if r.status_code == 200:
                ok = True
                break
        except Exception:
            time.sleep(0.5)
    if not ok:
        raise RuntimeError("Browser test server failed to start")

    yield

    try:
        server.should_exit = True
    except Exception:
        pass
    thread.join(timeout=10)
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(f"{BROWSER_DB_PATH}{suffix}").unlink(missing_ok=True)
        except OSError:
            pass
    for key, value in prev_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def seed_browser_catalog():
    """Deterministic per-test catalog seed for storefront/detail/cart flows."""
    con = sqlite3.connect(BROWSER_DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM inventory")
    cur.execute("DELETE FROM products")
    cur.execute(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, active) VALUES (?,?,?,?,?,?,1)",
        (
            "e2e_p1",
            "E2E-001",
            "E2E Laptop 14",
            129900,
            "AUD",
            '{"cpu":"Intel Core i7","graphics":"Intel Iris Xe","ram_gb":16,"storage":"512GB","wifi":"Wi-Fi 6","ports":["USB-C","HDMI"]}',
        ),
    )
    cur.execute(
        "INSERT INTO inventory (id, product_id, stock, warehouse) VALUES (?,?,?,?)",
        ("e2e_inv1", "e2e_p1", 6, "default"),
    )
    con.commit()
    con.close()
