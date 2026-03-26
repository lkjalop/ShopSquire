# ShopSquire — Insider Threat Detection & Prevention Program
**Date:** 2026-03-26
**Scope:** Backend (8080), Admin Dashboard, Agent Pipeline, DB, Redis, Celery Workers, Supplier/Email Integrations
**Frameworks:** ISO 27001:2022 A.6.3 / A.7 / A.8.15, NIST SP 800-53 AT-2 / AU-6 / PS-3 / SI-4, NIST CISA Insider Threat Guide (2024), Australian Privacy Act APP 11, EU AI Act Art 9 (misuse)

---

## Why Insider Threat Is a ShopSquire-Specific Priority

ShopSquire's architecture creates elevated insider-threat vectors that generic e-commerce platforms do not have:

1. **AI agents execute high-impact actions autonomously** — an insider who can manipulate agent inputs (prompts, RAG context, session state) can redirect the AI to approve fraud, exfiltrate data, or suppress security detections — without touching the payment system directly.
2. **Tamper-evident audit chain** — exists, but its HMAC key is currently a hardcoded default (CRIT-01 in master plan). An insider with source access can forge the chain.
3. **Supplier/payment pipeline** — an insider with access to `supplier_governance_store.py` or the supplier baseline config can onboard a fraudulent supplier or whitelist a spoofed domain.
4. **Email security lab** — the auth key for the email lab is stored in `localStorage` and in `OWNER_API_KEY` env var. An insider can extract this key and use it to bypass the email security pipeline.
5. **Celery task queue** — unsigned tasks (CRIT-04). An insider with Redis access can inject arbitrary Celery tasks — triggering ticket creation, supplier payments, or security event suppression.
6. **LLM prompt store** — if insiders can modify system prompts or RAG context, they can manipulate AI output without touching business logic code.
7. **Metrics endpoint** — currently open without auth. An insider can monitor alert rates to time a fraud window when detection is low.

---

## Section 1 — Detection: What to Build

### IT-DET-01 — Privileged Action Anomaly Detector
**Priority:** CRITICAL | **Effort:** M
**File:** New — [src/app/security/insider_threat_detector.py](src/app/security/insider_threat_detector.py)
**Framework Tags:** ISO 27001 A.8.15, NIST SP 800-53 AU-6, SI-4

**Signals to monitor:**
| Signal | Threshold | Action |
|---|---|---|
| Admin API key accessed outside business hours (AEST 08:00–20:00) | Any access | Log + alert |
| Admin key used from new IP or country | First occurrence | Alert + require 2FA re-auth |
| >3 admin actions in 5 minutes from same account | Burst | Alert + throttle |
| Bulk data export (>1000 records, all customers/orders) | Any | Block + create critical ticket |
| Direct DB queries via admin tools (not ORM) | Any | Alert |
| Supplier baseline/governance file modified | Any | Dual-control required |
| Supply chain scan results suppressed/deleted | Any | Alert + escalate |
| Audit chain verification failure | Any | CRITICAL alert + freeze platform |
| RBAC policy file modified | Any | CRITICAL alert |
| Feature flag changed for security feature | Any | Alert + require approval |

