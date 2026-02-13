# ShopSquire Next Steps & Action Plan

**Generated:** 2026-01-21
**Purpose:** Actionable implementation checklist with code snippets

---

## Quick Reference: What To Build Next

| Priority | Task | Effort | Risk if Skipped |
|----------|------|--------|-----------------|
| P0 | GDPR deletion endpoint | 2-3 hrs | Legal liability |
| P0 | GDPR export endpoint | 2-3 hrs | Legal liability |
| P0 | Sanitize PII in decision_logs | 1-2 hrs | Data breach |
| P0 | AlertManager setup | 2-4 hrs | Blind to outages |
| P1 | Gmail/M365 connector hardening (retries + idempotency) | 1-2 days | Duplicate incidents / missed mailflow |
| P1 | CV readiness + drift dashboards in admin UI | 1 day | Unknown model/config state; no regression visibility |
| P1 | Token budget tracking | 4-6 hrs | Cost overruns |
| P1 | Webhook integration tests | 2-3 hrs | Silent failures |
| P2 | Frontend cart/checkout | 2-3 days | No real UX |
| P2 | Adaptive learning pipeline | 1 week | No improvement loop |

### Completed (confirmed)

Since **2026-02-06**, the following items were implemented and validated via tests:

- Email Security MVP: rules + deterministic verdict gating, playbooks, metrics, and API (`/api/v1/email_security/evaluate`) plus Gmail/M365 webhook receivers and a connector worker.
- Redis-backed dedupe + ticket rate limiting (avoids per-process spam under multi-worker).
- CV readiness endpoint: `/api/v1/admin/cv/readiness` and CV incident drilldowns from persisted `evidence_bundles`.
- Deterministic CV “why/next steps” explanation (no LLM) attached to Tier2 CV results.
- Drift daily metrics MVP: `drift_daily_metrics` table + admin endpoints (`/api/v1/admin/drift/daily` + `/recompute`) and an integration test.

---

## Email Security: CV/OCR Strategy (BEC/Phishing) — Minimal → Smarter (No Overengineering)

### Goal

Detect BEC/phishing reliably with **rules-first, multi-signal gating**. Only add OCR when it increases recall (image-based evasion), and keep it **sandboxed + non-destructive**.

### Build Order (recommended)

1) **Start minimal (text + auth signals):** DMARC/SPF/DKIM + lightweight text heuristics.
2) **Reduce false positives:** multi-signal gating + rate limiting + consistent thresholds.
3) **Add OCR only for images:** sandboxed worker extracts text from image-only emails and feeds the *same* heuristics.
4) **Optional later:** ML anomaly/fusion — only as an advisory score; destructive actions stay human-approved.

### CV/OCR Strategy

- **Default:** DMARC + text heuristics for BEC/phishing; do **not** OCR by default.
- **When OCR is enabled:** OCR only for **image-only** emails (or when body is empty/minimal but images exist).
- **Attachment rule:** never execute attachments; treat them as bytes; never unzip/parse beyond safe image decoding.
- **OCR implementation choice:** prefer lightweight OCR (Tesseract via `pytesseract`) with strict caps:
  - max bytes per image
  - max images per email
  - timeout per image
  - fail closed to “no OCR text” (do not block)

### Guardrails (must-have)

- **Redaction:** sanitize headers/content before emission; hash stable identifiers (message-id, from, reply-to, domain).
- **Isolation:** OCR runs in an isolated worker/sandbox; no filesystem/network write access beyond telemetry.
- **Human-in-the-loop:** OCR findings create tickets; destructive actions require approval.

### Reducing False Positives (multi-signal gating)

Use `config/feature_flags.json` → `SECURITY_THRESHOLDS` (already present):

- DMARC: `DMARC_FAIL_WARN` (0.25), `DMARC_FAIL_ERROR` (0.5)
- BEC indicators: `BEC_WARN_INDICATORS` (2), `BEC_ERROR_INDICATORS` (3)
- IoC: `IOC_WARN_COUNT` (1), `IOC_ERROR_COUNT` (2)
- Anomaly: `ANOMALY_LONG_TOKEN_LEN` (500), `ANOMALY_REPEAT_MIN` (50)

