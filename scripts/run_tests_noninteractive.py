import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIP_LOG = ROOT / "pip_install_out.txt"
PYTEST_LOG = ROOT / "pytest_run_out.txt"
EXIT_LOG = ROOT / "pytest_exit_code.txt"
PRETEST_LOG = ROOT / "pretest_db_debug.txt"

pkgs = ["pytest", "requests", "pyyaml"]
playwright_pkg = "playwright"

def run(cmd, capture_file=None, env=None):
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    out = proc.stdout.decode("utf-8", errors="replace")
    if capture_file:
        capture_file.write_text(out, encoding="utf-8")
    return proc.returncode, out

if __name__ == "__main__":
    # Prefer SQLite for local/CI tests unless explicitly overridden
    os.environ.setdefault("DATABASE_URL", "sqlite:///test.sqlite")
    # Stabilize tests: disable console tracing exporter and persist security events synchronously
    os.environ.setdefault("DISABLE_TRACING", "1")
    os.environ.setdefault("SECURITY_OBSERVER_SYNC", "1")
    # Ensure Phase 1 runs observe security events by default
    os.environ.setdefault("SECURITY_OBSERVER_SAMPLE_RATE", "1")
    # Avoid importing complex UI routes with f-strings during some test runs
    # NOTE: don't disable UI routes globally because some Phase 1 tests exercise the UI.
    # NOTE: we avoid applying aggressive test-only skips here globally because
    # some Phase 1 tests validate the security observer and UI routes. Phase 2
    # (chaos/load) will apply stricter test-safe env overrides when executed.
    # 1) Install packages
    print("Installing packages:", pkgs + [playwright_pkg])
    rc, out = run([sys.executable, "-m", "pip", "install"] + pkgs + [playwright_pkg], capture_file=PIP_LOG)
    print(f"pip install exit code: {rc}")

    # 2) Optionally install Playwright browsers (best-effort)
    try:
        rc2, out2 = run([sys.executable, "-m", "playwright", "install"], capture_file=None)
        print("Playwright browsers install exit code:", rc2)
    except Exception as e:
        print("Playwright browser install failed (continuing):", e)

    # 3) Run pytest (whole suite or subset via TEST_ARGS env var)
    test_args = sys.argv[1:] or (sys.argv[1:] if len(sys.argv) > 1 else [])
    if not test_args:
        # Phase 1: run core unit/api tests; skip browser/e2e and heavy chaos/load suites
        phase1 = ["-q", "--ignore", "tests/browser", "--ignore", "tests/pw", "--ignore", "tests/chaos", "--ignore", "tests/load"]
        env1 = os.environ.copy()
        # Test-safe overrides: avoid LLM calls and model warmup during Phase 1
        env1.setdefault("USE_LLM_RERANK", "0")
        env1.setdefault("USE_OLLAMA_INTENT", "0")
        env1.setdefault("USE_LLM_SUMMARY", "0")
        env1.setdefault("MODEL_WARMUP_ON_STARTUP", "0")
        # Use opt-in mocks for LLM and inventory during test runs unless real services configured
        env1.setdefault("USE_MOCK_LLM", "1")
        env1.setdefault("USE_MOCK_INVENTORY", "1")
        env1.setdefault("DISABLE_PLAYWRIGHT_TESTS", "1")
        # Ensure schema exists and seed minimal catalog data for NLP -> products flows
        if env1.get("SEED_TEST_DATA", "1").lower() in ("1", "true", "yes"):
            # Ensure TimescaleDB on Postgres, else no-op
            init_code = (
                "import os; from sqlalchemy import text as _t; from src.app.models.db import db_session;"
                "from src.app.models.init_db import ensure_metadata;"
                "url = os.environ.get('DATABASE_URL','');"
                "with db_session() as db:"
                "\n    \n    "
                "    (url.startswith('postgres') and db.execute(_t('CREATE EXTENSION IF NOT EXISTS timescaledb')))"
                "; ensure_metadata()"
            )
            run([sys.executable, "-c", init_code], capture_file=None, env=env1)
            run([sys.executable, "scripts/seed_products.py"], capture_file=None, env=env1)
        # Pre-run DB inspection to help diagnose SQLite visibility/races
        dbg_code = r"""
import os, re, sqlite3
url = os.environ.get('DATABASE_URL','sqlite:///test.sqlite')
print('PRETEST DATABASE_URL=', url)
m = re.match(r'sqlite(\+pysqlite)?:/{2,3}(?P<p>.*)', url)
if m:
    path = m.group('p')
    if path.startswith('/'):
        path = path.lstrip('/')
    print('PRETEST sqlite file=', path)
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        for tbl in ('security_events','incidents'):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                cnt = cur.fetchone()[0]
                print(f"PRETEST TABLE {tbl} COUNT={cnt}")
            except Exception as e:
                print(f"PRETEST TABLE {tbl} error: {e}")
        conn.close()
    except Exception as e:
        print('PRETEST sqlite connect error', e)
else:
    print('PRETEST non-sqlite DB, skipping rowcounts')
"""
        run([sys.executable, '-c', dbg_code], capture_file=PRETEST_LOG, env=env1)
        rc1, out1 = run([sys.executable, "-m", "pytest"] + phase1, capture_file=PYTEST_LOG, env=env1)
        print("Phase 1 exit code:", rc1)
        # Phase 2: run chaos and load tests with observer skip to minimize latency on hot paths
        env2 = os.environ.copy()
        env2["SKIP_OBSERVER_ENDPOINTS"] = "/api/v1/recommend,/api/v1/admin"
        env2["SECURITY_OBSERVER_SAMPLE_RATE"] = "0"
        # Test-safe overrides for chaos/load phases
        env2["RATE_LIMIT_PER_IP_PER_MIN"] = env2.get("RATE_LIMIT_PER_IP_PER_MIN", "0")
        env2["MAX_CONCURRENCY"] = env2.get("MAX_CONCURRENCY", "0")
        env2["CHAOS_ERROR_PROB"] = env2.get("CHAOS_ERROR_PROB", "0")
        # Disable UI routes for heavy phases to reduce import-time overhead
        env2["DISABLE_UI_ROUTES"] = env2.get("DISABLE_UI_ROUTES", "1")
        env2.setdefault("USE_MOCK_LLM", "1")
        env2.setdefault("USE_MOCK_INVENTORY", "1")
        # Stabilize concurrency tests by holding a short busy window on overview
        env2["BACKPRESSURE_TEST_DELAY_SEC"] = env2.get("BACKPRESSURE_TEST_DELAY_SEC", "0.3")
        rc2, out2 = run([sys.executable, "-m", "pytest", "-q", "tests/chaos"], capture_file=PYTEST_LOG, env=env2)
        print("Phase 2 (chaos) exit code:", rc2)
        rc3, out3 = run([sys.executable, "-m", "pytest", "-q", "tests/load"], capture_file=PYTEST_LOG, env=env2)
        print("Phase 3 (load) exit code:", rc3)
        final_rc = 0 if (rc1 == 0 and rc2 == 0 and rc3 == 0) else 1
        # Optional Phase 4: Playwright E2E (requires server & UI routes enabled)
        if os.environ.get("RUN_PLAYWRIGHT", "0") in ("1", "true", "yes"):
            env4 = os.environ.copy()
            env4["DISABLE_UI_ROUTES"] = "0"
            # Allow base URL override; default to local dev server
            env4.setdefault("PLAYWRIGHT_BASE_URL", "http://127.0.0.1:8081")
            rc4, out4 = run([sys.executable, "-m", "pytest", "-q", "tests/pw"], capture_file=PYTEST_LOG, env=env4)
            print("Phase 4 (playwright) exit code:", rc4)
            final_rc = 0 if (final_rc == 0 and rc4 == 0) else 1
        EXIT_LOG.write_text(str(final_rc), encoding="utf-8")
        print("Pytest exit code:", final_rc)
        print("Logs written:", PIP_LOG, PYTEST_LOG, EXIT_LOG)
        sys.exit(final_rc)
    else:
        # Custom run
        env = os.environ.copy()
        cmd = [sys.executable, "-m", "pytest"] + test_args
        rcx, outx = run(cmd, capture_file=PYTEST_LOG, env=env)
        EXIT_LOG.write_text(str(rcx), encoding="utf-8")
        print("Pytest exit code:", rcx)
        print("Logs written:", PIP_LOG, PYTEST_LOG, EXIT_LOG)
        sys.exit(rcx)