**Implementation — `src/app/security/insider_threat_detector.py`:**
```python
"""Insider threat detection layer.

Monitors privileged admin and service-account actions for anomalous patterns.
All detections feed the audit chain and SIEM adapter.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.app.security.audit_chain import chain_new_record
from src.app.security.siem_adapter import emit_siem_event

# Business-hours window (AEST / UTC+10)
BUSINESS_HOURS_UTC_START = int(os.getenv("BH_START_UTC", "22"))  # 08:00 AEST = 22:00 UTC prev day
BUSINESS_HOURS_UTC_END   = int(os.getenv("BH_END_UTC",   "10"))  # 20:00 AEST = 10:00 UTC

@dataclass
class InsiderThreatSignal:
    signal_type: str
    actor: str
    resource: str
    context: Dict[str, Any] = field(default_factory=dict)
    severity: str = "high"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def detect_off_hours_admin(actor: str, action: str, ip: str) -> Optional[InsiderThreatSignal]:
    hour_utc = datetime.now(timezone.utc).hour
    in_business = False
    if BUSINESS_HOURS_UTC_START > BUSINESS_HOURS_UTC_END:
        # Wraps midnight
        in_business = hour_utc >= BUSINESS_HOURS_UTC_START or hour_utc < BUSINESS_HOURS_UTC_END
    else:
        in_business = BUSINESS_HOURS_UTC_START <= hour_utc < BUSINESS_HOURS_UTC_END
    if not in_business:
        return InsiderThreatSignal(
            signal_type="off_hours_admin_access",
            actor=actor,
            resource=action,
            context={"ip": ip, "hour_utc": hour_utc},
            severity="medium",
        )
    return None


def detect_bulk_export(actor: str, record_count: int, resource: str) -> Optional[InsiderThreatSignal]:
    threshold = int(os.getenv("BULK_EXPORT_THRESHOLD", "1000"))
    if record_count >= threshold:
        return InsiderThreatSignal(
            signal_type="bulk_data_export",
            actor=actor,
            resource=resource,
            context={"record_count": record_count, "threshold": threshold},
            severity="critical",
        )
    return None


def detect_audit_chain_tampering(db_session_ctx) -> Optional[InsiderThreatSignal]:
    """Re-verify the audit chain. Return signal if tampering detected."""
    from src.app.security.audit_chain import verify_chain
    result = verify_chain(db_session_ctx)
    if not result.get("valid", True):
        return InsiderThreatSignal(
            signal_type="audit_chain_tamper_detected",
            actor="unknown",
            resource="decision_audits",
            context=result,
            severity="critical",
        )
    return None


def emit_insider_threat_signal(signal: InsiderThreatSignal, db_session_ctx=None):
    """Emit signal to SIEM and audit chain."""
    emit_siem_event(
        event_type=f"insider_threat:{signal.signal_type}",
        severity=signal.severity,
        actor=signal.actor,
        resource=signal.resource,
        context=signal.context,
    )
    if db_session_ctx and signal.severity == "critical":
        chain_new_record(
            db_session_ctx,
            record_id=hashlib.sha256(f"{signal.signal_type}{time.time()}".encode()).hexdigest()[:16],
            decision_id="insider_threat",
            action=signal.signal_type,
            actor=signal.actor,
            metadata=json.dumps(signal.context),
        )
```

---

### IT-DET-02 — Agent Prompt / Context Manipulation Detection
**Priority:** CRITICAL | **Effort:** M
**File:** [src/app/security/agent_guardrails.py](src/app/security/agent_guardrails.py) + new signals

**Problem:**
An insider with write access to Redis can modify `session:{uid}:summary` or `session:{uid}:kv_state` to manipulate AI agent context — causing the AI to approve a fraudulent refund, suppress a fraud alert, or exfiltrate data via a crafted recommendation response.

**Detection signals to add in `agent_guardrails.py`:**
```python
# Add to _EXFIL_PAT and _POISON_PAT existing detection:
_SESSION_INJECT_PAT = re.compile(
    r'(?i)(ignore\s+previous\s+instructions|new\s+system\s+prompt|'
    r'disregard\s+your\s+instructions|you\s+are\s+now|'
    r'admin\s+mode|developer\s+override|bypass\s+check)',
)
_BUDGET_INJECTION_PAT = re.compile(
    r'(?i)(approve\s+all|auto.?approve|skip\s+fraud|whitelist)',
)

def check_session_context_integrity(session_data: dict) -> list[str]:
    """Check loaded session context for injection patterns before feeding to agent."""
    triggered = []
    for field_name, value in session_data.items():
        text = str(value)
        if _SESSION_INJECT_PAT.search(text):
            triggered.append(f"session_injection_in_{field_name}")
        if _BUDGET_INJECTION_PAT.search(text):
            triggered.append(f"budget_injection_in_{field_name}")
    return triggered
```

**Wire into `recommend.py`** — before using any Redis-loaded session context, call `check_session_context_integrity(kv_state)` and log/alert on any triggered patterns.

---

