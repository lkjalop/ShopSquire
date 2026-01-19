import os
import time
import json
import pytest
import urllib.request

# Integration E2E scaffold
# This test expects the integration stack to be available at http://localhost:8080
# and Postgres/Redis to be available via docker-compose. By default this test will
# be skipped unless the environment variable `RUN_INTEGRATION` is set to '1'.


def is_service_up(url: str, timeout: float = 0.5) -> bool:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


@pytest.mark.integration
def test_e2e_basic_health():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Integration tests disabled. Set RUN_INTEGRATION=1 to enable.")

    base = os.getenv("INTEGRATION_BASE_URL", "http://localhost:8080")
    # wait for health endpoint
    deadline = time.time() + 20
    while time.time() < deadline:
        if is_service_up(base + "/health"):
            break
        time.sleep(0.5)
    assert is_service_up(base + "/health"), "API health endpoint not reachable"

    # Basic flow (create a product, create draft order, call recommend) can be
    # added here once environment and migrations are provisioned. This scaffold
    # keeps the test minimal and focuses on stack readiness.
