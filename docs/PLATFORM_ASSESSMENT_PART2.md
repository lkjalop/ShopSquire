# ShopSquire Platform Assessment — Part 2
## Security Threat Model, Gaps, Compass Artifact Analysis, RAG, Cost & Recommendations

*Assessment Date: 2026-02-22 | Branch: wip/docker-real-env-20260213*

---

## 1. Security Threat Model

Four principal threat actors. Each gets a full breakdown.

---

### 1.1 Threat Actor: Human Buyers (External Users)

**Attack surface:** Storefront chat, complaint/returns submission, image uploads, voice input

**Active threats and mitigations:**

| Threat | Severity | Existing Control | Gap |
|---|---|---|---|
| Prompt injection via chat | High | write schema guard, regex deny patterns, security_aware_llm.py pre/post check | No token budget enforcement; no output schema validation |
| Return fraud (fake images) | High | CV analysis, serial mismatch (CV02), duplicate image (CV01), fraud scoring | Adversarial JPEG perturbations can defeat OCR |
| Repeat fraudster (identity cycling) | High | repeat_offender_pattern (CV15), trust scoring | No cross-session fingerprinting (device/browser) |
| Excessive returns abuse | Medium | returns_last_30_days threshold, trust tier | Threshold is static; no ML-based anomaly detection |
| PII submission to exploit LLM | High | Client-side PII detection (Luhn, SSN, bank, email) | Client-side only; backend LLM must also reject PII |
| Session hijacking | High | Session tokens with expiry | No device fingerprint binding to session |
| Voice input manipulation | Medium | Voice → text → existing NLP checks | No speaker verification; voice replay attacks possible |
| Image polyglots (PDF-that-is-also-ZIP) | High | intake_gate magic bytes check | PDF polyglot detection explicitly missing |
| Decompression bomb via image | High | intake_gate archive bomb detection | Decompression runs in-process (OOM risk) |
| QR code injection in images | High | BarcodeDecodeResult + QR allowlist | QR allowlist defaults to localhost (dev only) |
| SSRF via user-submitted URLs | Medium | QR URL allowlist | Other URL fields not uniformly SSRF-checked |

**Missing buyer controls:**
1. **Device/browser fingerprinting** — sophisticated fraudsters cycle accounts but reuse devices
2. **Velocity limits per order ID** — single order should allow max N complaint submissions
3. **Sandboxed image processing** — decompression and OCR should run in isolated subprocess/container
4. **CAPTCHA / proof-of-work** for guest submissions (no account = no history = easy abuse)

---

### 1.2 Threat Actor: Human Admin / Insider Threats

**Attack surface:** Admin dashboard (`:3001`), API keys, database access, playbook editor, GDPR exports

**Active threats and mitigations:**

| Threat | Severity | Existing Control | Gap |
|---|---|---|---|
| Privilege escalation | High | RBAC (MERCHANT/OWNER/DEVELOPER), AdminMfaMiddleware | No session re-elevation (privilege stays for session duration) |
| Exfiltration via BI export | High | Role checks on /admin/powerbi/export.csv | No DLP scanning on exported data; no export audit alert |
| Playbook tampering | High | Playbook editor with publish/rollback | No approval workflow before publish (single admin can deploy) |
| Forced reauth bypass | High | security_forced_reauth_flags table | Flag clearing must be admin-only AND audit-logged |
| Credential theft (API key in localStorage) | High | API key stored in browser localStorage | XSS attack → key theft → full API access |
| Audit log tampering | High | Immutable audit_log_chain (Merkle + prev_hash) | Chain integrity verification endpoint not confirmed |
| SQL injection via admin endpoints | High | Parameterized queries (mostly) | Raw SQL in admin endpoints not fully audited |
| Data exfiltration via compliance exports | High | Owner-only role for compliance | No watermarking; exports not logged |
| Stale admin sessions | Medium | Session expiry | No session activity timeout; no concurrent session limit |
| GRC fingerprint export abuse | Medium | Owner-only | No export rate limiting |

**Missing insider threat controls:**
1. **4-eyes principle on playbook publish** — require 2 admin approvals before any playbook goes live
2. **Export DLP** — scan all CSV/JSON exports for bulk PII patterns before delivery
3. **Session activity timeout** — idle sessions > 30 min should require re-auth
4. **Concurrent session limits** — one admin session per user at a time
5. **Break-glass logging** — when owner bypasses checks, explicit audit event with mandatory justification field
6. **Key rotation API** — MERCHANT_API_KEY, OWNER_API_KEY need versioned rotation endpoint

---

### 1.3 Threat Actor: 3rd Party Supplier Attacks (Supply Chain)

**Attack surface:** Email ingest (Gmail/M365), webhook endpoints, inventory sync connector, attachment analysis

**Active threats and mitigations:**

