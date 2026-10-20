import os
import time
import socket
import subprocess
import sys

import pytest
import requests


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
        for path in ("/healthz", "/health", "/readyz"):
            try:
                r = requests.get(base_url.rstrip("/") + path, timeout=1)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
        time.sleep(0.5)
    return False


from contextlib import contextmanager
import uuid

_RUNTIME = pytest.StashKey()


def disable_message_connectors(env):
    """Remove inherited external-message authority from a copied test environment."""
    env.update(SECRETS_PROVIDER="env", SECRETS_PROVIDER_STRICT="0", INCIDENT_ALERTS_ENABLED="0")
    for key in list(env):
        if key.startswith(("JIRA_", "SN_", "SMTP_", "SENDGRID_", "SLACK_", "TEAMS_", "VAULT_")):
            env[key] = ""
    for key in ("JIRA_BASE_URL", "JIRA_PROJECT_KEY", "JIRA_API_TOKEN", "JIRA_USER", "JIRA_EMAIL",
                "SN_INSTANCE_URL", "SN_USERNAME", "SN_PASSWORD", "SN_TOKEN", "SMTP_PASSWORD",
                "SLACK_WEBHOOK_URL", "TEAMS_WEBHOOK_URL", "SENDGRID_API_KEY"):
        env[key] = ""
        env[key + "_REF"] = ""


@contextmanager
def _owned_runtime(config, *, artifact_directory=None, env_overrides=None, publish_base_url=True):
    import json
    from pathlib import Path
    from sqlalchemy.engine import make_url
    import sqlite3

    host = os.getenv("SECURITY_TEST_HOST", "127.0.0.1")
    if host != "127.0.0.1":
        raise RuntimeError("Owned security tests require IPv4 loopback")
    port = _find_free_port(int(os.getenv("SECURITY_TEST_PORT", "8082")))
    base_url = f"http://{host}:{port}"
    explicit_directory = os.getenv("PYTEST_OWNED_SECURITY_DIRECTORY")
    directory = (Path(artifact_directory) if artifact_directory is not None else
                 Path(explicit_directory) if explicit_directory else
                 Path(config.rootpath) / ".artifacts" / ("owned-security-" + uuid.uuid4().hex))
    directory.mkdir(parents=True, exist_ok=False)
    db_path = directory / "security.sqlite3"
    database_url = "sqlite:///" + db_path.as_posix()
    parent_url = make_url(os.environ.get("DATABASE_URL", "sqlite://"))
    if parent_url.get_backend_name() == "sqlite" and parent_url.database:
        parent_path = Path(parent_url.database)
        if parent_path.is_file():
            with sqlite3.connect(parent_path) as source, sqlite3.connect(db_path) as target:
                source.backup(target)
    flags = directory / "feature_flags.json"
    flags.write_text(json.dumps({
        "USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False, "DECISION_LOG_WRITES_ENABLED": False,
        "DEGRADATION": {"enabled": True}, "TEST_FORCE_BAD_SKU": False,
    }), encoding="utf-8")
    env = os.environ.copy()
    env.update(DATABASE_URL=database_url, DATABASE_URL_RO=database_url, DATABASE_URL_REF="",
        FEATURE_FLAGS_PATH=str(flags), APP_ENV="test", SECURITY_TEST_MODE="1",
        DISABLE_TRACING="1", OTEL_SDK_DISABLED="true", SECURITY_AUTOROUTE_ENABLED="0",
        EXTERNAL_RESEARCH_ENABLED="0", SEMANTIC_RESEARCH_FIXTURES_ENABLED="0", SECURITY_BLOCK_MODE="200",
        SECURITY_OBSERVER_SYNC="1", FAQ_INDEX_ON_STARTUP="0", VISUAL_SEARCH_INDEX_ON_STARTUP="0",
        OLLAMA_PREWARM_DISABLED="1", VLM_WARMUP_ON_START="0", CV_WARMUP_ON_START="0",
        WEBHOOK_DISPATCHER_WORKER_ENABLED="0", TASK_CONSUMER_ENABLED="0",
        PAYMENT_EXECUTION_ENABLED="0", ALLOW_DEMO_CHECKOUT="0", INCIDENT_ALERTS_ENABLED="0",
        SECRETS_PROVIDER="env", SECRETS_PROVIDER_STRICT="0",
        FULFILLMENT_SUPPLIER_TRANSPORT="sandbox", FULFILLMENT_PO_TRANSPORT="sandbox",
        CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    for key in ("OLLAMA_URL", "OLLAMA_BASE_URL", "OLLAMA_HOST"):
        env[key] = "http://127.0.0.1:1"
    for key in ("REDIS_URL", "SCHEDULER_REDIS_URL", "RQ_REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        env[key] = "redis://127.0.0.1:1/0"
    for key in ("STRIPE_API_KEY", "STRIPE_API_KEY_REF", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_ID_REF",
                "PAYPAL_CLIENT_SECRET", "PAYPAL_CLIENT_SECRET_REF", "ERP_PO_URL", "ERP_API_KEY", "REDIS_URL_REF"):
        env[key] = ""
    # An owned API must not inherit authority to send messages or create real
    # incidents. Explicit test-owned adapters may be supplied through overrides.
    disable_message_connectors(env)
    env.update(env_overrides or {})

    proc = None
    log_path = directory / "server.log"
    previous_base = os.environ.get("E2E_BASE_URL")
    with log_path.open("w", encoding="utf-8") as log:
        try:
            subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=os.getcwd(), env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
            proc = subprocess.Popen([
                sys.executable, "-m", "uvicorn", "src.app.main:create_app", "--host", host,
                "--port", str(port), "--factory", "--log-level", "error",
            ], cwd=os.getcwd(), env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=os.name != "nt")
            (directory / "owner.json").write_text(json.dumps({"pid": proc.pid, "base_url": base_url,
                "database_path": str(db_path), "database_url": database_url}), encoding="utf-8")
            if not _wait_ready(base_url, timeout=30):
                raise RuntimeError(f"Owned security API was not ready; inspect {log_path}")
            if publish_base_url:
                os.environ["E2E_BASE_URL"] = base_url
            yield {"base_url": base_url, "owned": True, "process_id": proc.pid,
                   "database_path": str(db_path), "database_url": database_url}
        finally:
            if publish_base_url:
                if previous_base is None:
                    os.environ.pop("E2E_BASE_URL", None)
                else:
                    os.environ["E2E_BASE_URL"] = previous_base
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session):
    # The root conftest migrates its disposable database first. Publish the
    # owned API URL before test modules capture E2E_BASE_URL at collection.
    if os.getenv("SECURITY_SERVER_SPAWN", "0") == "1":
        context = _owned_runtime(session.config)
        metadata = context.__enter__()
        session.config.stash[_RUNTIME] = (context, metadata)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    runtime = session.config.stash.get(_RUNTIME, None)
    if runtime is not None:
        runtime[0].__exit__(None, None, None)
        session.config.stash[_RUNTIME] = None


@pytest.fixture(scope="session", autouse=True)
def security_test_server(pytestconfig):
    runtime = pytestconfig.stash.get(_RUNTIME, None)
    if runtime is not None:
        yield runtime[1]
        return
    provided = os.getenv("E2E_BASE_URL")
    if provided and _wait_ready(provided, timeout=2):
        yield {"base_url": provided, "owned": False}
        return
    yield None
