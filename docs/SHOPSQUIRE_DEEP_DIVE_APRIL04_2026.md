# ShopSquire Platform Deep Dive — April 4, 2026

> **Scope:** Full platform audit covering shopfront (5173), email security lab (8080), backend services, security agents.
> **What this answers:** What works vs. stubbed, production vs. enterprise grade gaps, UI/UX framework theatre, security agent improvements.

---

## 1. How the Platform Actually Works

### 1.1 Shopfront Flow (port 5173)

```
User types query (or uploads image)
    │
    ▼
App.tsx — PII scan (Luhn/SSN/bank regex, client-side)
    │    — Device lane: Windows / MacBook / Tablet detection
    │    — Session read from sessionStorage
    ▼
POST /api/v1/chat  ──→  chat.py (91 KB) ──→  recommend.py (552 KB, 11,922 lines)
    │
    ├── LLM complexity scoring (llm_provider.py)
    │       0-4 → llama3.3:8b (small)
    │       5-7 → mixtral:8x7b (medium)
    │       8-10 → larger model
    │
    ├── Orchestrator (orchestrator.py, 3,846 lines)
    │       EXPLORE → EVALUATE → PLAN → ACTION phases
    │       Memory: Redis session:{uid}:summary / kv_state / recent_retrieval
    │       Policy gates, playbook execution, RAGAS hooks
    │
    ├── NQE (flows/nqe.py, 44 KB)
    │       Generates follow-up questions
    │       ⚠ BUG-1: previously_asked_ids NOT loaded from Redis → context loss
    │
    ├── Fraud scoring (fraud_scorer.py, 28 KB, 26+ signals)
    │
    ├── Product ranking (recommendations.py 89 KB: ALS + bandit)
    │
    └── Decision log → bitemporal DB record (valid_from/to + system_from/to)
         + immutable hash chain (audit_chain.py)

    ▼
Response: {products[], trace_id, nqe_questions[], security_signals}
    │
    ▼
Frontend renders:
    ProductGrid (grid/list/detailed modes)
    ChatOverlay with NQE buttons
    If image uploaded → ImageRecommendPanel + CVResultsPanel (trust levels)
    "Why this?" button → opens DecisionTrace.tsx
        Connects: WS wss://host/api/v1/decisions/{traceId}/events/ws
        Fallback: SSE /api/v1/decisions/{traceId}/events/stream
        Fallback: polling /api/v1/decisions/{traceId} (50ms)
        Tabs: events / summary / why / intent / multimodal / complexity /
              memory / security / audit / raw
```

**WebSocket path confirmed wired end-to-end:**
Frontend: `DecisionTrace.tsx` tries `/api/v1/decisions/{traceId}/ws` first, then `/events/ws`
Backend: `decisions.py:619` and `decision_trace_events.py:276` both expose `/{trace_id}/events/ws`
⚠ **Path mismatch:** frontend's first attempt uses `/decisions/{id}/ws`, backend only serves `/decisions/{id}/events/ws` — the fallback SSE path saves it, but WS never connects on first try. Fix: update the WS URL in `DecisionTrace.tsx` to include `/events/ws`.

---

### 1.2 Email Security Lab Flow (port 8080)

```
Browser → GET /merchant/email-lab
    │
    ▼
merchant_dashboard.py:1156 (server-side HTML, inline in Python — NO templates dir)
    Renders: ~1,800 lines of inline HTML+JS
    Buttons wired via inline JS → fetch() calls to port 8080 API

    ├── [Analyze] → POST /api/v1/email_security/evaluate
    │       ↓
    │   email_security.py (4,958 lines, REAL)
    │       DMARC/SPF/DKIM (dns_verify.py, live DNS)
    │       BIMI logo verification (bimi_verifier.py, DNS + HTTPS HEAD + homoglyph)
    │       Attachment intel (email_attachment_intel.py, 23 KB)
    │       Header forensics (email_header_forensics.py)
    │       URL click protect (email_url_click_protect.py)
    │       BEC kill chain (bec_kill_chain.py)
    │       Sender trust (email_sender_trust.py)
    │       Verdict → EmailEvaluateResponse (JSON)
    │
    ├── [Image in email] → GAN detector (6 signals: FFT, histogram, texture, EXIF, JPEG Q-table, diffusion)
    │                    → Steg detector (8 methods: LSB entropy, chi-square, SPA, JPEG DCT, F5, SRM, cross-channel)
    │                    → Adversarial image detector
    │
    ├── [Escalate] → POST /api/v1/incidents/escalate
    │       Creates incident record + optional Jira/ServiceNow ticket
    │       ⚠ Escalation room WebSocket wired (escalation_room.py:681) but full workflow broken
    │
    ├── [Demo] → loads preset payload (inline JS)
    │
    ├── [Threat Hunt] → GET /merchant/email-lab/threat-hunt?ctx=TOKEN
    │       Separate HTML page (merchant_dashboard.py:810)
    │
    └── [Agents SSE] → simulated SSE stream (merchant_dashboard.py inline JS)

Auth: expects OWNER_API_KEY in env or localStorage 'ss_owner_key'
⚠ BUG-8: mismatch shows as "SECURITY REVIEW — ERROR" (401/403 display artifact)
Fix: localStorage.setItem('ss_owner_key', '<key>') in browser console
```