**Gating rule (suggested default):**
- Warning: ≥2 indicators total (e.g., keyword + reply-to mismatch) **or** 1 IoC + 1 other indicator
- Error: ≥3 indicators total **and** at least 1 IoC or DMARC fail

### Ticket flood controls

Use `TICKET_RATE_LIMIT` in `config/feature_flags.json`:
- When exceeded: emit telemetry + aggregate counters, but do not open N tickets.

### What to build next to make agents “smarter”

**Rules first**
- Expand keyword sets (invoice/payment change, wire, urgency, gift cards).
- Lookalike domains + simple Levenshtein/keyboard-adjacent check.
- Reply-to mismatch check (From domain ≠ Reply-To domain), weighted as an indicator.

**IoC enrichment**
- Maintain deny-lists (known bad domains, shorteners, ASN/country exceptions if desired).
- Extract IoCs from both text body and OCR text (URLs, domains, IPs).
- Escalate only with multiple IoCs or known-bad sources.

**OCR (optional)**
- Add a sandboxed OCR worker for image-only emails; plug extracted text into the same rules.
- Constrain resources/time and log OCR failures as telemetry (not errors).

**Model guardrails (if/when ML arrives)**
- Conservative thresholds + require multi-signal consensus before auto-escalation.
- Keep auto-actions limited to telemetry/tickets; destructive actions require approval.
- Log IAM activity around escalations (audit agent behavior).

### Concrete implementation plan (code)

- `src/app/security/email_security_rules.py`
  - new: canonical indicator extraction (DMARC/auth, reply-to mismatch, keywords, IoCs, anomaly flags)
  - output contract: `{indicators: [...], iocs: [...], score, severity, reasons}`
- `src/app/security/email_ocr_worker.py`
  - new: `extract_text(images) -> {text, per_image, timings}`
  - enforce caps + timeouts; no network; no file writes except optional temp in a locked dir
- `src/app/security/email_security.py`
  - integrate multi-signal gating; call OCR worker only when enabled + image-only
  - ticketing uses `TICKET_RATE_LIMIT`; telemetry always records the decision
- `config/feature_flags.json`
  - keep all thresholds under `SECURITY_THRESHOLDS` (single source)
  - add `SECURITY_OCR_ENABLED` and caps if you want them configurable

### Tests to add (minimum useful set)

- Unit: reply-to mismatch detection and threshold gating.
- Unit: IoC extractor tags known-bad domains and shorteners.
- Integration: “image-only phishing” with embedded OCR text (PNG metadata like existing CV tests) triggers OCR path and creates a ticket at WARN/ERROR based on thresholds.
- Chaos: OCR worker timeout returns gracefully (no crash, telemetry logged, ticket not spammed).

### Playbooks (Email Security)

Keep playbooks small and deterministic; the “smartness” comes from **better signals + better gating**, not 50 playbooks.

Suggested IDs/actions (for demo + production hardening):

- `PB-EMAIL-001` (severity: medium) — DMARC fail-rate elevated
  - Actions: open ticket, recommend SPF/DKIM alignment, list top failing sources, attach telemetry snapshot
- `PB-EMAIL-002` (severity: high) — likely BEC (multi-signal)
  - Signals: reply-to mismatch + payment keywords + 1+ IoC OR DMARC fail
  - Actions: open ticket + suggest temporary mailbox rule + require approval for account/RBAC actions
- `PB-EMAIL-003` (severity: high) — image-based phishing (OCR)
  - Signals: image-only + OCR extracted suspicious intent + IoC(s)
  - Actions: open ticket, attach OCR excerpt (redacted), store hashes, recommend quarantine rule
- `PB-EMAIL-004` (severity: low) — anomaly-only
  - Signals: long token / repeated sequence with no IoCs
  - Actions: telemetry only (no ticket) unless rate-limit allows + repeated occurrences

Implementation note:
- You can either (a) add `config/security/email_playbooks.json` and a `select_email_playbook()` alongside existing `select_playbook()`, or (b) extend the existing registry to include an `email_signal_map` and keep one selector.

---

