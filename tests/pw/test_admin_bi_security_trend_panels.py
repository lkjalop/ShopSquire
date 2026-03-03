import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _find_free_port(start: int = 5176) -> int:
    port = start
    while _is_port_open("127.0.0.1", port):
        port += 1
    return port


def _wait_http_ready(url: str, timeout_s: int = 75) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Admin frontend did not become ready: {url}")


@pytest.fixture(scope="module")
def admin_frontend_server(test_server):
    admin_dir = Path(__file__).resolve().parents[2] / "src" / "frontend" / "admin-react"
    if not admin_dir.exists():
        raise RuntimeError(f"admin-react directory not found: {admin_dir}")

    port = _find_free_port(int(os.getenv("PLAYWRIGHT_ADMIN_FRONTEND_PORT", "5176")))
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["VITE_API_BASE"] = test_server["base_url"]
    env["VITE_API_KEY"] = "local-merchant-key"
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        pytest.skip("npm executable not found in PATH for admin Playwright test")

    proc = subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(admin_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_http_ready(base_url, timeout_s=90)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(os.getenv("DISABLE_PLAYWRIGHT_TESTS", "0") in ("1", "true", "yes"), reason="Playwright disabled by env")
def test_admin_bi_panels_render_security_matrix_and_decision_replay(page, admin_frontend_server):
    page.add_init_script(
        """
        localStorage.setItem('shopsquire_api_key', 'local-merchant-key');
        localStorage.setItem('x-api-key', 'local-merchant-key');
        """
    )

    page.route(
        "**/api/v1/admin/me",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"role":"merchant","allowed_roles":["merchant"]}'
        ),
    )
    page.route(
        "**/api/v1/admin/overview",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"revenue_today":1234.5,"orders_today":12,"autonomy_percent":70,"security_status":"guarded","critical_events_24h":1,"approval_pending":2,"decision_series":[],"approval_latency_p95_sec":0,"policy_reject_rate":0,"uptime_seconds":1000}',
        ),
    )
    page.route(
        "**/api/v1/admin/bi/transactions/timeseries**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"granularity":"day","start":"2026-02-01","end":"2026-03-01","series":[{"bucket":"2026-02-10","orders":10,"revenue":1200,"paid":8,"refunded":1,"chargeback":1,"pending_payment":0}],"totals":{"orders":10,"revenue":1200,"aov":120,"paid":8,"refunded":1,"chargeback":1,"pending_payment":0}}',
        ),
    )
    page.route(
        "**/api/v1/admin/security/attacks/timeseries**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"hours":24,"buckets":[{"hour":"2026-02-26T10:00:00Z","security_type":"network","threat":"c2_beacon","vector":"callback","count":4}],"totals_by_type":[{"security_type":"network","count":4}]}',
        ),
    )
    page.route(
        "**/api/v1/admin/security/geoip-asn/trends**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"hours":24,"trends":[{"asn":"AS13335","country":"US","count":3,"network_confidence":0.7,"network_confidence_avg":0.7,"asn_risk_avg":0.3,"vpn_or_hosting_hits":1,"velocity_anomaly_hits":0,"sender_tool_behavior_avg":0.2,"ip_churn_velocity":0.1,"geo_trust_level":"medium","last_seen":"2026-02-26T10:00:00Z","business_contexts":{},"security_contexts":{}}]}',
        ),
    )
    page.route(
        "**/api/v1/admin/upsell/performance**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"ctr":0.11,"add_to_cart_rate":0.06,"blocked_poisoned_candidates":1,"impressions":100}',
        ),
    )
    page.route(
        "**/api/v1/admin/bi/executive-pulse**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"window":{"start":"2026-02-01","end":"2026-03-01"},"kpis":{"revenue":1200,"gross_margin_pct":32.5,"refund_pct":10,"chargeback_pct":5,"approval_rate":88,"autonomy_pct":74,"mttd_minutes":2.1,"mttr_minutes":8.2},"trend_overlays":{"revenue":[{"bucket":"2026-02-10","actual":1200,"baseline":1100,"anomaly_low":900,"anomaly_high":1300,"is_anomaly":false}],"causal_factors":[{"id":"promo","count":3}]},"agentic_ops":{"auto_vs_human":[{"bucket":"2026-02-10","auto":8,"human":2}],"false_positive_drift":[{"week":"2026-W08","fp_rate":3.1,"total":20}],"per_agent":[{"agent":"Security_Agent","error_rate":1.0,"avg_latency_ms":42,"count":20}]},"security_incursions_matrix":[{"week":"2026-W08","type":"network","severity":"high","count":4}],"decision_replay":[{"policy_version":"v1","decisions":100,"approval_rate":88.2}]}',
        ),
    )
    page.route(
        "**/api/v1/admin/bi/trend-pack/alarms**",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"ok","weeks":8,"alarm_count":0,"alarms":[]}'),
    )
    page.route(
        "**/api/v1/admin/bi/query-agent",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"ok","intent":"security_incursions","rows":[{"type":"network","count":4}]}'),
    )
    page.route(
        "**/api/v1/admin/bi/agentic-rag/summary**",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"ok","days":7,"event_counts":{"context_injected":4},"contexts_injected":4,"verify_failures":0,"avg_budget_utilization":0.41}'),
    )
    page.route(
        "**/api/v1/admin/bi/db-stack/status",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"postgres_source_of_truth":true,"timescaledb_extension":true,"timescale_cagg_orders_hourly":false,"redis_configured":true,"neo4j_pilot_enabled":false}'),
    )

    page.goto(f"{admin_frontend_server}/?tab=merchant-bi", wait_until="commit", timeout=90000)
    page.get_by_text("Merchant BI Dashboard", exact=False).wait_for(timeout=20000)
    page.get_by_text("Executive Pulse", exact=False).wait_for(timeout=20000)
    page.get_by_text("Security Incursions Matrix", exact=False).wait_for(timeout=20000)
    page.get_by_text("Decision Replay", exact=False).wait_for(timeout=20000)
    page.get_by_text("network", exact=False).first.wait_for(timeout=20000)
    page.get_by_text("v1", exact=False).first.wait_for(timeout=20000)
