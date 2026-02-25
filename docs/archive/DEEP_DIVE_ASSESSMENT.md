# ShopSquire Platform — Deep Dive Assessment
**Date:** 2026-02-24  
**Scope:** Full codebase audit — frontend/backend wiring, CV security matrix, agent intelligence, admin/merchant dashboard, readiness gaps, supply chain detection design.

---

## 1. CV Security Matrix: Why Nothing Shows Up

### Root Cause Analysis

When you upload the 6 test images from `dump/test-cv/` (apple-red.jpg, cracked-mac.jpg, lenovo-pro7.webp, mac-unicode-^^fake-5481-1234-4567-0987-oct2030^^.png, macbook-QR.png, macbook.jpg), the system **actually processes them** — QR detection, OCR, image consistency analysis, and security observer **all fire**. The problem is **the data never reaches the Security Matrix UI** due to three layers of wiring issues:

### Issue 1: Security Observer Key Names Don't Match Frontend Expectations (CRITICAL)

The backend `compute_risk()` returns these keys:
| Backend Key | Frontend Expects | Result |
|------------|-----------------|--------|
| `mitre_atlas` | `mitre` or `mitre_details` | **Empty table** |
| `stride_categories` (object) | `stride` (array) | **"None" shown** |
| `owasp_llm_top10` | `owasp_llm` or `owasp` | **"None" shown** |
| `owasp_agentic_top10` | `owasp_agentic` | **"None" shown** |
| `dread_avg` (number) | `dread_avg` | **Works** ✅ |
| `cvss_score` | `cvss_score` | **Works** ✅ |
| `pasta_stage` / `pasta` | `pasta_stage` / `pasta` | **Works** ✅ |

The `normalizeSecurityPayload()` function in `DecisionTrace.tsx` correctly finds the data via `raw.details`, but it doesn't remap the key names. So the rendering code reads `security.stride` → `undefined` → shows "None".

**Fix:** Either rename the backend keys to match the frontend, or add key normalization in `normalizeSecurityPayload()`:
```typescript
// In normalizeSecurityPayload():
if (merged.mitre_atlas && !merged.mitre) merged.mitre = merged.mitre_atlas;
if (merged.stride_categories && !merged.stride) merged.stride = Object.keys(merged.stride_categories);
if (merged.owasp_llm_top10 && !merged.owasp_llm) merged.owasp_llm = merged.owasp_llm_top10;
if (merged.owasp_agentic_top10 && !merged.owasp_agentic) merged.owasp_agentic = merged.owasp_agentic_top10;
```

### Issue 2: `trace_id` Used for Security Matrix Is `decision_id`, Not `case_id`

The `security_scan` trace event in `support_complaints.py` submit endpoint is logged with `trace_id=decision_id` (line ~1870). The frontend resolves `traceId` as `j.decision_trace_id || j.trace_id || j.decision_id || j.case_id`. Since the backend response returns both `decision_id` and `case_id`, the frontend should correctly find it — **but only if the timeline fetch endpoint uses the same ID**.

The `DecisionTrace` component fetches from `/api/v1/trace/{traceId}/timeline`. The backend submit response does include `decision_id`, which is used as the `trace_id` for the `log_trace_event` call. **This should wire correctly** ✅, provided the trace events API returns events keyed by this ID.

### Issue 3: Tesseract Binary Not Installed

```
pytesseract: FAIL - tesseract is not installed or it's not in your PATH
```

The `pytesseract` Python package is installed, but the **Tesseract OCR binary** is not on the system PATH. This means:
- OCR text extraction silently returns `""` for all images
- The filename `mac-unicode-^^fake-5481-1234-4567-0987-oct2030^^.png` which has embedded text overlay — **no OCR text is extracted from it**
- Prompt injection detection via OCR text (`_detect_ocr_prompt_injection()`) has nothing to scan
- The security matrix "CV Prompt Injection" signal only shows when it detects prompt injection in QR payload text (which works for `macbook-QR.png`)