## Immediate Actions (Do First)

### 1. GDPR Data Deletion Endpoint

**Create file:** `src/app/routers/privacy.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from src.app.deps import get_db, get_redis, require_role
import logging

router = APIRouter(prefix="/privacy", tags=["privacy"])
logger = logging.getLogger(__name__)

@router.delete("/data/{uid}")
async def delete_user_data(
    uid: str,
    db=Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(require_role(["ROLE_OWNER"]))
):
    """GDPR Article 17: Right to Erasure"""
    deleted = {
        "decision_logs": 0,
        "decision_audits": 0,
        "order_sessions": 0,
        "orders": 0,
        "session_memory": False
    }

    try:
        # Delete decision logs
        cursor = db.execute(
            "DELETE FROM decision_logs WHERE input_data LIKE ?",
            (f'%"uid": "{uid}"%',)
        )
        deleted["decision_logs"] = cursor.rowcount

        # Delete decision audits for those decisions
        cursor = db.execute(
            """DELETE FROM decision_audits
               WHERE decision_id IN (
                   SELECT id FROM decision_logs
                   WHERE input_data LIKE ?
               )""",
            (f'%"uid": "{uid}"%',)
        )
        deleted["decision_audits"] = cursor.rowcount

        # Delete order sessions
        cursor = db.execute(
            "DELETE FROM order_sessions WHERE uid = ?", (uid,)
        )
        deleted["order_sessions"] = cursor.rowcount

        # Delete orders (or anonymize - depending on legal requirements)
        cursor = db.execute(
            "UPDATE orders SET customer_id = 'DELETED' WHERE customer_id = ?",
            (uid,)
        )
        deleted["orders"] = cursor.rowcount

        db.commit()

        # Clear Redis session memory
        redis.delete(f"session:{uid}:summary")
        redis.delete(f"session:{uid}:kv_state")
        redis.delete(f"session:{uid}:recent_retrieval")
        deleted["session_memory"] = True

        # Log deletion for audit
        logger.info(f"GDPR deletion completed for uid={uid}: {deleted}")

        return {
            "status": "deleted",
            "uid": uid,
            "deleted_records": deleted
        }

    except Exception as e:
        logger.error(f"GDPR deletion failed for uid={uid}: {e}")
        raise HTTPException(500, f"Deletion failed: {str(e)}")


@router.get("/export/{uid}")
async def export_user_data(
    uid: str,
    db=Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(require_role(["ROLE_OWNER", "ROLE_MERCHANT"]))
):
    """GDPR Article 20: Right to Data Portability"""
    export = {
        "uid": uid,
        "exported_at": datetime.utcnow().isoformat(),
        "decision_logs": [],
        "orders": [],
        "session_memory": None
    }

    # Export decision logs
    rows = db.execute(
        """SELECT id, agent_name, input_data, proposed_action,
                  created_at, execution_status
           FROM decision_logs
           WHERE input_data LIKE ?""",
        (f'%"uid": "{uid}"%',)
    ).fetchall()
    export["decision_logs"] = [dict(r) for r in rows]

    # Export orders
    rows = db.execute(
        "SELECT * FROM orders WHERE customer_id = ?", (uid,)
    ).fetchall()
    export["orders"] = [dict(r) for r in rows]

    # Export session memory
    summary = redis.get(f"session:{uid}:summary")
    kv = redis.get(f"session:{uid}:kv_state")
    if summary or kv:
        export["session_memory"] = {
            "summary": json.loads(summary) if summary else None,
            "kv_state": json.loads(kv) if kv else None
        }

    return export
```

**Register in main.py:**
```python
from src.app.routers import privacy
app.include_router(privacy.router, prefix="/api/v1")
```

---

### 2. Sanitize PII in Decision Logs

**Update:** `src/app/services/recommendations.py`

```python
import hashlib
from src.app.deps import scrub_pii

def _sanitize_decision_input(uid: str, query: str) -> str:
    """Sanitize input before storing in decision_logs"""
    return json.dumps({
        "uid_hash": hashlib.sha256(uid.encode()).hexdigest()[:16],
        "query_sanitized": scrub_pii(query),
        "query_length": len(query)
    }, ensure_ascii=False)

# In the decision logging code, replace:
# "input": json.dumps({"uid": uid, "query": query})
# With:
# "input": _sanitize_decision_input(uid, query)
```