| Threat | Severity | Existing Control | Gap |
|---|---|---|---|
| BEC (Business Email Compromise) | Critical | Multi-signal BEC detection, bank field extraction, vendor baseline matching | Thread analysis depth unclear; no per-supplier behavioral baseline |
| Invoice redirect fraud | Critical | _INVOICE_REDIRECT_PAT, vendor baseline matching | Vendor baseline only catches known vendors |
| Reply-chain hijacking | High | prior_reply_chain_id tracking | Chain analysis depth not confirmed |
| Lookalike domain + homoglyph | High | normalize_domain(), confusable homoglyph detection | Unicode normalization may miss exotic scripts |
| Malicious attachment (macro malware) | Critical | Attachment forensics, LOLBins detection | No sandbox detonation for Office macros in-process |
| Webhook replay attack | High | Timestamp tolerance + replay cache | Local replay cache lost on restart; Redis recommended |
| Shopify webhook spoofing | High | HMAC-SHA256 verification | Multiple webhooks — confirm ALL use HMAC, not just Shopify |
| Inventory connector compromise | High | Sync worker runs with DB write access | No allowlist for acceptable inventory delta ranges |
| C2 beacon via email | High | _C2_BEACON_PAT regex | Regex-only; no network sandbox or DNS analysis |
| Supply chain software compromise | High | admin_supply_chain.py monitoring | Dependency auditing (pip audit) not confirmed |

**Missing supply chain controls:**
1. **Per-supplier behavioral baseline** — track normal email frequency, timing, content patterns per vendor; flag deviation
2. **Out-of-band verification workflow** — when bank change detected, automatically trigger OOB verification (SMS/phone) before any payment update
3. **Supplier onboarding KYV** — Know Your Vendor process with approved domain registry
4. **Inventory delta alerting** — flag inventory changes > X% in single sync as anomalous
5. **Dependency audit in CI** — `pip audit` + `npm audit` in every build

---

### 1.4 Threat Actor: Email BEC / Ransomware / Malware

**This is the most mature threat detection area in the platform.**

**Detection coverage:**

| Threat Vector | Detection Method | Confidence |
|---|---|---|
| BEC (bank change) | _BANK_CHANGE_PAT + bank_fields extraction + vendor baseline | High |
| Spearphishing (reply-to mismatch) | Reply-to domain comparison + homoglyph | High |
| Lookalike domains | normalize_domain() + confusable chars | High |
| Ransomware threat email | _RANSOMWARE_PAT ("your files encrypted", "bitcoin payment") | Medium (regex-only) |
| LOLBins in attachments | _LOLBINS_PAT (certutil, mshta, rundll32, bitsadmin) | High |
| Macro malware | PDF metadata analysis, compression artifacts | Medium |
| C2 beaconing | _C2_BEACON_PAT | Low (keyword-only) |
| Fileless attack | _FILELESS_PAT (invoke-expression, powershell -w hidden) | Medium |
| Data exfiltration request | _EXFIL_PAT | Medium |
| Keylogger deployment | _KEYLOGGER_PAT | Low |
| OAuth phishing | Runbook simulation exists | Unknown |

**Gaps in email security:**
1. **URL detonation is referenced but sandboxing unclear** — `detonation` field in EmailEvaluateResponse suggests sandbox exists, but implementation unknown
2. **DKIM/SPF/DMARC results accepted as strings** — if email gateway is compromised, these can be spoofed
3. **No per-tenant threat intelligence sharing** — similar BEC campaigns across tenants should alert all
4. **Attachment processing in-process** — Office document macros should run in isolated VM
5. **No MISP/OpenCTI integration** — IOC enrichment source not specified (could be internal only)

---

### 1.5 Computer Vision & OCR Capabilities and Threats

