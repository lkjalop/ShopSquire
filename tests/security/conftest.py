import os
import time
import threading
import socket
from urllib.parse import urlparse

import pytest
import requests
import uvicorn


def _find_free_port(start: int = 8082) -> int:
    port = start
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _wait_ready(base_url: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(base_url.rstrip("/") + "/health", timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session", autouse=True)
def security_test_server():
    """Start a local API server for red-team tests if none is running."""
    env_base = os.getenv("E2E_BASE_URL")
    if env_base:
        if _wait_ready(env_base, timeout=2):
            yield {"base_url": env_base}
            return

    host = os.getenv("SECURITY_TEST_HOST", "127.0.0.1")
    # Pick a free port deterministically to avoid races with TIME_WAIT / parallel runs.
    requested = int(os.getenv("SECURITY_TEST_PORT", "8082"))
    port = _find_free_port(requested)
    base_url = f"http://{host}:{port}"

    if _wait_ready(base_url, timeout=2):
        os.environ["E2E_BASE_URL"] = base_url
        yield {"base_url": base_url}
        return

    db_path = os.path.join("tests", "security", "redteam.sqlite")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ.setdefault("DISABLE_TRACING", "1")

    from src.app.main import create_app

    app = create_app()
    config = uvicorn.Config(app=app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not _wait_ready(base_url, timeout=60):
        raise RuntimeError("Security test server did not become ready")

    os.environ["E2E_BASE_URL"] = base_url
    yield {"base_url": base_url}
    try:
        server.should_exit = True
    except Exception:
        pass
    thread.join(timeout=10)