---

### 3. AlertManager Setup

**Create file:** `config/observability/alertmanager.yml`

```yaml
global:
  slack_api_url: '${SLACK_WEBHOOK_URL}'

route:
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'critical-alerts'
    - match:
        severity: warning
      receiver: 'warning-alerts'

receivers:
  - name: 'default'
    slack_configs:
      - channel: '#shopsquire-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'

  - name: 'critical-alerts'
    slack_configs:
      - channel: '#shopsquire-critical'
        title: 'CRITICAL: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_KEY}'

  - name: 'warning-alerts'
    slack_configs:
      - channel: '#shopsquire-warnings'
```

**Add to docker-compose.observability.yml:**

```yaml
  alertmanager:
    image: prom/alertmanager:latest
    ports:
      - "9093:9093"
    volumes:
      - ./config/observability/alertmanager.yml:/etc/alertmanager/alertmanager.yml
    command:
      - '--config.file=/etc/alertmanager/alertmanager.yml'
```

**Update prometheus.yml:**

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

rule_files:
  - '/etc/prometheus/rules/*.yml'
```

---

### 4. Playwright Test Setup

**Install:**
```bash
pip install playwright pytest-playwright
playwright install chromium
```

**Create:** `tests/browser/test_checkout_flow.py`

```python
import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8080"

@pytest.fixture(scope="session")
def browser_context_args():
    return {"viewport": {"width": 1280, "height": 720}}

def test_storefront_loads(page: Page):
    """Storefront page loads with products"""
    page.goto(f"{BASE_URL}/ui/storefront")

    # Check page title
    expect(page).to_have_title("ShopSquire Storefront")

    # Check products are displayed
    products = page.locator(".product-card")
    expect(products).to_have_count_greater_than(0)

def test_product_detail_page(page: Page):
    """Product detail page shows specs"""
    page.goto(f"{BASE_URL}/ui/storefront")

    # Click first product
    page.locator(".product-card").first.click()

    # Should navigate to product detail
    expect(page).to_have_url_matching(r"/ui/product/.+")

    # Check product info displayed
    expect(page.locator(".product-title")).to_be_visible()
    expect(page.locator(".product-price")).to_be_visible()

def test_add_to_cart_flow(page: Page):
    """User can add product to cart"""
    page.goto(f"{BASE_URL}/ui/product/LAPTOP-001")

    # Click add to cart
    page.locator("button:has-text('Add to Cart')").click()

    # Cart should update
    cart_count = page.locator(".cart-count")
    expect(cart_count).to_have_text("1")

def test_checkout_form_validation(page: Page):
    """Checkout form validates required fields"""
    page.goto(f"{BASE_URL}/ui/checkout")

    # Try to submit empty form
    page.locator("button:has-text('Place Order')").click()

    # Should show validation errors
    expect(page.locator(".error-message")).to_be_visible()

def test_mobile_responsive(page: Page):
    """Page is usable on mobile viewport"""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(f"{BASE_URL}/ui/storefront")

    # Mobile menu should be present
    expect(page.locator(".mobile-menu-toggle")).to_be_visible()

    # Products should still be visible
    expect(page.locator(".product-card").first).to_be_visible()
```

**Run tests:**
```bash
pytest tests/browser/ --headed  # Watch browser
pytest tests/browser/           # Headless
```

---

### 5. Token Budget Tracking

**Create:** `src/app/services/token_budget.py`

```python
from datetime import date
from typing import Optional
import redis