---

## 2. What Works vs. What Is Stubbed

### ✅ FULLY WIRED AND REAL

| Component | Location | Evidence |
|-----------|----------|----------|
| Chat → recommend pipeline | `routers/recommend.py` 552KB, 11,922 lines | Core path end-to-end |
| Decision trace (WS/SSE/poll) | `routers/decisions.py:619`, `decision_trace_events.py:276` | 3-tier fallback confirmed |
| Orchestrator (4-phase) | `services/orchestrator.py` 3,846 lines | EXPLORE→EVALUATE→PLAN→ACTION |
| NQE follow-up questions | `flows/nqe.py` 44 KB | Real game/software detection, use-case KB |
| Fraud scoring | `services/fraud_scorer.py` 28 KB | 26+ signals, GNN-based |
| Email security engine | `security/email_security.py` 4,958 lines | Full BEC/phishing/spoofing |
| BIMI verifier | `security/bimi_verifier.py` | Live DNS + SVG validation + homoglyph |
| GAN image detector | `security/gan_image_detector.py` | 6-signal composite (FFT/histogram/texture/EXIF/JPEG/diffusion) |
| Steg detector | `security/steg_detector.py` 839 lines | 8 independent methods |
| DMARC/SPF/DKIM | `security/email_dns_verify.py` | Live DNS lookups |
| Bitemporal audit trail | `models/db.py` decision_logs table | valid_from/to + system_from/to + hash chain |
| Playbook engine | `services/playbook_engine.py` 72 KB | typed action execution |
| Cart + upsell | `routers/cart.py` + `services/checkout_upsell.py` 42 KB | Bundle pricing, ALS upsell |
| Auth / RBAC | `security/auth.py` 40 KB | JWT httpOnly, multi-tenant, role gates |
| CSRF protection | `security/csrf_middleware.py` + `lib/csrf.ts` | Double-submit cookie pattern |
| Supply chain governance | `security/supplier_governance_store.py` 32 KB | KYV registry, vendor baselines |
| Image upload → CV analysis | `routers/cv.py` 67 KB | OCR, damage, forensics |
| Product ranking | `services/recommendations.py` 89 KB | ALS collaborative filtering + bandit |
| Escalation room (WS) | `routers/escalation_room.py:681` | WS wired, workflow partially broken |
| Framework correlation | `security/framework_correlation.py` 63 KB | MITRE/OWASP/STRIDE/PASTA |
| Security event ingest | `security/security_event_ingest.py` 35 KB | DB-backed pipeline |
| Inventory agent | `services/inventory_agent.py` 69 KB | Supply chain, order matching |

### ⚠ PARTIALLY WIRED / HAS KNOWN BUGS