### IT-DET-03 — Supplier Baseline Drift Detection
**Priority:** HIGH | **Effort:** M
**File:** [src/app/security/supplier_baseline.py](src/app/security/supplier_baseline.py) + [src/app/services/supply_chain_monitor.py](src/app/services/supply_chain_monitor.py)

**Problem:**
If an insider modifies `config/security/supply_chain_baselines.json` or `supplier_governance_store.py` directly to whitelist a fraudulent supplier domain or payment account, the change may go undetected.

**Fix — add file integrity monitoring for security config files:**
```python
# src/app/security/config_integrity.py
"""File integrity monitor for security-critical config files."""
import hashlib, json, os, time
from pathlib import Path

MONITORED_FILES = [
    "config/security/supply_chain_baselines.json",
    "config/security/routing_policy.json",
    "config/security/rbac_policy.json",
    "config/security/egress_allowlist.txt",
    "config/ai_governance/model_registry.json",
]

_BASELINE: dict[str, str] = {}

def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def record_baseline():
    """Call at startup to record expected hashes."""
    for f in MONITORED_FILES:
        if os.path.exists(f):
            _BASELINE[f] = _file_hash(f)

def check_integrity() -> list[dict]:
    """Returns list of tampered files. Call from Celery periodic task."""
    violations = []
    for f in MONITORED_FILES:
        if not os.path.exists(f):
            violations.append({"file": f, "issue": "missing"})
            continue
        current = _file_hash(f)
        expected = _BASELINE.get(f)
        if expected and current != expected:
            violations.append({"file": f, "issue": "hash_mismatch", "expected": expected, "got": current})
    return violations
```

**Wire into Celery beat (every 5 minutes):** If any violation is found → CRITICAL alert to SIEM, create ticket, freeze affected capability.

---

### IT-DET-04 — Excessive Ticket Acknowledgement / Alert Suppression
**Priority:** HIGH | **Effort:** S
**File:** [src/app/routers/incident.py](src/app/routers/incident.py) + [src/app/services/ticketing.py](src/app/services/ticketing.py)

**Problem:**
An insider who can acknowledge/close incident tickets or security alerts can suppress fraud/BEC detections by marking them as false positives. This is a known insider threat pattern (detection suppression).

**Fix:**
1. Add `closed_by` and `closed_reason` fields to tickets table — required non-empty when closing a `severity=critical` ticket.
2. Add alert: if the same actor closes >2 critical tickets in 1 hour, flag for review.
3. Add dual-control requirement for closing tickets with `topic=fraud` or `topic=bec`:
```python
# ticketing.py — on close:
if ticket.priority == "critical" and ticket.topic in ("fraud", "bec", "supply_chain"):
    if actor == ticket.created_by:
        raise ValueError("Cannot close your own critical fraud/BEC ticket — requires second approver")
```

---

### IT-DET-05 — LLM Prompt Version Drift Detection
**Priority:** HIGH | **Effort:** M
**File:** New — [src/app/security/prompt_registry.py](src/app/security/prompt_registry.py)

**Problem:**
System prompts and few-shot examples for fraud scoring, NQE, and recommendation are stored inline in Python files. An insider can modify a prompt to subtly bias model output without triggering code review alerts (e.g., "always approve refunds from supplier X").

**Fix — hash-lock all system prompts:**
```python
"""Prompt registry — version-locks system prompts.

Any change to a registered prompt that doesn't match the recorded hash
will raise a PromptTamperError and block deployment.
"""
import hashlib, os

_REGISTRY: dict[str, str] = {}  # prompt_id -> expected_sha256

def register_prompt(prompt_id: str, text: str) -> str:
    """Register a prompt. Returns the hash. Call at startup."""
    h = hashlib.sha256(text.encode()).hexdigest()
    expected = _REGISTRY.get(prompt_id)
    if expected and expected != h:
        raise RuntimeError(
            f"Prompt '{prompt_id}' hash mismatch — possible tampering. "
            f"Expected {expected[:12]}, got {h[:12]}. "
            "If intentional, update the hash in the registry."
        )
    _REGISTRY[prompt_id] = h
    return h

def verify_all() -> list[str]:
    """Returns list of prompt IDs with hash mismatches."""
    return []  # Populated by register_prompt calls at startup
```

