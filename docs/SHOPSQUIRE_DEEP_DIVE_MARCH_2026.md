# ShopSquire — Comprehensive Platform Deep Dive
**Date:** March 2026 · **Branch:** `wip/docker-real-env-20260213`
**Model:** Claude Sonnet 4.6 · **Author:** Automated Analysis
**Last Updated:** 2026-03-24 — Code fixes applied (see §14 Changelog)

---

## Table of Contents
1. [Platform Architecture Snapshot](#1-platform-architecture-snapshot)
2. [Why the LLM Summary Sounds Robotic](#2-why-the-llm-summary-sounds-robotic--how-to-fix-it)
3. [NLP Context & Answer Quality](#3-nlp-context--answer-quality)
4. [Does Each Deployment Need a Custom Model?](#4-does-each-deployment-need-a-custom-model)
5. [Production & Enterprise Readiness](#5-production--enterprise-readiness)
6. [Supply Chain Attack Defence](#6-supply-chain-attack-defence)
7. [Email Security — Wiring & Button Status](#7-email-security--wiring--button-status)
8. [FAQ & Knowledge Base — Repair / Warranty / BSOD](#8-faq--knowledge-base--repair--warranty--bsod)
9. [Agent Intelligence Assessment](#9-agent-intelligence-assessment)
10. [Critical Bugs Tracker](#10-critical-bugs-tracker)
11. [Priority Backlog — What to Build Next](#11-priority-backlog--what-to-build-next)
12. [Competitive Positioning 2026](#12-competitive-positioning-2026)
13. [Files to Edit / Refactor / Add](#13-files-to-edit--refactor--add)

---

## 1. Platform Architecture Snapshot

| Layer | What It Is | Status |
|---|---|---|
| **Chat / NLP entry** | `routers/chat.py` → delegates to `routers/recommend.py` | ✅ wired |
| **4-Phase Orchestrator** | EXPLORE → EVALUATE → PLAN → ACTION | ✅ working |
| **LLM Routing** | Complexity 0–10 → small/medium/large Ollama model | ⚠️ BUG-2 multimodal scores too low |
| **Redis Session Memory** | `session:{uid}:summary`, `kv_state`, `recent_retrieval`, `agent_steps` | ✅ exists, ⚠️ NQE never reads it |
| **Decision Audit Trail** | Bitemporal, per-event trace DB, SSE streaming | ✅ solid |
| **Security Stack** | 55+ modules, 12-layer middleware, rate limit, PCI, mTLS | ✅ strong |
| **Email Security** | `/merchant/email-lab` server-side HTML, wired to `/api/v1/email_security/evaluate` | ⚠️ auth key gotcha (see §7) |
| **CV / Visual Search** | Image triage, QR decode, OCR, steg detection | ⚠️ BUG-3 runtime deps missing in Docker |
| **FAQ** | 59-entry hardcoded bank, Jaccard + intent match | ⚠️ missing repair / diagnostic entries |
| **Frontend** | React/TypeScript Vite @ port 5173 | ✅ mostly wired |

---

## 2. Why the LLM Summary Sounds Robotic — How to Fix It

### The Root Cause (screenshots: `sec-LLM-summ.png`, `where payload.png`)

There are **two response generators** chained in `routers/recommend.py:8782–8810`:

```
1. _summarize_results()  ← tries LLM, 6s timeout → falls back if Ollama slow/down
2. _deterministic_assistant_message()  ← template engine (always succeeds)
```

**`_summarize_results` (line 2851)** — the LLM path:
```python
prompt = (
    "You are a concise shopping assistant. "
    "Summarize the result set in 1-2 sentences, mention budget/spec constraints if present, "
    "and suggest next step. Do not invent products.\n"
    f"Query: {query}\n"
    f"Constraints: {constraints}\n"
    f"Top results: {items}\n"    # only name + price, NO specs
)
```

**Three problems with this prompt:**
1. **No instruction to answer the user's direct question** — "Is $1800 enough for a gaming laptop?" gets summarised into *"I found 3 results between $800 and $1,800"* because the prompt says "summarize results", not "answer the user's question first".
2. **No product specs in context** — `items` is just `"Lenovo IdeaPad 5 ($1,299); ASUS ROG ($1,499)"` — no RAM, GPU, screen Hz. The LLM cannot say "yes the ROG has a 4060 GPU and 144Hz screen perfect for gaming".
3. **Small model doing synthesis** — routed to `llama3.3:8b` (BUG-2), which lacks the reasoning depth for nuanced Q&A.

**`_deterministic_assistant_message` (line 3110)** — the fallback template:
```python
opening = "Great news for your gaming setup — "
core    = f"found {n} matches between ${budget_min:,} and ${budget_max:,}"
# Result: "Great news for your gaming setup — I've found 3 matches between $800 and $1,800."
```
This **never mentions whether the budget is sufficient**, what GPU the top result has, or answers a yes/no question.

**`_build_brand_budget_answer` (line 2964)** — handles "is $X enough?" but:
```python
if brand_hint not in _SUPPORTED_IMAGE_BRAND_HINTS:
    return ""   # silent empty string if no recognizable brand in query
```
Query: *"Is $1,800 enough for a gaming laptop?"* — no brand detected → returns `""` → no budget answer at all.

### How to Fix It (files + approach)

#### Fix A — Rewrite the `_summarize_results` prompt (HIGH IMPACT, 30 min)

**File:** `src/app/routers/recommend.py:2865`

Replace the prompt with:
```python
# Include specs for top 3 results
def _spec_summary(r: dict) -> str:
    specs = r.get("specs") or {}
    parts = []
    if specs.get("ram_gb"):     parts.append(f"{specs['ram_gb']}GB RAM")
    if specs.get("gpu_model"):  parts.append(specs["gpu_model"])
    if specs.get("refresh_hz"): parts.append(f"{specs['refresh_hz']}Hz")
    if specs.get("storage_gb"): parts.append(f"{specs['storage_gb']}GB SSD")
    price = int(r.get("price_cents", 0) / 100)
    return f"- {r.get('name')} (${price:,}): {', '.join(parts)}"

top_specs = "\n".join(_spec_summary(r) for r in results[:3])

prompt = f"""You are a friendly, direct shopping assistant.
The user asked: "{query}"

Answer their question DIRECTLY in the first sentence (yes/no if it is a yes/no question, or a direct recommendation if not).
Then in 1-2 sentences mention the top options and why they fit.
Be conversational, not robotic. Do not list every product.

Budget constraints: min=${constraints.get('budget_min','any')}, max=${constraints.get('budget_max','any')}
Use case: {constraints.get('use_case','general')}

Top matching products:
{top_specs}

Keep your response under 60 words. Be warm and specific."""
```

This change alone transforms:
> "Great news for your gaming setup — I've found 3 matches between $800 and $1,800."

Into:
> "Yes, $1,800 is more than enough for a solid gaming laptop. The ASUS ROG Strix G16 ($1,499) packs a 4060 GPU and 165Hz screen perfect for competitive gaming — and leaves budget for accessories."

#### Fix B — Extend `_build_brand_budget_answer` to work without brand (MEDIUM IMPACT, 20 min)

**File:** `src/app/routers/recommend.py:2995`

Currently bails if brand not recognized. Add a generic branch:
```python
# After the brand_hint check fails, use generic answer from results
if asks_budget and budget_max and results:
    cheapest = min(_row_price(r) for r in results if _row_price(r) > 0)
    if cheapest <= float(budget_max):
        return f"Yes, your budget of ${int(budget_max):,} covers these options, starting from ${int(cheapest):,}."
    return f"Your budget of ${int(budget_max):,} is slightly short — closest options start around ${int(cheapest):,}."
```

#### Fix C — Route synthesis queries to medium model (BUG-2, see §10)

**File:** `src/app/services/llm_provider.py:142`
Add +2 for any query containing "enough", "should I", "which is better", "recommend" — these are synthesis/comparison queries that need real reasoning.

---

## 3. NLP Context & Answer Quality

### Current Flow

```
User types: "Is $1,800 enough for a gaming laptop?"
         ↓
NLP slot extraction (llama3.3:8b)
  → budget_max: 1800
  → use_case: gaming
  → persona: gamer
         ↓
Product search (vector + BM25)
  → 3 results
         ↓
_summarize_results()  [LLM prompt — see §2]
  → FAILS or returns generic 1-liner
         ↓
_deterministic_assistant_message()
  → "Great news for your gaming setup — I've found 3 matches..."
         ↓
NQE asks: "What type of games do you play?"
```

### What's Missing

| Gap | Impact | Fix Location |
|---|---|---|
| LLM prompt doesn't echo user's question | No direct answer | `recommend.py:2865` |
| No product specs in LLM context | No "this has 4060 GPU" answers | `recommend.py:2864` |
| Budget sufficiency only works with named brands | No generic yes/no | `recommend.py:2995` |
| NQE fires even when question was answered | Feels broken | `flows/nqe.py` + BUG-1 |
| No "gaming type" use-case followup | Correct but generic | NQE templates already exist — BUG-1 blocks them |
| LLM summary uses 128 token limit | Cuts off mid-sentence | `recommend.py:2893` → raise to 200 |

### NQE "What Type of Gaming?" — Why It Doesn't Show

The NQE **does have** this template (in `config/nqe_templates.json`), but:
1. **BUG-1**: `nqe_asked_ids` never loaded from Redis → same questions repeat every turn
2. The NQE is not suppressed on zero-result turns (BUG-5) so it fires at wrong times
3. Once BUG-1 is fixed, NQE should correctly ask "What games do you play? (AAA titles, esports, casual?)" on second turn

---

## 4. Does Each Deployment Need a Custom Model?

**Short answer: No.** ShopSquire uses a **retrieval-augmented approach**, not a fine-tuned model per client.

### How It Works

```
Client products → Postgres + pgvector index
                       ↓
User query → NLP slot extraction (generic Ollama model)
                       ↓
Vector + BM25 search against client's product catalog
                       ↓
LLM synthesis (generic Ollama model) + retrieved products as context
```

The **product knowledge lives in the database**, not the model weights. This is architecturally correct and scalable. You do NOT need a per-client fine-tuned model.

### What You DO Need Per Client

| Requirement | How Handled |
|---|---|
| Product catalog ingestion | `sync-worker` Docker service (CSV / Shopify sync) |
| Category-specific NQE templates | Already per-category JSON files (`nqe_templates_laptop.json`, `_phone`, `_tv`, etc.) |
| Brand-specific budget logic | `_SUPPORTED_IMAGE_BRAND_HINTS` dict (add client brands) |
| Custom FAQ answers | `faq_bank.py` — currently generic, make it injectable per tenant |
| Use-case knowledge base | **Missing** — build JSON specs for client's domain (see §11) |
| Tenant isolation | ✅ Done — `X-Tenant-Id` header, per-tenant quota, DB isolation |

### Recommendation

Add a **tenant config JSON** per deployment that specifies:
- Brand catalog (for budget answer logic)
- Category default (laptops? phones? furniture?)
- FAQ overrides (client-specific warranty period, return policy)
- Use-case KB entries (client sells gaming PCs → inject gaming specs)

No fine-tuning required. Retrieval handles the rest.

---

## 5. Production & Enterprise Readiness

### Security Middleware Stack (✅ Solid)

12 middleware layers in `main.py:459–523`:
1. `RateLimitMiddleware` — per-key + per-IP
2. `GlobalRequestShapeMiddleware`
3. `ComplianceMiddleware` — PCI detection
4. `AdminMfaMiddleware`
5. `IdempotencyMiddleware`
6. `InternalMTLSMiddleware` — mTLS inter-service
7. `TLSFingerprintMiddleware` — JA3 fingerprinting
8. `PciBoundaryMiddleware` — PCI-DSS data isolation
9. `WebhookSecurityMiddleware`
10. `VersionDeprecationMiddleware`
11. `SecurityHeadersMiddleware`
12. `CORSMiddleware`

### Docker Hardening (✅ Solid)

- Non-root user (`shopsquire`)
- `CAP_DROP: ALL`
- `seccomp: default`
- Read-only root filesystem, `tmpfs /tmp:256M`
- All services have health checks with retry logic

### Production Secrets Enforcement (`config.py:120–130`) (✅ Correct)

```python
if _is_non_dev_env(s.app_env):
    if not _redis_url_has_auth(s.redis_url):
        raise RuntimeError("missing_required_secret:REDIS_URL_password")
    if not _is_truthy_env("PG_ENCRYPTION_AT_REST", "1"):
        raise RuntimeError("insecure_runtime:PG_ENCRYPTION_AT_REST_required")
```

### Observability (✅ Good)

- OpenTelemetry auto-instrumentation
- Per-request trace IDs
- Bitemporal decision audit trail
- Structured logging via `init_logging()`
- Health endpoints: `/api/v1/health` (basic) + dependency health with latency

### Gaps Blocking Enterprise SLA

| Gap | Severity | Evidence |
|---|---|---|
| CV runtime deps (pyzbar, pytesseract, paddleocr, imagehash) missing from Docker | **HIGH** | BUG-3 — all CV silent-fails |
| NQE context loss — same questions repeat | **CRITICAL** | Screenshots smart-1/2.png, BUG-1 |
| Multimodal queries routed to small model | **HIGH** | Screenshots lenovo-multimodal.png, BUG-2 |
| Shortlist erased on zero-result turns | **MEDIUM** | BUG-4 |
| No load test evidence | **HIGH** | Unknown throughput ceiling |
| Human escalation room incomplete | **MEDIUM** | `EscalationRoom.tsx` exists but workflow broken |
| GeoIP / ASN risk scoring absent from fraud scorer | **MEDIUM** | See §6 |
| MITRE ATT&CK / ATLAS mapping partial | **LOW** | Incomplete threat correlation |

### Throughput Estimate

Based on architecture (no load test data available):
- Single Ollama node (8b model): ~3–8 concurrent recommend calls
- With Redis caching (semantic cache hits): 50–100 req/sec cached
- Recommendation: Redis semantic cache hit rate must be >60% for production throughput

---

## 6. Supply Chain Attack Defence

### What's Currently Built

**`services/supply_chain_monitor.py`:**
- Endpoint integrity checks (HEAD request + SSL issuer verification)
- JSON response anomaly detection (field add/delete, type changes)
- Suspicious marker scan (script tags, eval calls, data URIs, base64 exe)
- Vendor baseline config at `config/security/supply_chain_baselines.json`

**`security/supply_chain_controls.py` + `supply_chain_automation.py`:**
- Control gate for vendor actions
- Automated response playbooks

**`services/supply_chain_cv.py`:**
- Computer vision checks on supplier-submitted product images
- Checks for steganographic payloads in supplier assets

### Screenshot Evidence (where-payload.png)

The visual search correctly flagged:
- ✅ QR code detected in uploaded image with URL `https://en.m.wikipedia.org`
- ✅ OCR text extracted: "ESPORTS LEGION WORLD CUP RISE ABOVE" (steganographic text)
- ✅ Steganography anomaly detected (score 0.423) — metadata hiding
- ✅ Products shown were still correct (attack failed to hijack results)

**This demonstrates the platform CAN defend against image-embedded supply chain attacks in product listings.**

### Gaps in Current Supply Chain Defence

| Gap | Risk | What's Needed |
|---|---|---|
| **No vendor risk scoring** (financial, reputational) | Can't tier vendor trust | Integrate D&B / Creditsafe API or static JSON vendor ratings |
| **No third-party CVE tracking** | Don't know if vendor software has known vulns | Subscribe to NVD feed, correlate vendor domains |
| **No SCA (Software Composition Analysis)** | Own dependencies unchecked | Add `pip-audit` / `safety` to CI/CD pipeline |
| **No SBOM (Software Bill of Materials)** | Can't prove to enterprise buyers | Generate SBOM with `syft` in Docker build |
| **GNN fraud ring detection incomplete** | Miss coordinated supply chain fraud rings | Implement Neo4j + PyG GNN (infrastructure exists) |
| **No outbound traffic baseline** | Can't detect C2 beaconing from compromised workers | Add network egress monitoring to Docker compose |
| **JA4 TLS fingerprinting partial** | Can't detect sophisticated bot fingerprint evasion | Complete `tls_fingerprint_middleware.py` integration into fraud scorer signals |
| **CISA KEV integration absent** | Miss known-exploited vulnerability alerts | Integrate CISA KEV API feed to vendor risk dashboard |

### Current Posture Assessment

**Can it secure an ecommerce platform as-is?**

| Threat | Can Handle? | Notes |
|---|---|---|
| BEC (Business Email Compromise) | ✅ Yes | Email lab + DKIM/SPF/DMARC + sender trust |
| Prompt injection via email | ✅ Yes | `adversarial_email_pipeline.py` |
| QR code / steganographic payloads in product images | ✅ Yes (if BUG-3 fixed) | CV triage pipeline — needs runtime deps |
| Synthetic supplier invoice fraud | ✅ Yes | PDF baseline diff, visual diff |
| Credential stuffing / account takeover | ✅ Yes | Rate limiting, MFA middleware, fraud scorer |
| Supply chain image tampering | ✅ Yes | `supply_chain_cv.py` |
| Third-party JS injection (Magecart-style) | ⚠️ Partial | No client-side monitoring, no CSP enforcement on storefront |
| Coordinated fraud ring | ⚠️ Partial | GNN not deployed; static rules only |
| Vendor software supply chain (npm/pip compromise) | ❌ No | No SCA, no SBOM |
| Zero-day in vendor API | ❌ No | No CVE tracking |

**Summary: Strong detection for email and image-layer attacks. Gaps in third-party software supply chain and coordinated ring detection.**

---

## 7. Email Security — Wiring & Button Status

### What the Screenshots Show

**`email-check.png`:** Supplier invoice (Ingram Fake Pty Ltd) with bank change request — correctly flagged with EXECUTIVE SUMMARY showing:
- What Happened: fraudulent supplier impersonation
- Business Risk: High risk
- Why Flagged: 3+ indicators
- Immediate Actions: listed
- Security score badges visible
- **"SECURITY REVIEW — ERROR"** at bottom

**`email-new plain.png`:** Full analysis view with all collapsible sections expanded (Gov/Trust, Tone, etc.)

### Button Wiring Status

The Email Security Triage Lab is at `/merchant/email-lab` (server-side HTML, not React frontend).

| Button | Function | Backend Call | Status |
|---|---|---|---|
| **Analyze** | `analyze()` | `POST /api/v1/email_security/evaluate` | ✅ Wired |
| **Escalate** | `submitEscalate()` | Same + `POST /api/v1/incidents/escalate` | ✅ Wired |
| **Demo** | `loadDemoAssets()` | Loads preset email scenarios | ✅ Wired |
| **Agents** | `simulateAgents()` | Pushes SSE trace events | ✅ Wired |
| **Detach Rail** | `toggleDetachRightRail()` | Pure JS / CSS | ✅ Wired |
| **Open In New Tab** | `openRightRailTab()` | Opens right panel separately | ✅ Wired |

### Root Cause of "SECURITY REVIEW — ERROR"

The lab authenticates via API key. The `analyze()` function tries:
```javascript
fetch('/api/v1/email_security/evaluate', {
    headers: { 'x-api-key': getApiKey() }
})
// If 401/403, retries with:
headers: { 'x-api-key': getOwnerKey() }
```

Where `getOwnerKey()` reads from localStorage key `ss_owner_key` and falls back to the env var `OWNER_API_KEY` baked into the HTML.

**If you see "SECURITY REVIEW — ERROR":**
1. Open browser DevTools → Network tab → check the `evaluate` call
2. If 401/403: the `OWNER_API_KEY` env var is not matching what the API expects
3. Fix: ensure `OWNER_API_KEY` in your `.env` matches `config.py`'s `owner_api_key` setting
4. Or: set it in localStorage: `localStorage.setItem('ss_owner_key', 'your-key-here')`

The error message "SECURITY REVIEW — ERROR" appears at the bottom of the security overview section when the `verdict_action` field in the response maps to an error state in the rendering logic — **this is a display artifact of an auth failure, not a security engine failure.**

### What Still Needs Work (Email Security)

1. **No email security buttons in the React frontend** (`AdminDashboard.tsx`) — only the server-side HTML lab has the full UI. The React admin dashboard shows `email_xdr.warnings` count only.
2. **Escalation room workflow** (`EscalationRoom.tsx`) — exists in React but the full incident workflow is broken (human review, assignment, resolution).
3. **BIMI logo verification** — wired in backend but not surfaced in the email lab UI.
4. **Outbound email anomaly** — `email_security_admin.py` has the endpoint but no UI.

---

## 8. FAQ & Knowledge Base — Repair / Warranty / BSOD

### What Exists

**`services/faq_bank.py`** — 59 hardcoded entries covering:
- Returns & refunds (5 entries)
- Shipping & tracking (5 entries)
- Payments (6 entries)
- Account management (4 entries)
- Warranties (2 entries — generic only)
- Complaints & support (6 entries)
- Privacy & data (3 entries)

**`services/faq_v2.py`** — semantic matching with Jaccard similarity + intent boost. Accessible via `GET /api/v1/query?q=...`

**`routers/support.py`** — uses FAQ v2 for support tickets

**`routers/recommend.py:8996–9008`** — injects FAQ playbooks for damaged devices:
```python
"faq_playbooks": [
    {"id": "faq_bsod", ...},       # ✅ BSOD detected
    {"id": "faq_cracked_screen", ...},
]
```

### Can the Platform Answer These Questions?

| Question | Can Answer? | How |
|---|---|---|
| "What is your return policy?" | ✅ Yes | faq_bank entry |
| "Is my laptop under warranty?" | ⚠️ Partial | Generic "1-year warranty" response, no product-specific check |
| "My laptop has a BSOD / Blue Screen" | ✅ Yes | `recommend.py:8998` injects BSOD playbook + triggers repair flow |
| "My screen is cracked, what do I do?" | ✅ Yes | `faq_cracked_screen` playbook + CV damage triage |
| "How do I diagnose a laptop that won't turn on?" | ❌ No | Not in FAQ bank |
| "Can I get a software repair for Windows corruption?" | ❌ No | Not in FAQ bank |
| "Is my SSD failing? How do I know?" | ❌ No | Not in FAQ bank |
| "What does error code 0x0000007E mean?" | ❌ No | Not in FAQ bank |
| "Does my warranty cover liquid damage?" | ❌ No | Generic warranty only |
| "How do I claim warranty for manufacturer defect?" | ⚠️ Partial | Generic "register warranty via manufacturer link" |

### Questions to Ask to Trigger Platform Intelligence

These queries will engage the platform's deeper reasoning:

**Visual / CV Intelligence:**
- "My laptop screen has a crack — can I fix it?" → upload photo → CV damage triage → repair/return playbook
- "Is this laptop real or a fake?" → upload product image → GAN detection + steganography check
- "Can you find something similar to what I'm showing you?" → upload image → visual similarity search

**Budget Intelligence:**
- "Is $1,500 enough for an MSI gaming laptop?" → budget answer (with brand detected)
- "What's the cheapest Lenovo with 32GB RAM?" → constraint + ranking

**Security Intelligence (admin/owner):**
- "Check this invoice from our supplier" → email lab → BEC/bank fraud detection
- "Is this QR code safe to scan?" → CV payload analysis

**Support / Repair Intelligence:**
- "My laptop shows a blue screen with WHEA_UNCORRECTABLE_ERROR" → BSOD playbook + NQE (hardware type, age, warranty status)
- "I received a damaged laptop" → image upload → CV damage score → auto return request
- "Why won't my laptop charge?" → support flow + FAQ + possible escalation

**Multi-Turn Conversational Intelligence:**
- "I need a laptop for uni" → NQE asks: What are you studying? Budget? Mac or Windows? → smart disambiguation

### Missing FAQ Entries (Add These)

**File to edit:** `src/app/services/faq_bank.py`

Add ~20 repair/diagnostic entries:
```python
# Physical damage
{"q": "My laptop screen is cracked. What are my options?",
 "a": "Upload a photo of the damage so we can assess repair vs replace. Most cracked screens qualify for repair if under warranty.",
 "tags": ["repair", "screen", "damage"]},

# BSOD / software
{"q": "My laptop has a blue screen of death (BSOD). What do I do?",
 "a": "A BSOD usually means a driver, hardware, or Windows file issue. Note the error code (e.g., WHEA_UNCORRECTABLE_ERROR) and we can guide you to the right fix or warranty claim.",
 "tags": ["bsod", "blue screen", "repair", "software"]},

{"q": "My laptop won't turn on at all",
 "a": "Try a hard reset (hold power 10 seconds). If still dead, it may be a battery or motherboard fault — contact support with your order number for warranty assessment.",
 "tags": ["repair", "power", "wont turn on"]},

# Warranty
{"q": "Does my warranty cover accidental damage?",
 "a": "Standard manufacturer warranties cover manufacturing defects, not accidental damage. Accidental damage protection is available as an add-on at checkout.",
 "tags": ["warranty", "accidental", "damage"]},

{"q": "My laptop battery drains too fast. Is that covered?",
 "a": "Battery degradation below 80% capacity within the warranty period is typically covered. Contact us with your purchase date and we'll arrange assessment.",
 "tags": ["warranty", "battery", "repair"]},
```

---

## 9. Agent Intelligence Assessment

### Agent Inventory

| Agent | Status | Intelligence Level | Notes |
|---|---|---|---|
| **NLP_Search_Agent** | ✅ Active | Good — intent + slot extraction | Could benefit from multi-intent decomposition |
| **Product_Ranking_Agent** | ✅ Active | Good — multi-signal scoring | |
| **Fraud_Scoring_Agent** | ✅ Active | Strong — 26+ signals | Missing GeoIP, ASN, JA4 (see §6) |
| **NQE (Next Question Engine)** | ✅ Active but broken | Good templates, context blind | BUG-1: never loads Redis state |
| **CV_Label_Agent** | ⚠️ Runtime broken | Sophisticated | BUG-3: missing pyzbar/pytesseract in Docker |
| **Security_Observer_Agent** | ✅ Active | Strong | Solid threat correlation |
| **Inventory_Agent** | ✅ Active | Basic | Stock check, no demand forecasting |
| **Policy_Gate_Agent** | ✅ Active | Good | Rule-based + DB-backed |
| **Playbook_Engine** | ✅ Active | Good | BSOD, cracked screen, BEC playbooks |
| **Email Security Agents** | ✅ Active | Very Strong | BIMI, DKIM, BEC, prompt injection, QR/OCR |
| **Audit_Evidence_Agent** | ✅ Active | Good | Bitemporal compliance trace |
| **Product_Identity_Agent** | ❌ Missing | — | Planned, not implemented |
| **Use-Case KB Agent** | ❌ Missing | — | No gaming/uni/creative spec KB |
| **GNN Fraud Ring Detector** | ❌ Missing | — | Neo4j + PyG infrastructure exists |
| **BI_Query_Agent** | ✅ Active | Good | NL-to-SQL for admin analytics |

### How to Make Agents More Human / Non-Technical

**Current responses are technical because:**
1. LLM prompt doesn't specify audience tone
2. Decision trace events use internal codes (`steg_detection`, `qr_ocr`, `payload_type`)
3. No personality layer on top of raw agent outputs

**Fixes:**

**1. Add tone injection to `_summarize_results` prompt:**
```python
"Speak like a knowledgeable friend, not a database. "
"Use plain English. Avoid technical jargon. "
"If mentioning specs, explain what they mean for the use case. "
"e.g., instead of '16GB DDR5 RAM', say '16GB of memory — plenty for running games and Chrome at the same time'."
```

**2. Add a `humanize_trace_events()` layer in `DecisionTrace.tsx`:**
Map internal codes to friendly labels:
```typescript
const FRIENDLY_LABELS = {
  "steg_detection": "Hidden payload detected in image",
  "qr_ocr": "QR code decoded — URL checked",
  "payload_type": "Attack type identified",
  "fraud_score": "Risk assessment complete",
  "nqe_fire": "Asking a clarifying question",
};
```

**3. Add a "What This Means For You" field to recommendations:**
Not just: *"Found 3 matches"*
But: *"These three laptops can all run Valorant smoothly at 144fps, and your $1,800 budget has $300 left over for a gaming headset and mouse."*

---

## 10. Critical Bugs Tracker

| ID | Title | Severity | Root Cause | Fix File | Fix Summary |
|---|---|---|---|---|---|
| **BUG-1** | NQE context loss — same questions repeat | 🔴 CRITICAL | `NQEInput.previously_asked_ids` never loaded from Redis | `recommend.py:~5020`, `flows/nqe.py:33` | Load `nqe_asked_ids` / `nqe_answered_fields` from Redis before NQE call |
| **BUG-2** | Multimodal queries routed to small model | 🟠 HIGH | Visual similarity + image = max +3 pts → stays at tier 0 | `llm_provider.py:142` | Add +2 for synthesis/comparison intent; +2 for visual similarity with image |
| **BUG-3** | CV runtime deps missing in Docker | 🟠 HIGH | `pyzbar`, `pytesseract`, `paddleocr`, `imagehash` not in container | `requirements.txt` + `Dockerfile` | Add packages; test with `lenovo-pro7.webp` |
| **BUG-4** | Shortlist erased on zero-result turns | 🟡 MEDIUM | `last_shortlist_skus` unconditionally overwritten with `[]` | `recommend.py:~8600` | Only overwrite if new results are non-empty |
| **BUG-5** | NQE fires on follow-up explain queries | 🟡 MEDIUM | `_is_followup_explain_query()` pattern too narrow | `recommend.py:~5193` | Broaden pattern: detect "why", "tell me more", "explain", "what does that mean" |
| **BUG-6** | LLM summary doesn't answer yes/no questions | 🟠 HIGH | Prompt says "summarize", not "answer" | `recommend.py:2865` | Rewrite prompt (see §2, Fix A) |
| **BUG-7** | Budget sufficiency requires named brand | 🟡 MEDIUM | `_build_brand_budget_answer` returns "" without brand | `recommend.py:2995` | Add generic branch (see §2, Fix B) |
| **BUG-8** | Email lab auth key mismatch → ERROR display | 🟡 MEDIUM | `OWNER_API_KEY` env not matching or localStorage not set | `.env` / `merchant_dashboard.py:484` | Document key setup; add clearer error message |

---

## 11. Priority Backlog — What to Build Next

### Sprint 1 — Fix Core Intelligence (1 week)

| # | Task | File(s) | Effort |
|---|---|---|---|
| 1.1 | Fix BUG-1: Load NQE state from Redis | `recommend.py:5020`, `flows/nqe.py` | 3h |
| 1.2 | Fix BUG-6: Rewrite `_summarize_results` prompt | `recommend.py:2865` | 2h |
| 1.3 | Fix BUG-7: Generic budget sufficiency answer | `recommend.py:2995` | 1h |
| 1.4 | Fix BUG-2: Complexity scoring for synthesis queries | `llm_provider.py:142` | 1h |
| 1.5 | Fix BUG-4: Protect shortlist on zero results | `recommend.py:~8600` | 1h |
| 1.6 | Fix BUG-5: Broaden follow-up explain detection | `recommend.py:5193` | 1h |

### Sprint 2 — CV, FAQ, Repair Intelligence (1–2 weeks)

| # | Task | File(s) | Effort |
|---|---|---|---|
| 2.1 | Fix BUG-3: Add CV deps to Docker | `requirements.txt`, `Dockerfile` | 2h |
| 2.2 | Add 20+ repair/warranty/BSOD FAQ entries | `services/faq_bank.py` | 2h |
| 2.3 | Build Use-Case Knowledge Base JSON | New: `config/use_case_kb.json` | 4h |
| 2.4 | Add tone/humanization layer to LLM prompts | `recommend.py:2865` + `flows/nqe.py` | 2h |
| 2.5 | Friendly trace event labels in `DecisionTrace.tsx` | `frontend/src/components/DecisionTrace.tsx` | 3h |
| 2.6 | Fix email lab auth key error message | `merchant_dashboard.py:2000` | 1h |

### Sprint 3 — Agent Completion (2–3 weeks)

| # | Task | File(s) | Effort |
|---|---|---|---|
| 3.1 | Build `Product_Identity_Agent` | New: `services/product_identity_agent.py` | 8h |
| 3.2 | Escalation room full workflow | `EscalationRoom.tsx` + `routers/escalation_room.py` | 12h |
| 3.3 | Tenant config JSON per deployment | New: `config/tenant/{tenant_id}.json` | 4h |
| 3.4 | Email security buttons in React `AdminDashboard.tsx` | `frontend/src/components/AdminDashboard.tsx` | 4h |
| 3.5 | Generic budget answer without brand | `recommend.py:2995` | 1h |

### Sprint 4 — Security Hardening (3–4 weeks)

| # | Task | File(s) | Effort |
|---|---|---|---|
| 4.1 | GeoIP + ASN risk scoring in fraud scorer | `services/fraud_scorer.py` | 6h |
| 4.2 | JA4 TLS fingerprinting integration | `security/tls_fingerprint_middleware.py` | 4h |
| 4.3 | SBOM generation in Docker build | `Dockerfile` | 2h |
| 4.4 | `pip-audit` in CI/CD | `.github/workflows/` | 2h |
| 4.5 | GNN fraud ring detection (Neo4j + PyG) | New: `services/fraud_ring_gnn.py` | 16h |
| 4.6 | MITRE ATT&CK / ATLAS full mapping | `security/threat_matrix.py` | 8h |
| 4.7 | CISA KEV feed integration | New: `services/cisa_kev_feed.py` | 4h |

### Sprint 5 — Performance & Scale

| # | Task | Effort |
|---|---|---|
| 5.1 | Load test to establish throughput baseline | 4h |
| 5.2 | Redis semantic cache tuning (target >60% hit rate) | 4h |
| 5.3 | LLM async queue for summary (background, not blocking) | 2h — `LLM_ASYNC_QUEUE_ENABLED=1` already coded |
| 5.4 | Decision trace WebSocket streaming (vs SSE) | 8h |
| 5.5 | Tenant FAQ injection system | 4h |

---

## 12. Competitive Positioning 2026

### Where ShopSquire Sits

```
                HIGH SECURITY DEPTH
                       │
     CrowdStrike ──────┤────── Darktrace
     (enterprise)      │       (network NDR)
                       │
LOW ECOMMERCE ─────────┼───────────────── HIGH ECOMMERCE
DOMAIN DEPTH           │                    DOMAIN DEPTH
                       │
     Shopify ──────────┤── ShopSquire ◄─── TARGET QUADRANT
     (no AI security)  │   (AI intel +         (unoccupied)
                       │    shift-left
     Agentforce ───────┤    security)
     (generic AI)      │
                       │
                LOW SECURITY DEPTH
```

### Competitive Matrix (Updated March 2026)

| Platform | Ecommerce AI | Security Depth | Agent Framework | Decision Audit | Price |
|---|---|---|---|---|---|
| **ShopSquire** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Mid |
| Shopify + Sidekick | ⭐⭐⭐ | ⭐ | ⭐⭐ | ⭐ | Mid |
| Salesforce Agentforce | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | High |
| Adobe Commerce (Magento) | ⭐⭐⭐ | ⭐ | ⭐ | ⭐ | High |
| CrewAI / LangGraph (custom) | ⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | Dev cost |
| CrowdStrike Falcon | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | Very High |
| Darktrace | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | Very High |

### ShopSquire Killer Differentiators

1. **Bitemporal decision audit trail** — no other ecommerce platform has this. Every recommendation decision is replayable by policy version. Critical for regulated industries (APRA, PCI-DSS audit trails).
2. **CV return fraud triage** — image-based damage detection integrated into the return flow. Reduces fraudulent return approvals. No competitor has this at this depth.
3. **In-pipeline security agents** — security is not a bolt-on; it's wired into the recommendation pipeline itself. QR/steganography/BEC detection happens before the LLM responds.
4. **Email BEC defence purpose-built for ecommerce** — supplier bank change fraud, invoice manipulation, reply-chain hijacking — scenarios that Shopify and Magento have zero native defence for.
5. **Multi-agent orchestration with human-readable decision trace** — explainability at the agent step level, not just the final answer.

### ANZ Market Opportunity

- **$62B ANZ ecommerce market** — underpenetrated by AI-native security platforms
- **AusPost / StarTrack integration** — unique opportunity for AU logistics-linked fraud detection
- **APRA CPS 234 compliance** — Australian banks and insurers must demonstrate cyber resilience. ShopSquire's bitemporal audit trail is a strong compliance narrative.
- **No local competitor** — most AU ecommerce platforms use US-based tools with no AU-specific compliance posture.

### Frameworks Applicable for Enterprise Sales

| Framework | Relevance | ShopSquire Coverage |
|---|---|---|
| **MITRE ATLAS** (Oct 2025 agentic update) | Context poisoning, memory manipulation, RAG credential harvesting | ⭐⭐⭐ partial |
| **MAESTRO** (CSA Feb 2025) | Agentic AI threat modeling | ⭐⭐ partial |
| **OWASP LLM Top 10 2025** | LLM08 vector weaknesses → `semantic_cache.py` | ⭐⭐⭐ good |
| **OWASP Agentic AI Top 10** (Dec 2025) | Agentic authorization failures | ⭐⭐ partial |
| **JA4 TLS fingerprinting** | AWS WAF, Cloudflare Enterprise (March 2025) | ⭐⭐ partial |
| **CISA KEV** | CVE-2025-54236 Magento SessionReaper (CVSS 9.1) | ❌ not tracked |

---

## 13. Files to Edit / Refactor / Add

### Edit (Existing Files)

| File | What to Change | Priority |
|---|---|---|
| `src/app/routers/recommend.py:2865` | Rewrite `_summarize_results` prompt — answer user question first, include specs, raise token limit to 200 | 🔴 P1 |
| `src/app/routers/recommend.py:2995` | Add generic budget answer without requiring brand name | 🔴 P1 |
| `src/app/routers/recommend.py:5020` | Load `nqe_asked_ids`/`nqe_answered_fields` from Redis into NQEInput before orchestrator call | 🔴 P1 |
| `src/app/routers/recommend.py:5193` | Broaden `_is_followup_explain_query()` regex patterns | 🟠 P2 |
| `src/app/routers/recommend.py:~8600` | Only overwrite `last_shortlist_skus` when new results are non-empty | 🟠 P2 |
| `src/app/services/llm_provider.py:142` | Add +2 complexity for synthesis/comparison queries; +2 for visual_similarity with image | 🟠 P2 |
| `src/app/services/faq_bank.py` | Add 20+ repair, diagnostic, BSOD, warranty-specific entries | 🟡 P3 |
| `src/app/routers/merchant_dashboard.py:2000` | Improve "SECURITY REVIEW — ERROR" message to include auth troubleshooting hint | 🟡 P3 |
| `frontend/src/components/DecisionTrace.tsx` | Add `FRIENDLY_LABELS` map for internal agent codes | 🟡 P3 |
| `frontend/src/components/AdminDashboard.tsx` | Add email security evaluation buttons wired to `/api/v1/email_security/evaluate` | 🟡 P3 |
| `requirements.txt` + `Dockerfile` | Add `pyzbar`, `pytesseract`, `paddleocr`, `imagehash` | 🟠 P2 |

### Add (New Files)

| File | Purpose | Priority |
|---|---|---|
| `config/use_case_kb.json` | 30+ use case specs (gaming AAA, gaming esports, university, creative, law student, medical student, travel, corporate) with RAM/GPU/display/battery constraints | 🟠 P2 |
| `config/tenant/{tenant_id}.json` | Per-tenant FAQ overrides, brand catalog, category defaults | 🟡 P3 |
| `src/app/services/product_identity_agent.py` | Vision LLM → extract specs from product image → inject as search constraints | 🟠 P2 |
| `src/app/services/fraud_ring_gnn.py` | GNN fraud ring detection using Neo4j + PyG | 🟡 P4 |
| `src/app/services/cisa_kev_feed.py` | Poll CISA KEV API, alert on vendor-domain CVEs | 🟡 P4 |
| `src/app/services/geoip_risk.py` | MaxMind GeoIP2 + ASN risk scoring → inject into `fraud_scorer.py` | 🟡 P3 |
| `docs/LOAD_TEST_RESULTS.md` | Baseline throughput, latency p95/p99, cache hit rate | 🟠 P2 |

### Refactor

| File | What to Refactor | Priority |
|---|---|---|
| `src/app/routers/recommend.py` | Extract `_summarize_results` into `services/response_synthesizer.py` — it's grown beyond a helper function | 🟡 P3 |
| `src/app/services/faq_v2.py` | Replace Jaccard with sentence-transformer embeddings for semantic FAQ matching (current Jaccard misses synonyms: "broken" ≠ "damaged") | 🟡 P3 |
| `src/app/flows/nqe.py` | Add `load_nqe_context(uid, redis)` function called before template selection | 🔴 P1 |

---

---

## 14. Changelog — Fixes Applied 2026-03-24

All changes made in a single session. Branch: `wip/docker-real-env-20260213`.

### ✅ FIX-1 — `_summarize_results` Prompt Rewrite
**File:** `src/app/routers/recommend.py:2871`
**Before:** Generic "Summarize the result set" prompt — no specs, no direct question answering, 128-token limit
**After:**
- Builds `_spec_summary_for_llm()` helper that extracts RAM, GPU model, GPU VRAM, Hz, SSD, CPU per product
- Prompt explicitly says "Answer the user's question DIRECTLY in the first sentence — yes/no if yes/no"
- Tells LLM to explain specs in plain English ("16GB of memory — enough to run games and Chrome at the same time")
- Budget, use_case, brands injected into prompt context
- Token limit raised 128 → 220; temperature 0.2 → 0.3

**Expected output change:**
> Before: *"I've found 3 matches between $800 and $1,800."*
> After: *"Yes, $1,800 covers solid gaming laptops — the ASUS ROG Strix G16 ($1,499) has a 4060 GPU and 165Hz display, perfect for competitive gaming."*

---

### ✅ FIX-2 — `_build_brand_budget_answer` Generic Branch
**File:** `src/app/routers/recommend.py:3053`
**Before:** Silently returned `""` when no brand name detected in query — "Is $1,800 enough for a gaming laptop?" got no budget answer
**After:** New generic branch uses actual result prices to produce a yes/no answer without needing a brand:
> *"Yes, $1,800 covers these gaming options, with models starting from $1,299."*
> *"Your $800 budget is a little short — the closest options start around $950."*

---

### ✅ FIX-3 — `_is_followup_explain_query` Extended Patterns (BUG-5)
**File:** `src/app/routers/recommend.py:983`
**Before:** Regex missed common natural follow-up phrasings — "what about", "show me more", "more info", "I'm confused", "what do you mean", "more options"
**After:** Added 15+ additional patterns covering:
- `more about`, `what about`, `show me more`, `more info`, `more detail`, `more options`
- `anything else`, `tell me about`, `what makes`, `give me more`, `i want more`
- `sounds good`, `go on`, `continue`, `keep going`, `what else`
- `not sure`, `i'm confused`, `confused`, `don't understand`
- `what do you mean`, `what does that mean`, `huh`
- `can you explain`, `please explain`, `explain more`

This prevents NQE from re-asking budget/use-case questions when the user is simply asking for more detail.

---

### ✅ FIX-4 — NQE Question Prioritization (Domain-specific before Generic)
**File:** `src/app/flows/nqe.py:666`
**Before:** When trimming to `cap` (3 or 2 questions), keep_set was:
`{'ask_budget', 'ask_budget_tier', 'ask_use_case', 'ask_platform', 'ask_brand_pref'}` — generic slot questions always won over domain-specific context questions like `ask_gaming_depth`

**After:** New priority ordering:
1. **Domain-specific first** (use-case context that determines what budget makes sense):
   - `ask_university_subject` (if university use case detected)
   - `ask_gaming_depth` (if gaming detected but no specific game named) ← **was missing**
   - `ask_software_confirm` (if specific software detected)
   - `ask_corporate_work_type` (if work/office context)
   - `ask_touch_screen_type` (if touch need detected)
   - `ask_image_model` (if uploaded image unidentified)
2. **Generic slots after** (budget, use_case, brand — already known from context)

**Impact:** For "I need a gaming laptop with $1,800 budget":
- Before: First question = "What's your budget?" (already told us!)
- After: First question = "What kind of games will you play?" (with light/casual/competitive/AAA options)

---

### ✅ FIX-5 — FAQ Bank Expanded (59 → 85 entries)
**File:** `src/app/services/faq_bank.py`
**Added 26 entries across 3 new categories:**

**Physical damage & repair (10 entries):**
- Cracked screen options and warranty check
- Won't turn on / hard reset guidance
- Hinge damage, keyboard fault, liquid damage
- Battery drain warranty, overheating / fan fault

**Software failures & BSOD (8 entries):**
- BSOD general guidance (note the error code)
- Repeated crashes diagnostic steps
- `WHEA_UNCORRECTABLE_ERROR` → hardware fault → warranty
- `MEMORY_MANAGEMENT` → RAM fault → Windows Memory Diagnostic
- Windows won't load → Startup Repair
- Stuck on loading screen → Safe Mode
- Slow performance → disk/startup/malware
- Reinstall Windows guidance

**Extended warranty & protection (8 entries):**
- Accidental damage policy (not standard warranty)
- How to claim warranty repair
- 6-month-old hardware fault → covered
- Standard warranty length (1 year most brands)
- Post-purchase warranty extension
- Dead pixel policy

**To trigger these via chat:**
- *"My laptop shows a blue screen with WHEA_UNCORRECTABLE_ERROR"*
- *"My laptop won't turn on"*
- *"Is liquid damage covered by warranty?"*
- *"My screen is cracked — what are my options?"*
- *"My laptop battery drains really fast"*

---

### 📋 Status of All Known Bugs After This Session

| Bug | Status | Fix Location |
|---|---|---|
| BUG-1: NQE context loss | ✅ **Already fixed** (prior session) | `recommend.py:5017`, `6130`, `8461` |
| BUG-2: Multimodal under-scoring | ✅ **Already fixed** (prior session) | `llm_provider.py:142` |
| BUG-3: CV runtime deps missing | 🔴 **Still open** | `requirements.txt` + `Dockerfile` |
| BUG-4: Shortlist erased on zero results | ✅ **Already fixed** (prior session) | `recommend.py:9268` |
| BUG-5: NQE fires on explain queries | ✅ **Fixed** (FIX-3, this session) | `recommend.py:983` |
| BUG-6: LLM summary robotic/no Q&A | ✅ **Fixed** (FIX-1, this session) | `recommend.py:2871` |
| BUG-7: Budget answer needs brand | ✅ **Fixed** (FIX-2, this session) | `recommend.py:3053` |
| BUG-8: Email lab auth mismatch | 🟡 **Open** (env config issue) | `.env` / `OWNER_API_KEY` |

### 🔴 Remaining Open Issues (not fixed this session)

1. **BUG-3 (CV deps)** — Add to `requirements.txt`: `pyzbar`, `pytesseract`, `paddleocr`, `imagehash`. Requires Docker rebuild.
2. **BUG-8 (email auth)** — Set `OWNER_API_KEY` in `.env` to match `config.py`; or set in browser: `localStorage.setItem('ss_owner_key', 'your-key')`.
3. **Product_Identity_Agent** — Not yet implemented. Vision LLM spec extraction for uploaded product images.
4. **Escalation room workflow** — `EscalationRoom.tsx` exists but full human review workflow is incomplete.
5. **GeoIP/ASN + JA4 in fraud scorer** — Signals exist but not wired to fraud score.

---

*Report generated: 2026-03-24 · Fixes applied: 2026-03-24 · Next review: 2026-04-07*
*To flag updates or contradictions, update this document with date stamp.*