| Component | Bug | Fix Location |
|-----------|-----|-------------|
| NQE context (BUG-1) | `previously_asked_ids` never loaded from Redis | `recommend.py:~5020` |
| Multimodal scoring (BUG-2) | Visual+text routes to prefer_small | `llm_provider.py:142` +2 signal |
| CV runtime deps (BUG-3) | pyzbar/pytesseract/paddleocr/imagehash absent from Docker | `docker-compose.yml` + Dockerfile |
| Shortlist on zero-results (BUG-4) | `last_shortlist_skus` overwritten with `[]` | `recommend.py:~8600` |
| NQE fires on explain queries (BUG-5) | Pattern too narrow | `recommend.py:~5193` |
| LLM summary (BUG-6) | Doesn't answer yes/no questions directly | `recommend.py:2865` prompt rewrite |
| Budget answer (BUG-7) | Returns "" if no brand detected | `recommend.py:2995` add generic branch |
| Email lab auth (BUG-8) | 401/403 shown as "SECURITY REVIEW — ERROR" | `.env` OWNER_API_KEY or localStorage |
| Decision trace WS URL | Frontend tries `/decisions/{id}/ws`, backend only has `/decisions/{id}/events/ws` | `DecisionTrace.tsx` WS URL string |
| Security block mode | `_block_response()` defaults to HTTP 200 not 403 | Set `SECURITY_BLOCK_MODE=403` env |
| Audit chain secret | `AUDIT_CHAIN_SECRET not set` — insecure dev placeholder | Set in `.env` before production |
| CV Tier 2 pipeline | `cv_tiered.py:35` notes "placeholder: BasicCVTriage with extra metadata" | `services/cv_tiered.py` |
| Escalation room workflow | WS wired but incident resolution flow broken | `routers/escalation_room.py` |

### ❌ STUBBED (NotImplementedError or no-op)

| Component | File | Status |
|-----------|------|--------|
| Voice ASR | `services/voice_asr.py:22` | `raise NotImplementedError` — browser STT only |
| Voice TTS | `services/voice_tts.py:20` | `raise NotImplementedError` |
| Email outbound (SendGrid) | `services/email_sendgrid.py` | Stub |
| ERP/EDI order sync | `services/erp_edi.py:113` | Falls back to `_load_stub()` |
| Shipping providers | `services/shipping_providers.py:9` | `raise NotImplementedError` |
| NLP contract analysis | `services/nlp_contract.py:29` | `raise NotImplementedError` |
| Graph retrieval | `services/graph_retrieval.py:25,28` | `raise NotImplementedError` |
| PayPal / Revolut / GooglePay / Afterpay | `routers/payments.py:94` | disabled/not_ready — Stripe only |
| CV object detector | `services/cv_object_detector.py` | Minimal implementation |
| S3 storage | `services/storage_s3.py:9` | No-op stub when `AWS_*` not configured |
| Neo4j / GNN fraud rings | Not in docker-compose | GNN code exists, graph DB absent |

---

## 3. Production Grade vs. Enterprise Grade

### Definitions

**Production Grade** = Handles real traffic reliably. Core paths work without silent failures. Errors are caught and reported. Security basics enforced. No known critical bugs in hot paths.

**Enterprise Grade** = Multi-tenant isolation proven. SLAs enforced by code. Full compliance mapping (PCI/GDPR/ISO27001/AI Act). Observability complete (traces → SIEM). Auth hardened (MFA, secret rotation, mTLS). Zero critical CVEs in runtime deps. Disaster recovery tested.

---

### 3.1 Current State: **Late Prototype / Pre-Production**

The platform has enterprise-grade _architecture_ (bitemporal audit, framework correlation, playbook engine, RBAC, CSRF, mTLS stubs) but pre-production _runtime_ (8 known bugs, fail-open defaults, missing Docker deps, dev secret placeholders).

---

### 3.2 Gaps to Production Grade

These are blockers — things that will cause silent failures or security holes in a real environment.

#### P0 — Must fix before any real user traffic

| Gap | What Breaks | Fix |
|-----|-------------|-----|
| **BUG-3: CV Docker deps** | All CV silent-fails. QR/OCR/steg/hash never run. Security matrix events empty. | Add to `Dockerfile`: `pyzbar libzbar0 tesseract-ocr paddleocr imagehash` |
| **BUG-1: NQE context loss** | NQE asks the same questions on every turn. Users click back off. | Load `nqe_asked_ids` from Redis kv_state at `recommend.py:~5020`, inject into `NQEInput.previously_asked_ids` |
| **SECURITY_BLOCK_MODE=200** | Security block returns HTTP 200 with `"blocked": true`. Clients may not check JSON body. OWASP LLM Top 10 LLM08. | Set `SECURITY_BLOCK_MODE=403` in `.env.production` |
| **AUDIT_CHAIN_SECRET unset** | Audit hash chain uses insecure dev placeholder. Compliance audit fails. | Generate `openssl rand -hex 32` → `AUDIT_CHAIN_SECRET=<value>` in secrets manager |
| **BUG-8: Email lab auth** | "SECURITY REVIEW — ERROR" blocks every email analysis. Merchants can't use it. | Ensure `OWNER_API_KEY` in backend env matches value in `localStorage.getItem('ss_owner_key')` at 8080 |
| **DecisionTrace WS URL mismatch** | WS never connects. SSE fallback works but adds latency. Trace drops in prod. | `DecisionTrace.tsx`: change first WS attempt from `…/decisions/{id}/ws` to `…/decisions/{id}/events/ws` |

