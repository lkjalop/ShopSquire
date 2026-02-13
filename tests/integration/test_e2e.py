import os
import time
import pytest
import requests


# Integration E2E
# This test expects the integration stack to be available at http://localhost:8080
# and Postgres/Redis to be available via docker-compose. By default this test will
# be skipped unless the environment variable `RUN_INTEGRATION` is set to '1'.


def is_service_up(url: str, timeout: float = 0.5) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.integration
def test_e2e_full_flow():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Integration tests disabled. Set RUN_INTEGRATION=1 to enable.")

    try:
        base = os.getenv("INTEGRATION_BASE_URL")
        if not base:
            host = os.getenv("API_HOST", "localhost")
            port = os.getenv("API_PORT", "8080")
            base = f"http://{host}:{port}"
        # wait for health endpoint
        deadline = time.time() + 60
        while time.time() < deadline:
            if is_service_up(base + "/health"):
                break
            time.sleep(0.5)
        assert is_service_up(base + "/health"), "API health endpoint not reachable"

        headers = {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}
        # Best-effort: touch products endpoint to validate auth + basic DB connectivity.
        # We intentionally avoid using an in-process SQLAlchemy engine here because it may
        # point at a different database than the running API.
        requests.get(f"{base}/api/v1/products/list", headers=headers, timeout=5)

        # Call recommend endpoint
        resp = requests.get(
            f"{base}/api/v1/recommend/suggest",
            params={"uid": "int-test-1", "query": "test"},
            headers=headers,
            timeout=5,
        )
        assert resp.status_code == 200, f"Recommend endpoint failed: {resp.status_code} {resp.text}"
        body = resp.json()

        # Wait a short moment for background decision log writes (best-effort)
        time.sleep(0.5)

        # Validate decision log existence via the running API (same DB, same config).
        if os.getenv("DECISION_LOG_WRITES_ENABLED", "1") not in ("0", "false", "no"):
            rdec = requests.get(
                f"{base}/api/v1/decisions/latest",
                params={"uid": "int-test-1"},
                headers=headers,
                timeout=5,
            )
            assert rdec.status_code == 200, f"decisions/latest failed: {rdec.status_code} {rdec.text}"
            dec = rdec.json() if rdec.content else {}
            assert dec.get("id"), f"Expected a decision id for uid, got: {dec}"

        # Basic content checks
        assert "results" in body
        assert isinstance(body.get("results"), list)
    finally:
        pass