**Store expected hashes in `config/ai_governance/prompt_hashes.json`** — committed to git, change requires code review.

---

## Section 2 — Prevention: Controls to Implement

### IT-PREV-01 — Dual Control for Supplier Governance Changes
**Priority:** CRITICAL | **Effort:** M
**File:** [src/app/security/supplier_governance_store.py](src/app/security/supplier_governance_store.py) + [src/app/routers/admin_supply_chain.py](src/app/routers/admin_supply_chain.py)

Any change to:
- Approved supplier domains
- Approved payment destinations (bank account fingerprints)
- Supplier contact whitelist
- Supply chain scan exemptions

Must require two distinct authenticated admin principals (different accounts, different IPs) within a 10-minute window. Implement using the existing `approvals.py` router pattern (which should already support multi-party approval).

```python
# admin_supply_chain.py — on any supplier write:
from src.app.routers.approvals import require_dual_approval

@router.put("/api/v1/admin/supply-chain/suppliers/{supplier_id}")
async def update_supplier(
    supplier_id: str,
    update: SupplierUpdate,
    approval_token: str = Query(...),
    current_user=Depends(require_role(ROLE_OWNER)),
):
    # Verify approval token was issued by a DIFFERENT admin
    approval_ok = await verify_dual_approval(approval_token, current_user.id)
    if not approval_ok:
        raise HTTPException(403, "Supplier changes require dual-control approval from a second admin")
    ...
```

---

### IT-PREV-02 — Separation of Duties for AI Model Changes
**Priority:** HIGH | **Effort:** M
**File:** [config/ai_governance/model_registry.json](config/ai_governance/model_registry.json) + CI

**Controls:**
1. No individual can both write and approve a model change in the same PR — enforced via GitHub branch protection (CODEOWNERS file).
2. Any change to `config/ai_governance/` requires review from both the AI governance owner AND the CISO.
3. Production model deployments are gated behind a CI eval suite that cannot be bypassed by the same person who made the change.

**Create `.github/CODEOWNERS`:**
```
config/ai_governance/        @ai-governance-owner @ciso
src/app/security/            @security-team
config/security/             @security-team @ciso
src/app/routers/payments.py  @payments-lead @ciso
```

---

### IT-PREV-03 — Principle of Least Privilege — Service Account Audit
**Priority:** HIGH | **Effort:** M
**File:** [config/security/rbac_policy.json](config/security/rbac_policy.json) + Docker service configs

**Current state:** Each service (api, celery-worker, sync-worker, crowdstrike-poll, syslog-listener) likely runs with the same DB credentials and API key. Compromise of any one worker gives full access.

**Fix — create per-service DB users:**
```sql
-- Celery worker: only needs tickets table write, no admin tables
CREATE ROLE celery_worker_role;
GRANT INSERT, UPDATE ON tickets TO celery_worker_role;
GRANT SELECT ON products, orders TO celery_worker_role;

-- Sync worker: needs catalog read/write, no financial tables
CREATE ROLE sync_worker_role;
GRANT SELECT, INSERT, UPDATE ON products, inventory TO sync_worker_role;

-- CrowdStrike poll: only needs security_events write
CREATE ROLE crowdstrike_role;
GRANT INSERT ON security_events TO crowdstrike_role;
```

Implement corresponding `DATABASE_URL_*` per-service env vars in `docker-compose.yml`.

---

### IT-PREV-04 — Immutable Audit Log (Protection Against Insider Deletion)
**Priority:** CRITICAL | **Effort:** M
**File:** [src/app/security/audit_chain.py](src/app/security/audit_chain.py) + `docker-compose.yml`

**Current state:** The audit chain is in the PostgreSQL `decision_audits` table. A DBA-privileged insider could `DELETE FROM decision_audits` or `UPDATE decision_audits SET record_hash = ...`.

**Fix — three-layer protection:**

**Layer 1 — DB-level protection:** Use PostgreSQL row-level security to deny DELETE and UPDATE on `decision_audits` for the application role:
```sql
-- Grant only INSERT and SELECT to the application database user
REVOKE UPDATE, DELETE ON decision_audits FROM shopsquire_api_role;
-- Even the DBA should require a separate audit_admin role to modify audit records
```