#### P1 — Fix before launch

| Gap | Impact | Fix |
|-----|--------|-----|
| **BUG-4: Shortlist erased** | Zero-result turn wipes previous shortlist. Users have to restart search. | `recommend.py:~8600`: only overwrite `last_shortlist_skus` when `len(new_results) > 0` |
| **BUG-6: LLM summary doesn't answer** | "Is $1800 enough for gaming?" returns a product list, no yes/no. High churn. | `recommend.py:2865`: rewrite prompt to lead with direct answer, then products |
| **BUG-7: Budget with no brand** | `_build_brand_budget_answer()` returns `""` when no brand in query. Silent empty. | `recommend.py:2995`: add generic budget branch for brandless queries |
| **BUG-2: Multimodal under-scoring** | Image+text routes to `llama3.3:8b`. Poor visual reasoning. | `llm_provider.py:142`: +2 score for visual_similarity + synthesis intent flags |
| **BUG-5: NQE on explain queries** | NQE fires on "tell me more about X" turns. Confuses users. | `recommend.py:~5193`: broaden `_is_followup_explain_query()` regex patterns |
| **Stripe-only payments** | PayPal/Revolut/Afterpay stubs will throw 500 if accidentally enabled. | Document payment scope. Add explicit `feature_flags.json` guards for disabled providers. |

#### P2 — Production hardening

| Gap | Fix |
|-----|-----|
| No MFA enforcement | `security/auth.py`: add `require_mfa: bool` field to RBAC role definitions |
| S3 storage is no-op | Set `AWS_S3_BUCKET` / `AWS_ACCESS_KEY_ID` in production; add startup health check |
| CV Tier 2 is placeholder | `services/cv_tiered.py:35`: wire real vision LLM (Ollama LLaVA) for tier 2 |
| ERP/EDI stub fallback | Set `ERP_EDI_STUB_PATH` guard to fail loudly in production |
| No rate-limit per-tenant | `security/rate_limit.py`: add tenant_id dimension to token bucket key |

---

### 3.3 Gaps to Enterprise Grade

These require architectural work beyond bug fixes.

#### Architecture Gaps

| Gap | Current State | What's Needed |
|-----|---------------|---------------|
| **Multi-tenant data isolation** | PostgreSQL schema search_path set in config but not enforced per-request | Row-level security (RLS) policies on all tables + middleware that sets `SET ROLE tenant_{id}` per request |
| **GNN fraud ring detection** | `gnn_fraud_detector.py` real, but Neo4j absent from docker-compose | Add `neo4j:5` service to docker-compose + `FRAUD_GRAPH_NEO4J_URI` env |
| **SIEM integration** | `security/siem_adapter.py` 27 KB real code, no live feed wired | Configure `SIEM_WEBHOOK_URL` + `SIEM_API_KEY`; wire `security_event_ingest.py` emit to SIEM adapter |
| **JA3/JA4 TLS fingerprinting** | `security/tls_fingerprint_middleware.py` exists (3 KB) | Add to FastAPI middleware chain in `main.py`; configure `JA4_BLOCKLIST` feed |
| **Escalation room full workflow** | WS wired, but incident state machine incomplete | `escalation_room.py`: implement `OPEN → ASSIGNED → INVESTIGATING → RESOLVED` state transitions with SLA timers |
| **Human escalation room** | Partially built | Complete message threading, staff assignment, SLA breach alerts |
| **mTLS for service-to-service** | `security/internal_mtls.py` 4 KB exists | Generate service certs; wire in docker-compose `MTLS_CERT_PATH` / `MTLS_KEY_PATH` per service |
| **Decision replay** | `routers/decision_replay.py` exists | Verify full replay path works for incident forensics |

#### Compliance Gaps