**CV Pipeline (what's implemented):**
```
Libraries: OpenCV (headless), Pillow, pytesseract (Tesseract), PaddleOCR, pyzbar (barcodes)

Capabilities:
  - Damage detection (location, severity, confidence)
  - Serial number extraction (OCR + regex)
  - QR/barcode decode (pyzbar)
  - Image forensics (phash, sha256, tampering detection)
  - Duplicate image detection (fraud_image_hashes table)
  - Order ID extraction from images (CV09: ocr_order_id_mismatch)
  - Label reading for return verification
```

**CV Security rules in place:**
- CV01: Duplicate image (phash matching against fraud_image_hashes)
- CV02: Serial mismatch
- CV09: OCR order ID mismatch
- CV13: Return window expired
- CV15: Repeat offender pattern
- CV21: Fraud score high
- CV26: Counterfeit indicator

**CV Attack vectors (threats):**
| Attack | Description | Current Defense | Gap |
|---|---|---|---|
| Adversarial perturbation | JPEG noise that fools OCR but looks normal to humans | None | No adversarial detection |
| Print-and-photograph | Print correct serial, photograph on wrong product | CV02 + image forensics | Camera artifacts analysis would help |
| AI-generated fake images | Synthetic damage photos (Midjourney, FLUX) | Image forensics (compression artifacts) | No GAN/diffusion detection |
| Deepfake receipts | AI-generated order confirmation images | PDF metadata analysis | Limited to PDF; PNG receipts not detected |
| Template manipulation | Reuse legitimate image, edit serial/order ID | phash similarity + edited_regions scoring | edited_regions scoring not confirmed |
| High-volume submission | Flood CV pipeline with valid images | Quota check (TenantQuotaGuard) | Quota limits not specified |
| Image steganography | Hidden payload in valid image | intake_gate (magic bytes) | No steganography detection |
| EXIF data spoofing | Manipulate image metadata to fake authenticity | Not detected | EXIF analysis missing |

**CV Recommendations:**
1. Add **EXIF metadata analysis** (camera make/model, GPS, timestamp consistency)
2. Add **GAN/diffusion detection** — ELA (Error Level Analysis) + frequency domain analysis
3. Isolate image processing in **subprocess/container** (decompression + OCR out of main process)
4. Add **cross-complaint image clustering** (find coordinated fraud campaigns using perceptual hash clusters)
5. Consider **Microsoft Azure AI Vision** or **Google Vision API** as a fallback for edge cases where PaddleOCR fails

---

## 2. Security Controls: What's In vs What's Missing

### 2.1 Implemented Well

```
✅ Multi-layer middleware (11 layers, well-ordered)
✅ HMAC webhook signature verification (Stripe, GitHub, Slack, generic)
✅ Webhook replay prevention (timestamp tolerance + cache)
✅ Write schema guard (allowlists on public endpoints, regex deny on admin)
✅ Intake gate (magic bytes, extension blacklist, archive bomb, prompt injection)
✅ Security-aware LLM wrapper (pre/post check, context sanitization)
✅ Forced reauth enforcement (security_forced_reauth_flags)
✅ Bruteforce detection + impossible travel detection
✅ Bitemporal decision logs (valid_time + system_time)
✅ Immutable audit chain (Merkle root + prev_hash)
✅ PCI boundary enforcement
✅ PII encryption (encrypt_pii(), pii_hash())
✅ Admin MFA enforcement
✅ Role-based access control (3 roles)
✅ Email BEC multi-signal detection (strong)
✅ Attachment forensics (PDF metadata, bank field extraction, vendor baseline)
✅ Homoglyph/lookalike domain detection
✅ CV fraud rules (23 rules, CV01-CV26)
✅ Trust routing with configurable thresholds
✅ Playbook orchestration with DLQ + retry
✅ MITRE ATT&CK tagging in email verdicts
✅ Idempotency middleware for write endpoints
✅ Concurrency limiting (per-IP + per-tenant)
✅ Chaos engineering injection
✅ OpenTelemetry distributed tracing
```

### 2.2 Missing / Gaps (Prioritized)

**P0 — Fix before production:**

1. **CSRF protection** — No anti-CSRF tokens on state-changing endpoints. SameSite cookies may or may not be set. Implement double-submit cookie or synchronizer token.

2. **API keys in localStorage** — `shopsquire_api_key` stored in localStorage is XSS-exfiltrable. Move to `httpOnly` session cookies.

3. **Distributed rate limiting** — Fixed-window in-memory counters reset on pod restart. Use Redis sliding-window via `redis-py` + Lua script.

4. **QR allowlist production config** — Default `{localhost, 127.0.0.1}` must be overridden at deploy time. Production must require `https://` + explicit domain allowlist.

5. **Sandboxed file processing** — CV/OCR and attachment decompression run in-process. Use `multiprocessing` or container sidecar to isolate crash/OOM risk.

**P1 — Fix within sprint:**

6. **CSP headers** — `SecurityHeadersMiddleware` must enforce `Content-Security-Policy: default-src 'self'` to prevent XSS.

7. **Secret rotation** — MERCHANT_API_KEY, OWNER_API_KEY, DEVELOPER_API_KEY need versioned rotation endpoint + rotation schedule documented.

8. **SQL injection audit** — Raw `db.execute(sql_text("..."))` calls in admin endpoints need parameterization review. Use ORM or `bindparams()` explicitly.

9. **4-eyes playbook approval** — Playbook publish must require 2 admin approvals before going live.

10. **Export DLP** — Scan CSV/JSON exports for bulk PII before delivery; log all export events.

**P2 — Plan for next quarter:**

11. **Device fingerprinting** — Bind sessions to browser fingerprint + IP; detect account cycling.

12. **Per-supplier behavioral baseline** — Track normal email patterns per vendor; anomaly score deviation.

13. **OOB verification workflow** — Auto-trigger phone/SMS confirmation for bank change requests.

14. **Dependency auditing in CI** — `pip audit`, `npm audit`, Dependabot alerts.

15. **Audit chain verification endpoint** — Confirm `audit_log_chain` Merkle root is verifiable; expose `/api/v1/admin/audit/verify/{chain_id}`.

---

## 3. Compass Artifact Analysis: What's In, What to Add

The compass artifact describes **Atomic Agent RAG Pipelines** built on three pillars. Here's how ShopSquire maps to each.

### 3.1 Pillar 1: Typed Schemas (BaseIOSchema)

**Compass vision:** Every agent has a `BaseIOSchema` subclass for both input and output. Pydantic validation fires at each handoff — if a planner produces malformed output, the pipeline halts immediately.

**ShopSquire status: ★★☆☆☆ (Partial)**

What exists:
- `EmailEvaluateRequest` / `EmailEvaluateResponse` — well-typed Pydantic models (good)
- `CVAnalyzeRequest` — typed request schema (good)
- `ResumeSchema`, `TriageOutcome`, `FairnessAudit` — typed recruiting schemas (good)
- `trace_contracts.py` — validates trace event shapes (partial)

What's missing:
- No `BaseIOSchema` for the complaint triage pipeline (dict-passing between service calls)
- No typed contract between NLP → CV → FraudScorer → TrustRouting (implicit kwargs)
- No output validation on LLM responses (LLM can return arbitrary structure)
- No schema registry (no way to see all agent contracts at a glance)

**What to add (no latency cost):**
```python
# Add to services/schemas/complaint_triage.py
from pydantic import BaseModel
from typing import Literal, List, Optional

class ComplaintTriageInput(BaseModel):
    complaint_text: str
    order_id: str
    customer_id: Optional[str]
    guest_email: Optional[str]
    issue_type: Literal["refund", "return", "warranty", "quality", "fraud"]
    images: List[ImageMeta] = []
    trace_id: str

class ComplaintTriageOutput(BaseModel):
    intent: ComplaintIntent
    fraud_score: float  # 0-1
    trust_tier: Literal["high_trust", "medium_trust", "guarded", "manual_review"]
    cv_verdict: CVVerdict
    recommended_action: Literal["auto_approve", "auto_reject", "human_review", "escalate"]
    playbook_id: Optional[str]
    reasons: List[str]
    trace_id: str

# Each sub-agent then has its own typed I/O
class NLPAgentInput(BaseModel):
    text: str
    issue_type: str

class NLPAgentOutput(BaseModel):
    intent: ComplaintIntent
    confidence: float
    contract_like: bool
    bec_indicators: List[str]
```

Pydantic validation is **free at runtime** (microseconds). Zero added latency. Zero inference cost. Massive gain in debuggability and error isolation.

### 3.2 Pillar 2: Dynamic Context Injection (BaseDynamicContextProvider)

**Compass vision:** Context providers wrap retrieved document snippets and inject them into agent system prompts at runtime. Hot-swappable — inject threat intel, patient records, or market data without changing agent logic.

**ShopSquire status: ★★☆☆☆ (Ad-hoc)**

What exists:
- `security_aware_llm.py` sanitizes context before LLM calls (good)
- Context dict passed as kwargs (untyped, ad-hoc)
- No formal `ContextProvider` abstraction
- No retrieval step before LLM calls (LLM operates ungrounded)

What's missing and what to add:
```python
# Add to services/context_providers.py
from abc import ABC, abstractmethod
from typing import List
from pydantic import BaseModel

class ContextChunk(BaseModel):
    doc_id: str
    chunk_id: str
    relevance_score: float
    text: str
    source: str  # "product_catalog" | "faq" | "threat_intel" | "order_history"

class BaseContextProvider(ABC):
    @abstractmethod
    async def get_context(self, query: str, top_k: int = 5) -> List[ContextChunk]:
        ...

class ProductCatalogProvider(BaseContextProvider):
    """Retrieves product specs from vector index."""
    async def get_context(self, query: str, top_k: int = 5) -> List[ContextChunk]:
        # TF-IDF or embedding search over product catalog
        ...

class ThreatIntelProvider(BaseContextProvider):
    """Retrieves live IOCs and threat signatures."""
    async def get_context(self, query: str, top_k: int = 5) -> List[ContextChunk]:
        # Query threat intel feed for relevant indicators
        ...

class FAQProvider(BaseContextProvider):
    """Retrieves FAQ answers — cache-augmented for static content."""
    _cache: dict = {}  # Cache FAQs; refresh daily
    async def get_context(self, query: str, top_k: int = 5) -> List[ContextChunk]:
        # Semantic search over FAQ KB
        ...
```

**Runtime cost:** Context retrieval (TF-IDF or embedding search) takes 10-50ms. This replaces the current "send query directly to LLM" with "retrieve relevant context, then send to LLM." Net result: smaller prompts (cost reduction) + grounded answers (quality improvement).

### 3.3 Pillar 3: Agent Chaining (Without Added Latency or Inference Cost)

**Compass vision:** `run_atomic_rag()` orchestrates: planner → retriever → deduplication → context injection → answerer. All control flow is plain Python. Output of one step = input of next, validated against Pydantic contracts.

**ShopSquire status: ★★☆☆☆ (Implicit chaining)**

The chains exist but are encoded as procedural function calls, not typed pipelines:

```python
# Current (implicit, hard to test/parallelize):
intent = ComplaintNLP(text).extract()
if is_contract_like_text(text):
    contract = run_contract_assist(text)
bec = detect_bec_indicators(email, headers)
cv_result = await cv_agent.analyze(images)
fraud = FraudScorer(cv_result, history).score()
trust = compute_trust_score(customer)
action = auto_approve_decision(fraud, trust, cv_result)

# Proposed (typed, parallelizable, testable):
input = ComplaintTriageInput(...)

# Independent chains run in parallel
async with asyncio.TaskGroup() as tg:
    nlp_task = tg.create_task(nlp_chain.run(input))
    cv_task = tg.create_task(cv_chain.run(input))
    trust_task = tg.create_task(trust_chain.run(input))

# Typed merge
verdict = verdict_chain.run(VerdictInput(
    nlp=nlp_task.result(),
    cv=cv_task.result(),
    trust=trust_task.result()
))
```

**Latency impact:** Same total compute work, parallel execution → 2-3x faster.
**Inference cost:** Unchanged (same LLM calls, just concurrent).
**Maintenance benefit:** Each chain is independently testable, loggable, and replaceable.

---

## 4. GLM-4.7, Interleaved Thinking, CacheRAG & TimescaleDB

### 4.1 GLM-4.7 (Interleaved Thinking)

**What GLM-4.7 offers:**
- 355B-parameter MoE (32B active per inference) — cost-efficient
- Three thinking modes: **interleaved** (reason before every tool call), **preserved** (retain reasoning across turns), **turn-level** (toggle per request)
- Benchmarks: 95.7% AIME 2025, 87.4% τ²-Bench tool use, +15.5% web browsing with context management

**ShopSquire applicability:**
- **Interleaved thinking** is directly relevant to the complaint triage pipeline — reasoning before each CV/fraud check step would improve decision quality
- **Preserved thinking** would help the escalation room — agent maintains context across multi-turn investigator conversations without re-deriving it
- **Turn-level toggle** is perfect for the chat agent — disable thinking for simple FAQ queries, enable for fraud analysis

**Cost concern:** GLM-4.7 is a self-hosted MoE model. Running 32B active parameters requires approximately 2x A100 80GB or equivalent. For a self-hosted deployment this is feasible; for cloud inference you'd use the Zhipu API.

**Recommendation:** Do NOT switch to GLM-4.7 as primary model. Instead, use it as a **specialized reasoning node** for the complaint fraud assessment step where decision quality matters most. Use cheaper models (GPT-4o-mini, Haiku 4.5) for FAQ/chat where latency and cost dominate.

**Better alternative for ShopSquire:** Claude Sonnet 4.6 with extended thinking already supports interleaved reasoning between tool calls. Given the codebase's existing Anthropic orientation (the platform is assessed using Claude), enable extended thinking for the security-aware LLM wrapper on high-stakes decisions:

```python
# In security_aware_llm.py
thinking_config = {
    "type": "enabled",
    "budget_tokens": 5000  # 5K thinking tokens for fraud analysis
} if decision_requires_reasoning(context) else {"type": "disabled"}
```

This adds reasoning capability **only when needed**, keeping costs controlled.

### 4.2 Cache-Augmented Generation (CacheRAG)

**What CacheRAG offers:** Pre-load static corpora into extended context cache. 40.5x faster than standard RAG for static content (2.33s vs 94.35s). Zero retrieval latency.

**ShopSquire applicability (HIGH):**

Three content types are perfect for CacheRAG:

| Content | Update frequency | Size | CacheRAG benefit |
|---|---|---|---|
| FAQ knowledge base (`/ui/faq_kb.json`) | Weekly | Small (~50KB) | 40x faster FAQ answers |
| Product catalog specs | Daily | Medium (~500KB) | Grounded product Q&A |
| Security rules/playbook definitions | Monthly | Small (~100KB) | Faster rule evaluation |

**Implementation (using Anthropic prompt caching):**
```python
# Product catalog cached in system prompt prefix
# Anthropic charges $0.30/M for cache writes, $0.03/M for cache reads
# vs $3.00/M for fresh input tokens

client.messages.create(
    model="claude-sonnet-4-6",
    system=[
        {
            "type": "text",
            "text": PRODUCT_CATALOG_TEXT,  # ~50K tokens
            "cache_control": {"type": "ephemeral"}  # 5-minute TTL
        },
        {
            "type": "text",
            "text": SECURITY_RULES_TEXT,
            "cache_control": {"type": "ephemeral"}
        }
    ],
    messages=[{"role": "user", "content": user_query}]
)
```

**Estimated savings:** If product catalog is pre-cached:
- Current: 50K tokens × $3.00/M = $0.15 per query
- With caching: 50K tokens × $0.03/M = $0.0015 per query (100x cheaper)
- At 1,000 queries/day: $150/day → $1.50/day

**This is the highest-ROI single change for inference cost reduction.**

### 4.3 TimescaleDB (Current Status & What to Do)

Currently: bootstrapped (extension created via `/api/v1/admin/db/ensure-timescale`) but **not actually used**. All time-series queries use standard SQL `date_trunc()` / `substr()`.

**Convert these tables to TimescaleDB hypertables:**

```sql
-- Time-series tables that benefit most
SELECT create_hypertable('decision_trace_events', 'created_at',
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE);

SELECT create_hypertable('security_events', 'created_at',
  chunk_time_interval => INTERVAL '1 day');

SELECT create_hypertable('email_security_incidents', 'created_at',
  chunk_time_interval => INTERVAL '1 week');

SELECT create_hypertable('decision_logs', 'created_at',
  chunk_time_interval => INTERVAL '1 week');

-- Continuous aggregate for BI dashboard (replaces manual date_trunc SQL)
CREATE MATERIALIZED VIEW orders_daily
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', created_at) AS day,
       tenant_id,
       count(*) AS order_count,
       sum(amount_cents) AS revenue_cents,
       sum(CASE WHEN status = 'refunded' THEN 1 ELSE 0 END) AS refund_count
FROM orders
GROUP BY day, tenant_id;

-- Add retention policy (prevent unbounded growth)
SELECT add_retention_policy('decision_trace_events', INTERVAL '1 year');
SELECT add_retention_policy('security_events', INTERVAL '2 years');

-- Compression (90%+ space savings for data > 7 days old)
ALTER TABLE decision_trace_events SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'trace_id'
);
SELECT add_compression_policy('decision_trace_events', INTERVAL '7 days');
```

**Benefit:** The `admin_bi.py` timeseries endpoint query drops from O(full table scan) to O(recent chunks). At 1M+ events, this is a 100x query speedup without Kafka or a separate data warehouse.

---

## 5. RAG Strategy: What to Use and When

**Current state: No RAG.** LLM queries are ungrounded — the model hallucinates product details, policy terms, and return rules.

### 5.1 The Right RAG for Each Use Case

| Use Case | Recommended RAG Type | Why |
|---|---|---|
| FAQ answers | **Cache-Augmented Generation (CAG)** | Static content; 40x faster; zero retrieval |
| Product catalog Q&A | **Dense vector RAG** (pgvector or Chroma) | Semantic similarity search over product embeddings |
| Policy/return rules | **CAG** | Static; update weekly |
| Supplier threat detection | **Graph RAG** | Relationships: supplier → known domains → flagged IOCs |
| Fraud pattern matching | **Graph RAG** | Customer → orders → return patterns → fraud signals |
| Decision history ("what did we decide for similar cases?") | **Hybrid (vector + BM25)** | Semantic + keyword for audit queries |
| Real-time threat intel | **Agentic RAG** | Dynamic; agent plans which feeds to query |

### 5.2 Implementation Priority

**Phase 1 (immediate, low cost): CAG for FAQs and product specs**
- Pre-load `faq_kb.json` + product catalog into Anthropic prompt cache
- Eliminates hallucinated product details
- Reduces per-query cost by 100x for cached portions

**Phase 2 (next sprint): pgvector for product similarity**
- PostgreSQL `pgvector` extension (already have PostgreSQL)
- Embed product catalog with `text-embedding-3-small` ($0.02/M tokens)
- At query time: embed user question → cosine similarity → top-5 products
- Cost: one-time embedding of catalog (~$2 for 10K products), then $0.00002 per query

**Phase 3 (next quarter): Graph RAG for fraud and supplier threats**
- Neo4j is already in dependencies (but unused in agents)
- Build entity graph: Customer → Orders → Returns → CVCases → FraudFlags
- Build supplier graph: Supplier → Domains → EmailThreads → BankAccounts → Flags
- Graph traversal finds fraud rings and coordinated campaigns that vector similarity misses

**Phase 4: Agentic RAG for complex queries**
- For multi-step questions ("what's the best product for X use case under $Y with 5-star reviews and free returns?")
- Agent plans: query product catalog → filter by price → check review data → verify return policy → synthesize answer
- This is where LangGraph or atomic agent chaining adds real value

### 5.3 RAGAS Evaluation

`test_ragas_baseline.py` exists. Currently aspirational since RAG doesn't exist. Once Phase 1 is implemented:
- Track: faithfulness (no hallucinations), answer relevancy, context precision, context recall
- Set minimum thresholds per metric in CI (fail build if faithfulness < 0.85)
- Run RAGAS evaluation nightly against a curated test set

---

## 6. What's Missing

### 6.1 Architecture Gaps

**1. No formal agent framework**
ShopSquire's agents are service functions. They work, but they can't be:
- Composed by non-engineers
- Swapped at runtime
- Tested in isolation with typed I/O
- Monitored as distinct units in observability

**Recommendation:** Formalize using Pydantic `BaseModel` input/output + async task groups. Do NOT adopt LangGraph or CrewAI — they add framework complexity without adding value for a vertically-integrated product. Keep it plain Python.

**2. No RAG (addressed in Section 5)**

**3. No model routing/cascading**
All queries go to the same LLM. The compound cost savings from routing 60-70% of simple queries to a cheaper model (Haiku 4.5) while reserving Sonnet/Opus for fraud analysis would be substantial.

```python
# Simple model router
def route_model(query_type: str, complexity_score: float) -> str:
    if query_type == "faq" or complexity_score < 0.3:
        return "claude-haiku-4-5-20251001"  # $0.08/M input
    elif query_type == "product_query" or complexity_score < 0.7:
        return "claude-sonnet-4-6"  # $3.00/M input
    else:
        return "claude-opus-4-6"  # $15.00/M input
```

**4. No semantic caching**
Identical or near-identical queries should be cached. A semantic cache (embed query → cosine similarity → return cached response if similarity > 0.95) eliminates redundant LLM calls for common questions.

**5. No feedback loop from outcomes to model**
Analyst verdicts (`analyst_verdict`, `correction_ts`) exist in the email security schema but aren't yet used to update thresholds automatically. This feedback loop should close: analyst corrections → threshold recomputation → model fine-tuning signal.

**6. No CI/CD pipeline**
No `.github/workflows` or equivalent. A platform with 297 tests and no automated gate is dangerous — engineers can merge broken code.

### 6.2 Feature Gaps

**7. No product knowledge base**
Users ask "does this product work with X?" and the LLM guesses. A RAG-grounded product knowledge base with specs, compatibility, manuals, and reviews would dramatically improve answer quality.

**8. No multi-tenant isolation verification**
`tenant_id` is used throughout but no middleware enforces it universally. A cross-tenant data leak is possible if one endpoint forgets to filter.

**9. No real-time inventory in chat**
"Is this in stock?" queries hit the LLM which can't know. The chat agent needs a real-time inventory tool call.

**10. No proactive security alerts to merchants**
When a BEC campaign is detected, the merchant should get an immediate notification (Slack/email), not just a dashboard update.

---

## 7. Over-Engineering Assessment

**Is ShopSquire over-engineered?** Partially, in specific areas.

### 7.1 Appropriately Complex (keep it)

- **11-layer middleware stack:** Each layer has a clear, non-overlapping responsibility. Removing any would create a gap. Keep.
- **Bitemporal decision logs:** Critical for compliance. The bitemporal model is industry-standard for regulated industries. Keep.
- **Immutable audit chain (Merkle):** Justified for tamper-evidence in financial/legal contexts. Keep.
- **Email XDR with MITRE ATT&CK tagging:** Sophisticated but the e-commerce attack surface is real. BEC causes billions in losses annually. Keep.
- **Decision Trace UI:** The 3-streaming-mode, 4-tab, draggable/detachable trace viewer is genuinely useful for operators and investigators. Keep.
- **89 routers:** This is a lot, but e-commerce is genuinely complex (payments, orders, CV, email, compliance, analytics). Not over-engineered — just comprehensive.

### 7.2 Likely Over-Engineered (simplify)

- **Recruiting module:** A full recruiting pipeline with fairness audits is not a natural fit for a shopping assistant. It reads as a proof-of-concept for the agent framework, not a business requirement. Unless there's a clear customer for this, move to a separate repository.

- **18+ admin panels:** The admin UI has panels for Grafana proxy, DMARC, GRC, compliance registry, drift detection, fairness audits, supply chain monitoring, interleaving experiments, and more. An early-stage product doesn't need all of these simultaneously. Consider feature-flagging most of them and activating on customer demand.

- **Chaos engineering in production middleware:** `chaos_error_injection` in the main request path is appropriate for testing environments but should be **removed from production middleware**. Move to a testing harness only.

- **TenantQuotaGuard for CV:** Quota management is right but the implementation may be premature if there's only one tenant. Build it when multi-tenancy goes live.

- **RAGAS evaluation tests without RAG:** `test_ragas_baseline.py` tests a system that doesn't have RAG. This is aspirational test-writing, which is fine for documentation purposes but misleading in a test suite.

### 7.3 Things That Are Wrong (not just missing — actively problematic)

1. **API keys in localStorage** — this is a security anti-pattern. Any XSS attack (including third-party widget injection in admin browser) exfiltrates the key.

2. **Merchant dashboard unauthenticated on localhost** — The `ALLOW_UNAUTH_MERCHANT_DASHBOARD` flag and loopback IP check is fine for dev but the code comment says "local demo mode." This must be guaranteed-off in production, not just configured-off.

3. **In-memory rate limiting** — Rate limit state in a dict on each pod. In a multi-pod deployment, each pod has independent state. An attacker with knowledge of the deployment can bypass rate limits by routing requests across pods.

4. **Trace event in-memory cache (256 events/trace)** — If a pod restarts mid-investigation, the trace is lost. The decision trace UI will show incomplete data. This should be Redis-backed.

5. **`TEST_BYPASS_POLICY_GATE: true` in default feature_flags.json** — This should NEVER be `true` in a config file that ships with the codebase. If it accidentally propagates to a production environment (config file deployed without override), policy gates are silently disabled.

6. **No output schema validation on LLM responses** — If the LLM returns malformed JSON or unexpected structure, the service likely throws an unhandled exception or silently uses wrong data. Pydantic validation on LLM output is essential.

7. **Frontend has zero unit tests** — A React app with complex state (PII detection, streaming, multi-panel routing, CV evidence display) that has never been unit-tested is a reliability risk. A single refactor can break PII detection silently.

8. **No CI/CD gate** — All 297 tests exist but there's no evidence they run automatically on every commit. This makes them documentation, not quality gates.

---

## 8. Priority Improvement Roadmap

### Week 1 (Security P0)
```
□ Move API keys from localStorage to httpOnly session cookies
□ Add CSRF protection (double-submit cookie)
□ Override QR allowlist for production deployment
□ Distribute rate limiting to Redis (sliding window)
□ Set TEST_BYPASS_POLICY_GATE: false in feature_flags.json
□ Remove chaos injection from production middleware path
```

### Week 2-3 (Agent Formalization)
```
□ Add typed Pydantic BaseModel I/O to complaint triage pipeline
□ Add typed I/O to email security pipeline
□ Parallelize complaint triage (asyncio.TaskGroup for NLP + CV + trust)
□ Add output schema validation to security_aware_llm.py LLM calls
□ Add token budget enforcement to LLM wrapper
```

### Month 1 (RAG + Cost)
```
□ Implement CAG: cache product catalog + FAQ in Anthropic prompt cache
□ Add pgvector extension to PostgreSQL
□ Embed product catalog (one-time, ~$2)
□ Implement product similarity search endpoint
□ Implement model router: haiku for FAQ/simple, sonnet for complex, opus for fraud
□ Add semantic cache for chat queries (Redis + embedding similarity)
```

### Month 2 (TimescaleDB + Observability)
```
□ Convert decision_trace_events, security_events to hypertable
□ Create continuous aggregate for orders BI dashboard
□ Add data retention policies (1-2 years depending on table)
□ Add compression policy for cold data
□ Set up SLO dashboards (error budget burn rate) in Grafana
□ Add CI/CD pipeline (.github/workflows) with test gate
```

### Quarter 2 (Graph RAG + Feedback Loop)
```
□ Build customer fraud graph in Neo4j (Customer → Orders → Returns → Flags)
□ Build supplier threat graph (Supplier → Domains → BankAccounts → IOCs)
□ Implement feedback loop: analyst corrections → threshold recomputation → RAGAS eval
□ Add EXIF metadata analysis to CV pipeline
□ Add GAN/diffusion detection to CV pipeline (ELA + frequency domain)
□ Implement 4-eyes playbook approval workflow
□ Add per-supplier behavioral baseline for email security
```

---

## 9. Final Assessment: How Good Is This Platform?

### Against the 2026 Agentic Landscape

ShopSquire occupies a **distinctive niche** that no existing framework covers:

**No one else combines:**
- Email XDR (BEC/ransomware detection)
- CV-based return fraud analysis
- Bitemporal compliance audit trails
- Real-time human escalation rooms
- MITRE ATT&CK-tagged decision traces
- Playbook orchestration with DLQ
- Fairness auditing for AI decisions

...in a **self-hosted, open, vertically-integrated e-commerce platform**.

This is genuinely differentiated. Salesforce Agentforce is SaaS-only and doesn't have the security depth. Microsoft Copilot Studio has the security depth (Azure Sentinel) but not the e-commerce triage. Zendesk AI has e-commerce but no XDR. None of them have the audit trail depth.

### What's Actually Wrong

The platform is **sophisticated in the wrong direction for its stage**. It has:
- Enterprise-grade compliance features (bitemporal logs, Merkle chains) — but no RAG
- 297 backend tests — but zero frontend tests
- Full email XDR — but no CI/CD gate
- TimescaleDB bootstrapped — but not actually used
- RAGAS tests — but no retrieval system
- Neo4j in dependencies — but no knowledge graph

The pattern is: **infrastructure over-prepared, core intelligence under-developed**.

The platform needs to ship RAG before shipping Graph RAG. It needs model routing before interleaved thinking. It needs semantic caching before CacheRAG optimization. **Foundation first.**

### Closing Recommendation

The compass artifact's atomic agent pipeline model is the right target architecture. The implementation order is:
1. **Typed I/O schemas** (Pydantic BaseModel at every agent handoff) — zero cost, immediate debuggability
2. **CAG for static content** (FAQ + product catalog in prompt cache) — 100x cost reduction
3. **Model routing** (haiku/sonnet/opus by query complexity) — 60-70% cost reduction
4. **Parallel agent dispatch** (asyncio.TaskGroup for independent sub-tasks) — 2-3x latency reduction
5. **pgvector semantic search** (product Q&A grounding) — eliminates hallucination
6. **Graph RAG** (fraud rings, supplier networks) — only then does Neo4j pay its infrastructure cost

Do not chase GLM-4.7 interleaved thinking or Kimi K2 agent swarms until steps 1-4 are done. The bottleneck is not model capability — it's retrieval grounding and agent formalization. No amount of sophisticated in-context reasoning compensates for an LLM that doesn't know what products you sell.

---

*Part 1 covers: Architecture, Agents, Frontend, Observability, Parallelism, Test Infrastructure, Platform Comparison, TimescaleDB.*
*Part 2 covers: Threat Model, Security Gaps, Compass Artifact Analysis, RAG Strategy, GLM-4.7/CacheRAG, What's Missing, Over-Engineering, Priority Roadmap.*