**Fix:** Install Tesseract binary: `choco install tesseract` or download from https://github.com/UB-Mannheim/tesseract/wiki

### What Actually Works

| Component | Status | Notes |
|-----------|--------|-------|
| pyzbar QR decode | ✅ Working | Detects QR in `macbook-QR.png` → `http://en.m.wikipedia.org` |
| OpenCV QR fallback | ✅ Working | Backup decoder available |
| Image sanitization | ✅ Working | MIME validation, EXIF strip, SHA256/phash |
| Image consistency | ✅ Working | Cross-image comparison, mismatch detection |
| QR prompt injection | ✅ Working | Detects injection patterns in QR payload text |
| Security observer | ✅ Working | Produces DREAD, CVSS, severity, risk scores |
| Fraud scoring | ✅ Working | Signal enrichment, composite scoring |
| Forensics (ELA) | ✅ Working | Manipulation detection |
| OCR text extraction | ❌ Broken | Tesseract binary missing |
| Security Matrix display | ❌ Key mismatch | MITRE/STRIDE/OWASP sections always show "None" |

### Verified: QR Code + Prompt Injection Detection Path

Tested with `macbook-QR.png`:
1. `decode_barcodes()` → finds 1 QR code: `http://en.m.wikipedia.org`
2. `_detect_ocr_prompt_injection()` → scans QR data for injection patterns → **no injection in this QR** (it's a clean Wikipedia URL)
3. QR finding tagged into `image_consistency` → reason: `qr_code_detected`, `qr_external_url_detected`
4. `security_observer.analyze_payload()` → produces `severity: critical`, DREAD scores, OWASP LLM Top 10 tags
5. `security_scan` trace event emitted ✅
6. **But** frontend `DecisionTrace` reads wrong keys → user sees empty matrix

---

## 2. Frontend–Backend Wiring Gaps

### The Two Frontend Systems Issue

There are **three** frontend codebases:

| Frontend | Location | Status |
|----------|----------|--------|
| **Storefront React** | `frontend/src/` | Active, customer-facing |
| **Legacy Admin** | `src/frontend/admin/` | 100% stubbed — hardcoded mock data, zero API calls |
| **Admin React SPA** | `src/frontend/admin-react/src/` | Full featured, 22 components, real API wiring |

**Risk:** If someone navigates to the legacy admin panel instead of the React admin SPA, they see fake data and think nothing works.

### Storefront Wiring Gaps

| Gap | Description | Severity |
|-----|-------------|----------|
| Submit path response mapping | Frontend reads `j.analysis`, `j.cv_tiered_analysis`, `j.evidence_tags` — backend `/support/complaints/submit` **returns all these** ✅ | OK |
| Analyze path missing `evidence_tags` | `cvAnalyze()` response hardcodes `evidence_tags: []` instead of reading from backend | HIGH |
| `qr_prompt_injection` not passed in submit | Submit path doesn't extract `j.qr_prompt_injection` (though the backend does return `qr_codes` in evidence) | MEDIUM |
| Security Matrix key mismatch | See §1 above | CRITICAL |

### Admin React SPA Wiring

The Admin React SPA (`src/frontend/admin-react/`) has **solid API wiring** via `api.ts` (~800+ lines). Key findings:

| Component | Wiring Status |
|-----------|--------------|
| Overview | ✅ Real API calls → `/healthz`, `/admin/overview`, `/admin/live-feed` |
| Decisions | ✅ Real → queries decision log entries |
| Security | ✅ Real → queries security events |
| MerchantBIPro | ⚠️ Real APIs + **deterministic fallback** — silently shows fake data when DB is empty |
| GrafanaDashboards | ⚠️ Real proxy → requires running Grafana instance |
| SupplyChainSim | ✅ Real → SSE streaming from supply chain sim harness |
| EmailXdr | ✅ Real → email security incident investigation |
| Compliance/GRC | ✅ Real → compliance reports and risk register |

---

## 3. Agent Intelligence & Cost Optimization

### Current Architecture

The platform has a sophisticated **3-tier routing system** that already pre-filters before LLM:

```
Tier 0: Rule/Cache Match (confidence ≥ 0.95) → NO LLM CALL → $0
Tier 1: Standard (default) → Single LLM pass → $
Tier 2: Complex (risk ≥ 0.5, amount ≥ $250, low confidence, multi-turn) → Interleaved LLM → $$
```

**What's already rule-based (no LLM cost):**
- 11 intent regex patterns (product search, pricing, comparison, order status, return, support, stock, restock, bulk, urgent, pre-order)
- Semantic cache with SHA256 keys
- Binary classification for damage detection
- Image forensics (ELA, copy-move, splice detection)
- Fraud scoring with signal enrichment
- QR/barcode decoding
- Security observer (24 regex-based signal categories)
- Trust routing (progressive access control)
- Policy gate (deterministic conflict resolution)

### Cost Optimization Opportunities

#### A. Expand Tier 0 Rule Coverage (HIGH IMPACT, LOW EFFORT)

The current 11 intent patterns cover basic queries. Add these deterministic handlers:

```
1. FAQ/Policy queries — match "what is your return policy", "shipping time", "warranty" → serve from faq_kb.json directly, skip LLM
2. Simple price lookups — match "how much is X", "price of X" → direct DB query
3. Order tracking — match "where is my order #" → direct API call to order status
4. Stock availability — match "is X in stock" → direct inventory check
5. Cart operations — match "add X to cart", "remove X" → direct cart mutation
```

Each of these currently falls to Tier 1 (single LLM call) but can be answered with zero model inference.

#### B. TF-IDF + EWMA for Ambiguous Signal Triage (NEW)

For signals that don't clearly match Tier 0 rules:

```python
# Proposed: Lightweight TF-IDF classifier before LLM
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier

class IntentClassifierLocal:
    """Sub-millisecond intent classification using TF-IDF + SGD.
    Falls back to LLM only when confidence < threshold."""
    
    def classify(self, text: str) -> tuple[str, float]:
        vec = self.vectorizer.transform([text])
        proba = self.model.predict_proba(vec)[0]
        intent = self.labels[proba.argmax()]
        confidence = proba.max()
        return intent, confidence  # If conf < 0.7, escalate to Tier 1
```

**EWMA (Exponentially Weighted Moving Average)** for anomaly detection is already implemented in `analytics/anomaly.py` but not wired into the real-time routing path. Wire it as a pre-screen:

```python
# Before LLM: check if the user's session behavior is anomalous
ewma = compute_ewma_score(session_metrics)
if ewma > threshold:
    route = "security_review"  # Skip LLM, go to human
```

#### C. Isolation Forest for Ambiguous Signals (ALREADY EXISTS)

`agent_behavior_anomaly.py` has IsolationForest but it's used for **agent** behavior, not **user** behavior. Extend to user session anomaly:

```python
# Already have:
from src.app.services.agent_behavior_anomaly import AgentBehaviorAnomalyDetector

# Add: User session anomaly detector using same pattern
class UserSessionAnomalyDetector:
    """Uses IsolationForest on user session features to flag anomalous sessions
    BEFORE invoking LLM — prevents costly inference on bot/abuse traffic."""
    features = ["queries_per_minute", "cart_abandonment_rate", "repeat_query_ratio"]
```

#### D. Rule Engine Underutilized

The DB-backed `rule_definitions` table supports expressions but only regex matching is implemented. The `_evaluate_expression()` function in `rule_store.py` handles `>`, `<`, `==`, `contains` operators. Populate with rules like:

```json
{
  "domain": "intent",
  "condition": "confidence > 0.95",
  "action": "auto_respond",
  "priority": 1
}
```

### Cost Savings Estimate

| Change | Queries Diverted from LLM | Est. Monthly Savings |
|--------|--------------------------|---------------------|
| FAQ expansion to Tier 0 | ~30% of support queries | $$ |
| TF-IDF intent pre-classifier | ~15% more Tier 0 hits | $$ |
| Session anomaly pre-screen | ~5% abuse/bot traffic | $ |
| EWMA threshold gating | ~3% anomalous sessions | $ |
| **Total** | **~50%+ LLM call reduction** | **Significant** |

---

## 4. Merchant/Admin Backend & Graphs

### PowerBI Integration: ✅ Working

| Endpoint | Status | Format |
|----------|--------|--------|
| `GET /admin/powerbi/dataset` | ✅ Real | JSON (up to 500 rows from 3 tables) |
| `GET /admin/powerbi/export.csv` | ✅ Real | Streaming CSV with date/status/severity filters |
| `GET /admin/powerbi/export.ndjson` | ✅ Real | Streaming NDJSON for BI tools |
| `GET /admin/powerbi/export.zip` | ✅ Real | Zipped multi-table CSVs |
| `GET /admin/powerbi/export/{table}.csv` | ✅ Real | Per-table CSV (decisions/orders/security) |

All use real SQL queries with parameterized filters and OIDC auth.

### BI Timeseries: ✅ Working

`GET /admin/bi/transactions/timeseries` — full implementation with:
- SQLite + PostgreSQL dual-dialect
- TimescaleDB `time_bucket()` and continuous aggregate support
- Day/month granularity
- Pydantic-typed response

### Real-Time Graphs Assessment

| Graph System | Status | Issues |
|-------------|--------|--------|
| **MerchantBIPro (SVG charts)** | ⚠️ Partial | Custom SVG line/bar charts work, but **no periodic polling** — loads once on mount. Falls back to `buildDeterministicTransactionDemo()` synthetic data when API returns empty. |
| **Grafana embeds** | ⚠️ Depends on Grafana | 6 dashboards referenced by UID. `/merchant/bi` has `refresh=10s` in iframe URLs. Requires running Grafana + provisioned dashboards. |
| **Admin analytics** | ⚠️ Hybrid | Inline HTML fallback with Grafana iframes + 3 JS cards fetching from fraud/geo APIs. |
| **Context graph** | ✅ Real | `/api/v1/graph/context` returns node-edge structure from real DB queries. |

### Playwright Verification: ⚠️ Minimal

| Test | What It Verifies | Graph Testing |
|------|-----------------|---------------|
| `test_admin_dashboards.py` | Text presence on admin page | ❌ No chart rendering |
| `test_decision_trace_e2e.py` | Decision trace UI opens | ❌ No security matrix checks |
| `test_trace_sse_policy_gate.py` | SSE stream returns events | ✅ Tests real-time streaming |
| `test_storefront_chat_with_admin_flow.py` | CV → escalation flow | ❌ No graph checks |

**No Playwright test verifies that BI charts actually render data.** The `test_admin_dashboards` test only confirms the dashboard HTML loads — not that SVG charts contain plotted data points.

---

## 5. Platform Readiness — Showcase Blockers

### Blockers (Must Fix)

| # | Issue | Impact | Effort |
|---|-------|--------|--------|
| 1 | **Security Matrix key mismatch** — MITRE/STRIDE/OWASP always show "None" | Demo-breaking for security showcase | 30 min |
| 2 | **Tesseract binary not installed** — OCR/text overlay detection disabled | Text-based prompt injection invisible | 10 min |
| 3 | **Legacy admin has zero API calls** — visitors see fake data | Confusing for admin demo | Remove or redirect |
| 4 | **MerchantBIPro synthetic fallback silently masks empty DB** — charts look real but data is fake | Misleading BI showcase | Add "Demo Data" badge |
| 5 | **No periodic graph refresh** — BI charts load once, never update | "Real-time" claim doesn't hold | Add `setInterval` polling |

### High Priority

| # | Issue | Impact |
|---|-------|--------|
| 6 | Grafana dependency for 6+ dashboards — requires running Grafana stack | Admin dashboard partially broken without Docker |
| 7 | Analyze path hardcodes `evidence_tags: []` | CVResultsPanel shows no tags after analyze |
| 8 | `AnalyticsEventSink.record()` is a no-op | Analytics enrichment silently drops data |
| 9 | `security_observer_timeseries` table may not exist | EWMA/IsolationForest analytics return empty |
| 10 | Admin React SPA build→deploy path unclear | `static/admin/index.html` may not exist |

### Nice to Have

| # | Issue |
|---|-------|
| 11 | Add Playwright test for security matrix rendering |
| 12 | Add Playwright test for MerchantBIPro chart rendering with seeded data |
| 13 | Wire EWMA anomaly scores into the DecisionTrace panel |
| 14 | Add WebSocket/SSE push for BI chart updates |

---

## 6. Supply Chain Attack Detection Lab — Design

### Current State

You already have a solid foundation:

**Existing capabilities:**
- 8 supply chain attack scenarios (Magecart, watering hole, CI/CD poisoning, C2 beaconing, LOLBin, macro delivery, dependency confusion, firmware implant)
- Full simulation harness with 6-agent chain (intake → IOC extractor → security observer → threat intel → policy engine → escalation)
- SSE streaming for real-time agent step visualization
- Celery swarm for parallel scenario execution
- Real-time 3σ anomaly detection for provider metrics
- Admin React `SupplyChainSim` component with full UI

**What's missing for a full "Supply Chain Security Lab" (analogous to Email Security Lab):**

### Proposed Architecture

Extend the existing Email Security Lab pattern to create a unified "Threat Detection Lab":

```
┌─────────────────────────────────────────────────────────────────┐
│                    THREAT DETECTION LAB                          │
├──────────────────┬──────────────────┬───────────────────────────┤
│  Email Security  │  Supply Chain    │  Endpoint/Network         │
│  Lab (Existing)  │  Lab (Extend)    │  Detection (New)          │
├──────────────────┼──────────────────┼───────────────────────────┤
│ BEC simulation   │ Magecart inject  │ DNS anomaly detection     │
│ Phishing detect  │ CI/CD poisoning  │ TLS cert anomalies        │
│ DMARC/SPF/DKIM   │ Dep. confusion   │ Beacon periodicity        │
│ Canary tokens    │ C2 beaconing     │ Process tree analysis     │
│ Reply hijack     │ LOLBin abuse     │ Network flow baseline     │
│ IOC enrichment   │ Firmware implant │ Lateral movement detect   │
└──────────────────┴──────────────────┴───────────────────────────┘
                          │
                    ┌─────┴──────┐
                    │  Unified   │
                    │  Detection │
                    │  Engine    │
                    └─────┬──────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
         TF-IDF       EWMA      IsolationForest
         Signal      Baseline    Anomaly
         Classifier  Deviation   Detector
              │           │           │
              └───────────┼───────────┘
                          │
                    ┌─────┴──────┐
                    │  Playbook  │
                    │  Selection │
                    │  Engine    │
                    └─────┬──────┘
                          │
            ┌─────────────┼─────────────┐
            │             │             │
        Containment   Escalation    Evidence
        (IP block,    (P0→Slack,    (Bundle,
         rate limit,   P1→Jira)     Snapshot,
         session kill)              SIEM handoff)
```

### Implementation Plan — Reuse Existing Patterns

**Option A: Extend the Email Security Lab link**

Add a new tab/section to the existing admin email security console at `/admin/email-security`:

```python
# New router: src/app/routers/admin_threat_lab.py
@router.get("/scenarios")
async def list_threat_scenarios():
    """Unified catalog: email (6) + supply chain (8) + endpoint (new)"""
    
@router.post("/simulate/{scenario_id}")
async def simulate_threat(scenario_id: str):
    """Run any scenario through the unified detection engine"""

@router.get("/simulate/{scenario_id}/stream")  
async def stream_simulation(scenario_id: str):
    """SSE stream of agent thinking steps"""
```

**Option B: Use TF-IDF + EWMA + Isolation Forest for Signal Triage**

Instead of becoming an XDR, use lightweight ML to highlight ambiguous signals:

```python
class ThreatSignalClassifier:
    """Lightweight signal triage — NOT an XDR, just a smart filter."""
    
    def __init__(self):
        # TF-IDF for text-based signal classification
        self.tfidf = TfidfVectorizer(max_features=500)
        # EWMA for baseline deviation detection
        self.ewma_window = 3600  # 1 hour
        # IsolationForest for multi-dimensional anomaly scoring
        self.iso_forest = IsolationForest(contamination=0.05)
    
    def classify_signal(self, signal: dict) -> dict:
        """
        Returns:
            - signal_type: 'supply_chain' | 'endpoint' | 'network' | 'email'
            - confidence: float
            - anomaly_score: float from IsolationForest
            - baseline_deviation: float from EWMA
            - playbook_id: suggested playbook based on signal+tags
        """
```

**Option C: Security Tag → Playbook Routing (Most Pragmatic)**

Use the existing playbook engine with tag-based routing — no new ML needed:

```json
// config/security/threat_lab_playbooks.json
{
  "tag_map": {
    "dns_anomaly+beacon_detected": "PB-NET-01",
    "tls_cert_mismatch": "PB-NET-02",
    "supply_chain+dependency_confusion": "PB-SC-07",
    "lateral_movement_detected": "PB-EPT-01"
  },
  "signal_map": {
    "supply_chain": {"playbook_id": "PB-SC-GENERIC", "trigger": "any"},
    "c2_beacon": {"playbook_id": "PB-NET-C2", "trigger": "any"},
    "process_anomaly": {"playbook_id": "PB-EPT-PROCESS", "trigger": "any"}
  }
}
```

### Recommended Approach: Option C + lightweight EWMA/TF-IDF

1. **Use existing playbook engine** — no new ML infrastructure
2. **Add 4-6 endpoint/network scenarios** to the existing supply chain sim harness
3. **Wire EWMA baseline deviation** (already in `analytics/anomaly.py`) as a signal amplifier
4. **Add TF-IDF** only for text-based signal classification of unstructured logs
5. **IsolationForest** only for multi-dimensional anomaly scoring on provider metrics
6. **Keep it NOT an XDR** — it's a "smart playbook router with statistical anomaly detection"

### New Scenarios to Add

| ID | Name | Type | Detection Method |
|----|------|------|-----------------|
| NET-01 | DNS Tunneling Detection | Network | EWMA on DNS query volume + payload size |
| NET-02 | TLS Certificate Anomaly | Network | Baseline comparison on cert attributes |
| NET-03 | Beacon Periodicity Detection | Network | FFT/autocorrelation on connection intervals |
| EPT-01 | Process Tree Anomaly | Endpoint | IsolationForest on process spawn patterns |
| EPT-02 | File Integrity Violation | Endpoint | Hash comparison against known-good baseline |
| SC-09 | Registry/Config Poisoning | Supply Chain | TF-IDF classification of config changes |

---

## 7. Agent Architecture Improvements Summary

### Current Agent Chain (per request)

```
Input → Guardrails → Security Observer → Agent Guardrail Gate 
→ Tier Router → [Cache/Rules/LLM] → AB Variant → Agent Execution
→ Policy Gate → Incident Ticketing → Response
```

### Recommended Improvements

1. **Add TF-IDF intent pre-classifier before Tier Router** — diverts 15-30% more queries to Tier 0 at sub-ms latency
2. **Wire EWMA session anomaly** into the intake gate — blocks abuse before LLM invocation
3. **Expand FAQ coverage in Tier 0** — the `faq_kb.json` exists but isn't deeply wired into the rule engine
4. **Add response caching at the orchestrator level** — cache full orchestration results (not just LLM outputs) for identical queries
5. **Use `tier_router_learned.py` XGBoost classifier** — it exists but isn't the default; enable it via feature flag to learn optimal routing from historical data
6. **Monitor Tier distribution** — add a dashboard panel showing Tier 0/1/2 distribution over time to track cost optimization progress

### Agent Behavior Anomaly (Already Exists, Underutilized)

`AgentBehaviorAnomalyDetector` in `agent_behavior_anomaly.py` uses IsolationForest on:
- Recommendation call count
- Parse failure count  
- Hallucination count
- Review queue depth
- Latency

This is great for detecting rogue agents but isn't wired into the main request pipeline. Wire it into the orchestrator for continuous monitoring.

---

## 8. Quick Fix Priority Order

For a showcase-ready demo, fix in this order:

### Fix 1: Security Matrix Key Normalization (30 min)
In `frontend/src/components/DecisionTrace.tsx`, update `normalizeSecurityPayload()` to remap backend keys.

### Fix 2: Install Tesseract (10 min)
```powershell
choco install tesseract
# Or download from https://github.com/UB-Mannheim/tesseract/wiki
```

### Fix 3: Analyze Path Evidence Tags (15 min)
In `frontend/src/components/RightPanelExtras.tsx`, read `(resp as any)?.evidence_tags` instead of hardcoding `[]`.

### Fix 4: Add "Demo Data" Indicator (15 min)
In `MerchantBIPro`, show a visible badge when `buildDeterministicTransactionDemo()` is used.

### Fix 5: Add BI Chart Polling (20 min)
In `MerchantBIPro`, add `setInterval(fetchData, 30000)` for 30s refresh.

### Fix 6: Remove/Redirect Legacy Admin (10 min)
Replace `src/frontend/admin/index.html` with a redirect to the React admin SPA.

---

## Appendix: Full File Map

### Backend Routes (Verified Real)
| Router | Endpoints | Status |
|--------|-----------|--------|
| `cv.py` | `/cv/analyze`, `/cv/upload`, `/cv/nonce` | Real |
| `support_complaints.py` | `/support/complaints/submit`, `/submit-guest` | Real |
| `admin.py` | PowerBI exports, DB ops, flags, keys | Real |
| `admin_bi.py` | BI timeseries | Real |
| `admin_analytics.py` | Dashboard HTML | Real (inline fallback) |
| `admin_drift.py` | Drift monitoring | Real |
| `admin_supply_chain_sim.py` | Supply chain sim | Real |
| `admin_email_security.py` | Email security lab | Real (22 endpoints) |
| `graph.py` | Context graph | Real |
| `merchant_dashboard.py` | Merchant BI | Real |
| `admin_grafana_proxy.py` | Grafana reverse proxy | Real (needs Grafana) |

### Frontend Components (Storefront)
| Component | API Endpoint | Wiring Status |
|-----------|-------------|---------------|
| `CameraButton` | triggers file capture | ✅ |
| `RightPanelExtras` | `/support/complaints/submit`, `/cv/analyze` | ⚠️ Evidence tags gap |
| `CVResultsPanel` | reads `CVSubmitResult` | ✅ |
| `DecisionTrace` | `/decisions/{id}`, `/trace/{id}/timeline` | ⚠️ Key mismatch |
| `SecurityDemo` | `/security/demo/events` | ✅ |
| `EscalationRoom` | SSE/WebSocket room stream | ✅ |
| `ChatOverlay` | `/orchestrate` | ✅ |

### Frontend Components (Admin React SPA)
| Component | Wiring | Notes |
|-----------|--------|-------|
| MerchantBIPro | ✅ Real + fallback | Custom SVG charts |
| SupplyChainSim | ✅ Real SSE | Full sim UI |
| EmailXdr | ✅ Real | Investigation workflow |
| Overview | ✅ Real | Live feed |
| GrafanaDashboards | ⚠️ Needs Grafana | 8 dashboard UIDs |