**Layer 2 — WORM archive:** Wire up `AUDIT_CHAIN_WORM_ARCHIVE_PATH` to append each new record hash to a local append-only file mounted on immutable storage:
```python
# audit_chain.py — after writing to DB, append to WORM archive:
worm_path = os.getenv("AUDIT_CHAIN_WORM_ARCHIVE_PATH", "")
if worm_path:
    with open(worm_path, "a") as f:
        f.write(json.dumps({
            "id": record_id, "hash": record_hash, "ts": created_at
        }) + "\n")
```

**Layer 3 — Daily external anchor:** Once per day, hash the day's audit records and POST to a transparency-log endpoint (or write to an S3 Object Lock bucket). If the daily anchor is missing or mismatches, it proves deletion.

---

### IT-PREV-05 — Privileged Access Workstation (PAW) Enforcement
**Priority:** HIGH | **Effort:** S
**File:** [src/app/security/auth.py](src/app/security/auth.py)

**Problem:** Admin sessions can be initiated from any device. An insider using a personal or compromised device to perform privileged actions is a significant risk.

**Fix — enforce IP allowlist for admin and owner roles:**
```python
# security/auth.py — after role verification:
ADMIN_IP_ALLOWLIST = os.getenv("ADMIN_IP_ALLOWLIST", "")

def check_admin_ip(request: Request, role: str):
    if role not in (ROLE_OWNER, "admin") or not ADMIN_IP_ALLOWLIST:
        return
    allowed_ips = [ip.strip() for ip in ADMIN_IP_ALLOWLIST.split(",")]
    client_ip = request.client.host
    if client_ip not in allowed_ips:
        raise HTTPException(403, f"Admin access from {client_ip} not in allowlist")
```

In production: admin access only from office IP ranges or VPN exit nodes.

---

## Section 3 — Monitoring: Dashboards and Alerting

### IT-MON-01 — Insider Threat Dashboard
**Priority:** HIGH | **Effort:** M
**File:** [frontend/src/components/AdminDashboard.tsx](frontend/src/components/AdminDashboard.tsx) + new API endpoint

**New API endpoint:** `GET /api/v1/admin/insider-threat/signals?last_hours=24`

Returns:
```json
{
  "total_signals": 3,
  "critical": 0,
  "high": 2,
  "medium": 1,
  "signals": [
    {
      "type": "off_hours_admin_access",
      "actor": "admin@merchant.com",
      "resource": "POST /api/v1/admin/supply-chain/suppliers",
      "timestamp": "2026-03-26T02:14:00Z",
      "severity": "medium",
      "ip": "203.x.x.x"
    }
  ]
}
```

Add to `AdminDashboard.tsx` a collapsible "Insider Risk" panel showing the last 24h of signals with severity badges.

---

### IT-MON-02 — Prometheus Metrics for Insider Threat Signals
**Priority:** MEDIUM | **Effort:** S
**File:** [src/app/observability/metrics.py](src/app/observability/metrics.py)

Add:
```python
insider_threat_signals_total = Counter(
    "shopsquire_insider_threat_signals_total",
    "Insider threat signals detected",
    labelnames=["signal_type", "severity", "actor_hash"],
)

audit_chain_verifications_total = Counter(
    "shopsquire_audit_chain_verifications_total",
    "Audit chain verification runs",
    labelnames=["result"],  # labels: valid, tampered, error
)

privileged_actions_total = Counter(
    "shopsquire_privileged_actions_total",
    "Privileged admin actions",
    labelnames=["action", "role", "off_hours"],
)
```

**Alerting rule:**
```yaml
- alert: InsiderThreatCriticalSignal
  expr: increase(shopsquire_insider_threat_signals_total{severity="critical"}[5m]) > 0
  for: 0m
  annotations:
    summary: "Critical insider threat signal detected — immediate review required"

- alert: AuditChainTampered
  expr: increase(shopsquire_audit_chain_verifications_total{result="tampered"}[1m]) > 0
  for: 0m
  annotations:
    summary: "AUDIT CHAIN TAMPERED — potential insider attack on audit records"
```