class TokenBudget:
    """Track and enforce token usage limits per user"""

    LIMITS = {
        "guest": {"daily_tokens": 1000, "daily_usd": 0.10},
        "basic": {"daily_tokens": 10000, "daily_usd": 1.00},
        "premium": {"daily_tokens": 100000, "daily_usd": 10.00},
        "enterprise": {"daily_tokens": float('inf'), "daily_usd": float('inf')}
    }

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def _daily_key(self, uid: str, metric: str) -> str:
        return f"budget:{uid}:{metric}:{date.today()}"

    def get_usage(self, uid: str) -> dict:
        """Get current usage for user"""
        tokens = int(self.redis.get(self._daily_key(uid, "tokens")) or 0)
        cost = float(self.redis.get(self._daily_key(uid, "cost")) or 0)
        return {"tokens": tokens, "cost_usd": cost}

    def check_budget(self, uid: str, tier: str, estimated_tokens: int) -> tuple[bool, str]:
        """Check if request is within budget"""
        limits = self.LIMITS.get(tier, self.LIMITS["guest"])
        usage = self.get_usage(uid)

        if usage["tokens"] + estimated_tokens > limits["daily_tokens"]:
            return False, "daily_token_limit"

        # Estimate cost (rough: $0.002 per 1K tokens)
        estimated_cost = (estimated_tokens / 1000) * 0.002
        if usage["cost_usd"] + estimated_cost > limits["daily_usd"]:
            return False, "daily_cost_limit"

        return True, "ok"

    def record_usage(self, uid: str, tokens: int, cost: float):
        """Record actual usage after request completes"""
        token_key = self._daily_key(uid, "tokens")
        cost_key = self._daily_key(uid, "cost")

        pipe = self.redis.pipeline()
        pipe.incrby(token_key, tokens)
        pipe.incrbyfloat(cost_key, cost)
        pipe.expire(token_key, 86400)
        pipe.expire(cost_key, 86400)
        pipe.execute()

    def get_remaining(self, uid: str, tier: str) -> dict:
        """Get remaining budget for user"""
        limits = self.LIMITS.get(tier, self.LIMITS["guest"])
        usage = self.get_usage(uid)
        return {
            "tokens_remaining": max(0, limits["daily_tokens"] - usage["tokens"]),
            "cost_remaining_usd": max(0, limits["daily_usd"] - usage["cost_usd"])
        }
```

**Usage in routers:**
```python
from src.app.services.token_budget import TokenBudget

@router.get("/recommend/suggest")
async def suggest(
    uid: str,
    query: str,
    redis=Depends(get_redis)
):
    budget = TokenBudget(redis)
    user_tier = get_user_tier(uid)  # Implement based on your user model

    # Estimate tokens (rough: 4 chars = 1 token)
    estimated_tokens = len(query) // 4 + 500  # query + response

    allowed, reason = budget.check_budget(uid, user_tier, estimated_tokens)
    if not allowed:
        return {
            "status": "budget_exceeded",
            "reason": reason,
            "remaining": budget.get_remaining(uid, user_tier)
        }

    # Process request...
    result = await process_recommendation(uid, query)

    # Record actual usage
    budget.record_usage(uid, result["tokens_used"], result["cost"])

    return result
```

---

### 6. Webhook Integration Tests

**Create:** `tests/integration/test_webhook_delivery.py`

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import responses

from src.app.main import app

client = TestClient(app)

@pytest.fixture
def mock_webhook_config(monkeypatch, tmp_path):
    """Create temporary webhook config"""
    config = tmp_path / "webhooks.yml"
    config.write_text("""
decision_events:
  - url: https://webhook.test/decisions
    secret: test_secret
security_events:
  - url: https://webhook.test/security
    secret: test_secret
""")
    monkeypatch.setenv("WEBHOOK_CONFIG_PATH", str(config))
    return config

@responses.activate
def test_decision_approve_fires_webhook(mock_webhook_config):
    """Approving a decision sends webhook"""
    # Mock the webhook endpoint
    responses.add(
        responses.POST,
        "https://webhook.test/decisions",
        json={"received": True},
        status=200
    )

    # Create a test decision first
    # ... (setup code)

    # Approve the decision
    response = client.post(
        f"/api/v1/decisions/{decision_id}/approve",
        params={"approved_by": "test_user"},
        headers={"x-api-key": "test_key"}
    )

    assert response.status_code == 200

    # Verify webhook was called
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == "https://webhook.test/decisions"

    # Verify payload
    payload = responses.calls[0].request.body
    assert "decision.approved" in payload
    assert decision_id in payload

@responses.activate
def test_webhook_retry_on_failure(mock_webhook_config):
    """Webhook retries on failure"""
    # First call fails, second succeeds
    responses.add(
        responses.POST,
        "https://webhook.test/decisions",
        json={"error": "timeout"},
        status=503
    )
    responses.add(
        responses.POST,
        "https://webhook.test/decisions",
        json={"received": True},
        status=200
    )

    # Trigger webhook
    # ...

    # Should have retried
    assert len(responses.calls) == 2

@responses.activate
def test_security_escalate_fires_webhook(mock_webhook_config):
    """Escalating security event sends webhook"""
    responses.add(
        responses.POST,
        "https://webhook.test/security",
        json={"received": True},
        status=200
    )

    # Create and escalate security event
    # ...

    response = client.post(
        f"/api/v1/admin/security/events/{event_id}/escalate",
        headers={"x-api-key": "test_key"}
    )

    assert response.status_code == 200
    assert len(responses.calls) == 1
```

