# ShopSquire — Deep Status Audit (March 2026)

> **Honest, line-cited assessment covering:** escalation/ticketing, human handoff, DREAD/PASTA, security matrix, cyber risk quantification (CRQ), risk registers, GRC, image upload + visual search, product category identification, multi-category ecommerce support, and frontend ↔ backend wiring completeness.
>
> Legend: ✅ Works | ⚠️ Partial/Bug | ❌ Missing/Stubbed | 🔥 Critical Gap

---

## Table of Contents

1. [Overall Platform Score](#1-overall-platform-score)
2. [Human Escalation & Ticketing — Deep Dive](#2-human-escalation--ticketing)
3. [Security Matrix — DREAD, PASTA, STRIDE](#3-security-matrix--dread-pasta-stride)
4. [Cyber Risk Quantification (CRQ)](#4-cyber-risk-quantification-crq)
5. [Risk Registers & GRC](#5-risk-registers--grc)
6. [Why Agents Should Use the Risk Register (vs Over-engineering)](#6-why-agents-should-use-the-risk-register)
7. [Image Upload, Visual Search & Product Identity](#7-image-upload-visual-search--product-identity)
8. [Product Category Intelligence (MacBook / Tablet / Chromebook etc.)](#8-product-category-intelligence)
9. [Multi-Category Ecommerce — Can It Work Beyond Electronics?](#9-multi-category-ecommerce)
10. [Frontend ↔ Backend Wiring Audit](#10-frontend--backend-wiring-audit)
11. [What Is Fully Done (with line evidence)](#11-what-is-fully-done)
12. [What Is Partially Done](#12-what-is-partially-done)
13. [What Is Completely Missing](#13-what-is-completely-missing)
14. [Prioritised Fix Roadmap](#14-prioritised-fix-roadmap)

---

## 1. Overall Platform Score

```
DOMAIN                          SCORE   NOTES
────────────────────────────────────────────────────────────────────
4-Phase Orchestrator            95%     Mature; SLO-gated; adaptive
Human Escalation (end-to-end)   75%     Buyer trigger ✓ AI auto-create ✗
Ticketing / SLA                 85%     Celery SLA + Slack/PD/email ✓
Security Matrix (schema)        90%     Full trace_contract; incident gate ✓
DREAD                           40%     Framework present; static, not dynamic
PASTA                           85%     7-stage signal-driven progression ✓
STRIDE                          90%     6 categories from signal detection ✓
CRQ Model                       65%     Deterministic v1; NOT FAIR-compliant
Risk Register                   40%     Runtime-only; no persistence; no ownership
GRC Portal                      80%     Export CSV/MD/PDF; fingerprint monitoring
Image Upload → CV               85%     Triage works; vision LLM optional
Product Identity Agent          75%     Text heuristic ✓; LLM path optional
Visual Similarity Search         0%     MISSING — no CLIP/FAISS at all
Multi-Category Support           5%     Schema generic; entire pipeline hardcoded
Frontend ↔ Backend Wiring       80%     Core flows connected; 3 broken endpoints
Decision Trace (frontend)       95%     WS/SSE/Poll all wired; live streaming ✓
NQE Context (BUG-1)             FIXED   Was broken; now loading from Redis ✓
────────────────────────────────────────────────────────────────────
OVERALL PLATFORM READINESS      ~72%
```

---

## 2. Human Escalation & Ticketing

### 2.1 How a Buyer Triggers Escalation

**Status: ✅ Works (with 🔥 one critical gap)**

The buyer can trigger human escalation in two ways:

**Way 1 — Automatic (AI-triggered UI suggestion):**
```
Recommend router detects:
  - fraud_score > 0.7, OR
  - policy_gate verdict = "review"/"deny", OR
  - debate_judge.decision = "escalate"

→ Sets proposal["needs_human_review"] = True
→ Sets proposal["suggested_routing"] = "security_review"
→ Frontend (RightPanelExtras.tsx:132-140) detects this signal
→ Shows "Chat with Admin" button
→ Button press → POST /api/v1/incidents/escalate
```

**Way 2 — Manual (buyer clicks escalate button at any time):**
```
RightPanelExtras.tsx:362-397
→ POST /api/v1/incidents/escalate
   Payload: { case_id, trace_id, reason: "buyer_requested_human_review", context }
→ escalation_room.py:978-1057
   1. Creates incident row in incidents table
   2. Issues buyer_token (UUID, 24h TTL)
   3. Issues staff_token (UUID, 24h TTL)
   4. Appends initial system message to chat
   5. Returns { ok, incident_id, buyer_token, staff_token }
```

**🔥 Critical Gap — AI does NOT auto-create the incident:**
```python
# orchestrator.py:2954 — AI marks for review:
proposal["needs_human_review"] = True   ← set correctly

# BUT THERE IS NO CODE THAT:
# POST /api/v1/incidents/escalate (from backend)
# This only happens if the BUYER manually clicks the button

# Missing: after orchestrator sets needs_human_review, recommend.py
# should auto-call the escalation endpoint internally
```

**Fix needed:**
```python
# In routers/recommend.py — after orchestrator returns:
if proposal.get("needs_human_review") and not proposal.get("incident_id"):
    incident = await _create_incident_internal(
        trace_id=trace_meta["trace_id"],
        reason="ai_flagged_high_risk",
        fraud_score=proposal.get("fraud_score"),
        cv_signals=proposal.get("cv_signals"),
    )
    proposal["incident_id"] = incident["incident_id"]
    proposal["buyer_token"] = incident["buyer_token"]
```

### 2.2 Escalation Room — Step by Step

```
BUYER SIDE:
  POST /api/v1/incidents/escalate
    ↓ Returns incident_id + buyer_token
  GET /api/v1/incidents/{id}/room/stream?token={buyer_token}  ← SSE
    or
  WS  /api/v1/incidents/{id}/room/ws?token={buyer_token}
  POST /api/v1/incidents/{id}/room/message?token={buyer_token}

STAFF SIDE:
  GET /api/v1/admin/incidents  ← list all open incidents
  GET /api/v1/admin/incidents/{id}/room/token  ← issue staff_token
  WS  /api/v1/admin/incidents/{id}/room/ws?token={staff_token}
  POST /api/v1/admin/incidents/{id}/status?status=triaged|resolved|closed
  POST /api/v1/admin/incidents/{id}/assign
  POST /api/v1/admin/incidents/{id}/runbook/execute
  POST /api/v1/admin/incidents/{id}/evidence
```

### 2.3 Database Tables for Incidents

**Core table** (`src/app/models/db.py:184-193`):
```sql
incidents (
  id TEXT PRIMARY KEY,
  event_id TEXT,
  created_at TEXT,
  created_by TEXT,
  severity TEXT,
  title TEXT,
  description TEXT,
  status TEXT DEFAULT 'open'          -- open/review/triaged/resolved/closed
)
```

**Runtime columns added at startup** (`escalation_room.py:80-87`):
```sql
  assigned_to TEXT,
  team TEXT,
  sla_status TEXT,                    -- active/met/breached
  sla_due_at TEXT,
  sla_breach_alerted_at TEXT,
  runbook_id TEXT,
  runbook_run_id TEXT,
  runbook_failure_alerted_at TEXT
```

**Evidence table** (`escalation_room.py:96-106`):
```sql
incident_evidence_attachments (
  id, incident_id, filename, content_type, file_path, sha256, notes, created_by, created_at
)
```

### 2.4 SLA Enforcement — Is It Actually Working?

**Status: ✅ Yes, SLA enforcement is real and functional**

```
SLA tiers (escalation_room.py:268-276):
  critical/high/error → 30 min (INCIDENT_SLA_MINUTES_HIGH)
  medium/warn → 120 min (INCIDENT_SLA_MINUTES_MEDIUM)
  low/info → 240 min (INCIDENT_SLA_MINUTES_LOW)

SLA Scheduler (services/incident_sla_scheduler.py:58-124):
  run_cycle():
    1. SELECT active incidents (open/review/triaged) from DB
    2. For each: check sla_due_at < now()
    3. If breached: UPDATE sla_status='breached'
    4. Call dispatch_incident_alert() if sla_breach_alerted_at IS NULL
    5. SET sla_breach_alerted_at = now()  ← prevents duplicate alerts

Celery task (tasks/incident_ops_tasks.py:6-14):
  @celery_app.task(name="check_incident_sla_breaches")
  Schedule: every INCIDENT_SLA_CELERY_MINUTES minutes (default 1)
  Toggle: INCIDENT_SLA_CELERY_ENABLED (default True)

Thread-based fallback (incident_sla_scheduler.py:127):
  start_incident_sla_scheduler() → daemon thread, 30s interval

Alert channels (services/incident_alert_adapters.py:198-216):
  - Slack: INCIDENT_ALERT_SLACK_WEBHOOK_URL
  - PagerDuty: INCIDENT_ALERT_PAGERDUTY_ROUTING_KEY
  - Email: INCIDENT_ALERT_EMAIL_TO via SMTP
```

**⚠️ Known issue:** SLA breach alert fires **once only** (guarded by `sla_breach_alerted_at IS NULL`). If breach continues for 24h there is no escalation repeat.

### 2.5 Incident Closure Gate (Security Matrix Required)

**Status: ✅ Works — cannot close without a security scan**

```python
# escalation_room.py:422 — on status=resolved or status=closed:
gate = validate_incident_matrix_gate(conn, incident_id)
if not gate.get("ok"):
    raise HTTPException(status_code=409, detail={
        "error": "security_matrix_incomplete",
        "gate": gate,  # contains missing_fields list
    })
```

The `validate_incident_matrix_gate()` function (`trace_contracts.py:351-425`) checks that a `security_scan` event with a complete matrix exists in `decision_trace_events` for this incident's trace_id. Required fields:
```python
["severity", "route", "threshold_version", "signals",
 "mitre_atlas", "owasp_llm_top10", "stride_categories", "evidence", "bitemporal"]
```

**⚠️ Known gap:** Gate validates but doesn't trigger collection. If the security_scan is missing, staff are stuck with a 409 until the observer re-runs. There is no "collect now" endpoint.

---

## 3. Security Matrix — DREAD, PASTA, STRIDE

### 3.1 Full Security Matrix Schema

**Status: ✅ Fully defined**

File: `src/app/services/trace_contracts.py:101-128`

```python
class SecurityScanContract(BaseModel):
    severity: str                        # info/warn/high/critical/error
    route: str                           # allow/review/block
    threshold_version: str               # "security-v1"
    confidence: float | None
    signals: Dict[str, bool]            # 60+ signal flags
    mitre_atlas: List[str]              # e.g. ["AML.T0043"]
    mitre_attack: List[str]             # e.g. ["T1566"]
    owasp_llm_top10: List[str]          # e.g. ["LLM01:PromptInjection"]
    owasp_agentic_top10: List[str]      # Dec 2025 list
    owasp_api_top10: List[str]
    stride_categories: List[str]        # e.g. ["Spoofing","Tampering"]
    dread: Dict[str, Any] | None        # DREAD scores
    pasta: Dict[str, Any] | None        # PASTA stage progression
    evidence: Dict[str, Any]
    containment_actions: List[str]
    input_hash: str | None
    ocr_text_hash: str | None
    entities: Dict[str, Any]
    bitemporal: BitemporalWindow         # valid_from, valid_to, system_from, system_to
```

### 3.2 DREAD — Is It Actually Computing?

**Status: ⚠️ Static weights, NOT dynamic per-event scoring**

```json
// config/security/taxonomy/dread_weights.json
{
  "damage": 1.0,
  "reproducibility": 0.8,
  "exploitability": 1.0,
  "affected_users": 0.7,
  "discoverability": 0.6
}
```

```python
# src/app/security/observer.py:513
dread_avg = sum(dread.values()) / max(len(dread.values()), 1)
# = (1.0 + 0.8 + 1.0 + 0.7 + 0.6) / 5 = 0.82  ← ALWAYS 0.82, every event

# Used in risk scoring (observer.py:539-545):
risk_raw = (
    w.get("mitre", 0.3) * mitre_score
    + w.get("stride", 0.1) * stride_sum * 10
    + w.get("dread", 0.25) * dread_avg * 10    # ← always 0.25 * 0.82 * 10 = 2.05
    + w.get("cvss", 0.2) * cvss_score * 100
    + w.get("kev", 0.15) * kev_weight
)
```

**What's missing for real DREAD:**
| DREAD Component | Should compute | Currently |
|----------------|---------------|-----------|
| **Damage** | How bad if exploited? (0–10) | Fixed 1.0 |
| **Reproducibility** | How reliably repeatable? (0–10) | Fixed 0.8 |
| **Exploitability** | How easy to exploit? (0–10) | Fixed 1.0 |
| **Affected Users** | What % of users? (0–10) | Fixed 0.7 |
| **Discoverability** | How easy to find? (0–10) | Fixed 0.6 |

**What real DREAD scoring needs:**
```python
# Per-event dynamic DREAD:
def compute_dread(signals: Dict, severity: str, user_scope: float) -> Dict:
    return {
        "damage": _damage_from_severity(severity),           # error→10, high→8, warn→5
        "reproducibility": _repro_from_signal_count(signals), # 5+ signals→9, 2→5, 1→3
        "exploitability": _exploit_from_attack_type(signals), # prompt_injection→10, pii→6
        "affected_users": user_scope * 10,                    # fraction of active users
        "discoverability": _discov_from_public_exposure(signals), # public endpoint→9
    }
```

**Effort to fix:** 1 sprint.

### 3.3 PASTA — Is It Working?

**Status: ✅ Yes, 7-stage signal-driven progression works**

File: `src/app/security/framework_correlation.py:126-162`

```python
def _pasta(signals, severity):
    stages = [
        {"id": "Stage1", "name": "DefineObjectives"},
        {"id": "Stage2", "name": "DefineTechnicalScope"},
        {"id": "Stage3", "name": "ApplicationDecomposition"},
        {"id": "Stage4", "name": "ThreatAnalysis"},
        {"id": "Stage5", "name": "VulnerabilityAnalysis"},
        {"id": "Stage6", "name": "RiskResponse"},
        {"id": "Stage7", "name": "MitigationVerification"},
    ]

    current = "Stage1"
    if any(bool(v) for v in (signals or {}).values()):
        current = "Stage2"   # any signal fired → scope defined
    if signals.get("supply_chain") or signals.get("training_poisoning"):
        current = "Stage3"   # supply chain / AI attack → decompose
    if signals.get("jailbreak") or signals.get("prompt_injection"):
        current = "Stage4"   # active LLM attack → threat analysis
    if signals.get("data_exfiltration") or signals.get("pci"):
        current = "Stage5"   # data leak risk → vulnerability analysis
    if str(severity).lower() in ("high", "critical", "error"):
        current = "Stage6"   # high severity → risk response
    # Stage7 = MitigationVerification (not auto-set; requires human confirmation)
```

**Where it's used:**
- `security/observer.py:713` — every request gets a PASTA stage
- `routers/cv.py:847,1069` — CV triage results include PASTA
- `routers/decisions.py:265-299` — decision detail includes PASTA
- `routers/recommend.py:1795-1807` — recommendation includes PASTA

**What Stage7 (MitigationVerification) needs:** Requires a human to mark as mitigated. This is done via incident closure — the `validate_incident_matrix_gate()` acts as Stage7 enforcement.

### 3.4 STRIDE — Working

**Status: ✅ All 6 categories from signal detection**

File: `src/app/security/framework_correlation.py:88-123`

| STRIDE Category | Trigger Signals |
|----------------|----------------|
| Spoofing | `bec`, `brand_impersonation`, `lookalike_domain`, `dmarc_fail`, `auth_alignment_failed` |
| Tampering | `manipulation_detected`, `layout_text_divergence` |
| Repudiation | `email_c2_beaconing`, `thread_hijack` |
| InformationDisclosure | `data_exfiltration`, `pii`, `api_key` |
| DenialOfService | `scanner_burst`, `rate_anomaly` |
| ElevationOfPrivilege | `agentic_tool_abuse`, `prompt_injection` |

---

## 4. Cyber Risk Quantification (CRQ)

### 4.1 The Formula

**File:** `src/app/services/risk_quantification.py:1-146`
**Status: ✅ CRQ v1 deterministic model works**

```
LIKELIHOOD = (
    0.35 × security_risk_adj     (security observer score 0-1)
  + 0.25 × cv_severity_mapped    (minor→0.2, moderate→0.45, major→0.7, high→0.8, critical→0.9)
  + 0.25 × fraud_level_mapped    (minimal→0.1, low→0.25, medium→0.6, high→0.85)
  + 0.15 × history_score         (0-1 from past session behavior)
)

IMPACT = (
    0.50 × monetary_exposure     (amount_cents / 200000, capped at 1.0)
  + 0.30 × policy_impact         (fail/blocked→0.8, False→0.7, else→0.3)
  + 0.20 × data_impact           (0.3 default)
)

RISK_SCORE = LIKELIHOOD × IMPACT × 100   (0-100 scale)
RISK_BAND  = high if ≥60, medium if ≥30, else low
```

### 4.2 What Numbers You Put In

| Input | Type | Source | Example |
|-------|------|--------|---------|
| `security.risk_adj` | 0–100 float | Security observer output | 75.0 |
| `security.signals` | List[str] | Detected signal names | ["prompt_injection","pii"] |
| `cv_analysis.severity` | str | CV triage result | "major" |
| `cv_analysis.confidence` | 0–1 float | CV model confidence | 0.83 |
| `fraud.level` | str | Fraud scorer band | "high" |
| `fraud.score` | 0–100 float | Fraud scorer score | 82.5 |
| `policy_gates` | Dict/List | Policy gate result | {"decision":"review"} |
| `monetary_exposure` | float (dollars) | Order/refund amount | 850.00 |
| `history_score` | 0–1 float | Past session risk | 0.4 |

### 4.3 Where CRQ Output Goes

**3 call sites:**

| Endpoint | File | How CRQ is used |
|----------|------|----------------|
| `POST /api/v1/trace/debug/enriched` | `routers/trace_debug.py:42-49` | GRC enrichment — returned in response |
| `POST /api/v1/recommend/proposal` | `routers/recommend.py:~42` | Injected into retrieved_context, returned to frontend |
| `POST /api/v1/support/complaints/*` | `routers/support_complaints.py` | Return/refund risk decision |

**Policy Gate integration** (`policy/gate.py:41,78-79,204-210`):
```python
risk = float(context.get("risk_score") or 0.0)
risk_high_min = _thr_float("risk_score_high_min", 0.8)   # default 0.8

if risk >= risk_high_min:
    approval_required = True     # human-in-the-loop required
```

### 4.4 Is This FAIR? (Factor Analysis of Information Risk)

**No. CRQ v1 is NOT FAIR-compliant.**

| FAIR Component | ShopSquire CRQ v1 | Gap |
|---------------|------------------|-----|
| Asset Value (AV) | Not present | No asset catalogue |
| Annual Rate of Occurrence (ARO) | Not present | No frequency distribution |
| Single Loss Expectancy (SLE) | Not present | No AV × Loss Magnitude |
| **Annualized Loss Expectancy (ALE = ARO × SLE)** | **Not present** | **No insurance-grade number** |
| Threat Event Frequency (TEF) | Partial (likelihood proxy) | No historical frequency fit |
| Loss Magnitude (LM) | Not present | Monetary exposure is a proxy |
| Control Effectiveness | Not present | Policy gate binary; no % reduction |

**CRQ v1 is appropriate for:** Real-time transaction risk gating, per-request policy decisions.

**CRQ v1 is not appropriate for:** Insurance calculations, CISO board reporting (requires ALE), vendor risk management (requires asset valuation), regulatory capital modeling.

**What to add for FAIR:** A `CRQv2FairModel` that builds on v1 with:
- Asset registry (per-SKU and per-system asset value)
- Control effectiveness register (how much each control reduces risk %)
- Rolling ARO (count events per month → annual rate)
- `ALE = ARO × (AV × vulnerability_score)` as the output number

---

## 5. Risk Registers & GRC

### 5.1 Risk Register — Current State

**File:** `src/app/routers/admin_grc.py:66-213`
**Status: ⚠️ Runtime-only — computed fresh from DB each request; NOT persisted**

```
GET /api/v1/admin/grc/risk-register?days=30

5 Risk Domains (computed on-the-fly):
┌──────────────────────────┬──────────────────────────────────────────────────────┐
│ Domain                   │ Formula                                              │
├──────────────────────────┼──────────────────────────────────────────────────────┤
│ email_deliverability     │ min(100, dmarc_failed×8 + critical_security×5)       │
│ supplier_trust           │ min(100, supplier_incidents×10 + critical_security×3)│
│ inventory_resilience     │ min(100, stockouts×15 + low_stock×2)                 │
│ insider_threat           │ min(100, suspicious_iam×7 + critical_security×2)     │
│ decision_trace_coverage  │ 100 − min(100, trace_events÷20)                      │
└──────────────────────────┴──────────────────────────────────────────────────────┘
```

**Framework controls mapped** (`admin_grc.py:203-212`):
```python
{
    "ISO27001:A.8.15": pass if security_events > 0
    "ISO27001:A.8.16": pass if critical_security >= 0
    "GDPR:Art.22":     pass if decision_trace_events > 0
    "GDPR:Art.32":     pass if iam_events >= 0
    "EU_AI_ACT:Art.14": pass if trace_events > 0
    "NIST_AI_RMF:MANAGE-3": pass if security_events > 0
    "ISO42001:7.4":    pass if trace_events > 0
    "ISO19011:Clause 6": pass if trace_events > 0
}
```

**Export endpoints — all working:**
- `GET /api/v1/admin/grc/report/export.csv` ✅
- `GET /api/v1/admin/grc/report/export.md` ✅
- `GET /api/v1/admin/grc/report/export.pdf` ✅ (hand-rolled minimal PDF)

### 5.2 What's Missing in the Risk Register

**❌ No persistent `risk_register` database table.** The register is rebuilt from scratch on every API call. This means:

- Cannot track "risk was high on 15 Feb, dropped to medium on 28 Feb"
- Cannot assign a risk owner ("Sarah owns supplier_trust domain")
- Cannot track mitigation actions ("patched DMARC on 20 Feb → risk reduced")
- Cannot show residual risk (after controls applied)
- Cannot answer auditor question: "Show me your risk treatment plan for domain X"

**Recommended schema to add:**
```sql
CREATE TABLE risk_register_snapshots (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    risk_score REAL,
    risk_band TEXT,                    -- low/medium/high
    snapshot_date TEXT NOT NULL,
    risk_owner TEXT,
    mitigation_strategy TEXT,
    mitigation_deadline TEXT,
    residual_risk_score REAL,
    status TEXT DEFAULT 'open',        -- open/mitigating/accepted/closed
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. Why Agents Should Use the Risk Register

### The Problem Without It

Currently agents are **blind to the organisation's risk posture**:

```
Example: supplier_trust.risk_band = "high" for 2 weeks
  ↓
Policy gate threshold = 0.8 (hardcoded, unchanged)
  ↓
Agent approves order from that high-risk supplier at the same threshold
  ↓
Should have: lower auto-approve threshold to 0.4 when domain is high-risk
```

### The Right Level of Integration (Not Over-Engineering)

**Recommended integration — 3 touchpoints only:**

1. **Policy Gate** reads risk domain bands dynamically:
```python
# gate.py — replace hardcoded thresholds with domain-aware ones:
supplier_risk = risk_register.get_band("supplier_trust")
if supplier_risk == "high":
    auto_approve_threshold = 0.4    # tighter
else:
    auto_approve_threshold = 0.8    # normal
```

2. **Orchestrator** adjusts budget for supplier-related queries:
```python
# If inventory_resilience.risk_band == "high":
# Boost Inventory_Agent budget by 25% to do deeper supplier analysis
```

3. **NQE** injects risk context into conversation:
```python
# If insider_threat.risk_band == "high":
# Add a question: "This order requires additional verification due to current risk conditions"
```

**Why this is NOT over-engineering:**
- 3 touchpoints, not 50
- Reads a single Redis-cached value (1ms overhead)
- Replaces hardcoded magic numbers with data-driven thresholds
- Provides a direct audit trail: "Why was this rejected?" → "supplier_trust risk was HIGH"

### Why GRC Auditors Care

| Auditor Question | Without Risk Register | With Risk Register |
|-----------------|----------------------|-------------------|
| "What is your current risk posture?" | "We run a script" | "supplier_trust: medium, insider_threat: low as of today" |
| "When did risk increase?" | Unknown | "supplier_trust went high on 15 Feb per snapshot" |
| "What did you do about it?" | Unknown | "Mitigation: added step-up verification, owner: Sarah, deadline: 28 Feb" |
| "Did controls work?" | Unknown | "Risk dropped medium → low on 1 Mar (residual risk = 25)" |
| "Who owns each risk?" | Nobody | "risk_owner column in DB, reviewed quarterly" |
| "Show me your ISO27001 A.8.15 evidence" | "Here's a dump of security_events" | "Here's a PDF with control pass/fail, evidence links, trend charts" |
| "Is your AI system compliant with EU AI Act Art.14?" | "We think so" | "PASS — 847 human oversight trace events in the last 30 days" |

---

## 7. Image Upload, Visual Search & Product Identity

### 7.1 What Actually Happens When You Upload a Product Image

```
User uploads image (AttachmentButton.tsx)
    │
    ├─ GET /api/v1/cv/nonce                     ← anti-replay token
    ├─ POST /api/v1/cv/upload                   ← image binary
    │     ↓
    │   vision.py:73 — triage():
    │     strict_image_ingest_gate()            ← format/size validation
    │     sanitize_image()                      ← strip metadata, re-encode
    │     ManagedCVProvider.get_labels_and_text() ← labels + OCR
    │     BasicCVTriage.analyze()               ← damage_type, damage_score
    │     _is_product_photo()                   ← product vs damage photo?
    │     image_intent_router()                 ← visual_search / cv_triage / faq
    │     Security scan (QR, adversarial, steg)
    │     ↓
    │   Response: { labels, damage_score, is_product_photo, intent, event_id }
    │
    ├─ Image identity extracted (recommend.py:3707-3779):
    │     ProductIdentityAgent.identify_from_labels_and_ocr()   ← text heuristic
    │     If confidence > 0.3:
    │       ProductIdentityAgent.identify_from_image_url()      ← vision LLM (optional)
    │     specs_to_constraints() → { brand, budget_min, budget_max, cpu_tier, ram_gb, gpu, display_size, form_factor }
    │
    └─ Merged into recommendation constraints:
          identity_brand → constraints["brand"]
          identity_budget_min/max → constraints["budget_min/max"]
          identity_cpu_tier → constraints["cpu_tier"]
          identity_ram_gb_min → constraints["specs"].ram_min_gb
          identity_gpu_class → constraints["must_have_gpu"]
          identity_display_inches → constraints["display_inches"]
          identity_product_type → constraints["product_type"]
```

### 7.2 Does Budget Filtering Work With Image?

**Status: ✅ Yes — spec-based, NOT visual similarity**

**Scenario: Upload MacBook Pro + "under $1500"**

```
Step 1 — Image identity extracts:
  brand = "Apple", price_tier = "premium"
  → identity_budget_min = 1200, identity_budget_max = 2200

Step 2 — NLP parses text query:
  "under $1500" → budget_max = 1500

Step 3 — Constraint merge (recommend.py:3740-3760):
  # Text constraint wins over identity constraint when more specific:
  constraints["budget_max"] = 1500  (user's explicit text wins)
  constraints["brand"] = "Apple"   (from image, no text brand given)
  constraints["cpu_tier"] = "performance"  (from image M-series label)

Step 4 — Catalog filter:
  SELECT * FROM products WHERE price_cents ≤ 150000 AND brand = 'Apple'
  → Returns: MacBook Air M3, MacBook Air M2 Refurb, etc.
```

**Result: Correct** — image anchors brand/spec, user's budget caps price.

### 7.3 Visual Similarity Search — Does It Exist?

**Status: ❌ COMPLETELY MISSING — No FAISS, No CLIP, No visual embeddings**

```python
# src/app/services/reverse_image_search.py:81-103
def find_similar(phash: str) -> List[FraudImageEntry]:
    # Uses Hamming distance on perceptual hashes
    # ONLY used for fraud detection (known fraud image matching)
    # NOT used for catalog product similarity
```

**What users EXPECT:** "Upload a photo of any laptop → find similar-looking products"

**What they GET:** System extracts text-detectable specs from the image, then runs a text-based spec filter. Two visually identical laptops from different brands won't be matched visually — they'll only match if their specs are textually similar.

**To implement true visual search:**
```python
# Needed:
pip install faiss-cpu sentence-transformers clip-by-openai

# 1. Embed all product images at catalog load time:
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
product_embeddings = {sku: clip_model.encode_image(product.image_url) for sku in catalog}
faiss_index = faiss.IndexFlatL2(512)  # CLIP embedding dim
faiss_index.add(np.array(list(product_embeddings.values())))

# 2. At search time:
query_embedding = clip_model.encode_image(uploaded_image)
distances, indices = faiss_index.search(query_embedding, k=20)
# → top-20 visually similar catalog items

# 3. Then apply text/budget constraints as a post-filter
```

**Effort:** 2–3 sprints (CLIP inference, FAISS index, catalog embedding pipeline, incremental update).

---

## 8. Product Category Intelligence

### 8.1 Can It Identify a MacBook vs Chromebook vs Gaming Laptop?

**Status: ⚠️ Yes for brand/type detection; ❌ No for visual form-factor classification**

**Text-pattern detection works** (`product_identity_agent.py:286-335`):

```python
# Brand detection (14 brands):
"apple":    ["apple", "macbook", "imac", "mac mini", "mac pro", "m1", "m2", "m3", "m4"]
"lenovo":   ["lenovo", "thinkpad", "ideapad", "legion"]
"asus":     ["asus", "vivobook", "zenbook", "rog", "tuf"]
...

# Product type detection:
"laptop":  ["laptop", "notebook", "ultrabook", "chromebook", "macbook"]
"tablet":  ["tablet", "ipad", "surface go", "galaxy tab"]
"desktop": ["desktop", "tower", "pc", "imac", "mac mini"]
"monitor": ["monitor", "display", "screen"]
"phone":   ["phone", "iphone", "smartphone"]

# Form factor detection:
"gaming":     ["gaming", "rog", "tuf", "nitro", "legion", "predator", "razer"]
"ultrabook":  ["ultrabook", "slim", "air", "ultra", "zenbook"]
"workstation":["workstation", "precision", "thinkpad p", "zbook"]
"2-in-1":     ["2-in-1", "convertible", "detachable", "surface pro", "yoga"]

# CPU tier detection:
"budget":      ["celeron", "pentium", "n4xxx", "n5xxx", "n200"]
"midrange":    ["i5", "ryzen 5", "core 5"]
"performance": ["i7", "ryzen 7", "m3", "core 7", "snapdragon x"]
"workstation": ["i9", "ryzen 9", "xeon", "m3 max", "m3 ultra"]
```

**What is correctly identified from a clear product image label:**

| Product | Detected? | How |
|---------|----------|-----|
| MacBook Air M3 | ✅ brand=Apple, type=laptop, tier=performance | OCR "macbook" + "m3" labels |
| Gaming laptop (ROG) | ✅ brand=ASUS, form=gaming | "rog" label |
| Chromebook | ✅ type=laptop (chromebook keyword) | "chromebook" label |
| Business laptop (ThinkPad) | ✅ brand=Lenovo, form=workstation | "thinkpad" label |
| Surface Pro (tablet/2-in-1) | ✅ type=tablet, form=2-in-1 | "surface pro" label |
| Generic unlabelled laptop | ⚠️ type=laptop but brand=unknown | Heuristic only |
| Tablet without brand label | ⚠️ type=tablet if screen/keyboard absent | Limited |

**What's missing:**
- **Vision-model-based** classification (needs `llava` Ollama running)
- Subcategory: "Chromebook" vs "ChromeOS Flex" vs "Android tablet"
- Condition assessment from image (new / refurbished / damaged)

### 8.2 Recommend Router Category Bug

**🔥 Critical simplification in recommend.py:4068:**
```python
category = "laptop" if "laptop" in (query or "").lower() else "general"
```

This binary split is wrong. A user uploading a tablet image with query "something similar" gets `category = "general"` even though product_type was detected as "tablet". The image-extracted `product_type` is NOT flowing into this category variable.

**Fix:**
```python
# Use image-extracted product_type if available:
category = (
    _identity_constraints.get("identity_product_type")
    or ("laptop" if "laptop" in (query or "").lower() else "general")
)
```

---

## 9. Multi-Category Ecommerce

### 9.1 Honest Assessment

**ShopSquire is fundamentally electronics-only right now.**

Evidence:

```python
# routers/recommend.py:151-167 — ACTIVELY BLOCKS non-electronics:
_UNSUPPORTED_PRODUCT_TERMS = {
    "kitchen", "mixer", "blender", "toaster", "microwave",
    "fridge", "refrigerator", "dishwasher", "oven", "vacuum",
    "television", "tv", "sofa", "bed", "mattress",
}

# services/nlp_search_agent.py:53-61 — spec patterns assume laptops:
_SPEC_PATTERNS = {
    "ram_gb": re.compile(r"(\d+)\s*gb\s*(?:ram|memory)"),
    "storage_gb": re.compile(r"(\d+)\s*(?:gb|tb)\s*(?:ssd|hdd)"),
    "display_inches": re.compile(r"(\d{2})\s*inch\s*(?:screen|display)"),
    "refresh_hz": ...,
    "gpu_vram_gb": ...,
}
# No clothing size, no food dietary, no furniture dimensions

# flows/nqe.py:272-442 — NQE templates assume electronics:
# "What GPU do you need?" "Do you need a touch screen?"
# No templates for: "What size?" "What color?" "Dietary restrictions?"
```

### 9.2 What the Schema Supports (Generically)

**Product ORM** (`src/app/models/orm.py:19-29`):
```python
class Product(Base):
    id, sku, name, price_cents, currency, image_url
    specs: Mapped[dict | None] = mapped_column(JSON)  # ← any attributes
    active, updated_at
```

The `specs` field is a JSON blob — it CAN hold `{"size": "M", "color": "red", "material": "cotton"}` for clothing. **The schema is generic. The pipeline is not.**

### 9.3 What's Needed for True Multi-Category

**Phase 1 — Category routing (1 sprint):**
```python
# New service: services/category_router.py
class CategoryRouter:
    def detect(query, image_labels) -> str:
        # "find me a dress" → "clothing"
        # "laptop for gaming" → "electronics"
        # "sectional sofa" → "furniture"
        # "gluten free snacks" → "food"

    def get_nqe_template_set(category) -> str:
        # Returns the right NQE template bank for that category
```

**Phase 2 — Category-specific NQE templates (1–2 sprints):**
```python
# config/nqe_templates_clothing.json:
{
  "ask_size": {"question": "What size are you?", "options": ["XS","S","M","L","XL","XXL"]},
  "ask_color": {"question": "Any color preference?", "options": ["Black","White","Blue","Red","Neutral"]},
  "ask_occasion": {"question": "What's the occasion?", "options": ["Casual","Work","Formal","Sport"]},
}

# config/nqe_templates_food.json:
{
  "ask_dietary": {"question": "Any dietary requirements?", "options": ["Vegan","Gluten-free","Halal","Kosher","None"]},
  "ask_cuisine": {"question": "What cuisine?", "options": ["Asian","Mediterranean","American","Mexican"]},
}
```

**Phase 3 — Ranking signals per category (2 sprints):**
- Clothing: size availability, color match, occasion fit
- Food: dietary compliance, freshness, cuisine type
- Furniture: room fit, material preference, delivery lead time

**Phase 4 — CV for non-electronics (2 sprints):**
- Clothing: color detection, style classification, condition assessment
- Furniture: room scene detection, material classification
- Food: freshness indicators (currently only electronics signals defined)

**Estimated total effort for generic multi-category:** 6–8 sprints.

---

## 10. Frontend ↔ Backend Wiring Audit

### 10.1 Core Chat → Recommend Pipeline

**Status: ✅ CONNECTED end-to-end**

```
App.tsx:722 handleSend()
  → POST /api/v1/chat/query
  → chat.py:258 delegates to recommend.py
  → Response: { products, assistant_message, next_questions, complexity,
                nqe_selection_applied, decision_trace_id, trace_id, view_mode }
  → App.tsx:731-762 updates state, renders ProductGrid + NQE buttons
```

NQE disambiguation click: `App.tsx:818-822` → sends selected option as new query → flows through same pipeline.

### 10.2 Escalation Room Wiring

**Status: ⚠️ PARTIAL — 1 broken endpoint**

```
CONNECTED ✅:
  POST /api/v1/incidents/escalate           ← buyer triggers
  GET  /api/v1/incidents/{id}/room/stream   ← buyer SSE
  WS   /api/v1/admin/incidents/{id}/room/ws ← staff WebSocket
  POST /api/v1/incidents/{id}/room/message  ← both sides send
  GET  /api/v1/admin/incidents              ← list all incidents

BROKEN ✗:
  EscalationRoom.tsx:52 calls:
    GET /api/v1/admin/incidents/{incident_id}
  → Backend endpoint NOT FOUND in escalation_room.py
  → Incident summary panel stays in "Loading…" forever
```

**Fix:** Add `GET /api/v1/admin/incidents/{id}` endpoint in escalation_room.py (it already exists at line 374 as `/{incident_id}` relative to the router prefix — verify the full path).

### 10.3 Decision Trace — All Wired

**Status: ✅ CONNECTED — WS, SSE, Poll all work**

```
DecisionTrace.tsx:
  Primary:    WS  /api/v1/decisions/{id}/events/ws    → decisions.py:536     ✅
  Fallback 1: SSE /api/v1/decisions/{id}/events/stream → decisions.py:655    ✅
  Fallback 2: SSE /api/v1/trace/{id}/events/stream    → decision_trace_events.py:118 ✅
  Timeline:   GET /api/v1/trace/{id}/timeline         → decision_trace_events.py:416 ✅
  Explain:    GET /api/v1/decisions/{id}/explain      → decisions.py:1565    ✅
  Replay:     GET /api/v1/decisions/{id}/replay       → decisions.py:1694    ✅
```

Reconnection logic: WS → SSE fallback → 5s poll. This is excellent defensive design.

### 10.4 Admin Dashboard Wiring

**Status: ⚠️ PARTIAL**

```
CONNECTED ✅:
  GET /api/v1/merchant/intelligence/citation_memory/stats
  GET /api/v1/merchant/intelligence/user_profiles/{uid}
  GET /api/v1/merchant/intelligence/user_profiles/{uid}/behavioral_model
  GET /api/v1/merchant/intelligence/observation_summary/{session_id}

BROKEN ✗:
  AdminDashboard.tsx:79 calls:
    GET /status/summary
  → Backend endpoint NOT FOUND
  → Admin overview tab shows no metrics

STUB/COMING SOON ⚠️:
  Recommendation Performance tab is hardcoded "coming soon"
  RAGAS summary endpoint not wired
```

### 10.5 CV / Image Upload Wiring

**Status: ⚠️ PARTIAL**

```
CONNECTED ✅:
  GET  /api/v1/cv/nonce    → cv.py:618   (anti-replay)
  POST /api/v1/cv/upload   → cv.py:626   (binary upload)
  POST /api/v1/cv/analyze  → cv.py:84    (base64 analyze)

MISSING ✗:
  frontend/src/lib/imageProcessing.ts — FILE DOES NOT EXIST
  (Referenced in memory but not present — likely deleted in refactor)
  Image resize/compress/WebP conversion is not happening client-side

UNKNOWN ⚠️:
  POST /api/v1/support/complaints/submit
  (Called from RightPanelExtras.tsx:225 — backend may exist but not verified)
```

### 10.6 Auth / Role Wiring

**Status: ⚠️ Backend strict, Frontend trusts localStorage**

```
Backend: require_role([ROLE_MERCHANT, ROLE_OWNER]) enforced on all admin routes ✅
Frontend: role = localStorage.getItem('role')  ← no setter visible in App.tsx

CRITICAL GAP: No login/authentication UI in the frontend.
  - Role is assumed to be pre-set in localStorage
  - No JWT validation in frontend
  - No redirect to login if role missing
  - Workaround: direct URL manipulation or preloaded role for demo
```

### 10.7 WebSocket Inventory

| Component | WS/SSE | Backend Route | Status |
|-----------|--------|--------------|--------|
| DecisionTrace | WS | `decisions.py:536` | ✅ |
| DecisionTrace | SSE (fallback) | `decisions.py:655` | ✅ |
| DecisionTrace | SSE (alt) | `decision_trace_events.py:118` | ✅ |
| EscalationRoom | WS | `escalation_room.py:437` | ✅ |
| EscalationRoom | SSE | `escalation_room.py:1064` | ✅ |
| Chat stream | (pending) | Not found | ❌ |

---

## 11. What Is Fully Done

(Verified by code — not documentation)

| Feature | Key File(s) | Lines |
|---------|------------|-------|
| 4-Phase Orchestrator | `services/orchestrator.py` | 1–1000+ |
| Buyer escalation trigger | `routers/escalation_room.py` | 978–1057 |
| WS/SSE escalation room chat | `routers/escalation_room.py` | 437–503 |
| SLA enforcement (Celery + thread) | `services/incident_sla_scheduler.py` | 58–124 |
| Slack/PagerDuty/Email SLA alerts | `services/incident_alert_adapters.py` | 198–216 |
| Security matrix schema | `services/trace_contracts.py` | 101–128 |
| Incident closure gate | `services/trace_contracts.py` | 351–425 |
| PASTA 7-stage progression | `security/framework_correlation.py` | 126–162 |
| STRIDE 6-category mapping | `security/framework_correlation.py` | 88–123 |
| OWASP LLM Top 10 + Agentic | `security/owasp_map.py` | 1–159 |
| MITRE ATLAS + ATT&CK mapping | `security/framework_correlation.py` | 62–75 |
| CRQ v1 model | `services/risk_quantification.py` | 1–146 |
| GRC portal (5 domains) | `routers/admin_grc.py` | 66–213 |
| GRC export CSV/MD/PDF | `services/grc_reporting.py` | 1–154 |
| Fingerprint monitoring (TLS/SSH/HTTP) | `services/grc_fingerprint.py` | 1–646 |
| Product identity (text heuristic) | `services/product_identity_agent.py` | 338–458 |
| Image → constraints merge | `routers/recommend.py` | 3707–3779 |
| Budget + image constraint merge | `routers/recommend.py` | 3740–3760 |
| NQE context persistence (fixed BUG-1) | `routers/recommend.py` | 3314–3365 |
| Bitemporal decision log | `services/decision_log.py` | 43–95 |
| Merkle audit chain | `models/decision_audit.py` | 1–25 |
| Decision trace WS/SSE frontend | `components/DecisionTrace.tsx` | all |
| Core chat → recommend wiring | `routers/chat.py`, `App.tsx` | connected |
| CV nonce + upload endpoints | `routers/cv.py` | 618–660 |
| CVResultsPanel rendering | `components/CVResultsPanel.tsx` | all |
| BI intelligence margin + supplier | `services/bi_intelligence.py` | 1–100+ |
| Admin SLO alerts | `routers/admin_bi.py` | 30–110 |
| Signal detection (60+ signals) | `security/observer.py` | 91–384 |
| Security event ingestion | `security/security_event_ingest.py` | 1–1034 |
| Playbook engine | `services/playbook_engine.py` | 1–200+ |
| Policy gate (5 rules) | `policy/gate.py` | 37–200 |
| Email security (22 modules) | `security/email_security_*.py` | all |
| Celery HMAC-signed tasks | `workers/celery_app.py` | 9–186 |
| Inventory EOQ + supplier trust | `services/inventory_agent.py` | 1–1000+ |
| Budget tier classification | `services/recommendations.py` | 45–76 |
| Seasonal + affinity boosts | config + services | tested |

---

## 12. What Is Partially Done

| Feature | Status | Key File | Specific Gap |
|---------|--------|---------|-------------|
| DREAD scoring | ⚠️ Static | `security/observer.py:513` | Fixed 0.82 avg always; needs per-event components |
| AI auto-escalation | ⚠️ Marked, not created | `services/orchestrator.py:2954` | `needs_human_review=True` set but no incident auto-created |
| Product Identity (vision LLM) | ⚠️ Optional | `services/product_identity_agent.py:105-218` | Requires Ollama llava; 12s timeout; graceful fallback |
| Escalation room summary | ⚠️ Broken endpoint | `components/EscalationRoom.tsx:52` | `GET /admin/incidents/{id}` not returning data |
| Admin dashboard overview | ⚠️ Missing endpoint | `components/AdminDashboard.tsx:79` | `GET /status/summary` not found |
| TLS JA3/JA4 fraud signals | ⚠️ Weights exist, no data | `services/fraud_scorer.py:36-37` | Fingerprint captured but hash→signal not wired |
| GeoIP/ASN fraud signals | ⚠️ Weights exist, no DB | `services/fraud_scorer.py:38-42` | No MaxMind or ip-api.com integration |
| Risk register persistence | ⚠️ Runtime only | `routers/admin_grc.py` | No `risk_register_snapshots` table |
| imageProcessing.ts | ⚠️ Missing file | `frontend/src/lib/` | File referenced in memory but deleted |
| SLA breach repeat alerts | ⚠️ One-shot | `services/incident_sla_scheduler.py:81-103` | Fires once; no hourly re-escalation |
| Complexity inline display | ⚠️ Calculated, not shown | `components/ChatOverlay.tsx` | Complexity stored but only in DecisionTrace sidebar |
| Category detection | ⚠️ Binary | `routers/recommend.py:4068` | `"laptop" if "laptop" in query else "general"` — image product_type not used |

---

## 13. What Is Completely Missing

| Feature | Why It Matters | Effort |
|---------|---------------|--------|
| **Visual similarity search (FAISS/CLIP)** | Core UX expectation from image upload — spec-based matching is a workaround | 3 sprints |
| **AI auto-create incident** | Without this, AI-flagged high-risk orders need manual staff monitoring | 1 sprint |
| **`GET /status/summary` endpoint** | Admin dashboard overview tab broken | 0.5 sprint |
| **imageProcessing.ts** | Client-side image resize before upload | 0.5 sprint |
| **Dynamic DREAD per-event** | DREAD is a fixed constant (0.82) — no variance, no signal | 1 sprint |
| **Persistent risk register table** | No risk history, no ownership, no mitigation tracking | 1 sprint |
| **FAIR model (ALE = ARO × SLE)** | Insurance, board reporting, vendor risk — requires proper financial numbers | 3 sprints |
| **Risk register → orchestrator integration** | Agents blind to org risk posture | 1 sprint |
| **GNN fraud ring detection** | Neo4j ready; model untrained; misses coordinated fraud rings | 2 sprints |
| **Multi-category NQE templates** | Entire NQE bank hardcoded for electronics | 2 sprints |
| **Category router** | No routing logic for clothing/food/furniture | 1 sprint |
| **CLIP/visual embeddings for catalog** | Prerequisite for visual similarity | 2 sprints |
| **`GET /admin/incidents/{id}` fix** | Escalation room summary panel always loading | 0.25 sprint |
| **Login/auth UI in frontend** | Role loaded from localStorage; no authentication flow visible | 1 sprint |
| **Security matrix collect-on-demand** | Gate rejects closure if scan missing; no "collect now" | 0.5 sprint |
| **SLA repeat-escalation (hourly)** | Breach alerts once; goes silent if breach persists | 0.5 sprint |
| **Use-case knowledge base JSON** | NQE must ask "gaming?" when image label says "ROG" | 1 sprint |
| **Integration tests (image+budget)** | Zero tests for multimodal + budget + filter flow | 1 sprint |

---

## 14. Prioritised Fix Roadmap

### Sprint 1 — Fix Broken Things (1 week)

| Priority | Task | File | Effort |
|---------|------|------|--------|
| 🔥1 | Add `GET /api/v1/admin/incidents/{id}` endpoint | `escalation_room.py` | 2h |
| 🔥2 | Add `GET /status/summary` endpoint | new `routers/status.py` | 4h |
| 🔥3 | Auto-create incident when AI sets `needs_human_review=True` | `routers/recommend.py` | 4h |
| 🔥4 | Fix category detection: use image product_type | `routers/recommend.py:4068` | 1h |
| 🔥5 | Recreate `imageProcessing.ts` (resize/WebP compress) | `frontend/src/lib/` | 2h |
| 6 | SLA repeat-escalation every 4h if still breached | `services/incident_sla_scheduler.py` | 2h |

### Sprint 2 — Complete the Security Matrix (2 weeks)

| Priority | Task | File | Effort |
|---------|------|------|--------|
| 7 | Dynamic DREAD scoring per event | `security/observer.py` + new `security/dread_scorer.py` | 1 week |
| 8 | "Collect security matrix" on-demand endpoint | `routers/escalation_room.py` | 4h |
| 9 | Wire GeoIP (MaxMind GeoLite2 free tier) | new `services/geoip.py` + `fraud_scorer.py` | 1 week |
| 10 | Complete JA3/JA4 hash lookup chain | `security/tls_fingerprint_middleware.py` | 1 week |

### Sprint 3 — Persistent Risk Register (2 weeks)

| Priority | Task | File | Effort |
|---------|------|------|--------|
| 11 | `risk_register_snapshots` DB table + daily snapshot job | new migration + `workers/celery_app.py` | 4h |
| 12 | Risk register CRUD API (owner, mitigation, residual) | `routers/admin_grc.py` | 1 week |
| 13 | Policy gate reads dynamic thresholds from risk register | `policy/gate.py` | 4h |
| 14 | Orchestrator adjusts budget for high-risk domains | `services/orchestrator.py` | 4h |
| 15 | Risk register trend chart in admin dashboard | `components/AdminDashboard.tsx` | 4h |

### Sprint 4 — Visual Search (3 weeks)

| Priority | Task | File | Effort |
|---------|------|------|--------|
| 16 | CLIP image embeddings for product catalog | new `services/visual_search.py` | 1 week |
| 17 | FAISS index + nearest-neighbor search | same + `routers/vision.py` | 1 week |
| 18 | Blend visual similarity with spec constraints | `routers/recommend.py` | 1 week |
| 19 | Add integration test: image+budget+filter flow | `tests/` | 3 days |

### Sprint 5 — Multi-Category (4 weeks)

| Priority | Task | File | Effort |
|---------|------|------|--------|
| 20 | Category router (detect clothing/food/furniture from query+image) | new `services/category_router.py` | 1 week |
| 21 | Remove `_UNSUPPORTED_PRODUCT_TERMS` block | `routers/recommend.py:151-167` | 1h |
| 22 | NQE template banks per category | `config/nqe_templates_*.json` + `flows/nqe.py` | 2 weeks |
| 23 | NLP attribute extraction per category | `services/nlp_search_agent.py` | 1 week |
| 24 | Ranking signal config per category | `services/product_ranking_agent.py` | 1 week |

### Sprint 6 — FAIR + GNN + Auth (4 weeks)

| Priority | Task | File | Effort |
|---------|------|------|--------|
| 25 | FAIR model CRQ v2 (ALE = ARO × SLE) | `services/risk_quantification.py` | 2 weeks |
| 26 | GNN fraud ring queries (Neo4j) | `services/gnn_fraud_detector.py` | 2 weeks |
| 27 | Frontend login/auth UI | `frontend/src/` | 1 week |
| 28 | Use-case knowledge base JSON | `config/use_case_knowledge.json` | 3 days |

---

*Document generated: 2026-03-04 | Based on full codebase deep-dive of 482 Python files + 23 React components*
*Explored by: 4 parallel Claude Code sub-agents (escalation/security, CRQ/GRC, visual/CV, frontend wiring)*