| Framework | Current | Gap |
|-----------|---------|-----|
| **PCI DSS** | CSRF + auth real, PCI boundary files exist | No tokenization for card data; Stripe handles it but path not audited |
| **GDPR / APP** | DLP export module exists | No data subject request (DSR) API endpoint wired; no consent log |
| **ISO 42001 / EU AI Act** | Framework correlation 63 KB | No model card registry; no human oversight gate on high-risk AI decisions |
| **OWASP LLM Top 10 2025** | LLM08 (vector/embedding weaknesses) partially mapped | LLM01 (prompt injection) needs per-endpoint audit trail; LLM06 (excessive agency) needs agent action scope limits |
| **OWASP Agentic AI Top 10 Dec 2025** | Maestro boundaries + agent guardrails real | Context poisoning detection (MITRE ATLAS Oct 2025) not wired to guardrails |
| **SOC 2 Type II** | Audit chain real | No automated control evidence collection; no access review workflow |

#### Observability Gaps

| Gap | Fix |
|-----|-----|
| No distributed trace IDs in HTTP headers | Add `X-Trace-ID` propagation middleware; wire to OpenTelemetry |
| RAGAS evaluation hooks exist but no dashboard | Wire `services/drift_daily_metrics.py` to Grafana dashboard |
| No real-time anomaly alerting | Wire `services/anomaly_detector.py` → SIEM adapter → PagerDuty webhook |
| Celery worker health not exposed | Add `/health/workers` endpoint checking Celery inspect |

---

## 4. UI/UX Framework Theatre — Diagnosis and Fixes

"Framework theatre" = features that look comprehensive in code but deliver a confusing or hollow user experience.

### 4.1 Current Theatre Problems

#### Problem 1: Security is invisible until you dig for it
- CV detects QR injection, steg, adversarial — but products still show normally
- User must click "Why this?" → open DecisionTrace → select "security" tab → read raw signal JSON
- A merchant under a BEC attack gets zero visual cue unless they open the trace

**Fix:** Add a persistent security banner in `App.tsx` when `response.security_flags.length > 0`:
```tsx
// In App.tsx after processing chat response
if (response.security_signals?.threat_detected) {
  setSecurityAlert({ level: response.security_signals.severity, summary: response.security_signals.plain_english });
}
// Render above ProductGrid:
{securityAlert && <SecurityBanner level={securityAlert.level} message={securityAlert.summary} />}
```

#### Problem 2: DecisionTrace is an expert tool masquerading as UX
- 10 tabs of raw JSON/event streams
- No plain-English interpretation in the security tab
- Draggable modal that users don't know how to find

**Fix:**
1. Add a one-line verdict below each product card: "✓ 5 security checks passed" or "⚠ 1 risk signal: uploaded image contains hidden data"
2. In DecisionTrace `security` tab, add `plain_english_summary` field from backend. Backend: `observer.py` already logs events — add a `summarize_security_events()` call that maps signal codes to human sentences.
3. Surface the trace automatically (collapsed, not modal) below the chat response — like a receipt, not a hidden lab.

#### Problem 3: AdminDashboard is a tab graveyard
- 9 tabs: overview, NQE, recommendations, fraud, supply chain, intelligence, persona, security, health
- Most tabs show raw metrics or are minimal placeholders
- No executive summary that answers: "Is the system healthy right now? Any active threats?"

**Fix:** Replace the tab layout with a single-page command center:
```
┌─────────────────────────────────────────┐
│  SYSTEM STATUS    ●  Healthy            │
│  Active Sessions: 12  | Threats Today: 2│
│  [Email Lab] [Escalation] [Audit Trail] │
├──────────────┬──────────────────────────┤
│ LIVE THREATS │ RECOMMENDATION HEALTH    │
│  [table]     │  NQE rate / hit rate     │
├──────────────┴──────────────────────────┤
│ RECENT DECISIONS (bitemporal timeline)  │
└─────────────────────────────────────────┘
```

#### Problem 4: Email lab and shopfront are two disconnected UIs
- Merchant uses 5173 for shopping assistant, 8080 for email security — no shared nav
- No way to navigate from a suspicious recommendation to the email lab
- Two separate auth systems (VITE_API_KEY vs OWNER_API_KEY)

**Fix:**
1. Add a nav link in `App.tsx` header: `[Email Security Lab ↗]` pointing to `http://localhost:8080/merchant/email-lab`
2. Add `?prefill_sender=email@domain.com` parameter support to the email lab so clicking a supplier's name in the recommendation prefills the email analyzer
3. Standardise auth: backend should accept the same JWT from 5173 for email lab endpoints (add `require_role: MERCHANT` gate that reads the httpOnly cookie, not OWNER_API_KEY)