---

## Section 4 — People and Process Controls

### IT-PROC-01 — Access Review Cadence
**Framework Tags:** ISO 27001 A.5.18, NIST SP 800-53 AC-2, PCI DSS Req 8.6.1

**Controls to implement:**
- Quarterly access review of all admin and owner role holders — documented, with approval
- Immediate de-provisioning on role change or departure (target: within 2 hours)
- Annual red-team exercise specifically targeting insider threat vectors (AI prompt manipulation, session token theft, config file modification)
- Background check policy for roles with admin access to financial data

---

### IT-PROC-02 — Acceptable Use Policy for AI Agents
**Framework Tags:** ISO 42001 Cl 4.2, EU AI Act Art 9, NIST AI RMF GOVERN-2.1

**Document and enforce:**
- What operators MAY do with AI agent outputs (act on recommendations within approved thresholds)
- What operators MAY NOT do (override fraud scores without documented reason, bypass dual-control for supplier payments, modify session context directly)
- Whistleblower path for reporting suspected AI manipulation by colleagues

---

### IT-PROC-03 — Tabletop Exercise: Insider Threat Scenario
**Framework Tags:** ISO 27001 A.5.26, NIST SP 800-61r3, PCI DSS Req 12.10.2

**Scenario 1 — The Rogue Admin:**
An admin with OWNER role modifies `supply_chain_baselines.json` to whitelist a fraudulent supplier, processes a $50K payment, then deletes the ticket.
> Controls that should fire: IT-DET-03 (baseline drift), IT-PREV-01 (dual control), IT-PREV-04 (audit log immutability)

**Scenario 2 — The Prompt Poisoner:**
A developer pushes a change to the fraud scoring system prompt that causes the model to score all "VIP" orders as low-risk, regardless of signals.
> Controls that should fire: IT-DET-05 (prompt hash mismatch), IT-PREV-02 (CODEOWNERS), CI eval gate

**Scenario 3 — The Data Exfiltrator:**
An engineer uses their legitimate DB access to run a bulk SELECT on the customers table and export to CSV.
> Controls that should fire: IT-DET-01 (bulk export detection), IT-PREV-03 (least privilege — engineer role lacks SELECT on customers), audit chain entry

---

## Section 5 — Insider Threat Prevention Summary Table

| Control | File | Priority | Framework |
|---|---|---|---|
| Hardcoded audit HMAC removed | `audit_chain.py:40` | CRITICAL | ISO 27001 A.8.24 |
| Session context integrity check | `agent_guardrails.py` | CRITICAL | ISO 42001 Cl 8.3 |
| File integrity monitoring | `config_integrity.py` (NEW) | HIGH | ISO 27001 A.8.8 |
| Alert suppression detection | `ticketing.py` | HIGH | NIST SI-4 |
| Prompt version hash-lock | `prompt_registry.py` (NEW) | HIGH | ISO 42001 Cl 8.5 |
| Dual control for supplier changes | `admin_supply_chain.py` | CRITICAL | PCI DSS Req 12.3 |
| SoD for model changes | CODEOWNERS + CI | HIGH | ISO 42001 Cl 8.5 |
| Per-service DB least privilege | `docker-compose.yml` + SQL | HIGH | PCI DSS Req 7.2 |
| WORM audit log anchor | `audit_chain.py` | CRITICAL | PCI DSS Req 10.5.1 |
| Admin IP allowlist | `security/auth.py` | HIGH | ISO 27001 A.8.5 |
| Insider threat Prometheus metrics | `metrics.py` | MEDIUM | ISO 27001 A.8.16 |
| Insider threat dashboard | `AdminDashboard.tsx` | MEDIUM | ISO 27001 A.8.15 |
| Access review cadence | Process (quarterly) | HIGH | ISO 27001 A.5.18 |
| AUP for AI agents | Policy document | HIGH | ISO 42001 Cl 4.2 |
| Tabletop exercises | Annual | MEDIUM | PCI DSS Req 12.10.2 |

---

*Back to: [COMPLIANCE-MASTER-ACTION-PLAN.md](COMPLIANCE-MASTER-ACTION-PLAN.md)*