---

## Medium-Term Tasks

### 7. EU/GDPR Geo-Detection

**Create:** `src/app/middleware/gdpr.py`

```python
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import geoip2.database
import os

GDPR_COUNTRIES = {
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR',
    'DE', 'GR', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL',
    'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE', 'GB', 'IS', 'LI', 'NO'
}

class GDPRMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, geoip_db_path: str = None):
        super().__init__(app)
        db_path = geoip_db_path or os.getenv("GEOIP_DB_PATH", "GeoLite2-Country.mmdb")
        try:
            self.reader = geoip2.database.Reader(db_path)
        except:
            self.reader = None

    async def dispatch(self, request: Request, call_next):
        # Get client IP
        client_ip = request.client.host
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        # Detect country
        country = None
        if self.reader:
            try:
                response = self.reader.country(client_ip)
                country = response.country.iso_code
            except:
                pass

        # Set GDPR flags
        request.state.client_country = country
        request.state.gdpr_applicable = country in GDPR_COUNTRIES if country else False

        # Set retention policy
        if request.state.gdpr_applicable:
            request.state.retention_policy = {
                "session_ttl": 3600,        # 1 hour
                "decision_logs_days": 7,
                "require_consent": True
            }
        else:
            request.state.retention_policy = {
                "session_ttl": 10800,       # 3 hours
                "decision_logs_days": 90,
                "require_consent": False
            }

        return await call_next(request)
```

**Register in main.py:**
```python
from src.app.middleware.gdpr import GDPRMiddleware
app.add_middleware(GDPRMiddleware)
```

---

### 8. Distributed Tracing (Jaeger)

**Update:** `src/app/observability/tracing.py`

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
import os

def init_tracer(app):
    """Initialize OpenTelemetry with Jaeger exporter"""

    # Configure Jaeger exporter
    jaeger_host = os.getenv("JAEGER_HOST", "jaeger")
    jaeger_port = int(os.getenv("JAEGER_PORT", "6831"))

    exporter = JaegerExporter(
        agent_host_name=jaeger_host,
        agent_port=jaeger_port,
    )

    # Set up tracer provider
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # Auto-instrument Redis
    RedisInstrumentor().instrument()

    # Auto-instrument HTTP requests
    RequestsInstrumentor().instrument()

    return trace.get_tracer("shopsquire")
```

**Add Jaeger to docker-compose.observability.yml:**
```yaml
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "6831:6831/udp"   # Thrift compact
      - "16686:16686"     # UI
    environment:
      - COLLECTOR_OTLP_ENABLED=true
```

---

### 9. Dependency Health Checks

**Update:** `src/app/observability/health.py`

```python
import time
from typing import Dict, Any
import redis
import asyncio