#### Problem 5: NQE questions look like interrogation
- Questions appear as plain text below chat
- No visual differentiation between "I'm recommending" vs "I need more info"
- Users dismiss NQE as noise

**Fix:** Style NQE as a "preference wizard" card:
```tsx
// In ChatOverlay or App.tsx NQE rendering
<NQECard
  headline="Help me narrow this down"
  questions={nqeQuestions}
  onAnswer={handleNQEAnswer}
  skipLabel="Skip — show me what you have"
/>
```
With icon, progress indicator ("2 of 3 questions"), and a skip button that invokes `_is_followup_explain_query` path.

#### Problem 6: Loading states are abrupt
- No skeleton loading for ProductGrid while recommendation fetches
- No progress indication for CV analysis (can take 2-5s)
- No feedback that the chat message was received

**Fix:**
- Add `ProductGridSkeleton` component (4 placeholder cards with CSS pulse animation)
- Add CV progress bar: backend SSE stream already exists; frontend just needs to render stages: "Checking image integrity... Scanning for hidden data... Analyzing content..."
- Show typing indicator in ChatOverlay immediately on send

#### Problem 7: ProductComparison is a plain table
- HTML table with no visual diff highlighting
- No "best for your use case" indicator
- No spec explanation tooltips

**Fix:**
- Highlight winner per row in green
- Add "Best for: gaming / university / creative" badge using use_case from response
- Add `title` tooltip on spec rows explaining what the spec means in plain English

---

## 5. Security Agent Improvements

### 5.1 Shopfront (5173)

#### 5.1.1 Immediate Fixes

**A. Fix DecisionTrace WebSocket URL**
`frontend/src/components/DecisionTrace.tsx` — the first WS attempt fails because the path is wrong:
```ts
// Current (fails silently, falls through to SSE):
const wsUrl = `${wsBase}/api/v1/decisions/${traceId}/ws`;
// Fix:
const wsUrl = `${wsBase}/api/v1/decisions/${traceId}/events/ws`;
```
Backend path: `decisions.py:619` / `decision_trace_events.py:276` both use `/{trace_id}/events/ws`.

**B. Proactive security signal surfacing**
When `recommend.py` response includes `security_signals.threat_detected = true`, the frontend currently shows nothing visual. Add:
```ts
// App.tsx after processing response
if (msg.security_signals?.severity === 'high' || msg.security_signals?.severity === 'critical') {
  setSecurityBanner({
    msg: msg.security_signals.plain_text_summary || 'Security signal detected in this request',
    traceId: msg.trace_id
  });
}
```

**C. Server-side PII scrubbing**
Currently PII is detected client-side in `App.tsx` (Luhn/SSN/bank regex) — good. But if that check fails, raw PII flows to the LLM. Add backend validation in `recommend.py` before the LLM call:
```python
# recommend.py — before any LLM call
from security.observer import scrub_pii
cleaned_query = scrub_pii(user_message)
```

#### 5.1.2 Security Trace Enhancements

**D. Plain-English security summary in trace**
`security/observer.py` logs raw events. Add a `summarize()` function:
```python
# security/observer.py
SIGNAL_LABELS = {
    "qr_prompt_injection": "QR code in uploaded image contained a prompt injection attempt",
    "steg_lsb_high": "Image contains hidden data in pixel LSB planes (steganography)",
    "gan_synthetic": "Image appears to be AI-generated (no camera fingerprint)",
    "adversarial_patch": "Image contains adversarial pattern targeting vision models",
}
def summarize_signals(events: list[SecurityEvent]) -> str:
    hits = [SIGNAL_LABELS[e.signal_code] for e in events if e.signal_code in SIGNAL_LABELS]
    return "; ".join(hits) if hits else "No threats detected"
```
Expose via `GET /api/v1/decisions/{trace_id}/security-summary` — frontend DecisionTrace "security" tab renders this above the raw events.

**E. Post-hoc audit actions visible in UI**
`DecisionTrace.tsx` already has `POST /api/v1/decisions/{traceId}/posthoc` wired. But the UI for `fraud_confirmed / false_positive` actions is hidden. Surface it:
- Add a prominent "Flag this decision" button when `security_signals.risk_score > 0.5`
- Show existing audit trail entries in the `audit` tab with timestamps and actor IDs

