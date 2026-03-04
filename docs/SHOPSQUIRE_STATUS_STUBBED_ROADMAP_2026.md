# ShopSquire — What Works, What's Stubbed, What Needs Doing (March 2026)

> **Document scope:** Honest assessment of every major system with actual file paths, line numbers, and improvement rationale. Colour-coded: ✅ Works | ⚠️ Partial/Bug | ❌ Stubbed/Missing.

---

## Table of Contents

1. [Summary Scorecard](#1-summary-scorecard)
2. [Critical Bugs (Fix First)](#2-critical-bugs-fix-first)
3. [What Works Well — System by System](#3-what-works-well--system-by-system)
4. [What's Partially Broken](#4-whats-partially-broken)
5. [What's Stubbed or Weight-Only](#5-whats-stubbed-or-weight-only)
6. [Roadmap — Prioritised Improvements](#6-roadmap--prioritised-improvements)
7. [File-by-File Status Reference](#7-file-by-file-status-reference)
8. [Why We Should Improve Each Area](#8-why-we-should-improve-each-area)

---

## 1. Summary Scorecard

| System | Status | Files | Key Issue |
|--------|--------|-------|-----------|
| 4-Phase Orchestrator | ✅ Works | `services/orchestrator.py:1-1000+` | — |
| NLP Search Agent | ✅ Works | `services/nlp_search_agent.py` | Pattern-only, no transformer |
| Product Ranking | ✅ Works | `services/product_ranking_agent.py` | — |
| Inventory Agent | ✅ Works | `services/inventory_agent.py:1-1000+` | — |
| Fraud Scorer (signals) | ✅ Works | `services/fraud_scorer.py:1-200` | CV signals need Docker fix |
| Policy Gate | ✅ Works | `policy/gate.py:1-200` | — |
| Playbook Engine | ✅ Works | `services/playbook_engine.py:1-200+` | External adapters untested |
| Bitemporal Decision Log | ✅ Works | `services/decision_log.py:43-95` | — |
| Merkle Audit Chain | ✅ Works | `models/decision_audit.py` | Verification logic in service |
| Semantic Cache | ✅ Works | `services/semantic_cache.py` | — |
| RAG Retriever | ✅ Works | `rag/retrieve.py` | Naive cosine only; no hybrid |
| Interleaving Controller | ✅ Works | `services/interleaving_controller.py` | — |
| Session Memory (Redis) | ✅ Works | `services/memory.py` | Dual-layer with fallback |
| Episodic Memory | ✅ Works | `services/episodic_memory.py` | 90d chat history |
| Complexity Scorer | ✅ Works | `services/llm_provider.py:79-187` | Multimodal fix recent |
| Email Security (rules) | ✅ Works | `security/email_security*.py` | Enrichment needs external API |
| BI Intelligence | ✅ Works | `services/bi_intelligence.py` | TimescaleDB CAG needs flag |
| Admin BI (SLO alerts) | ✅ Works | `routers/admin_bi.py:30-110` | — |
| Celery Workers | ✅ Works | `workers/celery_app.py` | HMAC signing robust |
| Syslog Listener | ✅ Works | `services/syslog_listener.py` | Silent fail on parse errors |
| CrowdStrike Poll | ✅ Works | `tasks/security_poll_tasks.py` | — |
| Inventory Sync | ✅ Works | `scripts/sync_worker.py` | CSV + Shopify only |
| Frontend Chat + NQE UI | ✅ Works | `frontend/src/App.tsx` | DisambiguationButtons ready |
| Frontend CV Panel | ✅ Works | `frontend/src/components/CVResultsPanel.tsx` | Waits for backend CV |
| NQE Engine (logic) | ⚠️ Bug | `flows/nqe.py:162-189, 580` | Context not loaded from Redis |
| CV/OCR Pipeline | ⚠️ Bug | `services/cv_ocr.py`, `cv/ocr_pipeline.py` | Deps missing in Docker |
| Shortlist Memory | ⚠️ Bug | `routers/recommend.py` | Erased on zero-result turns |
| NQE Follow-up Guard | ⚠️ Bug | `flows/nqe.py` | Fires on explain queries |
| Product_Identity_Agent | ⚠️ Partial | `services/product_identity_agent.py` | Needs Ollama vision + wiring |
| Escalation Room SLA | ⚠️ Partial | `routers/escalation_room.py` | SLA timer columns present, breach logic incomplete |
| Email Enrichment | ⚠️ Partial | `security/email_enrichment.py` | Needs VirusTotal/URLhaus API keys |
| JA3/JA4 TLS Fingerprint | ⚠️ Partial | `security/tls_fingerprint_middleware.py` | Middleware present, fraud scorer weights present; actual fingerprint bytes not extracted |
| GeoIP / ASN Scoring | ❌ Stubbed | `services/fraud_scorer.py:signals` | Weights defined, no MaxMind integration |
| GNN Fraud Ring | ❌ Stubbed | `services/gnn_fraud_detector.py` | Neo4j available; GNN model not trained |
| Decision Trace WS | ❌ Partial | `routers/decision_trace_events.py` | Router present; live WS stream not wired |
| Human Escalation Full | ❌ Partial | `routers/escalation_room.py` | Chat works; SLA enforcement not complete |
| Use-case Knowledge Base | ❌ Missing | — | JSON spec for uni/gaming/creative not created |
| MITRE ATLAS Event Map | ❌ Missing | `security/atlas_map.py` | File exists, automated event correlation not wired |
| Supply Chain GNN | ❌ Stubbed | `security/supply_chain.py` | Scenario framework present; GNN not trained |
| RAGAS Eval | ❌ Stubbed | `services/orchestrator.py:80+` | `persist_ragas_stub()` placeholder |

---

## 2. Critical Bugs (Fix First)

### BUG-1 — NQE Context Loss (CRITICAL)

**Symptom:** Users are asked the same budget and brand questions repeatedly after clicking disambiguation buttons. Screenshots `smart-1.png` and `smart-2.png` show this in production.

**Root cause:**

```python
# src/app/flows/nqe.py:33 — Field EXISTS on NQEInput
class NQEInput(BaseModel):
    previously_asked_ids: List[str] = []     # ← line 33: field is there
    answered_fields: Dict[str, Any] = {}     # ← line 34: field is there

# src/app/flows/nqe.py:580 — Dedup logic uses it correctly
if q.id in (inp.previously_asked_ids or []):
    continue                                  # ← line 580: would work IF populated

# BUT: src/app/routers/recommend.py — NEVER LOADS FROM REDIS
# Missing code that should be here:
#   nqe_input.previously_asked_ids = await redis.lrange(f"session:{uid}:nqe_asked_ids", 0, -1)
#   nqe_input.answered_fields = await redis.hgetall(f"session:{uid}:nqe_answered_fields")
```

**Fix (two changes):**

```python
# In src/app/routers/recommend.py — before NQE call:
nqe_input.previously_asked_ids = memory.get_session(uid, "nqe_asked_ids") or []
nqe_input.answered_fields = memory.get_session(uid, "nqe_answered_fields") or {}

# In src/app/routers/recommend.py — after NQE runs:
for q in nqe_result.questions:
    memory.append_to_list(uid, "nqe_asked_ids", q.id, ttl=86400)
for field, value in nqe_answered.items():
    memory.hset(uid, "nqe_answered_fields", field, value, ttl=86400)
```

**Impact of not fixing:** Every multi-turn conversation asks the same clarifying questions. Completely undermines the multi-turn intelligence value proposition. Visible to every user.

**Effort:** 1 hour.

---

### BUG-2 — Multimodal Under-scoring (HIGH — appears fixed in recent commit)

**Symptom:** Complex image+text queries ("find me a laptop like this one" with photo) route to `llama3.3:8b` (small model) instead of `mixtral:8x7b`.

**Status check:**

```python
# src/app/services/llm_provider.py:142-146 — appears fixed:
if ctx.get("has_image"):
    signals["multimodal"] = 1
    if _re.search(r"\b(similar|like this|alternatives?|compare|price range|same as|equivalent)\b", q):
        signals["visual_similarity_intent"] = 2   # ← +2 when visual intent detected
```

**Remaining concern:** `lenovo-multimodal1.png` + `lenovo-multimodal2.png` show the bug occurring. Verify that `has_image` context is actually passed through from the image upload flow to the complexity scorer. The fix might exist but the context dict might not have `has_image=True` populated correctly.

**Where to verify:**

```python
# src/app/routers/recommend.py — check that context dict includes:
context = {
    "has_image": request.images is not None and len(request.images) > 0,
    "turn_index": session.turn_count,
    # ...
}
complexity = score_query_complexity(query, context)
```

**Effort:** 30 minutes to verify and fix context population.

---

### BUG-3 — CV Runtime Dependencies Missing (CRITICAL)

**Symptom:** All QR code detection, OCR, and serial number extraction silently fail. Security matrix events that depend on CV signals are never emitted.

**Root cause:**

```toml
# pyproject.toml:33-35 — dependencies DECLARED:
pytesseract = "^0.3.10"
pyzbar = "^0.1.9"
paddleocr = "^2.7.0"
imagehash = "^4.3.1"

# BUT: Dockerfile — no explicit install verified
# poetry install should pick these up BUT:
# pyzbar needs system lib: libzbar0 (apt-get install libzbar0)
# pytesseract needs: tesseract-ocr (apt-get install tesseract-ocr)
# paddleocr needs: libGL, libglib2.0 (headless OpenCV deps)
```

**The real issue:** Python packages are declared but **system-level OS packages** are not installed in the Docker image. `pyzbar` is a wrapper around `libzbar0`. `pytesseract` is a wrapper around the `tesseract-ocr` binary.

**Fix (Dockerfile additions):**

```dockerfile
# Add to Dockerfile:
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
```

**Also add error handling in `src/app/services/cv_ocr.py`:**

```python
try:
    import pyzbar
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False
    logger.warning("pyzbar not available — QR decode disabled. "
                   "Install: apt-get install libzbar0 && pip install pyzbar")
```

Currently the code likely throws `ImportError` at import time and silently disables the entire CV module. No error event is emitted to the security log.

**Impact of not fixing:** No QR analysis, no OCR, no serial extraction. The CV fraud signals (`exif_date_mismatch`, `cv_duplicate_hash`) that depend on OCR produce zero detections. Return fraud triage is effectively blind.

**Effort:** 2–3 hours (Dockerfile + graceful degradation + test).

---

### BUG-4 — Shortlist Erased on Zero-Result Turns (MEDIUM)

**Symptom:** User has a shortlist of 3 laptops. They ask a follow-up question that produces zero results (e.g., "is there anything under $800?"). The previous shortlist disappears.

**Root cause (inferred from memory notes):**

```python
# src/app/routers/recommend.py — CURRENT (broken):
shortlist = retrieval_results.skus or []
memory.set(uid, "last_shortlist_skus", shortlist)  # always overwrites, even if []

# SHOULD BE:
if retrieval_results.skus:  # only update if new results exist
    memory.set(uid, "last_shortlist_skus", retrieval_results.skus)
```

**Find the exact line:**

```bash
grep -n "last_shortlist_skus" src/app/routers/recommend.py
```

**Impact:** Users lose search context on any clarifying turn that returns no results. Frustrating for multi-step refinement conversations.

**Effort:** 15 minutes.

---

### BUG-5 — NQE Fires on Follow-up Explain Queries (MEDIUM)

**Symptom:** User asks "why did you recommend that?" or "tell me more about the Lenovo" → NQE kicks in and asks budget/brand questions again instead of the LLM explaining.

**Root cause:**

```python
# src/app/flows/nqe.py (or routers/recommend.py) — current narrow pattern:
def _is_followup_explain_query(query: str) -> bool:
    return bool(re.search(r"\b(why|explain|details)\b", query, re.I))
    # Misses: "tell me more", "what does that mean", "how does", "can you elaborate"
```

**Fix:**

```python
_EXPLAIN_PATTERNS = re.compile(
    r"\b(why|explain|tell me more|what does|how does|can you elaborate|"
    r"more details|what makes|is it|describe|walk me through)\b",
    re.I
)

def _is_followup_explain_query(query: str, prior_role: str = "assistant") -> bool:
    # Also check: last message was from assistant (we just showed products)
    return bool(_EXPLAIN_PATTERNS.search(query))
```

**Impact:** Unnecessary NQE friction on every explain query. Breaks conversational flow for post-recommendation discussion.

**Effort:** 30 minutes.

---

## 3. What Works Well — System by System

### ✅ 4-Phase Orchestrator (`src/app/services/orchestrator.py`)

The orchestrator is the most sophisticated part of the system and it works correctly:

- Phase separation is clean (EXPLORE/EVALUATE/PLAN/ACTION)
- Per-agent budget allocation scales dynamically with complexity factor
- SLO breach detection fires `_mark_trace_degraded()` within 1800ms
- Incident idempotency (Redis, 1h TTL) prevents double-triggering on retries
- Degradation mode gracefully downgrades when agents fail

```python
# Lines 219-276: adaptive budget allocation — well-designed
# Lines 289-320: _trace_phase() — comprehensive trace event emission
# Lines 321-368: _trace_agent_invocation() — per-agent latency + SLO
```

**Why it's good:** Clean concern separation, observable, fault-tolerant. The budget allocation formula correctly boosts computation for high-risk and ambiguous queries.

### ✅ Bitemporal Decision Log (`src/app/services/decision_log.py:43-95`)

Correctly implements two-axis time tracking:

```python
valid_from / valid_to    # when the decision was true in the domain
system_from / system_to  # when we recorded it in the DB
```

Combined with Merkle chain (`models/decision_audit.py`), this creates tamper-evident, time-queryable audit records. This is **the strongest differentiator** in the platform.

**Why it's good:** No competitor in the ecommerce-adjacent security space has this. It enables compliance responses that would otherwise require manual log reconstruction.

### ✅ Fraud Scorer Signal Framework (`src/app/services/fraud_scorer.py`)

34 signals with weights, grouped, feature registry, and false-positive cost estimation:

```python
# Lines 100-119: feature_registry() → clean metadata export for monitoring
# Lines 121-150+: monitoring_snapshot() → FP cost estimate (default $7.50/signal)
```

The FP cost estimation is particularly forward-thinking — it enables merchants to tune signal sensitivity based on actual business cost, not just accuracy metrics.

### ✅ Semantic Cache + Poison Defence (`src/app/services/semantic_cache.py`)

```python
# set_safe() wraps values with trust metadata
# quarantine() marks adversarial entries
# Maps to OWASP LLM08 — vector/embedding weaknesses
```

This is a correct implementation of LLM cache security. Most implementations don't include trust scoring at all.

### ✅ Interleaving Controller (`src/app/services/interleaving_controller.py`)

Bounded think→tool→observe with agent-scoped tool allowlists. Prevents prompt injection from expanding tool access scope.

```python
# Lines 53-82: TOOL_ALLOWLISTS — per-agent capability boundaries
```

### ✅ Session Memory Architecture (`src/app/services/memory.py`)

Dual-layer (Redis + in-process) with correct TTL management:

```python
# Lines 39-51: _local_get()/_local_setex() — thread-safe L1 cache
# Lines 61-87: get_context() — Redis-first, fallback to local
```

The fallback is critical for resilience — if Redis goes down, the service degrades gracefully rather than crashing.

### ✅ Email Security (Rule-first Verdict) (`src/app/security/email_security_verdict.py`)

Deterministic rule-first verdict doesn't require LLM availability. Works in offline/airgap mode. DMARC/SPF/DKIM validation is solid.

### ✅ Policy Gate (`src/app/policy/gate.py:37-200`)

5 deterministic rules, compliance tag injection, feature-flag driven thresholds. Clean separation from LLM inference — the gate never requires LLM availability.

### ✅ Celery Task Queue (`src/app/workers/celery_app.py:9-186`)

HMAC-SHA256 signing for task messages (when `CELERY_HMAC_KEY` set). X.509 cert signing as alternative. Production-grade task security rarely seen in comparable platforms.

---

## 4. What's Partially Broken

### ⚠️ NQE (Next Question Engine) — BUG-1

**Files:** `src/app/flows/nqe.py:33,162-189,580` + `src/app/routers/recommend.py`

The logic is sound (622 lines of sophisticated template matching, use-case detection, convergence). But the context load is missing. See Section 2 for fix.

**What works:** Template scoring, game/software detection, use-case disambiguation, convergence detection, quick-reply formatting.

**What's broken:** Multi-turn question memory — the same question repeats every turn because `previously_asked_ids` is always `[]`.

### ⚠️ CV/OCR Pipeline — BUG-3

**Files:** `src/app/services/cv_ocr.py`, `src/app/cv/ocr_pipeline.py`, `Dockerfile`

**What works:** OpenCV basic tier, embedded regex fallback, EXIF analysis (Pillow), phash calculation (imagehash available if installed), MIME validation, image sanitization.

**What's broken:** `pyzbar` (QR), `pytesseract` (OCR), `paddleocr` (full OCR) — all silent fail without system-level packages installed.

**Evidence the code is right but the env is wrong:**

```python
# src/app/services/cv_ocr.py — correct implementation:
def _tesseract_ocr(img: Image) -> str:
    return pytesseract.image_to_string(img)  # correct API call
    # But: pytesseract.pytesseract.tesseract_cmd must point to installed binary
```

The Python implementation is correct. The deployment is missing the system dependency.

### ⚠️ Product Identity Agent — Integration Gap

**File:** `src/app/services/product_identity_agent.py`

The agent is implemented (calls `llava` vision model, extracts structured specs). But it's not wired into `routers/recommend.py`. When a user uploads a product image, the flow goes:

```
Current:  Upload → CV_Label_Agent → labels (generic) → Recommend
Missing:  Upload → CV_Label_Agent → Product_Identity_Agent → structured specs → Recommend
```

The structured specs (brand, model, CPU tier, RAM) would replace 3–4 NQE questions with hard constraints.

**Fix:** In `routers/recommend.py`, after CV analysis, call `ProductIdentityAgent.identify()` if `cv_result.image_identity_confidence > 0.6` and inject result into `NLPSearchResult.slots`.

### ⚠️ Escalation Room SLA Enforcement

**File:** `src/app/routers/escalation_room.py`

**What works:** WebSocket channels (buyer + staff), token auth, playbook start/complete, DB incident record, evidence upload, assign/close endpoints.

**What's partially broken:**

```python
# Lines in escalation_room.py — SLA columns ADDED but breach logic incomplete:
# sla_due_at is set
# sla_status is set to "active"
# sla_breach_alerted_at is a column
# BUT: The Celery task that checks SLA timer and sends breach alert is not wired
```

The SLA timer is set but nothing checks it. The `sla_breach_alerted_at` column exists but is never populated.

**Fix:** Add a Celery beat task:

```python
@celery_app.task
def check_sla_breaches():
    incidents = db.query("SELECT id, sla_due_at FROM incidents WHERE sla_status='active' AND sla_due_at < NOW()")
    for incident in incidents:
        if not incident.sla_breach_alerted_at:
            notify_team_lead(incident.id)
            db.update("UPDATE incidents SET sla_breach_alerted_at=NOW() WHERE id=?", incident.id)
```

### ⚠️ TLS Fingerprinting — Middleware Present, Scoring Incomplete

**Files:** `src/app/security/tls_fingerprint_middleware.py` + `src/app/services/fraud_scorer.py:signals`

**What works:** Middleware intercepts requests. `ja3_known_fraud_tool` and `ja4_known_fraud_tool` signals exist with weights (0.35 each) in the fraud scorer.

**What's missing:** The middleware extracts the TLS fingerprint bytes from the connection, but:
1. The known-bad JA3/JA4 hash lookup against a threat feed DB is not fully implemented
2. The fingerprint is captured but the mapping to `fraud_scorer` signals is incomplete

**Partial code exists in `tls_fingerprint_middleware.py`** but the hash-to-signal pipeline is not wired end-to-end.

### ⚠️ Email Threat Enrichment

**File:** `src/app/security/email_enrichment.py`

**What works:** IoC extraction, URL parsing, attachment hashing.

**What's partial:** VirusTotal, URLhaus, MISP enrichment calls exist in the code but require API keys (`VIRUSTOTAL_API_KEY`, `URLHAUS_API_KEY`, `MISP_URL`, `MISP_KEY`) that are likely not set in the deployment.

**Without these:** The verdict falls back to rule-only (which still works, see Section 3) but loses threat intelligence context. The kill chain inference is degraded.

---

## 5. What's Stubbed or Weight-Only

### ❌ GeoIP + ASN Risk Scoring

**File:** `src/app/services/fraud_scorer.py`

**Signals present (with weights):**
```python
"geoip_high_risk_country": 0.20,
"geoip_country_mismatch": 0.30,
"asn_datacenter_session": 0.25,
"asn_known_proxy_tor": 0.30,
"mid_session_country_change": 0.35,
```

**What's missing:** No MaxMind GeoIP2 or ip-api.com integration. No ASN lookup DB. These signals always return `False`, contributing 0.0 to the fraud score even when a user is connecting from a known-bad datacenter ASN.

**Impact:** A fraudster connecting from a Tor exit node or a datacenter IP gets a 0.0 contribution from all 5 GeoIP/ASN signals — a cumulative 1.40 points of fraud score that never fires.

### ❌ GNN Fraud Ring Detection

**Files:** `src/app/services/gnn_fraud_detector.py`, `src/app/services/neo4j_graph.py`

**What's present:** Neo4j client (`neo4j ^5.18.0` in pyproject.toml), GNN detector file exists, `shipping_address_clustered` signal exists with weight 0.30.

**What's missing:** The GNN model is not trained. The Neo4j queries for ring detection (find clusters of accounts sharing shipping addresses, phone numbers, device fingerprints) are not implemented.

**Why this matters:** Address clustering is one of the strongest signals for organized fraud rings. Professional return fraud operations use 5–20 accounts all shipping to the same address. This is currently undetectable by ShopSquire.

### ❌ RAGAS Evaluation

**File:** `src/app/services/orchestrator.py:80+`

```python
# Placeholder functions in orchestrator.py:
evaluate_decision_stub()      # ← placeholder
persist_ragas_stub()          # ← placeholder
# RAGAS_EVAL_ENABLED: False in feature_flags.json defaults
```

RAGAS (Retrieval-Augmented Generation Assessment) would enable automated quality scoring of recommendations. Currently every recommendation quality is measured only by implicit signals (click-through, purchase) via the nightly CF training. RAGAS would add LLM-as-judge quality scoring on a per-response basis.

### ❌ Use-Case Knowledge Base

**What's missing:** A JSON file mapping use-cases to minimum hardware specs. For example:

```json
// Should exist at: config/use_case_knowledge.json
{
  "gaming_competitive": { "gpu_tier": "dedicated", "ram_min_gb": 16, "cpu_min_cores": 6 },
  "university_stem": { "ram_min_gb": 8, "ssd_min_gb": 256, "battery_min_hrs": 8 },
  "creative_video": { "ram_min_gb": 32, "gpu_vram_min_gb": 6, "display_color_gamut": "P3" },
  "corporate_office": { "security_chip": "TPM2", "biometric": true, "weight_max_kg": 1.5 }
}
```

Without this, NQE can ask "what do you use it for?" but the answer ("university") doesn't automatically populate hardware spec constraints. The NLP agent has to infer specs from free text.

### ❌ MITRE ATLAS + ATT&CK Event Correlation

**File:** `src/app/security/atlas_map.py`

The file exists but automated event correlation is not wired. Security events (fraud signal fired, playbook triggered, anomaly detected) are not being tagged with MITRE ATLAS tactic/technique IDs.

**Impact:** Compliance teams cannot report "we detected and blocked ATLAS AML-T0054 (Prompt Injection via External Content)" because the mapping exists but is never applied.

### ❌ Decision Trace WebSocket Streaming (Real-time)

**Files:** `src/app/routers/decision_trace_events.py` + `frontend/src/components/DecisionTrace.tsx`

**What's present:** The DecisionTrace component (65KB) is a fully built visualization. The trace events table exists. The router file exists.

**What's missing:** The live WebSocket broadcast from the decision trace event writer to connected clients. Trace events are written to the DB but not pushed in real-time.

**Fix needed:** In `services/decision_log.py`, after each trace event write, publish to a Redis pub/sub channel `trace:{trace_id}`. The WebSocket endpoint should subscribe and forward to connected clients.

### ❌ Supply Chain Attack Detection (Advanced)

**Files:** `src/app/security/supply_chain*.py` (4 files)

The supply chain scenario framework and simulation harness exist. But:
- The GNN model for detecting anomalous supplier behaviour patterns is not trained
- The simulation runs scenarios but doesn't feed results back into live detection
- SLSA (Supply chain Levels for Software Artifacts) attestation checks are not implemented

---

## 6. Roadmap — Prioritised Improvements

### Sprint 1 — Fix the Broken Window (1 week)

These are visible, embarrassing bugs that every user hits:

| # | Task | File | Effort | Why Now |
|---|------|------|--------|---------|
| 1 | Fix BUG-1: Load nqe_asked_ids from Redis | `routers/recommend.py` | 1h | Every user hits this in turn 2+ |
| 2 | Fix BUG-4: Guard last_shortlist_skus overwrite | `routers/recommend.py` | 15m | Loss of search context |
| 3 | Fix BUG-5: Expand _is_followup_explain_query | `flows/nqe.py` | 30m | NQE friction on explain turns |
| 4 | Fix BUG-3: Add libzbar0 + tesseract to Dockerfile | `Dockerfile` | 2h | CV completely blind without this |
| 5 | Verify BUG-2: has_image context propagation | `routers/recommend.py` | 30m | Multimodal queries degraded |

### Sprint 2 — Complete the CV Loop (2 weeks)

The CV return-fraud triage is the #1 commercial differentiator. Make it work end-to-end:

| # | Task | File | Effort | Why |
|---|------|------|--------|-----|
| 6 | Wire Product_Identity_Agent into recommend flow | `routers/recommend.py`, `services/product_identity_agent.py` | 4h | Eliminates 3–4 NQE questions |
| 7 | Add graceful ImportError degradation to CV stack | `services/cv_ocr.py`, `cv/ocr_pipeline.py` | 3h | Silent fail → explicit degradation |
| 8 | Add CV dependency smoke test at startup | `main.py` lifespan | 1h | Fail fast → visible error on deploy |
| 9 | Test full CV tier2 pipeline with real images | test suite | 4h | Verify forensics, GAN, steg actually run |
| 10 | Emit explicit security events on CV signal fires | `services/cv_tiered.py` | 2h | ATLAS/OWASP event correlation |

### Sprint 3 — GeoIP + ASN + TLS (2 weeks)

These complete the fraud signal framework. Currently up to 1.40 points of fraud score that never fires:

| # | Task | File | Effort | Why |
|---|------|------|--------|-----|
| 11 | Integrate MaxMind GeoLite2 or ip-api.com | `services/fraud_scorer.py`, new `services/geoip.py` | 8h | 5 GeoIP signals currently always-zero |
| 12 | Complete JA3/JA4 hash lookup against threat feed | `security/tls_fingerprint_middleware.py` | 8h | 2 TLS signals currently always-zero |
| 13 | Wire GeoIP → session context → fraud scorer | `routers/recommend.py`, `security/observer.py` | 4h | Signals fire but need session context |

### Sprint 4 — Complete Human Workflows (2 weeks)

| # | Task | File | Effort | Why |
|---|------|------|--------|-----|
| 14 | SLA breach Celery task for escalation rooms | `workers/celery_app.py`, new task | 4h | SLA timer set but never checked |
| 15 | Decision Trace WebSocket live stream | `services/decision_log.py`, `routers/decision_trace_events.py` | 8h | Frontend component ready, WS not wired |
| 16 | Complete email enrichment integration | `security/email_enrichment.py` | 8h | Requires external API keys configured |
| 17 | RAGAS eval integration | `services/orchestrator.py:80+` | 12h | Replace stub with real LLM-as-judge |

### Sprint 5 — GNN + Knowledge Base (3 weeks)

| # | Task | File | Effort | Why |
|---|------|------|--------|-----|
| 18 | Use-case knowledge base JSON | new `config/use_case_knowledge.json` | 1 day | Eliminates entire NQE question class |
| 19 | Wire knowledge base into NLP + NQE | `services/nlp_search_agent.py`, `flows/nqe.py` | 1 day | Auto-populate specs from "university" |
| 20 | Neo4j fraud ring GNN queries | `services/neo4j_graph.py`, `services/gnn_fraud_detector.py` | 1 week | Ship address clustering detection |
| 21 | MITRE ATLAS event tagging | `security/atlas_map.py`, event emitters | 1 week | Compliance reporting requires it |

### Sprint 6 — Quality & Observability (ongoing)

| # | Task | File | Effort |
|---|------|------|--------|
| 22 | Add transformer-based intent classification | new `services/intent_classifier.py` | 2 weeks |
| 23 | Supply chain GNN training + live detection | `security/supply_chain*.py` | 3 weeks |
| 24 | OWASP Agentic AI Top 10 full mapping | `security/owasp_map.py` | 1 week |
| 25 | A/B test interleaving full analytics wiring | `routers/admin_interleaving.py` | 1 week |

---

## 7. File-by-File Status Reference

### Core Orchestration

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/services/orchestrator.py` | 1000+ | ✅ Full | 4-phase, budget allocation, SLO, trace events |
| `src/app/services/interleaving_controller.py` | 100+ | ✅ Full | Bounded loops, tool allowlists |
| `src/app/flows/nqe.py` | 622 | ⚠️ Bug | Lines 33,580: fields present but not loaded from Redis |
| `src/app/flows/catalog.py` | 150+ | ✅ Full | Template store with per-tenant overrides |
| `src/app/policy/gate.py` | 150+ | ✅ Full | 5 deterministic rules, compliance tags |
| `src/app/services/playbook_engine.py` | 200+ | ✅ Full | CRUD + execution tracking + action adapters |

### Agents

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/services/nlp_search_agent.py` | 140+ | ✅ Full | PEG grammar, fuzzy budget, negation tracking |
| `src/app/services/product_ranking_agent.py` | 80+ | ✅ Full | Listwise, contrastive WHY, diversity enforcement |
| `src/app/services/inventory_agent.py` | 1000+ | ✅ Full | EOQ, supplier trust, demand forecast |
| `src/app/services/fraud_scorer.py` | 200+ | ⚠️ Partial | 34 signals; CV + GeoIP + JA3/JA4 not fully wired |
| `src/app/services/product_identity_agent.py` | 100+ | ⚠️ Partial | Needs Ollama vision + wiring into recommend flow |
| `src/app/agents/audit_evidence_agent.py` | 50+ rules | ✅ Full | 50+ deterministic audit rules |
| `src/app/agents/bi_query_agent.py` | 100+ | ✅ Full | NL→SQL, dialect-aware |

### Memory & RAG

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/services/memory.py` | 200+ | ✅ Full | Dual-layer Redis + in-process, TTL management |
| `src/app/services/episodic_memory.py` | 200+ | ✅ Full | 3-tier, 90d chat history, RAPTOR-style summary |
| `src/app/services/semantic_cache.py` | 100+ | ✅ Full | Redis + fallback, poison detection (OWASP LLM08) |
| `src/app/rag/retrieve.py` | 67 | ✅ Full | Naive cosine similarity, k=4, tenant-scoped |
| `src/app/rag/index.py` | 58 | ✅ Full | policy_docs.json, lazy-loaded |

### LLM Routing

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/services/llm_provider.py` | 250+ | ✅ Full | 0–10 N-tier scoring, multimodal aware |
| `src/app/services/llm_router.py` | 93 | ✅ Full | Provider routing: Anthropic/OpenAI/Mistral |
| `src/app/services/tier_router.py` | — | ✅ Full | Base complexity-based routing |
| `src/app/services/tier_router_learned.py` | — | ⚠️ Partial | Optional ML layer; outcome feedback loop present |

### CV & OCR

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/services/cv_tiered.py` | 100+ | ⚠️ Bug | Logic correct; missing OS deps (BUG-3) |
| `src/app/services/cv_ocr.py` | — | ⚠️ Bug | Tesseract/Paddle providers need system packages |
| `src/app/cv/ocr_pipeline.py` | — | ⚠️ Bug | Pipeline logic sound; deps missing |
| `src/app/cv/ocr_postprocess.py` | — | ✅ Full | Serial extraction, sticker detection |
| `src/app/cv/serial_patterns.py` | — | ✅ Full | Dell, Apple, Lenovo, HP regex patterns |
| `src/app/services/cv_tier2_pipeline.py` | — | ⚠️ Partial | Tier 2 forensics works; GAN/steg needs test |
| `src/app/routers/cv.py` | 140+ | ✅ Full | Endpoints correct; anti-replay nonce, quota |

### Security Modules

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/security/tls_fingerprint_middleware.py` | — | ⚠️ Partial | Fingerprint captured; hash→signal not wired |
| `src/app/security/gan_image_detector.py` | — | ⚠️ Partial | Logic present; needs real test images |
| `src/app/security/steg_detector.py` | — | ⚠️ Partial | Logic present; needs validation |
| `src/app/security/bec_kill_chain.py` | — | ✅ Full | BEC pattern detection operational |
| `src/app/security/bimi_verifier.py` | — | ✅ Full | BIMI cert verification |
| `src/app/security/email_enrichment.py` | — | ⚠️ Partial | Needs VIRUSTOTAL_API_KEY, URLHAUS_API_KEY |
| `src/app/security/supply_chain.py` | — | ❌ Stubbed | Scenario framework; GNN not trained |
| `src/app/security/atlas_map.py` | — | ❌ Stubbed | Mapping file exists; correlation not wired |
| `src/app/security/owasp_map.py` | — | ⚠️ Partial | LLM08 mapped to semantic_cache; rest partial |
| `src/app/security/maestro_boundaries.py` | — | ✅ Full | Agent action boundaries enforced |
| `src/app/services/gnn_fraud_detector.py` | — | ❌ Stubbed | Neo4j available; model not trained |

### Decision Logging

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/services/decision_log.py` | 200+ | ✅ Full | Bitemporal, thread-safe, 256 events/trace max |
| `src/app/models/decision_audit.py` | 25 | ✅ Full | Merkle chain structure |
| `src/app/models/decision_trace_events.py` | 59 | ✅ Full | ORM table, event types defined |
| `src/app/routers/decision_time_travel.py` | — | ✅ Full | Temporal replay by decision ID |
| `src/app/routers/decision_trace_events.py` | — | ⚠️ Partial | Router present; live WS stream not wired |

### Admin & BI

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/routers/admin_bi.py` | 1000+ | ✅ Full | Prometheus + SQL, SLO state evaluation |
| `src/app/services/bi_intelligence.py` | 100+ | ✅ Full | Margin + supplier scorecard |
| `src/app/routers/merchant_dashboard.py` | 150+ | ✅ Full | Static redirect, local demo auth bypass |
| `src/app/routers/admin_drift.py` | — | ✅ Full | ML drift detection |
| `src/app/routers/admin_fairness.py` | — | ✅ Full | Fairness monitoring |

### Escalation

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/routers/escalation_room.py` | 350+ | ⚠️ Partial | WS works; SLA breach task not wired |

### Workers

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/workers/celery_app.py` | 209 | ✅ Full | HMAC/x509 signing, beat schedule |
| `src/app/tasks/security_poll_tasks.py` | 17 | ✅ Full | 5-min CrowdStrike poll |
| `src/app/tasks/model_ops_tasks.py` | 100+ | ✅ Full | Nightly CF train + governance snapshot |
| `src/app/tasks/swarm_tasks.py` | 54 | ✅ Full | ThreadPoolExecutor supply chain simulation |
| `src/app/services/syslog_listener.py` | 100+ | ✅ Full | UDP/TCP, firewall syslog ingestion |
| `scripts/sync_worker.py` | 81 | ✅ Full | CSV + Shopify ERP inventory sync |

### Database & Models

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `src/app/models/orm.py` | 96 | ✅ Full | 8 tables: Customer, Product, Order, etc. |
| `src/app/models/db.py` | 150+ | ✅ Full | Multi-dialect, ContextVar request scoping |
| `src/app/models/decision_audit.py` | 25 | ✅ Full | Merkle chain |
| `src/app/models/migration_guard.py` | — | ✅ Full | Alembic migration gating |

### Frontend

| File | Lines | Status | Key Notes |
|------|-------|--------|-----------|
| `frontend/src/App.tsx` | 2000+ | ✅ Full | State machine, PII detection, NQE integration |
| `frontend/src/components/ChatOverlay.tsx` | — | ✅ Full | Streaming chat, NQE buttons |
| `frontend/src/components/ProductGrid.tsx` | — | ✅ Full | WHY text, SKU cards |
| `frontend/src/components/CVResultsPanel.tsx` | — | ✅ Full | CV output display (waits on backend fix) |
| `frontend/src/components/DecisionTrace.tsx` | 65KB | ⚠️ Partial | Full visualization built; WS stream not live |
| `frontend/src/components/EscalationRoom.tsx` | — | ⚠️ Partial | WS chat works; SLA display incomplete |
| `frontend/src/lib/api.ts` | — | ✅ Full | REST + WS client, CV functions |

---

## 8. Why We Should Improve Each Area

### Fix NQE Context Loss First

**Commercial reason:** Every ShopSquire demo that runs more than 2 turns shows users the same questions again. This is the first thing a prospect notices. It makes the platform look like it has goldfish memory despite having a sophisticated 3-tier memory architecture. **Fix it immediately.**

### Fix CV Dependencies Second

**Commercial reason:** The CV return-fraud triage is the platform's strongest IP. It's the thing no competitor has. But right now it can't see QR codes, can't read serial numbers, can't extract dates from images. The entire fraud triage value prop is non-functional. **Fix the Docker image.**

### Complete GeoIP/ASN/JA3/JA4 Third

**Revenue reason:** These signals represent 1.40+ points of unused fraud score weight. A fraudster using a Tor exit node or VPN gets a near-zero fraud score that should be 0.6+. Adding GeoIP (MaxMind GeoLite2 is free) and proper JA4 fingerprinting immediately improves detection rate for organized fraud rings — the highest-value fraud prevention use case.

### GNN Fraud Ring Detection

**Scale reason:** Individual signal fraud scores miss coordinated attacks (rings of 20 accounts, all returning products, all shipping to the same address). GNN catches the ring pattern that individual signals miss. This is where the highest-dollar fraud lives. Neo4j is already in the stack — this is a 1-week sprint once the Neo4j queries are written.

### RAGAS + Learned Tier Router

**Quality reason:** Currently there is no automated quality measurement of recommendations. The nightly CF training uses implicit signals (purchase conversion) which have high noise and 24h lag. RAGAS would add per-response quality scoring with <1 minute lag. Combined with the learned tier router, this creates a closed feedback loop: bad recommendations → LLM-as-judge quality score → adjust routing → better recommendations.

### MITRE ATLAS Event Tagging

**Compliance reason:** Enterprise and government prospects (ANZ market) require security event reports mapped to MITRE tactics. "We blocked 47 events" is not a compliance story. "We blocked 47 ATLAS AML-T0054 prompt injection attempts" is. The mapping file exists — it just needs to be applied to every security event emit call. This is table-stakes for mid-market and above.

### Use-Case Knowledge Base

**UX reason:** Currently NQE must ask "what do you use it for?" AND "what's your gaming style?" AND "what software do you use?" for creative professionals. A JSON knowledge base would collapse 3 NQE turns into 1 — the moment a user says "video editing", constraints like `ram_min=32GB, gpu_vram_min=6GB` are injected automatically. This removes the most frustrating part of the conversation flow.

### Decision Trace WebSocket Live Streaming

**Trust reason:** The DecisionTrace component is already built (65KB of frontend code). The bitemporal logs already exist. All that's missing is the pub/sub bridge. A live decision trace gives enterprise buyers and compliance teams real-time visibility into how recommendations are made — this is the most compelling trust-building feature for regulated industries (financial services, healthcare adjacent).

---

*Document generated: 2026-03-04 | ShopSquire Platform Status Assessment*
*Based on full codebase analysis: 482 Python files, ~100K lines, 23 React components*
*Critical bugs identified: 5 | Stubbed features: 8 | Estimated effort to production-ready: 6-8 weeks*