async def check_postgres(db) -> Dict[str, Any]:
    """Check PostgreSQL connectivity"""
    start = time.time()
    try:
        db.execute("SELECT 1").fetchone()
        return {
            "status": "healthy",
            "latency_ms": round((time.time() - start) * 1000, 2)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

async def check_redis(redis_client: redis.Redis) -> Dict[str, Any]:
    """Check Redis connectivity"""
    start = time.time()
    try:
        redis_client.ping()
        return {
            "status": "healthy",
            "latency_ms": round((time.time() - start) * 1000, 2)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

async def check_llm_provider() -> Dict[str, Any]:
    """Check LLM API availability (when integrated)"""
    # TODO: Implement actual LLM health check
    return {"status": "not_configured"}

async def dependency_health_snapshot(db, redis_client) -> Dict[str, Any]:
    """Get health status of all dependencies"""
    results = await asyncio.gather(
        check_postgres(db),
        check_redis(redis_client),
        check_llm_provider(),
        return_exceptions=True
    )

    return {
        "timestamp": time.time(),
        "dependencies": {
            "postgres": results[0] if not isinstance(results[0], Exception) else {"status": "error"},
            "redis": results[1] if not isinstance(results[1], Exception) else {"status": "error"},
            "llm": results[2] if not isinstance(results[2], Exception) else {"status": "error"}
        },
        "overall": "healthy" if all(
            r.get("status") == "healthy"
            for r in results
            if isinstance(r, dict) and r.get("status") != "not_configured"
        ) else "degraded"
    }
```

---

## Long-Term Tasks

### 10. Frontend Architecture

**Recommended Stack:**
```
Next.js 14 (App Router)
├── TypeScript
├── TailwindCSS
├── React Query (data fetching)
├── Zustand (state management)
└── Playwright (testing)
```

**Directory Structure:**
```
src/frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx              # Landing
│   ├── storefront/
│   │   ├── page.tsx          # Product grid
│   │   └── [sku]/page.tsx    # Product detail
│   ├── cart/
│   │   └── page.tsx
│   ├── checkout/
│   │   └── page.tsx
│   ├── account/
│   │   ├── page.tsx
│   │   ├── orders/page.tsx
│   │   └── privacy/page.tsx  # GDPR center
│   └── admin/
│       ├── page.tsx          # Dashboard
│       ├── approvals/page.tsx
│       ├── security/page.tsx
│       └── compliance/page.tsx
├── components/
│   ├── ProductCard.tsx
│   ├── Cart.tsx
│   ├── CheckoutForm.tsx
│   └── ...
├── lib/
│   ├── api-client.ts
│   └── hooks/
│       ├── useAuth.ts
│       ├── useCart.ts
│       └── useRecommendations.ts
└── package.json
```

---

### 11. Adaptive Learning Pipeline

**Architecture:**
```
┌─────────────────────────────────────────────────────┐
│                 FEEDBACK COLLECTION                  │
├─────────────────────────────────────────────────────┤
│  User Actions:                                       │
│  - Recommendation click → feedback_events           │
│  - Purchase after recommendation → conversion       │
│  - Human approval/rejection → quality signal        │
│  - Explicit feedback (thumbs up/down)              │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                 METRICS COMPUTATION                  │
├─────────────────────────────────────────────────────┤
│  Daily batch job computes:                          │
│  - Recommendation CTR                               │
│  - Conversion rate                                  │
│  - Human approval rate                              │
│  - False positive rate                              │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                 WEIGHT ADJUSTMENT                    │
├─────────────────────────────────────────────────────┤
│  If metrics degrade:                                │
│  - Decrease rollout percentage                      │
│  - Adjust scoring weights                           │
│  - Alert team for review                            │
│                                                     │
│  If metrics improve:                                │
│  - Gradually increase rollout                       │
│  - Log successful configuration                     │
└─────────────────────────────────────────────────────┘
```

**Create:** `src/app/services/adaptive_learning.py`

```python
from datetime import datetime, timedelta
from typing import Dict, Any
import json

class AdaptiveLearning:
    def __init__(self, db, redis):
        self.db = db
        self.redis = redis

    def record_feedback(self, decision_id: str, feedback_type: str, value: Any):
        """Record user feedback on a decision"""
        self.db.execute("""
            INSERT INTO decision_feedback
            (decision_id, feedback_type, value, created_at)
            VALUES (?, ?, ?, ?)
        """, (decision_id, feedback_type, json.dumps(value), datetime.utcnow()))
        self.db.commit()

    def compute_metrics(self, days: int = 7) -> Dict[str, float]:
        """Compute quality metrics over time window"""
        since = datetime.utcnow() - timedelta(days=days)

        # Recommendation CTR
        recs = self.db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN f.feedback_type = 'click' THEN 1 ELSE 0 END) as clicks
            FROM decision_logs d
            LEFT JOIN decision_feedback f ON d.id = f.decision_id
            WHERE d.agent_name = 'recommend' AND d.created_at > ?
        """, (since,)).fetchone()

        ctr = recs['clicks'] / max(recs['total'], 1)

        # Human approval rate
        approvals = self.db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN execution_status = 'approved' THEN 1 ELSE 0 END) as approved
            FROM decision_logs
            WHERE approval_required = 1 AND created_at > ?
        """, (since,)).fetchone()

        approval_rate = approvals['approved'] / max(approvals['total'], 1)

        return {
            "recommendation_ctr": ctr,
            "human_approval_rate": approval_rate,
            "computed_at": datetime.utcnow().isoformat()
        }

    def should_adjust_rollout(self, metrics: Dict[str, float]) -> tuple[bool, str, int]:
        """Determine if rollout should be adjusted"""
        # Thresholds
        CTR_THRESHOLD = 0.05  # 5% minimum CTR
        APPROVAL_THRESHOLD = 0.80  # 80% minimum approval

        current_rollout = self._get_current_rollout()

        if metrics["recommendation_ctr"] < CTR_THRESHOLD:
            return True, "decrease", max(0, current_rollout - 10)

        if metrics["human_approval_rate"] < APPROVAL_THRESHOLD:
            return True, "decrease", max(0, current_rollout - 10)

        # If metrics are good, consider increasing
        if metrics["recommendation_ctr"] > CTR_THRESHOLD * 2 and \
           metrics["human_approval_rate"] > 0.95 and \
           current_rollout < 100:
            return True, "increase", min(100, current_rollout + 5)

        return False, "maintain", current_rollout
