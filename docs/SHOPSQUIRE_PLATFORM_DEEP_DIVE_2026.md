# ShopSquire Platform Deep Dive — March 2026

> Comprehensive analysis of architecture, agent capabilities, what is done, what is broken,
> what is left to build, and how to make every layer more intelligent.

---

## Table of Contents

1. [What ShopSquire Is](#1-what-shopsquire-is)
2. [Full Architecture Map](#2-full-architecture-map)
3. [Agent Inventory — What Each Agent Can Do](#3-agent-inventory)
4. [What Is Done (Production-Ready)](#4-what-is-done)
5. [What Is Broken](#5-what-is-broken)
6. [What Is Left To Build](#6-what-is-left-to-build)
7. [Context Loss Root Cause & Fix](#7-context-loss-root-cause--fix)
8. [Multimodal Product Query Failures (Lenovo Demo)](#8-multimodal-product-query-failures)
9. [How To Make Every Agent Smarter](#9-how-to-make-every-agent-smarter)
10. [Security / Fraud / Email / CV Intelligence Upgrades](#10-security--fraud--email--cv-intelligence-upgrades)
11. [Should We Add MITRE / KEV / PASTA / DREAD / MAESTRO / JA3 / JA4 / GeoIP / ASN?](#11-threat-intelligence-framework-recommendations)
12. [Latest Research — Agentic AI Platforms Comparison](#12-latest-research--agentic-ai-platforms)
13. [Recommended Roadmap (Prioritised)](#13-recommended-roadmap)

---

## 1. What ShopSquire Is

ShopSquire is an **agentic AI commerce platform** with two distinct personalities:

| Layer | What it does |
|---|---|
| **Buyer Storefront** | Conversational product discovery, multimodal search (image + voice + text), NQE disambiguation, cart, returns |
| **Merchant Admin** | BI dashboards, playbook engine, incident room, CV triage, fraud review, email security, compliance audit |

**Niche / Differentiation:**
ShopSquire is NOT trying to be Shopify. It is an **AI intelligence layer** that embeds shift-left security, fraud detection, and agent orchestration on top of commerce primitives — pushing everything else (payments, shipping, ERP, SIEM) to best-of-breed integrations (Stripe, PayPal, ShipStation, AusPost, StarTrack, CrowdStrike, Datadog, Darktrace, NetSuite, Shopify, WooCommerce).

---

## 2. Full Architecture Map

```
┌────────────────────────────────────────────────────────────────────────┐
│  BUYER STOREFRONT (React/TypeScript on Vite, port 5173)               │
│  Chat UI · Product Grid · Compare · CV Upload · Cart · Voice STT      │
│  PII detection (Luhn, SSN, email) · Disambiguation buttons             │
└──────────────────────────┬─────────────────────────────────────────────┘
                           │ HTTPS / fetch
┌──────────────────────────▼─────────────────────────────────────────────┐
│  FastAPI BACKEND (port 8080)                                           │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  CHAT ROUTER  /api/v1/chat/query                                 │  │
│  │  Voice fusion · Image intent routing · PII scanning              │  │
│  │  Complexity scoring → model tier selection                       │  │
│  │  Chat history (SQLite/PostgreSQL)                                │  │
│  └──────────────────┬───────────────────────────────────────────────┘  │
│                     │ internal delegate                                │
│  ┌──────────────────▼───────────────────────────────────────────────┐  │
│  │  RECOMMEND ROUTER  /api/v1/recommend/suggest                     │  │
│  │  NQE (Next Question Engine) · Constraint parsing                 │  │
│  │  Intent detection · Safety policy gate                           │  │
│  │  Model theft detection · Redis memory lookup                     │  │
│  └──────────────────┬───────────────────────────────────────────────┘  │
│                     │                                                  │
│  ┌──────────────────▼───────────────────────────────────────────────┐  │
│  │  ORCHESTRATOR  4-Phase Agent Runtime                             │  │
│  │                                                                  │  │
│  │  Phase 1 EXPLORE     Phase 2 EVALUATE    Phase 3 PLAN           │  │
│  │  Security_Observer   Candidate_Retrieval Orchestrator           │  │
│  │  NLP_Search          Product_Ranking     Policy_Gate            │  │
│  │  CV_Label            Fraud_Scoring                               │  │
│  │                      Inventory_Agent                             │  │
│  │                                   Phase 4 ACTION                │  │
│  │                                   Playbook Engine               │  │
│  │                                   Payment Adapters              │  │
│  │                                   Incident Ticketing            │  │
│  └──────────────────┬───────────────────────────────────────────────┘  │
│                     │                                                  │
│  ┌──────────────────▼───────────────────────────────────────────────┐  │
│  │  MEMORY LAYER                                                    │  │
│  │  Redis: session summary · kv_state · retrieval cache             │  │
│  │  PostgreSQL/TimescaleDB: decision audit · chat history           │  │
│  │  Semantic cache (trust-scored)                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  79 Routers · 160+ Services · 55+ Security Modules                    │
└────────────────────────────────────────────────────────────────────────┘
         │                    │                    │
  ┌──────▼──────┐    ┌────────▼────────┐   ┌──────▼──────────┐
  │ PostgreSQL  │    │  Redis 7 (ACL)  │   │ Celery/RQ       │
  │ TimescaleDB │    │  Session cache  │   │ Background tasks│
  │ Chat audit  │    │  Semantic cache │   │ Email worker    │
  │ Decision log│    │  Agent bus      │   │ CrowdStrike poll│
  └─────────────┘    └─────────────────┘   └─────────────────┘
```

---

## 3. Agent Inventory

### 3.1 Core Recommendation Agents

| Agent | File | What It Can Do |
|---|---|---|
| **NLP_Search_Agent** | `services/orchestrator.py` | Parses user query into typed constraints: budget range, brand preference, use_case, spec requirements, negations. Runs spaCy + regex + embeddings. Classifies intent (browse / compare / procurement / support). |
| **Candidate_Retrieval_Agent** | `services/orchestrator.py` | Searches product catalog using vector embeddings + exact filter predicates. Returns ranked candidates with stock status. |
| **Product_Ranking_Agent** | `services/orchestrator.py` | Reranks candidates using LLM reasoning + rule-based scoring. Considers parsed constraints, fraud signals, inventory status. |
| **NQE (Next Question Engine)** | `flows/nqe.py` | Detects missing fields from constraint slots (budget, use_case, brand, specs). Proposes up to 3 targeted follow-up questions using template matching + RAG enrichment. **Currently broken: no memory of prior questions asked.** |
| **LLM Provider / Tier Router** | `services/llm_provider.py` | Complexity scoring 0–10. Routes to: small (llama3.3:8b, score 0–3), medium (mixtral:8x7b, score 4–6), large (score 7–10). Signals: length, comparison keywords, multimodal, multi-turn, negation, technical terms. |

### 3.2 Security Agents

| Agent | File | What It Can Do |
|---|---|---|
| **Security_Observer_Agent** | `security/observer.py` | Cross-modal payload analysis across text + voice + OCR + image labels + QR codes. Emits security events. Triggers block on critical/high severity. |
| **Jailbreak_Embedding_Guard** | `security/jailbreak_embedding_guard.py` | Detects prompt injection/jailbreak via embedding distance. Blocks queries semantically similar to known attacks. |
| **PII_NER** | `security/pii_ner.py` | Named entity recognition for PII: names, emails, phone numbers, addresses, government IDs. |
| **Policy Gate** | `policy/gate.py` | Zero-trust rule evaluation before/after agent steps. Classifies: allow / warn / redact / block. |
| **Model Theft Detector** | `security/` | Detects model extraction attacks via rate limiting, systematic query pattern detection, output fingerprinting. |
| **Transaction Firewall** | `security/transaction_firewall.py` | Per-transaction risk gate. Blocks high-risk payments before execution. |
| **Agent Guardrail** | `security/agent_guardrails.py` | Pre/post-invocation safety checks on every agent step. Assesses interaction intent. |

### 3.3 Fraud Detection Agents

| Agent | File | What It Can Do |
|---|---|---|
| **Fraud_Scoring_Agent** | `services/fraud_scorer.py` | 26+ weighted fraud signals across: image hash vs fraud DB, EXIF date mismatch, stock photo detection, image manipulation, account age < 30 days, chargeback history, return velocity, coupon stacking, device fingerprint clustering (Neo4j). |
| **Adversarial Image Detector** | `security/adversarial_image_detector.py` | Detects adversarially crafted/poisoned images submitted in product returns or support tickets. |
| **GAN Image Detector** | `security/gan_image_detector.py` | Detects AI-generated (GAN/diffusion) product images submitted as "real" product photos in returns. |
| **Steg Detector** | `security/steg_detector.py` | Detects steganographic payloads hidden in uploaded images (prompt injection via image metadata). |

### 3.4 Email Security Agents

| Agent | File | What It Can Do |
|---|---|---|
| **Email Security Engine** | `security/email_security.py` | Full email threat analysis: extracts IOCs, computes sender trust, applies rules (SPF/DKIM/DMARC), checks reply-to mismatch, domain spoofing, homograph attacks, attachment analysis. |
| **Email Rules Engine** | `security/email_security_rules.py` | Rule-based indicator extraction from email metadata and content. |
| **Verdict Engine** | `security/email_security_verdict.py` | Maps indicators to verdict: allow / review / block / sandbox. |
| **Sender Trust Scorer** | `security/email_sender_trust.py` | Persistent sender trust history. Degrades score on violations, boosts on clean sends. |
| **BIMI Verifier** | `security/bimi_verifier.py` | Brand Indicators for Message Identification verification (brand logo + certificate). |
| **Attachment Intel** | `security/email_attachment_intel.py` | Malware detection on email attachments. |

### 3.5 Computer Vision (CV) Agents

| Agent | File | What It Can Do |
|---|---|---|
| **CV_Label_Agent** | `services/orchestrator.py` | Image classification and label extraction. Runs in Phase 1 alongside Security_Observer. |
| **CV Triage (Basic)** | `services/cv_triage_basic.py` | Damage assessment for return/complaint images. Fast path, no OCR. |
| **CV Tier 2 Pipeline** | `services/cv_tier2_pipeline.py` | YOLO object detection → OCR (two passes) → QR/barcode detection → ELA forensics → Vision LLM lane. Generates 30+ evidence tags. |
| **Adversarial/GAN/Steg** | `security/adversarial_image_detector.py`, `gan_image_detector.py`, `steg_detector.py` | Detect manipulated, AI-generated, or steganographically modified images. |
| **Reverse Image Search** | `services/reverse_image_search.py` | Reverse image search for stock photo / identity fraud detection. |

### 3.6 Orchestration & Infrastructure Agents

| Agent | File | What It Can Do |
|---|---|---|
| **Orchestrator** | `services/orchestrator.py` | Master 4-phase runner. Adaptive token/tool budgets. SLO monitoring. A/B testing. Incident ticketing. Agent handoff. Graceful degradation (circuit breaker). |
| **Playbook Engine** | `services/playbook_engine.py` | Typed action execution: send_email, create_ticket, update_inventory, notify_merchant, escalate_human. Async scheduling + DLQ. |
| **Agentic RAG Pipeline** | `services/agentic_rag_pipeline.py` | 6-stage: PLAN → RETRIEVE → RANK → INJECT → DECIDE → VERIFY. Jailbreak prevention at injection stage. Trust-scored context injection. |
| **Inventory Agent** | `services/inventory_agent.py` | Real-time stock verification. Supply chain guardrails. Reorder alerts. Supplier validation. |
| **BI Query Agent** | `services/bi_query_agent.py` | Natural language to SQL/aggregation for merchant analytics queries. |
| **Debate Coordinator** | `services/debate_coordinator.py` | Multi-agent debate pattern: agents propose, challenge, and reconcile answers before final output. |

---

## 4. What Is Done

### Production-Ready (✅)

| Feature | Status |
|---|---|
| Natural language product search with constraint parsing | ✅ Working |
| Price range, brand, spec extraction from queries | ✅ Working |
| NQE disambiguation buttons on buyer storefront | ✅ UI working, backend broken (context loss) |
| Decision Trace real-time event panel | ✅ Working |
| Fraud scoring (26+ signals, image hashing, EXIF) | ✅ Working |
| Email security (DMARC/DKIM/SPF, attachment intel) | ✅ Working |
| CV Tier 2 Pipeline (YOLO, OCR, ELA, forensics) | ✅ Code done, ⚠️ missing runtime deps |
| PII detection + frontend Luhn card warning | ✅ Working |
| Jailbreak embedding guard | ✅ Working |
| Model theft rate limiting | ✅ Working |
| Policy gate (zero-trust, pre/post agent) | ✅ Working |
| Redis session memory (summary, kv_state, retrieval) | ✅ Working |
| Bitemporal decision audit logs (TimescaleDB) | ✅ Working |
| LLM complexity scoring + tier routing | ✅ Working (wrong tier for multimodal, see §8) |
| Playbook engine (send_email, create_ticket actions) | ✅ Working |
| Multi-payment provider integration (PayPal, Revolut, GooglePay, Afterpay) | ✅ Working |
| Admin merchant dashboard | ✅ Working |
| CrowdStrike threat polling worker | ✅ Working |
| Syslog listener | ✅ Working |
| BIMI verifier | ✅ Working |
| mTLS internal service communication | ✅ Working |
| Rate limiting + quota guards | ✅ Working |
| Feature flag system | ✅ Working |
| Observability (Prometheus, Grafana, OpenTelemetry) | ✅ Working |
| Recommendation bandit (exploration/exploitation) | ✅ Working |
| ALS collaborative filtering | ✅ Working |
| Agentic RAG with jailbreak prevention | ✅ Working |
| GAN image detector | ✅ Working |
| Steganography detector | ✅ Working |
| Adversarial image detector | ✅ Working |
| Semantic cache (trust-scored) | ✅ Working |
| Agent containment + SLO degradation | ✅ Working |
| Inventory supplier guardrails | ✅ Working |
| MISP threat feed integration | ✅ Working |
| Supply chain CV pipeline | ✅ Working |

---

## 5. What Is Broken

### Critical Bugs (🔴)

#### BUG-1: NQE Context Loss — Questions Repeat Every Turn

**Root Cause (confirmed by code trace):**
`NQEInput` has no `previously_asked_ids` field. The NQE engine runs from a blank slate on every turn. The memory infrastructure (`session:{uid}:kv_state`) exists in Redis but is never queried by the NQE for question history.

**Data Flow Breakdown:**
```
User clicks "Under $1,000" button
  → Frontend: sends nqe_selection + recent_messages (text only)
  → chat.py: passes nqe params to recommend — BUT NOT recent_messages
  → recommend.py: applies selection to constraints ✓
  → nqe.py: generates fresh missing_fields list from scratch ❌
  → NQE engine: re-asks budget question (still "missing") ❌
```

**Files to fix:** `flows/nqe.py`, `routers/recommend.py`, `routers/chat.py`, `services/memory.py`

**Minimum fix:**
```python
# In NQEInput (flows/nqe.py)
previously_asked_ids: List[str] = []

# In recommend.py — load from Redis before calling NQE
asked_ids = mem.get_kv(uid).get("nqe_asked_ids", [])
nqe_input = NQEInput(..., previously_asked_ids=asked_ids)

# In nqe.py propose() — skip already asked
templates = [t for t in templates if t.id not in inp.previously_asked_ids]

# After proposing — persist new IDs back to Redis
mem.set_kv(uid, {**kv, "nqe_asked_ids": asked_ids + [q.id for q in next_questions]})
```

---

#### BUG-2: Multimodal Complexity Under-Scoring → Wrong Model Tier

**Root Cause:** The complexity scorer in `llm_provider.py` adds +1 for multimodal but the visual similarity search intent (image + "similar to this") is not detected as a complex technical query. A Lenovo Pro 7 image + "similar laptops for university" query scores as `rule-based (prefer_small)` → `llama3.3:8b`.

**Expected:** Score ≥ 5 → medium model (mixtral or equivalent) for any image-anchored similarity + multi-intent query.

**Fix:** Boost complexity score when:
- Image is present AND query mentions "similar", "like this", "alternatives", "price range" → +2
- Any university/professional use-case query with image → +1

---

#### BUG-3: CV Pipeline Missing Runtime Dependencies

**Root Cause:** `pyzbar`, `pytesseract`, `paddleocr`, `imageio`/`imagehash`, and local Ollama models not installed in Docker container. CV pipeline code is complete but silently degrades.

**Symptoms:** QR code detection fails, OCR returns empty, security matrix empty, no escalation triggers.

---

#### BUG-4: Shortlist Erased on Zero-Result Turns

**Root Cause:** When a filter returns 0 products, `last_shortlist_skus` is unconditionally overwritten with `[]`. Follow-up queries ("compare those 3") lose the prior shortlist.

---

#### BUG-5: NQE Fires on Follow-Up Explain Queries

**Root Cause:** `_is_followup_explain_query()` pattern matching too narrow. NQE fires when user says "why did you pick those?" regenerating questions instead of explaining.

---

## 6. What Is Left To Build

### Tier 1 — Critical (blocks demo value)

| Feature | Effort | Impact |
|---|---|---|
| NQE context memory (fix BUG-1) | S | Removes most embarrassing UX failure |
| Visual similarity search: anchor to uploaded product specs | M | Enables "show me similar to this" correctly |
| Software/system requirements knowledge base | M | Enables "can I run X on this?" answers |
| CV pipeline runtime dependencies in Docker | S | Unlocks all CV features |
| Complexity boost for multimodal intent | XS | Correct model tier selection |
| Shortlist persistence on zero-result turns | XS | Fixes conversation continuity |

### Tier 2 — High Value

| Feature | Effort | Impact |
|---|---|---|
| Product spec extraction from image (vision→spec→search) | L | True visual product matching |
| University/gaming/workstation use-case knowledge layer | M | Smart suitability recommendations |
| JA3/JA4 TLS fingerprinting on buyer sessions | M | Fraud detection upgrade |
| GeoIP + ASN anomaly detection on transactions | M | Fraud/ATO prevention |
| MITRE ATT&CK mapping for security alerts | M | Compliance + SOC readability |
| MITRE ATLAS mapping for agentic AI attacks | M | AI-specific threat detection |
| OWASP Top 10 LLM 2025 enforcement | S | LLM security hardening |
| Human escalation room full workflow | M | Closes incident loop |
| Decision trace WebSocket streaming | M | Real-time trace UX |
| Semantic search upgrades (dense retrieval) | M | Better product matching |

### Tier 3 — Intelligence Enhancements

| Feature | Effort | Impact |
|---|---|---|
| Per-user product preference graph | L | Personalised recommendations |
| Debate coordinator for complex product comparisons | M | Higher quality LLM answers |
| Post-LLM verifier for factual claims | M | Hallucination reduction |
| RAGAS evaluation framework | M | Continuous quality measurement |
| Behavioural biometrics on buyer session | L | Fraud ring detection |
| Graph Neural Network fraud ring detection | L | Next-gen fraud |
| BI executive pulse alerts | M | Merchant value |
| ERP/EDI connector (NetSuite, SAP, Xero) | L | Enterprise integration |

---

## 7. Context Loss Root Cause & Fix

### Why the NQE forgets everything between turns

From the screenshot analysis (`smart-1.png` → `smart-2.png`):

1. User asked for gaming laptops $1500–$2100
2. NQE asked: brand preference, budget range, performance vs battery
3. User clicked "Better performance for gaming/creative work"
4. **Next turn: NQE asked the exact same questions again**

This is entirely because `NQEInput` has no `previously_asked_ids` field. The session memory (`session:{uid}:kv_state` in Redis) is never queried for NQE history before generating questions.

### Fix Strategy (Recommended)

**Step 1: Extend NQEInput model**
```python
# flows/nqe.py
class NQEInput(BaseModel):
    ...
    previously_asked_ids: List[str] = []  # ADD THIS
    answered_fields: Dict[str, Any] = {}  # ADD THIS — what user has already told us
```

**Step 2: Load history in recommend.py before calling NQE**
```python
# routers/recommend.py — before nqe_input construction
kv = mem.get_kv(uid) or {}
asked_ids = kv.get("nqe_asked_ids", [])
answered_fields = kv.get("nqe_answered_fields", {})

nqe_input = NQEInput(
    ...
    previously_asked_ids=asked_ids,
    answered_fields=answered_fields,
)
```

**Step 3: Filter in nqe.py propose()**
```python
def propose(self, inp: NQEInput) -> List[NQEQuestion]:
    # Filter out already-answered fields
    remaining_missing = [f for f in inp.missing_fields
                         if f not in inp.answered_fields]

    # Filter out already-asked question templates
    templates = self._match_templates(remaining_missing)
    templates = [t for t in templates if t.id not in inp.previously_asked_ids]
    ...
```

**Step 4: Persist asked IDs back to Redis after proposing**
```python
# routers/recommend.py — after NQE proposes questions
new_asked_ids = asked_ids + [q["id"] for q in next_questions]
mem.set_kv(uid, {**kv, "nqe_asked_ids": new_asked_ids})
```

**Step 5: Persist answered fields when user clicks option**
```python
# routers/recommend.py — in _apply_nqe_selection_to_constraints()
# Also persist to Redis kv_state:
answered_fields = kv.get("nqe_answered_fields", {})
answered_fields[nqe_question_id] = nqe_option_value
mem.set_kv(uid, {**kv, "nqe_answered_fields": answered_fields})
```

---

## 8. Multimodal Product Query Failures

### The Lenovo Demo Analysis

**Screenshot: `lenovo-multimodal1.png` + `lenovo-multimodal2.png`**
**Uploaded file: `dump/test-cv/lenovo-pro7.webp`**

**Query:** "can I get laptops similar to this? what price range should I expect? can I use it for university or would that be overkill?"

**What went wrong:**

| Problem | Root Cause | Fix |
|---|---|---|
| Model: `rule-based (prefer_small)` → `llama3.3:8b` | Complexity scorer only adds +1 for multimodal; "similar to this" visual similarity intent not detected as complex | Add +2 complexity signal for visual similarity intent with uploaded product image |
| Products not anchored to Lenovo Pro 7 specs | CV_Label_Agent returns generic labels ("laptop", "keyboard"), not "Lenovo Yoga Pro 7, i7-13700H, 16GB, 1TB". Vision-to-spec extraction not implemented | Add product recognition step: vision LLM → structured spec extraction → constraint injection |
| No university suitability assessment | No domain knowledge base for software requirements (Office 365, IDEs, Adobe Creative Suite, etc.) | Add use-case knowledge layer |
| NQE asks same questions after image upload | BUG-1 (context loss) | Fixed by NQE memory patch |
| "Why I selected this" missing | Products shown without why they match the uploaded device's profile | Add per-product delta explanation: "Similar CPU, 2x cheaper, lower GPU tier" |

### You are NOT a noob — this is a known hard problem

**Why multimodal product similarity is genuinely difficult:**

1. **Visual-to-spec grounding**: Converting a product photo into structured specs (CPU model, RAM, resolution) requires a capable vision-language model (GPT-4o Vision, LLaVA, or a fine-tuned product recognition model). Clip embeddings alone won't give you `i7-13700H`.

2. **Inventory anchoring**: Even if you identify the product, you need to find "similar but cheaper" in your own catalog — which requires spec-level similarity search, not just text embedding matching.

3. **Domain knowledge gap**: "Can I use it for university?" requires knowing: what degree, what software (AutoCAD? Blender? Python?), and what those apps require. This is a knowledge base problem.

4. **How leading platforms handle this:**

| Platform | Approach |
|---|---|
| **Google Shopping** | Visual search → product identification via product database, not spec extraction |
| **Amazon AI shopping** | "Find similar" uses product category + price anchoring |
| **ChatGPT (GPT-4o)** | Describes the laptop from image, searches web for spec sheet, then reasons about alternatives — but lacks your inventory |
| **Perplexity Shopping** | Multimodal + real-time web search, no local inventory |
| **Shopify AI** | No visual product similarity at all currently |

**ShopSquire's path:**
1. In Phase 1, after `CV_Label_Agent` runs, add a **Product_Identity_Agent** that uses vision LLM to extract structured specs from product images
2. Inject those specs as typed constraints into `Candidate_Retrieval_Agent`
3. Add a **Use_Case_Advisor_Agent** with a knowledge base of software requirements per profession/study field
4. Boost complexity score for visual similarity queries → medium model minimum

### System Requirements Awareness — Is this reasonable?

Yes, absolutely. This is a **knowledge layer gap**, not a model capability gap. What ShopSquire needs:

```json
{
  "use_case_requirements": {
    "university_general": {
      "min_ram_gb": 8,
      "min_storage_gb": 256,
      "recommended_cpu": "i5-12th gen or equivalent",
      "apps": ["Microsoft 365", "Teams", "Zoom", "Chrome"],
      "gpu_needed": false
    },
    "engineering_student": {
      "min_ram_gb": 16,
      "apps": ["AutoCAD", "SolidWorks", "MATLAB", "VS Code"],
      "gpu_needed": "for GPU-accelerated simulation"
    },
    "gaming_casual": {
      "min_gpu_vram_gb": 6,
      "apps": ["Steam", "Epic Games", "Discord"],
      "resolution_target": "1080p 60fps"
    },
    "gaming_competitive": {
      "min_gpu_vram_gb": 8,
      "min_refresh_hz": 144,
      "apps": ["CS2", "Valorant", "OBS Studio"]
    },
    "content_creator": {
      "min_ram_gb": 32,
      "apps": ["Adobe Premiere", "DaVinci Resolve", "Photoshop"],
      "gpu_needed": "CUDA/OpenCL for render acceleration"
    }
  }
}
```

This is not over-engineering — it is **domain-specific RAG**. Build it once as a structured JSON/YAML knowledge base and inject it at the Use_Case_Advisor stage.

---

## 9. How To Make Every Agent Smarter

### 9.1 NLP_Search_Agent

**Current:** Regex + spaCy NER for price ranges, brand names, spec terms.

**Upgrades:**
- **Typed constraint grammar**: Replace regex with a PEG parser for domain queries — handle "between $X and $Y", "at least N GB", "no more than X lbs"
- **Intent confidence scoring**: Return confidence 0–1 per slot, not binary
- **Semantic slot filling**: Use MiniLM embeddings to fill slots when user says "won't break the bank" (maps to low budget tier)
- **Negation tracking**: "not ASUS, not refurbished, prefer matte screen" — full negation constraint model
- **Session slot accumulation**: Merge slots across turns (turn 1: brand=Lenovo, turn 3: budget=$1000 → combined constraint)

### 9.2 Product_Ranking_Agent

**Current:** LLM reranking + rule scoring.

**Upgrades:**
- **Listwise LLM reranking** (RankGPT pattern): Present all 5–10 candidates to LLM in one pass with full constraint context, ask for ranked list with reasoning per item
- **Contrastive WHY generation**: For each recommended product, generate "why THIS vs the rejected ones" explanation
- **Diversity enforcement**: Prevent 3 near-identical products from dominating results
- **Personalization signal**: Weight by user's past clicks/purchases (bandit feedback loop already exists)

### 9.3 CV_Label_Agent → Product_Identity_Agent

**Current:** Generic image classification labels.

**Upgrades:**
- **Vision LLM spec extraction**: Pass image to LLaVA/GPT-4o with prompt: "Identify this laptop. Extract: brand, model, CPU tier, RAM hint, display size, form factor. Return JSON."
- **Spec-to-constraint injection**: Map extracted specs to typed constraints for Candidate_Retrieval_Agent
- **Product delta explanation**: For each result, compute and display: "Similar CPU (same tier), 2GB less RAM, ½ the price, smaller SSD"

### 9.4 NQE (Next Question Engine)

**Current:** Template matching, no memory of prior questions.

**Upgrades (beyond the memory fix):**
- **Adaptive question ordering**: Ask highest-value missing field first (budget narrows search most → ask first)
- **Implicit answer detection**: If user says "I mostly use it for university work" → infer use_case=university, skip that question
- **Convergence detection**: Once enough constraints are filled (≥3 high-signal slots), stop asking and just recommend
- **Personalised options**: Options on disambiguation buttons should be ranked by popularity for the detected product category
- **LLM-generated questions**: For novel/unseen constraint combinations, use small LLM to generate a relevant question instead of falling back to generic templates

### 9.5 Orchestrator

**Current:** 4-phase execution, adaptive budgets, SLO monitoring.

**Upgrades:**
- **Debate pattern for complex queries**: When complexity ≥ 7 or user asks "which is better", run Debate_Coordinator: each candidate is argued for/against before final ranking
- **Self-reflection step**: After Phase 3 PLAN, add a verification step: "Did we actually answer the user's question?" before emitting response
- **Streaming partial results**: Use SSE to stream Phase 1 + Phase 2 results to frontend progressively
- **Cross-turn semantic memory**: Store embedding of each user turn in Redis; on each new turn, retrieve semantically similar past turns and inject as context

### 9.6 Fraud_Scoring_Agent

**Current:** 26 weighted signals, image hashing, EXIF, graph signals.

**Upgrades:**
- **JA3/JA4 TLS fingerprinting**: Detect known fraud/bot TLS client signatures at session start
- **GeoIP + ASN risk scoring**: Detect sessions from known VPN/proxy/Tor exit ASNs, high-risk GeoIP regions for the transaction amount
- **Behavioral biometrics**: Mouse movement patterns, typing cadence, tap timing (mobile) — distinguish humans from bots/scripts
- **Graph Neural Network (GNN) fraud ring detection**: Replace Neo4j heuristics with GNN trained on fraud ring patterns (shared device fingerprints, shipping address clustering, timing correlations)
- **Velocity-by-cohort**: Compare return/refund/coupon velocity against similar-age accounts, not absolute thresholds

---

## 10. Security / Fraud / Email / CV Intelligence Upgrades

### 10.1 Email Security — Smart Upgrades

**Current capability:** DMARC/DKIM/SPF, sender trust, reply-to mismatch, attachment intel, BIMI.

**Gap analysis & upgrades:**

| Upgrade | How |
|---|---|
| **BEC detection via LLM** | Fine-tune or prompt a small LLM on Business Email Compromise patterns: urgency phrases, wire transfer requests, impersonation of executives. Rules alone miss nuanced BEC. |
| **Homograph attack detection** | Unicode normalization + confusable character detection (е vs e, ɑ vs a). Existing rule engine likely handles ASCII spoofing but not full Unicode confusables. |
| **Thread hijacking detection** | Track conversation threads: if an inbound email references an existing thread but comes from a new sender/domain, flag as thread hijacking. |
| **Lateral movement indicator** | If email contains internal credentials/config URLs after being forwarded, flag as potential lateral movement exfil. |
| **DMARC aggregate reporting** | Pull DMARC RUA reports for merchant domains to detect brand abuse at scale. |
| **VIP/executive domain watch** | Maintain a watchlist of merchant executive names + domains; alert on any external email that contains these. |

### 10.2 CV Security — Smart Upgrades

**Current capability:** GAN detection, steganography, adversarial image detection, ELA forensics.

**Upgrades:**

| Upgrade | How |
|---|---|
| **Diffusion model vs GAN separation** | Existing GAN detector may miss diffusion-model-generated fakes (Stable Diffusion, DALL-E, Midjourney). Add spectral analysis: diffusion images have characteristic high-frequency noise signatures. |
| **Deepfake document detection** | For submitted IDs/receipts: detect AI-generated documents via texture inconsistencies, metadata fingerprinting, font rendering artifacts. |
| **Return receipt fraud** | OCR extracted date + merchant name + amount → verify against order database. Flag impossible receipts (date before purchase, wrong amounts, mismatched merchant). |
| **Product authenticity CV** | For luxury/electronics returns: compare product serial number (OCR) against brand's known serial format + check against fraud serial database. |
| **Packaging integrity** | Detect if returned product packaging has been tampered with, resealed, or is a different product box. |

### 10.3 Fraud Detection — Smart Upgrades

**Current capability:** 26-signal weighted scoring, image hashing, EXIF, Neo4j graph signals.

**Upgrades:**

| Upgrade | How |
|---|---|
| **JA3/JA4 fingerprinting** | At TLS handshake layer (via nginx/Envoy), compute JA3 hash of client TLS parameters. Known fraudster/bot clients have documented JA3 fingerprints. Feed into fraud scorer as additional signal. JA4 is the modern replacement — captures more parameters. |
| **Device intelligence** | Browser fingerprint (canvas, WebGL, fonts, screen resolution, timezone) combined with IP + JA3 creates a persistent device identity even across VPN changes. |
| **GeoIP + ASN velocity** | Flag if same user's session IP changes country mid-session, or if checkout IP is in known datacenter ASN (bots/automation). |
| **Transformer-based anomaly detection** | Replace linear weighted scoring with a transformer that learns the full sequence of user actions (browse → add to cart → checkout → payment) and flags deviations from normal patterns. |
| **Federated fraud signals** | Participate in fraud consortium feeds (Sardine, Emailage/LexisNexis) to get cross-merchant fraud signals. |

---

## 11. Threat Intelligence Framework Recommendations

### Should ShopSquire add MITRE / KEV / PASTA / DREAD / MAESTRO / CVSS / JA3 / JA4 / GeoIP / ASN?

**Short answer: Yes to most, with clear scope per layer.**

| Framework | Verdict | How to Use in ShopSquire |
|---|---|---|
| **MITRE ATT&CK (Enterprise)** | ✅ Add | Map security alert events to ATT&CK Tactic/Technique IDs. Enables SOC analysts to understand ShopSquire alerts in their existing tooling. "Email phishing attempt" → T1566.001. |
| **MITRE ATLAS** | ✅ Add — high priority | MITRE ATLAS covers adversarial ML attacks: model theft, prompt injection, training data poisoning, model evasion. ShopSquire has agentic AI — ATLAS is directly applicable. Map jailbreak guard detections → ATLAS AML.T0051 (LLM Prompt Injection). |
| **MITRE CAPEC** | ✅ Light use | Common attack pattern enumeration. Useful for documenting what attack patterns each security module defends against. |
| **KEV (CISA Known Exploited Vulnerabilities)** | ✅ Add | Subscribe to CISA KEV feed. Any CVE in KEV affecting ShopSquire dependencies (FastAPI, PostgreSQL, Redis, Python libs) should trigger immediate patch SLA. Already have vuln_scan.py — wire it to KEV. |
| **PASTA** | ✅ Use for threat modeling | PASTA (Process for Attack Simulation and Threat Analysis) is a methodology, not a runtime framework. Run PASTA workshops for each new feature area. Document outputs in threat model artifacts. |
| **DREAD** | ✅ Internal scoring | DREAD (Damage, Reproducibility, Exploitability, Affected users, Discoverability) gives a simple numeric risk score per vulnerability. Use alongside CVSS for internal prioritisation. CVSS for external reporting, DREAD for internal triage speed. |
| **CVSS** | ✅ Already implied | CVSS scores for any CVE affecting ShopSquire components. Wire vuln_scan.py output to CVSS severity (critical ≥ 9.0, high ≥ 7.0) → auto-create incident tickets. |
| **MAESTRO** | ✅ Add — AI-specific | MAESTRO framework for agentic AI security covers: agent trust boundaries, tool misuse, autonomous decision risks. Directly applicable to ShopSquire's multi-agent orchestrator. Use to document and test agent security boundaries. |
| **JA3/JA4 Fingerprinting** | ✅ Add to fraud scorer | At nginx/reverse proxy layer, compute JA3/JA4 hash per buyer session. Feed into Fraud_Scoring_Agent as a signal. 10% weight. Known fraud toolkits have documented JA3 hashes. JA4 is the more modern standard (2023). |
| **GeoIP** | ✅ Add to fraud scorer | MaxMind GeoIP2 or ip-api.com. Signals: country risk tier, IP-to-billing-address country mismatch, high-risk country for transaction amount. 5–10% weight in fraud scorer. |
| **ASN (Autonomous System Number)** | ✅ Add to fraud scorer | Detect sessions from datacenter ASNs (not residential), known VPN/proxy ASNs, Tor exit nodes. Feed into fraud scorer. High-value transactions from datacenter ASNs → elevated risk. |
| **OWASP Top 10 LLM 2025** | ✅ Already partially covered | Map existing jailbreak guard, model theft, PII detection, RAG injection prevention to OWASP LLM Top 10 items. Fill gaps: add LLM output monitoring, supply chain AI model integrity checks. |
| **OWASP Agentic AI Top 10** | ✅ Add as soon as published | This is emerging (expected 2025–2026). Track and implement when available. ShopSquire's multi-agent system is a prime target for agentic-specific attacks. |

### Implementation Priority

```
1. MITRE ATLAS + OWASP LLM Top 10 (agentic AI specific)  → Q2 2026
2. JA3/JA4 + GeoIP + ASN in fraud scorer                 → Q2 2026
3. MITRE ATT&CK event mapping                             → Q2 2026
4. KEV feed integration into vuln_scan                    → Q1 2026
5. CVSS severity → incident auto-creation                 → Q1 2026
6. DREAD internal scoring for vulnerability triage        → Q2 2026
7. MAESTRO agent security boundary documentation          → Q3 2026
8. PASTA threat modeling sessions per feature             → Ongoing
```

---

## 12. Latest Research — Agentic AI Platforms

### 12.1 Memory & Context Management (Latest Research)

The core problem ShopSquire faces (NQE context loss) is one of the hardest problems in agentic AI. Here is what the leading research and platforms do:

| Approach | Description | Applicability to ShopSquire |
|---|---|---|
| **MemGPT / Letta** (2024) | Hierarchical memory: in-context (working), external (archival), recall (summary). Agent manages its own memory boundaries explicitly. | Implement a version of this: NQE working memory (current turn), session KV (24h Redis), long-term profile (PostgreSQL) |
| **LangChain ConversationBufferWindowMemory** | Rolling window of N last turns. Simple but effective for short sessions. | Already partially implemented (recent_messages). Gap: NQE doesn't see it. |
| **LangGraph StateGraph** | Each node in the graph has typed state. State flows between nodes, enabling true inter-agent memory. | Refactor orchestrator phases to use StateGraph pattern — NQE becomes a node that reads/writes to shared state |
| **OpenAI Assistant Threads** | Server-side persistent threads with full message history. Model always sees full context. | Implement per-uid server-side thread object that NQE and Orchestrator both read |
| **Episodic Memory (EM-LLM, 2024)** | Stores "events" (user actions + system responses) as memory units. Retrieves relevant episodes on each turn. | Store each NQE Q&A pair as an episode; retrieve similar episodes to inform future NQE questions |
| **RAPTOR (2024)** | Recursive abstractive processing: builds a tree of summaries at multiple granularities. | For long sessions (>20 turns), summarise clusters of prior conversation turns into higher-level summaries |

### 12.2 How Leading Agentic Platforms Handle This

| Platform | Context Management | Strengths | Gaps |
|---|---|---|---|
| **Salesforce Agentforce** | Explicit conversation state machine + Salesforce Data Cloud for customer history | Deep CRM integration, persistent customer context | Locked to Salesforce ecosystem, expensive |
| **Microsoft Copilot Studio** | Azure AI Memory + conversation history in Azure Cosmos DB | Enterprise AAD integration, Teams/O365 native | Heavy Azure dependency |
| **CrewAI** | Per-agent memory with shared crew memory. Short-term (in-context), long-term (ChromaDB), entity memory (factual). | Most complete open-source memory model | No ecommerce domain specialisation |
| **LangGraph** | Typed state that flows through graph nodes. Checkpointing to persistent storage. | Best for complex multi-agent state flows | Low-level, requires significant implementation |
| **AutoGen (Microsoft)** | GroupChat pattern: all agents see the full message history of the group | Simple, effective for multi-agent dialogue | No structured memory, context window limits |
| **Dust.tt** | Managed conversation context + tool call history per assistant | Production-ready, good developer UX | SaaS, limited customisation |
| **Lindy.ai** | Long-term memory per contact, updates automatically | Consumer-friendly persistent memory | Not open source, no ecommerce specialisation |

### 12.3 What ShopSquire Can Borrow

1. **CrewAI's 3-tier memory model**: Short-term (NQE working context, in-context window), long-term (Redis KV, 24h TTL), entity memory (product preferences, brand loyalty, price sensitivity profile)
2. **LangGraph's typed state**: Refactor Orchestrator to use a typed state object that all phases read and write — NQE becomes a first-class consumer of this state
3. **LangChain's message history**: Pass last 10 messages (not 6) to recommend endpoint, not just to chat endpoint

---

## 13. Recommended Roadmap

### Q1 2026 (Now — March)

| # | Item | Effort | Owner Area |
|---|---|---|---|
| 1 | Fix BUG-1: NQE context memory | S | Backend |
| 2 | Fix BUG-2: Complexity boost for multimodal | XS | Backend |
| 3 | Fix BUG-3: CV runtime dependencies in Docker | S | DevOps |
| 4 | Fix BUG-4: Shortlist not cleared on zero results | XS | Backend |
| 5 | KEV feed → vuln_scan wiring | S | Security |
| 6 | CVSS severity → incident auto-creation | S | Security |

### Q2 2026

| # | Item | Effort | Owner Area |
|---|---|---|---|
| 7 | Product_Identity_Agent (vision → spec extraction) | L | AI/CV |
| 8 | Use-case knowledge base (university, gaming, creative) | M | AI/Content |
| 9 | JA3/JA4 + GeoIP + ASN in fraud scorer | M | Security |
| 10 | MITRE ATT&CK event mapping | M | Security |
| 11 | MITRE ATLAS + OWASP LLM mapping | M | Security |
| 12 | Decision trace WebSocket streaming | M | Backend |
| 13 | Human escalation room full workflow | M | Backend |
| 14 | Session slot accumulation across NQE turns | M | AI |

### Q3 2026

| # | Item | Effort | Owner Area |
|---|---|---|---|
| 15 | Debate coordinator for complex comparisons | M | AI |
| 16 | Post-LLM verifier (hallucination reduction) | M | AI |
| 17 | BEC detection via LLM for email security | L | Security |
| 18 | GNN fraud ring detection | L | AI/Security |
| 19 | RAGAS evaluation pipeline | M | AI |
| 20 | ERP/EDI connector (NetSuite, Xero) | L | Integrations |
| 21 | MAESTRO agent boundary documentation + tests | M | Security |

---

*Document generated: March 2026 | ShopSquire Platform Deep Dive*
*Source analysis: codebase exploration (160+ services, 55+ security modules, 79 routers), existing investigation reports, screenshot analysis (smart-1.png, smart-2.png, lenovo-multimodal1.png, lenovo-multimodal2.png), NQE root cause trace*