#### 5.1.3 Policy Gate Visibility

**F. Show policy gate verdicts on product cards**
Each product recommendation passes through policy gates in the orchestrator. Expose the pass/fail per product:
```ts
// ProductGrid.tsx — in product card footer
{product.policy_gates && (
  <PolicyBadge gates={product.policy_gates} />
  // "✓ All policy checks passed" or "⚠ Budget gate: nearest match is $120 over"
)}
```
Backend already returns `policy_gate_results` in the recommendation payload — frontend just needs to render it.

---

### 5.2 Email Security Lab (8080)

#### 5.2.1 Immediate Fixes

**A. Fix auth UX (BUG-8)**
In `merchant_dashboard.py` email lab HTML, add a visible auth status indicator:
```html
<!-- Add to email lab header area -->
<div id="auth-status"></div>
<script>
  const key = localStorage.getItem('ss_owner_key');
  document.getElementById('auth-status').innerHTML = key
    ? '✓ Auth key set'
    : '⚠ No auth key — <a href="#" onclick="promptKey()">Set key</a>';
  function promptKey() {
    const k = prompt('Enter OWNER_API_KEY:');
    if (k) { localStorage.setItem('ss_owner_key', k); location.reload(); }
  }
</script>
```

**B. Show detection stages in real-time**
The email analysis is synchronous (single POST). Add an SSE-backed analysis endpoint that streams stages:
```python
# routers/email_security.py — new endpoint
@router.get("/evaluate/stream")
async def evaluate_email_stream(request: Request, payload: EmailEvaluateRequest):
    async def generate():
        yield f"data: {json.dumps({'stage': 'dns', 'label': 'Checking DMARC/SPF/DKIM...'})}\n\n"
        dns_result = await check_dns(payload.sender_domain)
        yield f"data: {json.dumps({'stage': 'dns', 'result': dns_result})}\n\n"
        yield f"data: {json.dumps({'stage': 'bimi', 'label': 'Verifying brand logo...'})}\n\n"
        # etc.
    return StreamingResponse(generate(), media_type="text/event-stream")
```
Frontend: replace `fetch()` with `EventSource` in the email lab JS.

#### 5.2.2 Threat Visualization

**C. BIMI / GAN / Steg verdicts need visual treatment**
Currently all verdicts return in JSON and the UI renders a generic verdict badge. Each detector deserves its own visual:

| Detector | Current | Improvement |
|----------|---------|-------------|
| BIMI | `verified: true/false` badge | Logo preview + domain match score |
| GAN | `is_synthetic: true/false` | 6-signal radar chart (spectral / histogram / texture / EXIF / JPEG / diffusion) |
| Steg | `steg_detected: true/false` | Show which of 8 methods fired, estimated payload size from SPA |
| DMARC | pass/fail text | SPF/DKIM/DMARC traffic light (3 independent checkboxes) |

**D. BEC Kill Chain visualization**
`security/bec_kill_chain.py` already maps detected signals to kill chain stages. Surface it:
```
Recon → Phishing Hook → Credential Harvest → Account Compromise → Wire Transfer Request
  ✓           ⚠                  ✗                  ✗                    ✗
 domain    lookalike          not yet              not yet              not yet
 observed   domain            confirmed            confirmed            confirmed
```
Render as a horizontal step-progress bar in the email lab verdict section.

**E. IOC extraction for threat hunters**
Add a "Copy IOCs" button that extracts:
- Sender IP, sending MX, envelope-from
- URLs found in body (via `email_url_click_protect.py`)
- Attachment hashes
- Detected homoglyph domains
```html
<button onclick="copyIOCs()">📋 Copy IOCs</button>
<script>
function copyIOCs() {
  const iocs = {
    sender_ip: lastResult.header_forensics?.sending_ip,
    urls: lastResult.url_analysis?.urls,
    attachment_hashes: lastResult.attachment_intel?.hashes,
    homoglyph_domains: lastResult.bimi?.homoglyph_candidates
  };
  navigator.clipboard.writeText(JSON.stringify(iocs, null, 2));
}
</script>
```

**F. Escalation prominence**
The Escalate button is same visual weight as Demo and Analyze. When `verdict_action === 'BLOCK'` or `severity === 'critical'`:
```html
<!-- merchant_dashboard.py: conditional class on Escalate button -->
<button class="btn {{'btn-danger' if severity == 'critical' else ''}}" ...>
  🚨 Escalate to Incident Room
</button>
```