```

---

## Testing Checklist

### Before Each PR
```bash
# Unit tests
pytest tests/ -v --ignore=tests/integration --ignore=tests/browser

# Security tests
pytest tests/test_security_*.py -v

# Integration tests (if env set)
RUN_INTEGRATION=1 pytest tests/integration/ -v
```

### Before Each Release
```bash
# Full test suite
pytest tests/ -v

# Browser tests
pytest tests/browser/ -v

# Load test (optional)
locust -f tests/performance/locustfile.py --headless -u 100 -r 10 -t 60s
```

### Coverage Report
```bash
pytest tests/ --cov=src/app --cov-report=html
open htmlcov/index.html
```

---

## Environment Variables Needed

```bash
# .env additions for production

# GDPR
GEOIP_DB_PATH=/path/to/GeoLite2-Country.mmdb

# Alerting
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
PAGERDUTY_KEY=your_pagerduty_key

# Tracing
JAEGER_HOST=jaeger
JAEGER_PORT=6831

# LLM (when integrated)
OPENAI_API_KEY=sk-...
LLM_DAILY_BUDGET_USD=100.00
LLM_DEFAULT_MODEL=gpt-4-turbo
```

---

## Quick Commands Reference

```bash
# Start full stack
docker-compose up -d
docker-compose -f docker-compose.observability.yml up -d

# Run specific test file
pytest tests/test_security_llm_top10.py -v

# Run Playwright tests with browser visible
pytest tests/browser/ --headed

# Check Prometheus metrics
curl http://localhost:8080/metrics

# View Grafana dashboards
open http://localhost:3000  # admin/admin

# View Jaeger traces
open http://localhost:16686

# Check health
curl http://localhost:8080/health
```

---

## Summary: Your Next Session

When you come back, start with:

1. **Create `src/app/routers/privacy.py`** - GDPR endpoints (copy code above)
2. **Update decision logging** - Add PII sanitization
3. **Create AlertManager config** - Set up Slack notifications
4. **Run existing tests** - Make sure nothing broke
5. **Create first Playwright test** - Start with storefront load test

This gives you legal compliance + observability + test foundation in one session.

---

*Document will be updated as implementation progresses.*