**G. Email sender history chart**
Wire `GET /api/v1/email_security/sender/{domain}/history` (if not existing, add it — query `security_event_ingest` for past events from that domain). Render as a small sparkline above the verdict: "This domain has 3 prior flags in the last 30 days."

---

## 6. Priority Fix List (Ranked by Impact)

| # | Fix | File | Effort | Impact |
|---|-----|------|--------|--------|
| 1 | BUG-3: Add CV Docker deps | `Dockerfile` | 30 min | Unblocks all CV/QR/OCR/steg |
| 2 | SECURITY_BLOCK_MODE=403 | `.env.production` | 5 min | Closes fail-open security hole |
| 3 | BUG-1: NQE context from Redis | `recommend.py:~5020` | 2h | Eliminates biggest UX regression |
| 4 | DecisionTrace WS URL fix | `DecisionTrace.tsx` | 15 min | WS now connects first try |
| 5 | AUDIT_CHAIN_SECRET | `.env.production` | 5 min | Compliance: audit chain secure |
| 6 | BUG-8: Email lab auth UX | `merchant_dashboard.py` | 1h | Email lab usable by merchants |
| 7 | BUG-6: LLM summary answers yes/no | `recommend.py:2865` | 1h | Core UX: budget questions answered |
| 8 | BUG-4: Shortlist zero-result | `recommend.py:~8600` | 30 min | UX: search doesn't reset on miss |
| 9 | Security banner in App.tsx | `frontend/src/App.tsx` | 2h | Threats visible without trace dive |
| 10 | Plain-English security summary | `security/observer.py` + new endpoint | 3h | Trace readable by non-engineers |
| 11 | BUG-2: Multimodal +2 score | `llm_provider.py:142` | 30 min | Better image+text reasoning |
| 12 | BUG-5: NQE explain gate | `recommend.py:~5193` | 1h | No NQE on "tell me more" |
| 13 | BUG-7: Budget no-brand | `recommend.py:2995` | 1h | Budget questions work without brand |
| 14 | Email lab SSE streaming | `routers/email_security.py` | 4h | Real-time analysis feedback |
| 15 | BEC kill chain visualization | `merchant_dashboard.py` JS | 4h | Threat context for merchants |
| 16 | Neo4j in docker-compose | `docker-compose.yml` | 2h | GNN fraud ring detection online |
| 17 | JA4 middleware wired | `main.py` middleware chain | 1h | TLS device fingerprinting active |
| 18 | NQE wizard card styling | `frontend/src/components/` | 3h | NQE feels helpful not intrusive |
| 19 | Admin dashboard command center | `AdminDashboard.tsx` | 1 day | Single-pane health view |
| 20 | Multi-tenant RLS (Postgres) | `models/db.py` + migrations | 2 days | Enterprise isolation proof |

---

## 7. Snapshot Assessment

```
COMPONENT                  STATUS          GRADE
─────────────────────────────────────────────────
Recommendation engine      REAL            Production (after BUG-1/4/6/7)
Email security detection   REAL            Production-ready
Decision trace / audit     REAL (WS bug)   Production (after URL fix)
Fraud scoring (26 signals) REAL            Production
CV analysis pipeline       REAL (no deps)  Production (after Docker fix)
Playbook engine            REAL            Production
RBAC / auth                REAL            Production (needs MFA for Enterprise)
Bitemporal audit           REAL            Production (needs secret set)
Escalation room            PARTIAL         Pre-production (workflow broken)
GNN fraud rings            CODE REAL       Pre-production (Neo4j absent)
SIEM integration           CODE REAL       Pre-production (no live wiring)
Multi-tenant isolation     MODULE REAL     Pre-production (RLS not enforced)
Voice ASR/TTS              STUB            Not started
ERP/EDI sync               STUB FALLBACK   Not started
Alt payment providers      STUB            Not started
```

**Bottom line:** The detection and recommendation engines are genuinely impressive and close to production-grade. The gaps are mostly deployment configuration, 8 known bugs in recommend.py, one URL typo in the frontend, and a handful of modules that have real code but aren't wired into the running system. Enterprise grade needs 3-4 weeks of hardening work (RLS, SIEM wiring, compliance gaps, escalation room, MFA).
