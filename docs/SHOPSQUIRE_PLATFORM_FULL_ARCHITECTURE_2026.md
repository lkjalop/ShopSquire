# ShopSquire — Full Platform Architecture Deep Dive (March 2026)

> **Document scope:** Complete platform analysis covering brand positioning, every agent, every pipeline, RAG/cache-RAG, the React frontend (port 5173), NLP/CV/OCR, buyer + agentic security, merchant & admin, email lab, escalation rooms, interleaved thinking, bitemporal decision tracing, dynamic prompt injection, and how the learned tier-router relates to GLM-style recursive learning. Includes left-to-right ASCII architecture diagrams and user-flow walkthroughs.

---

## Table of Contents

1. [What Is ShopSquire? — Brand Positioning](#1-what-is-shopsquire--brand-positioning)
2. [High-Level Architecture ASCII Map](#2-high-level-architecture-ascii-map)
3. [System Components At a Glance](#3-system-components-at-a-glance)
4. [Infrastructure & Docker Topology](#4-infrastructure--docker-topology)
5. [4-Phase Orchestrator — EXPLORE → EVALUATE → PLAN → ACTION](#5-4-phase-orchestrator)
6. [Agent Roster — All Active Agents](#6-agent-roster--all-active-agents)
7. [Pipeline Walkthroughs](#7-pipeline-walkthroughs)
   - 7.1 Product Recommendation Pipeline
   - 7.2 Return-Fraud CV Triage Pipeline
   - 7.3 Email Security Pipeline
   - 7.4 Incident Escalation Pipeline
   - 7.5 Decision Audit & Time-Travel Pipeline
8. [RAG & Cache-RAG Implementations](#8-rag--cache-rag-implementations)
9. [The Frontend — Port 5173 (React / TypeScript / Vite)](#9-the-frontend--port-5173)
10. [NLP Subsystem](#10-nlp-subsystem)
11. [Computer Vision & OCR Subsystem](#11-computer-vision--ocr-subsystem)
12. [Buyer Security & Fraud Scoring](#12-buyer-security--fraud-scoring)
13. [Agentic Platform Security](#13-agentic-platform-security)
14. [Merchant & Admin Platform](#14-merchant--admin-platform)
15. [Email Security Lab](#15-email-security-lab)
16. [Escalation Rooms](#16-escalation-rooms)
17. [Interleaved Thinking](#17-interleaved-thinking)
18. [Bitemporal Decision Trace](#18-bitemporal-decision-trace)
19. [Dynamic Prompt Injection for RAG Pipelines (Atomic Agents)](#19-dynamic-prompt-injection-for-rag-pipelines)
20. [Learned Tier Router & GLM-Style Recursive Learning](#20-learned-tier-router--glm-style-recursive-learning)
21. [Session & Episodic Memory Architecture](#21-session--episodic-memory-architecture)
22. [Complexity Scoring & LLM Model Selection](#22-complexity-scoring--llm-model-selection)
23. [Policy Gate & Playbook Engine](#23-policy-gate--playbook-engine)
24. [Compliance & Audit Chain](#24-compliance--audit-chain)
25. [User-Flow Walkthroughs (End-to-End)](#25-user-flow-walkthroughs-end-to-end)

---

## 1. What Is ShopSquire? — Brand Positioning

ShopSquire is an **AI intelligence and security orchestration layer** that sits on top of existing ecommerce infrastructure. It is **not** a Shopify replacement, a payment gateway, or a CrowdStrike substitute. It is the connective tissue between your storefront, your security stack, and your operations team.

```
                  ┌─────────────────────────────────────────────────────┐
                  │               SHOPSQUIRE LAYER                       │
                  │  AI-native · Agentic · Bitemporal · Shift-Left Sec  │
                  └─────────────────────────────────────────────────────┘
                         ▲                    ▲                  ▲
             ┌───────────┘          ┌─────────┘        ┌────────┘
             │ Shopify /            │ Stripe /          │ CrowdStrike /
             │ Magento /            │ Afterpay /        │ SIEM / Firewall /
             │ WooCommerce          │ PayPal             │ Email Security
             └──────────────────    └────────────────── └──────────────────
```

**Brand Positioning:**

| Dimension | Claim |
|-----------|-------|
| **Primary** | AI-native agentic intelligence + shift-left security for ecommerce |
| **Target** | Mid-market to enterprise merchants needing AI-augmented ops + security |
| **Differentiator #1** | Bitemporal decision audit trail — every agent decision is temporally versioned and cryptographically chained |
| **Differentiator #2** | Computer vision triage for return fraud — in-pipeline image forensics at claim submission time |
| **Differentiator #3** | 4-phase agentic orchestrator (EXPLORE→EVALUATE→PLAN→ACTION) with interleaved thinking loops |
| **Differentiator #4** | 55+ security modules baked into the recommendation pipeline, not bolted on |
| **ANZ Opportunity** | AusPost/StarTrack integration, $62B market, no local AI-native security platform competitor |
| **Competitive Quadrant** | Unoccupied: HIGH security depth + HIGH ecommerce domain depth |

**What ShopSquire Does (Feature Map):**

```
BUYER JOURNEY                     MERCHANT OPS                    SECURITY
─────────────                     ────────────                    ────────
Conversational shopping     →     Admin BI dashboard        →     Email threat lab
  + NQE clarification             Inventory intelligence          Return fraud CV triage
  + multimodal (images)           Supplier scorecard              Fraud ring detection
  + session memory                Order lifecycle mgmt            Escalation rooms
  + product comparison            Playbook automation             Compliance audit trail
  + voice (STT/TTS)               Celery background jobs          Bitemporal logs
  + recommendations               DMARC / BIMI controls           MAESTRO / ATLAS mapping
```

---

## 2. High-Level Architecture ASCII Map

```
USER (Browser, Mobile)
        │
        │  HTTPS / WSS
        ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Vite + React, :5173)                    │
│  ChatOverlay  │  ProductGrid  │  CVResultsPanel  │  DecisionTrace  │  Admin    │
│  EscalationRoom  │  CartPanel  │  DisambiguationButtons  │  VoiceSTT          │
└──────────────────────────────────┬────────────────────────────────────────────┘
                                   │  REST / WebSocket
                                   ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                    FASTAPI BACKEND (:8080)                                      │
│                                                                                │
│  ┌─ MIDDLEWARE STACK ──────────────────────────────────────────────────────┐  │
│  │ TLSFingerprint → RateLimit → SecurityHeaders → mTLS → PCI → Idempotency│  │
│  │ AdminMFA → Webhook → Compliance → CORS → OpenTelemetry                  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌─ ROUTER LAYER (79 routers) ────────────────────────────────────────────┐  │
│  │                                                                          │  │
│  │  /chat  /recommend  /cv  /vision  /voice  /intent  /query              │  │
│  │  /orders  /cart  /payments*  /billing  /products                        │  │
│  │  /decisions  /decision_time_travel  /trace_debug                        │  │
│  │  /fraud  /scoring  /email  /admin/email  /dmarc                         │  │
│  │  /admin/incidents  /incidents  /escalation_room                         │  │
│  │  /admin/bi  /admin/analytics  /admin/playbooks  /admin/grc              │  │
│  │  /session_memory  /audit  /graph  /security_integrations                │  │
│  │  /metrics (Prometheus)  /health  ...30+ more                            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌─ 4-PHASE ORCHESTRATOR ─────────────────────────────────────────────────┐  │
│  │                                                                          │  │
│  │  EXPLORE          EVALUATE          PLAN              ACTION             │  │
│  │  ──────────       ──────────        ──────────        ──────────        │  │
│  │  NLP_Search    →  Candidate_     →  Interleaving  →  Policy_Gate       │  │
│  │  Security_Obs     Retrieval         Controller        Playbook_Engine   │  │
│  │  CV_Label         Product_          Debate/           Decision_Log      │  │
│  │  Product_Id       Ranking           Refinement        Event_Bus         │  │
│  │  Agent            Fraud_Score                         Notifications     │  │
│  │                   Inventory                                              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌─ SERVICES LAYER (160+ services) ───────────────────────────────────────┐  │
│  │  LLM_Provider │ TierRouter │ SemanticCache │ RAG │ PolicyGate          │  │
│  │  FraudScorer │ InventoryAgent │ PlaybookEngine │ EpisodicMemory        │  │
│  │  EmailSecurity │ CVTiered │ BIIntelligence │ DecisionLog              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬────────────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
  ┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
  │  PostgreSQL  │    │     Redis :6379   │    │   Ollama (LLM)   │
  │  (Primary)   │    │  Session Memory  │    │  llama3.3:8b     │
  │  8 core ORM  │    │  Semantic Cache  │    │  mixtral:8x7b    │
  │  tables +    │    │  Celery Broker   │    │  llava (vision)  │
  │  audit chain │    │  Pub/Sub         │    └──────────────────┘
  └─────────────┘    └──────────────────┘
          │
  ┌───────┴──────────────────────────────────────────────────────┐
  │                   BACKGROUND WORKERS                          │
  │  Celery-Worker │ Celery-Beat │ Sync-Worker                   │
  │  CrowdStrike-Poll │ Syslog-Listener                          │
  └──────────────────────────────────────────────────────────────┘
          │
  ┌───────┴──────────────────────────────────────────────────────┐
  │                   OBSERVABILITY                               │
  │  Prometheus (:9090) │ Grafana (:3005) │ AlertManager (:9093) │
  │  OpenTelemetry (OTLP traces) │ Structured JSON logs          │
  └──────────────────────────────────────────────────────────────┘
```

---

## 3. System Components At a Glance

| Component | Technology | Scale |
|-----------|-----------|-------|
| Backend | FastAPI 0.110, Python 3.10+ | 79 routers, 160+ services |
| Frontend | React 18, TypeScript, Vite | 23 components |
| Primary DB | PostgreSQL 16 | 8 ORM tables + audit chain |
| Cache/Broker | Redis 7 | Session, semantic cache, Celery |
| LLM Inference | Ollama (local) + OpenAI/Anthropic fallback | 3-tier model selection |
| CV | OpenCV, Pillow, YOLO, Tesseract/Paddle | 7 CV service files |
| Task Queue | Celery 5.3, Redis broker | 4 scheduled tasks |
| Security | 55+ modules | MITRE ATLAS, MAESTRO, OWASP LLM Top 10 |
| Observability | Prometheus, Grafana, OpenTelemetry | Metrics + traces + structured logs |
| Graph | Neo4j + PyG (optional) | Fraud ring GNN detection |
| Auth | JWT, RBAC, mTLS (internal) | 5 role levels |
| Compliance | GDPR, PCI-DSS, SOC2, ISO42001 | Per-request middleware |

---

## 4. Infrastructure & Docker Topology

```
docker-compose.yml  (9 container services)

┌─────────────────────────────────────────────────────────────────────┐
│                         DOCKER NETWORK                               │
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │     api      │    │      db      │    │       redis          │  │
│  │ FastAPI:8080 │◄──►│ Postgres:5432│    │ Redis:6379           │  │
│  │ read_only    │    │ shopsquire DB│    │ requirepass ACL      │  │
│  │ non-root     │    └──────────────┘    │ DB0=app, DB1=celery  │  │
│  │ no-new-priv  │         ▲              └──────────────────────┘  │
│  └──────────────┘         │                       ▲                 │
│         ▲                 │                       │                 │
│         │                 └───────────────────────┤                 │
│  ┌──────┴──────────────────────────────────┐      │                 │
│  │           BACKGROUND WORKERS             │      │                 │
│  │                                           │      │                 │
│  │ sync-worker      ← CSV / Shopify ERP sync│      │                 │
│  │ crowdstrike-poll ← Threat intel (5min)   │      │                 │
│  │ syslog-listener  ← UDP/TCP :5514         │──────┘                 │
│  │ celery-worker    ← Async tasks           │                        │
│  │ celery-beat      ← Scheduled cron        │                        │
│  └───────────────────────────────────────────┘                       │
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  prometheus  │    │  grafana     │    │   alertmanager       │  │
│  │   :9090      │    │   :3005      │    │      :9093           │  │
│  │  (loopback)  │    │  (loopback)  │    │   (loopback)         │  │
│  └──────────────┘    └──────────────┘    └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Key security controls on `api` container:**
- `read_only: true` filesystem
- `no-new-privileges:true`
- `tmpfs: 256MB` for /tmp only
- Runs as `shopsquire` non-root user
- `INTERNAL_MTLS_REQUIRED=1` enforced between services

---

## 5. 4-Phase Orchestrator

**File:** `src/app/services/orchestrator.py`

The orchestrator is the heart of ShopSquire. Every inbound request flows through its 4-phase pipeline. Each phase has an **agent budget** (fraction of global token budget), **SLO targets** (ms), and an **adaptive complexity scalar**.

```
REQUEST
   │
   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  PHASE 1 — EXPLORE                                                        │
│                                                                            │
│  Goal: Gather raw signals about the user's intent and context             │
│                                                                            │
│  Agents invoked (parallel where possible):                                │
│   Security_Observer_Agent  (budget 20%) ─ threat context, session risk   │
│   NLP_Search_Agent         (budget 20%) ─ intent/slots/constraints       │
│   CV_Label_Agent           (budget 12%) ─ image forensics + labels       │
│   Product_Identity_Agent   (budget  8%) ─ vision LLM → product specs     │
│                                                                            │
│  Output: NLP slots, image signals, threat context, product identity       │
└─────────────────────────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  PHASE 2 — EVALUATE                                                        │
│                                                                            │
│  Goal: Score and rank candidates                                           │
│                                                                            │
│  Agents invoked (sequential pipeline):                                    │
│   Candidate_Retrieval_Agent (budget 16%) ─ catalog search + shortlist    │
│   Product_Ranking_Agent     (budget 20%) ─ listwise rerank + WHY text    │
│   Fraud_Scoring_Agent       (budget  6%) ─ 26+ signal risk score         │
│   Inventory_Agent           (budget  6%) ─ stock + ETA + supplier trust  │
│                                                                            │
│  Output: Ranked shortlist with fraud score, inventory status, WHY text   │
└─────────────────────────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  PHASE 3 — PLAN                                                            │
│                                                                            │
│  Goal: Refine decision via bounded think→tool→observe loops               │
│                                                                            │
│  Mechanisms:                                                               │
│   InterleavingController — up to 4 think/tool cycles (budget 4 tools)    │
│   NQE (Next Question Engine) — propose clarifying questions if needed     │
│   SemanticCache — check for prior equivalent queries                      │
│   PolicyGate — pre-screen proposed action for compliance                  │
│                                                                            │
│  Output: Final proposal or NQE questions, policy verdict                  │
└─────────────────────────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  PHASE 4 — ACTION                                                          │
│                                                                            │
│  Goal: Execute decision and persist audit trail                            │
│                                                                            │
│  Steps:                                                                    │
│   1. Policy_Gate_Agent final check (allow / review / deny)                │
│   2. Playbook_Engine trigger (if security condition met)                  │
│   3. decision_log.log_decision() — bitemporal DB write                   │
│   4. Agent_Bus.publish() — emit events to downstream consumers            │
│   5. Webhook dispatcher — notify external systems                         │
│   6. Return response to router → frontend                                 │
│                                                                            │
│  Output: API response + audit record + event bus notifications            │
└──────────────────────────────────────────────────────────────────────────┘
```

**Adaptive Agent Budgets** (`src/app/services/orchestrator.py:219-276`):

Budget allocation scales dynamically. The global budget is multiplied by a complexity factor:
```
factor = 1.0
  + 0.25 if tier >= 2
  + 0.25 if fraud_risk >= 40%
  + 0.20 if intent_confidence < 0.70
  + 0.15 if multi_turn depth > 3
```
This means a high-risk, low-confidence multi-turn query gets a 1.85× budget — each agent gets ~85% more computation time.

**SLO Enforcement:** Each agent step has a `AGENT_STEP_SLO_MS` threshold (default 1800ms). Breach triggers `_mark_trace_degraded("step_slo_breach")` and downgrades the trace quality metric in Prometheus.

---

## 6. Agent Roster — All Active Agents

### EXPLORE Phase Agents

#### NLP_Search_Agent
**File:** `src/app/services/nlp_search_agent.py`
**Budget:** 20% of global
**What it does:**
- Parses natural-language shopping queries into structured **slots** (budget_min/max, brands, specs, use-cases, negations)
- Uses a PEG-style grammar with regex patterns for fuzzy budget phrases ("around $1500", "between 1k and 2k")
- Tracks **intent confidence** (0.0–1.0 scale)
- Accumulates slots across multi-turn sessions (additive, not replacement)
- Detects: comparison intent, use-case signals (university, gaming, creative, corporate), negation ("not Dell", "no AMD")

**Input:** raw query string + session slot state
**Output:** `NLPSearchResult { slots: Dict, intent: str, confidence: float, missing_fields: List[str] }`

#### Security_Observer_Agent
**File:** `src/app/agents/security_observer_agent.py`
**Budget:** 20% of global
**What it does:**
- Runs at the top of every request to compute **threat context**
- Reads: session risk flags, fraud_score from prior turns, IP velocity signals, TLS fingerprint from middleware
- Emits `security_event` to event bus if any signal exceeds threshold
- Informs Phase 2 whether to boost Fraud_Scoring_Agent budget

**Input:** session context + request metadata
**Output:** `SecurityContext { threat_level: str, active_signals: List[str], session_risk: float }`

#### CV_Label_Agent
**File:** `src/app/services/cv_tiered.py` (tiered provider)
**Budget:** 12% of global
**What it does:**
- Ingests uploaded product images
- **Tier 0:** Hash + size extraction
- **Tier 1:** Object detection, text extraction, quality scoring (blur/histogram)
- **Tier 2:** Full forensics — EXIF analysis, manipulation detection, GAN detection, steganography, QR decode + redirect chain analysis
- Emits signals: `exif_date_mismatch`, `stock_photo_detected`, `manipulation_detected`, `cv_duplicate_hash`, etc.

**Input:** base64 or binary image + `CVContext`
**Output:** `CVAnalysisResult { labels: List, ocr_text: str, forensics: Dict, tier: int, signals: Dict }`

#### Product_Identity_Agent
**File:** `src/app/services/product_identity_agent.py`
**Budget:** 8% of global
**What it does:**
- Calls Ollama **llava vision model** to extract structured product specs from an uploaded image
- Extracts: brand, model, CPU tier, RAM, GPU, display size, form factor
- Injects extracted specs as **hard constraints** into the recommendation pipeline
- Replaces manual "what's the RAM in this laptop?" NQE questions when image is clear

**Input:** image URL or base64 + prior labels
**Output:** `ProductIdentity { brand: str, model: str, cpu_tier: str, ram_gb: int, gpu: str, ... }`

**Status:** Functional when Ollama is present; silently degrades if vision model unavailable.

### EVALUATE Phase Agents

#### Candidate_Retrieval_Agent
**File:** `src/app/services/recommendations.py`
**Budget:** 16% of global
**What it does:**
- Takes structured slots → constructs catalog query (price range, category, brand filters)
- Loads product catalog from PostgreSQL / JSON data
- Applies budget_tier bands (entry/mid/premium/flagship)
- Returns top-N candidate SKUs with scores
- Preserves `last_shortlist_skus` in Redis session for follow-up turns

**Input:** `RecommendationRequest { slots, session_id, filters }`
**Output:** `List[CandidateSKU { sku, score, price_cents, specs }]`

#### Product_Ranking_Agent
**File:** `src/app/services/product_ranking_agent.py`
**Budget:** 20% of global
**What it does:**
- **Listwise reranking** — evaluates all candidates together as a set, not pairwise
- Computes `spec_match_score` (0.0–1.0) per product vs. user constraints
- Enforces **diversity** — prevents N near-identical products dominating (diversity keys: brand|cpu_family|ram_tier)
- Generates **contrastive WHY explanations** — "Best pick because: M3 Pro matches your video editing need, 18GB fits Final Cut Pro, $300 under budget"

**Input:** `List[CandidateSKU]` + user constraints
**Output:** `RankedShortlist [ { sku, rank, score, why_text, diversity_key } ]`

#### Fraud_Scoring_Agent
**File:** `src/app/services/fraud_scorer.py`
**Budget:** 6% of global
**What it does:**
- Scores a transaction/claim across **34 fraud signals** in 13 categories
- Computes weighted fraud risk 0.0–1.0 → buckets: minimal/low/medium/high
- See Section 12 for full signal breakdown

#### Inventory_Agent
**File:** `src/app/services/inventory_agent.py` (~1000 lines)
**Budget:** 6% of global
**What it does:**
- Stock availability per SKU + warehouse
- **Lead time analysis** and supplier trust scoring (JIT, dual-source confirmation, trust bands)
- **EOQ (Economic Order Quantity)** calculations for reorder recommendations
- Daily demand forecasting and safety stock calculation
- Multi-supplier scenario handling, urgency escalation

**Input:** shortlisted SKUs
**Output:** `InventoryStatus { in_stock: bool, eta_days: int, supplier_trust: str, reorder_needed: bool }`

### PLAN Phase — NQE (Next Question Engine)

#### NQE — NextQuestionEngine
**File:** `src/app/flows/nqe.py` (622 lines)
**What it does:**
- Proposes **clarifying questions** when slots are insufficient (budget unknown, use-case unclear, etc.)
- **Up to 3 questions** per turn, risk-prioritized
- **Context injection:** injects facts from structured state into answered_fields, skips redundant questions for returning customers
- **Use-case detection:** university, gaming, corporate, touch-screen, creative
- **Game/software detection:** 14 game titles, 10 software titles (Minecraft → needs GPU; AutoCAD → needs RAM)
- **Quick-reply options:** returns `{ id, question, options: [str] }` for disambiguation buttons

```python
# Key NQEInput fields (src/app/flows/nqe.py:21-49)
class NQEInput(BaseModel):
    intent: str
    product_category: str
    missing_fields: List[str]
    previously_asked_ids: List[str]     # dedup across turns
    answered_fields: Dict[str, Any]     # injected from session memory
    facts: Dict[str, Any]               # Layer 1 memory
    has_image: bool
    image_identity_confidence: float
    detected_use_case: Optional[str]
    detected_games: List[str]
    detected_software: List[str]
    user_profile: Dict                  # returning customer prefs
```

**Critical flow:**
1. Inject `facts` → `answered_fields` (skip questions already answered by structured state)
2. Inject `user_profile` prefs (skip budget question for known budget tier)
3. Filter templates by `previously_asked_ids` (no repeats)
4. Score templates by relevance to `missing_fields`
5. Convergence detection: stop after 3 high-signal slots answered
6. Return ordered `List[NextQuestion]` (max 3)

### ACTION Phase Agents

#### Policy_Gate_Agent
**File:** `src/app/policy/gate.py` (150+ lines)
**What it does:**
- Deterministic rule-based gate for all tool calls
- Rules: sensitive field check, high-risk tool check, refund threshold, order cancel post-ship, refund aggregate window
- Outputs: `allow / review / deny` + compliance tags (PCI-DSS, GDPR, SOC2, ISO42001)
- Feature-flag driven thresholds from `config/feature_flags.json`

#### Audit_Evidence_Agent
**File:** `src/app/agents/audit_evidence_agent.py`
**What it does:**
- 50+ audit rules covering log integrity, privacy, access control, change management
- Maps to SOX, SOC2, ISO27001, GDPR, EUAI, ATLAS frameworks
- All checks are deterministic (database/fact-based, no LLM required)

#### BI_Query_Agent
**File:** `src/app/agents/bi_query_agent.py`
**What it does:**
- Natural-language to BI SQL adapter
- Intents: refund_rate, chargeback_rate, approval_rate, autonomy_rate, MTTD/MTTR, revenue trends
- Builds parameterized SQL with dialect-aware timestamp expressions (SQLite vs. PostgreSQL)

---

## 7. Pipeline Walkthroughs

### 7.1 Product Recommendation Pipeline

```
User types: "I need a laptop for uni, gaming on weekends, around $1500, not Dell"
                │
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ROUTER: /api/v1/recommend/proposal  (routers/recommend.py)           │
│                                                                       │
│ 1. Load session memory from Redis                                     │
│    session:{uid}:summary → chat history summary                      │
│    session:{uid}:kv_state → prior slots                              │
│    session:{uid}:nqe_asked_ids → previously asked questions          │
│    session:{uid}:structured_state → confirmed budget/brand facts     │
│                                                                       │
│ 2. Compute complexity score                                           │
│    → "gaming" +1, "university" +1, budget present +1 = score 4      │
│    → Tier: small (llama3.3:8b)                                       │
│                                                                       │
│ 3. Check SemanticCache                                                │
│    → cache miss (new query) → proceed to orchestrator                │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR PHASE 1 — EXPLORE                                        │
│                                                                       │
│ NLP_Search_Agent:                                                     │
│   budget_min=1400, budget_max=1600, use_case=["university","gaming"] │
│   negations=["Dell"], confidence=0.78                                 │
│                                                                       │
│ Security_Observer_Agent:                                              │
│   session_risk=0.02 (new session, no flags)                          │
│   threat_level="minimal"                                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR PHASE 2 — EVALUATE                                       │
│                                                                       │
│ Candidate_Retrieval_Agent:                                            │
│   Query: price 1400-1600, category=laptop, exclude brand=Dell        │
│   Results: 12 candidates                                              │
│                                                                       │
│ Product_Ranking_Agent:                                                │
│   Gaming need detected → boost GPU score                             │
│   University need → boost SSD score, battery                         │
│   Top 3: Lenovo IdeaPad Pro 5, ASUS ROG Zephyrus G14, Acer Nitro 5  │
│                                                                       │
│ Fraud_Scoring_Agent:                                                  │
│   Product search, not a return claim → score 0.01 (minimal)         │
│                                                                       │
│ Inventory_Agent:                                                      │
│   All 3 in stock, ETA 2 days, supplier trust=high                   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR PHASE 3 — PLAN                                           │
│                                                                       │
│ Missing fields: ["primary_use_depth", "touch_screen_needed"]         │
│ NQE fires (2 questions):                                             │
│   Q1: "Is gaming your main daily use or mostly for weekends?"        │
│       Options: [Mainly weekends, 50/50, Primary daily use]           │
│   Q2: "Do you need touch screen for uni?"                            │
│       Options: [Yes, helpful, No]                                     │
│                                                                       │
│ Persist: nqe_asked_ids → Redis                                       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR PHASE 4 — ACTION                                         │
│                                                                       │
│ PolicyGate: ALLOW (product recommendation, no risk flags)             │
│ Decision logged: bitemporal valid_from=now, valid_to=∞               │
│ Response sent to frontend:                                            │
│   - shortlist: [Lenovo, ASUS, Acer]                                   │
│   - next_questions: [Q1, Q2]                                         │
│   - complexity: { score: 4, tier: "small", model: "llama3.3:8b" }   │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 Return-Fraud CV Triage Pipeline

```
Buyer uploads photo of "damaged" laptop with return claim
                │
                ▼
POST /api/v1/cv/upload (routers/cv.py)
  │
  ├─ Issue nonce check (anti-replay)
  ├─ Consume CV quota (tenant budget)
  ├─ MIME validation + size limit check
  │
  ▼
CV Tier Router (services/cv_tiered.py)
  │
  ├─ Tier 0: Extract phash, file size, MIME
  ├─ Tier 1: Object detection (YOLO) → detect laptop, damage region
  │           OCR extraction (Tesseract/Paddle/fallback)
  │           Image quality: blur score, histogram anomaly
  │           EXIF analysis: capture date vs. claim date
  ├─ Tier 2: Manipulation detection (splicing, cloning)
  │           GAN/Diffusion detection
  │           Steganography scan
  │           QR code decode → redirect chain analysis
  │           Prompt injection detection in OCR text
  │
  ▼
Fraud_Scoring_Agent receives CV signals:
  exif_date_mismatch=True (photo from 2024, claim filed 2026) → +0.15
  damage_not_visible=True (no damage in image) → +0.20
  stock_photo_detected=True (phash match in fraud DB) → +0.25
  cv_metadata_stripped=True → +0.25
  ───────────────────────────────────────────────────
  risk_score = 0.85 → HIGH RISK
  │
  ▼
PolicyGate: risk > 0.7 → decision = "review" (human review required)
PlaybookEngine: trigger "high_risk_return_review" playbook
  Action 1: Create HumanReviewTask in DB
  Action 2: Create escalation room token (buyer + staff)
  Action 3: Notify staff team via email/Slack
Decision logged: bitemporal + evidence_bundle_id attached
```

### 7.3 Email Security Pipeline

```
Inbound email (raw MIME) → POST /api/v1/email/analyze
  │
  ├─ Rate limit check (per-minute per-tenant)
  ├─ Intake normalization (size, MIME, attachment scan)
  │
  ▼
Header Forensics (email_header_forensics.py):
  - SPF/DKIM/DMARC validation
  - Sender IP reputation
  - Received chain analysis (relay hopping)
  │
  ▼
Indicator Extraction (email_security_rules.py):
  - Extract IoCs: URLs, IPs, domains, attachment hashes
  - Pattern matching: phishing keywords, credential harvest patterns
  │
  ▼
Attachment Intelligence (email_attachment_parser.py):
  - Unzip, extract artifacts
  - Scan Office XML for VBA macros
  - Hash match against threat feed DB
  │
  ▼
Threat Enrichment (email_enrichment.py):
  - Enrich IoCs with threat intel APIs (VirusTotal, URLhaus)
  - Kill chain inference (BEC, spear phish, malware dropper)
  │
  ▼
Verdict Computation (email_security_verdict.py):
  - Rule-first deterministic verdict
  - Severity: ERROR / WARN / INFO
  - Route: BLOCK / SANDBOX / ALERT / ALLOW
  │
  ▼
Sender Trust Scoring (email_sender_trust.py):
  - Update persistent sender reputation
  - Score decay applied over time
  │
  ▼
Playbook Execution (if BLOCK/SANDBOX):
  - start_playbook_run()
  - execute_typed_actions(): quarantine, alert, ticket, forward
  - complete_playbook_run()
  │
  ▼
Admin Dashboard: email verdict + IoC list visible in /admin/email
```

### 7.4 Incident Escalation Pipeline

```
High-risk return claim (fraud_score > 0.7) triggers escalation
                │
                ▼
POST /api/v1/admin/incidents (escalation_room.py)
  - Create incident record (DB)
  - Generate buyer_token + staff_token (UUID, 24h TTL, Redis)
  - Start SLA timer (sla_due_at = now + sla_minutes)
  │
  ├─ Buyer WebSocket: /api/v1/incidents/{id}/ws?token={buyer_token}
  │     → buyer can attach additional evidence
  │     → buyer receives real-time staff messages
  │
  ├─ Staff WebSocket: /api/v1/admin/incidents/{id}/ws?token={staff_token}
  │     → staff sees full fraud signals + CV analysis
  │     → staff can: assign, escalate, resolve, close
  │
  ├─ Evidence Upload: POST /api/v1/incidents/{id}/evidence
  │     → additional images → re-run CV pipeline
  │
  └─ Playbook: execute "escalation_review" playbook
       - SLA check every 5 min via Celery beat
       - SLA breach → alert staff team lead
       - Auto-close after resolution
```

### 7.5 Decision Audit & Time-Travel Pipeline

```
Every agent decision →
  decision_log.log_decision()
    │
    ├─ Bitemporal DB write:
    │   INSERT INTO decision_logs (
    │     valid_from, valid_to,           ← domain time
    │     system_from, system_to,         ← DB recording time
    │     input_data, agent_reasoning,
    │     proposed_action, execution_status,
    │     policy_version, approval_required
    │   )
    │
    ├─ Merkle chain update (decision_audit.py):
    │   record_hash = SHA256(this_record)
    │   prev_hash = SHA256(previous_record)
    │   → tamper-evident chain
    │
    └─ Trace event emitted (decision_trace_events table):
        trace_id, seq, event_type, source_id, payload

Time-travel query → GET /api/v1/decisions/replay/by_id/{id}
  - Reconstructs the exact world state at any past valid_time
  - Returns all decisions valid at that time
  - Frontend: DecisionTrace.tsx visualizes the audit waterfall
```

---

## 8. RAG & Cache-RAG Implementations

ShopSquire has three distinct retrieval layers that work together:

### Layer 1 — Document RAG (`src/app/rag/`)

**File:** `src/app/rag/retrieve.py` + `src/app/rag/index.py`

```python
# Naive dense retrieval with cosine similarity
class SimpleEmbeddings:
    def embed(text: str) -> List[float]  # Simple TF-IDF-style embeddings
    def cosine(a, b) -> float

class RAGRetriever:
    chunk_size = 420 chars
    k = 4 hits

    def retrieve(query, tenant_id) -> List[RetrievedChunk]:
        chunks = doc_store.get_all(tenant_id)  # from policy_docs.json
        scored = [(cosine(embed(query), embed(c.content)), c) for c in chunks]
        return top_k(scored, 4)
```

**Document store:** `src/app/rag/sources/policy_docs.json` — tenant-keyed policy documents

**Guardrails:** `allow_query()` + `allow_doc()` — tenant-scoped allowlist prevents cross-tenant leakage

**What it's used for:** Policy retrieval (return policy, shipping policy, warranty terms) injected into recommendation responses and playbook decisions.

### Layer 2 — Semantic Cache (`src/app/services/semantic_cache.py`)

**This is "cache-RAG"** — a Redis-backed L1 cache in front of the LLM that stores prior responses keyed by semantic similarity, not exact string match.

```python
class SemanticCache:
    backend: Redis (with in-process dict fallback)

    def get(query_embedding) -> Optional[CachedResponse]:
        # Find semantically similar cached entry
        # Returns if cosine similarity > threshold

    def set_safe(key, value, trust_score, source_id):
        # Wraps value with metadata:
        # { _meta: { source_id, trust_score, poison_reason } }

    def quarantine(key, poison_reason):
        # Marks entry as suspected adversarial cache injection
        # Maps to OWASP LLM08: Vector/Embedding Weaknesses
```

**Security:** `quarantine()` implements protection against **cache poisoning attacks** — if a cached entry is suspected of being adversarially injected, it is flagged and excluded from future retrieval. This directly maps to OWASP LLM Top 10 2025 LLM08.

### Layer 3 — Episodic Memory as Implicit RAG (`src/app/services/episodic_memory.py`)

Returning user profiles and past session summaries act as **implicit RAG** — the system "retrieves" personalized context without needing a vector search because the user's profile is keyed by user_id:

```
Redis key: profile:{user_id} → UserProfile {
    preferred_brands, avoided_brands, budget_tier,
    typical_use_cases, purchase_history_summary,
    last_session_summary
}
```

When a returning user asks "same as last time but cheaper", the orchestrator loads their profile and injects it as context — effectively a zero-shot RAG over their history.

### Dynamic Prompt Injection for RAG

See Section 19 for full treatment.

---

## 9. The Frontend — Port 5173

**Technology:** React 18, TypeScript, Vite
**Location:** `frontend/src/`

### Application Structure

```
frontend/src/
├── App.tsx              (2000+ lines — main state machine + routing)
├── main.tsx             (Vite bootstrap)
├── index.css
├── components/
│   ├── ChatOverlay.tsx          Conversational chat UI + NQE buttons
│   ├── ProductGrid.tsx          Grid of product cards with WHY text
│   ├── ProductComparison.tsx    Side-by-side spec comparison
│   ├── AttachmentButton.tsx     Image upload → CV pipeline
│   ├── CVResultsPanel.tsx       CV analysis output (labels, OCR, forensics)
│   ├── CameraButton.tsx         Mobile camera capture
│   ├── CartPanel.tsx            Shopping cart
│   ├── DecisionTrace.tsx        Bitemporal audit waterfall (65KB!)
│   ├── EscalationRoom.tsx       Incident room WebSocket chat
│   ├── DisambiguationButtons.tsx NQE quick-reply options
│   ├── RightPanelExtras.tsx     Tabbed right panel
│   ├── AdminDashboard.tsx       Admin analytics (18KB)
│   ├── OOBVerification.tsx      Out-of-band SMS/email verify
│   └── SecurityDemo.tsx         Security features showcase
└── lib/
    ├── api.ts                   API client (REST + WebSocket)
    └── imageProcessing.ts       Resize, compress, format convert
```

### State Machine (App.tsx)

```typescript
// Core state (App.tsx)
const [chat, setChat] = useState<ChatMessage[]>([])
const [rightPanelMode, setMode] = useState<RightPanelMode>('grid')
const [products, setProducts] = useState<Product[]>([])
const [complexity, setComplexity] = useState<ComplexityInfo>()
const [voiceUsed, setVoiceUsed] = useState(false)

// RightPanelMode options:
type RightPanelMode = 'grid' | 'list' | 'compare' | 'cv' | 'cart' | 'faq' | 'security' | 'visual_search'
```

### Chat Message Structure

```typescript
type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  images?: string[]                        // base64 attached images
  disambiguation?: boolean                 // show NQE buttons?
  disambiguationOptions?: string[]         // quick-reply option labels
  nextQuestions?: NextQuestion[]           // NQE structured questions
  complexity?: { score: number; tier: string; model: string }
  voiceUsed?: boolean
  nqeSelection?: NqeInteraction            // user clicked NQE option
  nqeSelectionApplied?: Record<string, any>  // backend echoed constraints
}
```

### Real-Time Streaming

```
WebSocket /api/v1/chat/ws       → message streaming (word-by-word)
WebSocket /api/v1/chat/decide   → decision event streaming
WebSocket /api/v1/decisions/trace/ws → DecisionTrace live updates
WebSocket /api/v1/admin/incidents/{id}/ws → Escalation room (staff)
WebSocket /api/v1/incidents/{id}/ws      → Escalation room (buyer)
```

### PII Detection (App.tsx)

The frontend has client-side PII detection **before** messages are sent:

```typescript
// Credit card: Luhn algorithm + context keywords (card/cvv/expiry)
// SSN: regex \d{3}-\d{2}-\d{4}
// Email: RFC pattern
// Phone: international + US formats

// On detection: show user-facing WARNING (not silent block)
// Advice: "We detected what looks like a credit card number.
//          Please don't share payment details in chat."
```

### Image Upload Flow

```
User selects image (AttachmentButton) or captures (CameraButton)
  → imageProcessing.ts: resize + compress + convert to WebP
  → GET /api/v1/cv/nonce (anti-replay nonce)
  → POST /api/v1/cv/upload { nonce, order_id, image_binary }
  → Backend: CV pipeline (see Section 11)
  → Response: { labels, ocr_text, forensics, tier, signals }
  → CVResultsPanel.tsx: display results
  → ProductGrid: re-rank products anchored to detected specs
```

### API Client (`lib/api.ts`)

```typescript
apiUrl(path)    // Builds from VITE_API_BASE_URL env
wsUrl(path)     // Switches http→ws / https→wss automatically
safeJson(resp)  // Error-tolerant JSON parsing

// CV specific:
cvAnalyze(caseId, labels, extractedText, imagesB64)
cvUpload(nonce, orderId, imageBinary)
cvIssueNonce()
```

---

## 10. NLP Subsystem

ShopSquire's NLP is currently **pattern-based** (not transformer-based) for the slot extraction layer, with LLM inference used only for free-text generation.

### Intent Classification Flow

```
Raw query
  │
  ├─ Router-level: chat.py extracts budget/brand via regex
  │   Budget: "between $X and $Y", "under $X", "around $X"
  │   Brands: hardcoded allowlist (Apple, Dell, Lenovo, ASUS, HP, Acer, MSI, Microsoft, Samsung)
  │
  ├─ NLP_Search_Agent: PEG-style grammar
  │   Specs: storage/ram/display/battery/weight tokens
  │   Negations: "not X", "no X", "avoid X"
  │   Intent confidence: 0.0–1.0
  │
  ├─ NQE game/software detection:
  │   14 game titles (Minecraft → needs dGPU+fast storage)
  │   10 software titles (AutoCAD → needs dedicated workstation GPU)
  │
  └─ Complexity scorer: token-level intent signals
      "compare/vs/tradeoff" → +2
      "explain/why/how" → +1 (follow-up)
      "gaming+university+touch" → +3 (multi-intent)
```

### Multi-Turn Slot Accumulation

Slots are **additive** not replacement. Session Redis key `session:{uid}:structured_state` holds:
```json
{
  "budget_min": 1400, "budget_max": 1600,
  "brands": [], "negated_brands": ["Dell"],
  "use_cases": ["university", "gaming"],
  "specs": { "touch_screen": null, "ram_min": null }
}
```

Each turn merges new slots in, never overwrites confirmed ones. This is how "same as before but no Dell" works correctly.

### Query Clustering (`src/app/services/nlp_query_clustering.py`)

Groups semantically similar queries across sessions to:
- Identify product category trends
- Feed back into catalog ranking
- Power admin analytics ("most common search clusters")

---

## 11. Computer Vision & OCR Subsystem

### CV Architecture (3-Tier)

```
Image Input
    │
    ├─ TIER 0 (immediate, <10ms)
    │   phash extraction, file size, MIME type
    │   Check against fraud_image_hashes DB
    │
    ├─ TIER 1 (fast, <200ms)
    │   Object detection (YOLO/OpenCV)
    │   Text extraction (OCR chain — see below)
    │   Image quality: blur score, histogram anomaly, contrast
    │   EXIF analysis: capture date, GPS, camera model, software
    │   Serial number extraction (serial_patterns.py)
    │
    └─ TIER 2 (thorough, <2s)
        Image manipulation detection (splicing, cloning)
        GAN / Diffusion detection (gan_image_detector.py)
        Adversarial attack detection (adversarial_image_detector.py)
        Steganography scan (steg_detector.py)
        QR code decode (pyzbar) → redirect chain analysis
        Document forensics (cv_document_forensics.py)
        Prompt injection detection in OCR text
```

### OCR Provider Chain (`src/app/services/cv_ocr.py`)

```
Image → OCR request
    │
    ├─ Provider: tesseract (pytesseract)
    │   Windows path: C:\Program Files\Tesseract-OCR\tesseract.exe
    │   Linux: /usr/bin/tesseract
    │   BUG-3: not in Docker image → silent fail
    │
    ├─ Provider: paddle (paddleocr)
    │   Lazy-loaded (~500MB model download on first run)
    │   Superior for Chinese/Asian characters
    │   BUG-3: not in Docker image → silent fail
    │
    ├─ Provider: builtin (OpenCV-based)
    │   Basic text detection
    │   No layout understanding
    │   FUNCTIONAL (opencv-python-headless is installed)
    │
    └─ Provider: embedded (regex tokenization)
        Synthetic "boxes" for testing
        Always available as final fallback
```

### OCR Post-Processing (`src/app/cv/ocr_postprocess.py`)

After raw OCR text is extracted:
- Serial number extraction (Dell, Apple, Lenovo, HP patterns)
- Warranty void sticker detection
- Screen damage pattern matching
- Prompt injection scan (e.g., malicious text embedded in product label)

### QR Code Security Analysis

QR codes in product images get special treatment:

```python
# Decode QR → get URL → follow redirect chain → score risk
risk_signals = {
    "punycode_domain": True,      # IDN homograph attack
    "url_shortener": True,        # t.co, bit.ly, tinyurl
    "ip_literal": True,           # http://192.168.1.1/...
    "excessive_redirects": True,  # >3 hops
    "redirector_params": True,    # ?url= ?redirect= params
}
```

URL risk scored 0.0–1.0, triggers `threat_intel_url.py` enrichment.

### CV → Fraud Signal Mapping

| CV Finding | Fraud Signal | Weight |
|-----------|-------------|--------|
| EXIF date before purchase | `exif_date_mismatch` | 0.15 |
| phash match in fraud DB | `image_hash_match_fraud_db` | 0.35 |
| Stock photo detected | `stock_photo_detected` | 0.25 |
| Clone/splice detected | `manipulation_detected` | 0.20 |
| Serial doesn't match order | `serial_mismatch` | 0.40 |
| Wrong product category | `product_category_mismatch` | 0.30 |
| No damage in damage claim | `damage_not_visible` | 0.20 |
| Blur score too low | `cv_blur_score_low` | 0.15 |
| Histogram anomaly | `cv_histogram_anomaly` | 0.20 |
| EXIF metadata stripped | `cv_metadata_stripped` | 0.25 |
| Date impossible (future) | `cv_timestamp_impossible` | 0.30 |
| Duplicate hash across cases | `cv_duplicate_hash` | 0.35 |

---

## 12. Buyer Security & Fraud Scoring

### Fraud Signal Registry — All 34 Signals (`src/app/services/fraud_scorer.py`)

**Identity (1 signal):**
- `image_hash_match_fraud_db` (0.35) — phash matched known fraud image

**Computer Vision (8 signals):**
- `exif_date_mismatch` (0.15), `stock_photo_detected` (0.25), `manipulation_detected` (0.20)
- `serial_mismatch` (0.40), `product_category_mismatch` (0.30), `damage_not_visible` (0.20)
- `cv_blur_score_low` (0.15), `cv_histogram_anomaly` (0.20)

**History (3 signals):**
- `high_return_frequency` (0.15), `previous_fraud_flag` (0.30), `chargeback_history` (0.20)

**Account (1 signal):**
- `account_age_under_30_days` (0.10)

**Behavior (2 signals):**
- `unusual_purchase_velocity` (0.25), `rapid_photo_submission` (0.20)

**Device (2 signals):**
- `device_fingerprint_mismatch` (0.35–0.40), `session_hijack_indicators` (0.35)

**Network (4 signals):**
- `ip_velocity_spike` (0.30), `asn_datacenter_session` (0.25)
- `asn_known_proxy_tor` (0.30), `mid_session_country_change` (0.35)

**Geo (3 signals):**
- `geographic_anomaly` (0.20), `geoip_high_risk_country` (0.20), `geoip_country_mismatch` (0.30)

**Commerce (2 signals):**
- `coupon_stacking_attempt` (0.20), `price_manipulation_attempt` (0.35)

**Graph (1 signal):**
- `shipping_address_clustered` (0.30) — Neo4j: same ship address across multiple fraudulent claims

**TLS Fingerprint (2 signals):**
- `ja3_known_fraud_tool` (0.35), `ja4_known_fraud_tool` (0.35)

**Returns (1 signal):**
- `return_pattern_abuse` (0.30)

**Biometrics (3 signals):**
- `biometric_mouse_bot_pattern` (0.30), `biometric_typing_bot_pattern` (0.30), `biometric_tap_bot_pattern` (0.25)

**CV Extensions (4 signals):**
- `cv_metadata_stripped` (0.25), `cv_timestamp_impossible` (0.30), `cv_duplicate_hash` (0.35), `rapid_photo_submission` (0.20)

**Scoring formula:**
```python
risk = sum(weight for signal, weight in WEIGHTS.items() if signals[signal])
normalized = min(1.0, risk / max_possible_weight)
band = "high" if normalized >= 0.7 else "medium" if >= 0.4 else "low" if >= 0.2 else "minimal"
```

### False Positive Cost Estimation

```python
# monitoring_snapshot() includes FP cost estimate
fp_cost_per_signal = $7.50  # Default; configurable per signal
estimated_fp_cost = active_signal_count * fp_cost_per_signal * expected_fp_rate
```

This enables ROI analysis on each fraud signal — if a signal has high FP rate and high cost to merchant, it can be disabled.

---

## 13. Agentic Platform Security

### Security Middleware Stack

```
Inbound Request
    │
    ├─ TLSFingerprintMiddleware     JA3/JA4 fingerprinting
    ├─ RateLimitMiddleware          Per-user/tenant/endpoint limits
    ├─ SecurityHeadersMiddleware    HSTS, CSP, X-Frame-Options, nosniff
    ├─ InternalMTLSMiddleware       mTLS validation between services
    ├─ PciBoundaryMiddleware        Sensitive field redaction (card, cvv, pan)
    ├─ IdempotencyMiddleware        Duplicate request detection
    ├─ AdminMfaMiddleware           MFA enforcement for /admin routes
    ├─ WebhookSecurityMiddleware    HMAC webhook signature validation
    ├─ ComplianceMiddleware         GDPR/SOC2 per-request audit trail
    └─ GlobalRequestShapeMiddleware Anomalous request shape detection
```

### Security Frameworks Mapped

| Framework | Mapping File | Notes |
|-----------|-------------|-------|
| MITRE ATLAS | `security/atlas_map.py` | Agentic AI threat tactics |
| MAESTRO | `security/maestro_boundaries.py` | CSA Feb 2025 agentic threat model |
| OWASP LLM Top 10 2025 | `security/owasp_map.py` | LLM08 → semantic_cache.py |
| OWASP Agentic AI Top 10 | `security/owasp_map.py` | Dec 2025 |
| GDPR/SOC2 | `security/compliance.py` | Per-request middleware |
| PCI DSS | `security/pci.py`, `security/pci_boundary.py` | Card data redaction |
| ISO42001 | `models/compliance_registry.py` | AI governance |

### Agent Guardrails (`src/app/security/agent_guardrails.py`)

- Input validation on all agent inputs (schema-level)
- Output validation on all agent outputs (schema + content)
- Tool allowlists per agent role (see InterleavingController Section 17)
- Jailbreak defense: `jailbreak_embedding_guard.py` — detects adversarial prompts in embedding space
- Model theft defense: `model_theft.py` — monitors for extraction attacks (repeated boundary probing)

### Semantic Cache Poison Defense

```python
# semantic_cache.py — OWASP LLM08 implementation
cache.set_safe(key, value, trust_score=0.9, source_id="verified_product_db")
# If trust_score < threshold → quarantine flag set
# Quarantined entries excluded from future retrieval
```

---

## 14. Merchant & Admin Platform

### Admin Routes

| Route | Purpose |
|-------|---------|
| `/api/v1/admin/bi/slo` | SLO alerts: latency P95, quality drop, error rate |
| `/api/v1/admin/bi/transactions/timeseries` | Transaction analytics time series |
| `/api/v1/admin/analytics` | Real-time event analytics |
| `/api/v1/admin/drift` | ML model drift detection |
| `/api/v1/admin/fairness` | Recommendation fairness metrics |
| `/api/v1/admin/playbooks` | Playbook CRUD + execution history |
| `/api/v1/admin/email` | Email template management |
| `/api/v1/admin/email_security` | Email security rules + verdicts |
| `/api/v1/admin/dmarc` | DMARC policy management |
| `/api/v1/admin/grc` | GRC compliance portal |
| `/api/v1/admin/compliance_reports` | Compliance report generation |
| `/api/v1/admin/supply_chain` | Supply chain rules |
| `/api/v1/admin/supply_chain_sim` | Supply chain simulation |
| `/api/v1/admin/interleaving` | A/B test configuration |
| `/api/v1/admin/storage` | File/asset management |
| `/api/v1/admin/api_keys` | API key management |
| `/api/v1/admin/grafana_proxy` | Grafana dashboard proxy |

### BI Intelligence (`src/app/services/bi_intelligence.py`)

```python
margin_intelligence(window_days=90):
    # Per-SKU: revenue, cost, margin, margin_pct
    # Flags low-margin items (margin_pct < 10%)
    # Returns top 100 SKUs

supplier_scorecard(window_days=60):
    # Composite score: 0.45×on_time + 0.35×(1-defect) + 0.20×quality_norm
    # Sorted by score DESC
```

### SLO Alerting (`src/app/routers/admin_bi.py`)

```python
_slo_state(value, warn_thresh, crit_thresh) → "ok" | "warn" | "critical"
_http_p95_ms_from_prom() → Parse Prometheus histogram buckets → P95 latency
```

The SLO dashboard shows: recommendation latency P95, fraud score quality (ground truth accuracy), event drop rate (missed events).

### Merchant Dashboard (`src/app/routers/merchant_dashboard.py`)

- Local-only demo mode (bypasses auth for loopback addresses)
- Redirects to `/merchant/app/index.html?tab=merchant-bi`
- FAQ dashboard with API key auth for non-local access

### Celery Background Jobs

| Job | Schedule | Purpose |
|-----|---------|---------|
| `poll_crowdstrike` | Every 5 min | Pull CrowdStrike threat intel, ingest events |
| `train_recommend_cf_nightly` | 02:15 UTC | Retrain collaborative filtering model |
| `snapshot_forecast_governance` | 03:10 UTC | Save demand forecast governance snapshot |
| Inventory sync | Every 300s | Sync CSV/Shopify ERP stock levels |

---

## 15. Email Security Lab

**22 modules** covering the full email threat kill chain.

### Email Threat Detection Capabilities

```
Inbound Email
    │
    │ INTAKE
    ├─ Size limits, MIME validation
    ├─ Rate limiting (per-minute, per-tenant)
    ├─ Spoof flood load shedding
    │
    │ ANALYSIS
    ├─ Header forensics: SPF/DKIM/DMARC, relay chain, IP reputation
    ├─ IoC extraction: URLs, IPs, domains, hashes
    ├─ Attachment parsing: Office XML macros, PDF scripts, archives
    ├─ Attachment sandboxing (archive_sandbox.py)
    ├─ Threat enrichment: VirusTotal, URLhaus, MISP feeds
    │
    │ THREAT-SPECIFIC DETECTION
    ├─ BEC kill chain (bec_kill_chain.py): CEO fraud, wire transfer redirect
    ├─ BIMI verification (bimi_verifier.py): fake brand logos
    ├─ Mailbox compromise (mailbox_compromise.py): account takeover
    ├─ Phishing page detection (phishing_page_detector.py)
    ├─ NLP deception signals (nlp_deception.py): urgency, authority, fear
    │
    │ VERDICT & ACTION
    ├─ Rule-first deterministic verdict: BLOCK / SANDBOX / ALERT / ALLOW
    ├─ Severity: ERROR (immediate block) / WARN / INFO
    ├─ Sender trust score update (persistent reputation DB)
    ├─ Playbook execution (quarantine, alert, ticket, forward)
    └─ Admin dashboard: /api/v1/admin/email_security
```

### DMARC & BIMI (`src/app/routers/admin_dmarc.py`)

- DMARC policy CRUD for tenant domains
- DMARC report ingestion and parsing
- BIMI provider verification — validates brand logo certificates
- Policy enforcement recommendations

---

## 16. Escalation Rooms

**File:** `src/app/routers/escalation_room.py` (350+ lines)

Escalation rooms are **real-time bidirectional WebSocket channels** between a buyer and a staff member for resolving high-risk incidents.

```
Incident Created (high fraud score or manual trigger)
    │
    ├─ POST /api/v1/admin/incidents
    │   ├─ DB: incidents table (id, status, sla_due_at, assigned_to)
    │   ├─ Redis: buyer_token (UUID, 24h TTL)
    │   ├─ Redis: staff_token (UUID, 24h TTL)
    │   └─ Playbook: start "escalation_review" run
    │
    ├─ Buyer Channel: WS /api/v1/incidents/{id}/ws?token={buyer_token}
    │   Can: send messages, upload evidence photos
    │   Sees: staff messages, resolution status
    │
    ├─ Staff Channel: WS /api/v1/admin/incidents/{id}/ws?token={staff_token}
    │   Can: send messages, assign to team member, close/escalate
    │   Sees: fraud signals, CV analysis, buyer history, SLA timer
    │
    ├─ Evidence: POST /api/v1/incidents/{id}/evidence
    │   → Re-runs CV pipeline on new image
    │   → Updates fraud_score if new signals found
    │
    ├─ SLA Enforcement:
    │   sla_due_at set at creation (based on playbook config)
    │   Celery beat checks every 5 min
    │   Breach → alert team lead
    │
    └─ Resolution:
        POST /api/v1/admin/incidents/{id}/close
        Playbook: complete_playbook_run()
        Decision logged: bitemporal close event
        Redis tokens expire (or immediate delete)
```

---

## 17. Interleaved Thinking

**File:** `src/app/services/interleaving_controller.py`

Interleaved thinking is ShopSquire's implementation of **bounded think→tool→observe loops** — a form of chain-of-thought that interleaves reasoning with tool calls, preventing runaway reasoning without grounding in real data.

### How It Works

```
Phase 3 (PLAN) activates InterleavingController with:
  max_iterations: 3
  tool_budget: 4   (max tool calls per iteration)
  confidence_threshold: 0.9
  timeout_ms: 5000

Loop:
  1. THINK: Generate ThinkDecision { tool_name, arguments, stop, reason, confidence }
  2. TOOL:  Execute tool_name with arguments → ToolCall result
  3. OBSERVE: Record observation → update InterleavingState
  4. Check: confidence >= 0.9 OR budget exhausted OR timeout → STOP
```

### Stop Reasons

```python
class StopReason(Enum):
    max_iterations       # Reached max_iterations
    budget_exhausted     # tool_budget = 0
    high_confidence      # confidence >= 0.9
    user_interrupt       # User sent new message mid-loop
    error                # Tool call failed
    complete             # Naturally concluded
    timeout              # Exceeded timeout_ms
```

### Tool Allowlists Per Agent Role

```python
TOOL_ALLOWLISTS = {
    "orchestrator": [
        "retrieve_context", "check_policy", "get_recommendations"
    ],
    "fraud_scorer": [
        "check_phash", "verify_serial", "analyze_metadata", "check_history"
    ],
    "cv": [
        "cv_analyze", "cv_tier_route", "cv_damage_classify",
        "cv_ocr_extract", "cv_qr_decode", "cv_forensics",
        # + 16 more CV tools
    ],
    "recommendations": [
        "search_products", "get_similar", "check_availability"
    ],
    "inventory": [
        "check_stock", "query_supplier", "get_forecast", "check_demand"
    ],
}
```

**Security implication:** No agent can call tools outside its allowlist. This prevents prompt-injection-driven tool abuse (MITRE ATLAS: Context Poisoning → pivot to unauthorized tool calls).

### A/B Testing Integration

The interleaving controller is wired into the admin A/B test system (`admin_interleaving.py`). Merchants can configure:
- "Interleaving ON" vs. "Interleaving OFF" cohorts
- Max iterations per tier (Tier 1 gets 1 iteration, Tier 2 gets 3)
- Budget allocation experiments

---

## 18. Bitemporal Decision Trace

**Files:** `src/app/services/decision_log.py`, `src/app/models/decision_audit.py`, `src/app/models/decision_trace_events.py`

### What "Bitemporal" Means

Standard databases record **when data was stored** (transaction time). Bitemporal databases also record **when the fact was true in the real world** (valid time). ShopSquire records both:

```
                      valid_time (domain)
                      ───────────────────
valid_from ──────────────────────────────→  valid_to
     │                                           │
     │  Decision: "Refund approved for order X"  │
     │                                           │
     ▼──────────────────────────────────────────→
system_from ─────────────────────────────→  system_to
                      system_time (DB)
```

**Why this matters:**
- `valid_time` tells you: when was this decision actually correct in the domain?
- `system_time` tells you: when did we record it?
- Time-travel queries: "What did the system know at valid_time=2026-01-15?"
- Compliance: "Show me all decisions that were valid on the date of the audit"

### Decision Log Schema (`src/app/services/decision_log.py:43-95`)

```sql
INSERT INTO decision_logs (
    id, tenant_id, actor_id, actor_role, event_type, agent_name,
    valid_from, valid_to,           -- valid time dimensions
    system_from, system_to,         -- system time dimensions
    input_data,                     -- agent input (JSON)
    retrieved_context,              -- RAG chunks used (JSON)
    agent_reasoning,                -- LLM chain-of-thought
    proposed_action,                -- what the agent decided to do
    policy_version,                 -- which policy version applied
    approval_required,              -- human-in-the-loop flag
    execution_status                -- auto/approved/blocked/escalated
)
```

### Merkle Audit Chain (`src/app/models/decision_audit.py`)

```python
# Each decision record includes:
record_hash = SHA256(this_record_contents)
prev_hash   = SHA256(previous_record_contents)
# → Tamper-evident chain: modifying any record invalidates all subsequent hashes
```

This implements **NIST SP 800-209** tamper-evident logging for AI systems.

### Trace Events (`src/app/models/decision_trace_events.py`)

Per-turn granular events:
```
event_type: phase_started | agent_invocation | step_slo_breach |
            tool_call | observation | stop_reason | policy_check |
            playbook_trigger | decision_logged
```

Max 256 events per trace (configurable `_TRACE_EVENT_CACHE_MAX_PER_TRACE`).

### Bitemporal Metadata in Every Response

```python
# routers/recommend.py
def _trace_meta_payload(policy_version, context_ids=None):
    now = _now_iso()
    return {
        "bitemporal": {
            "valid_from": now,
            "valid_to": "infinity",      # until explicitly superseded
            "system_from": now,
            "system_to": "infinity",
        },
        "recorded_at": now,
        "context_ids": context_ids or [],
        "policy_version": policy_version,
    }
```

### Frontend: DecisionTrace.tsx

The `DecisionTrace.tsx` component (65KB) is a full audit waterfall visualization:
- Shows all trace events in sequence with timestamps
- Color-coded by phase (EXPLORE/EVALUATE/PLAN/ACTION)
- Shows agent invocations, tool calls, policy checks
- Links decisions to bitemporal record in DB
- Streams live via WebSocket `/api/v1/decisions/trace/ws`

---

## 19. Dynamic Prompt Injection for RAG Pipelines

**"Atomic Agents"** in ShopSquire refers to the pattern of building minimal, single-responsibility prompt units that are dynamically assembled from multiple sources just before LLM inference.

### How Dynamic Prompt Injection Works

```
                        ┌─────────────────────────────────┐
                        │    DYNAMIC PROMPT BUILDER        │
                        │                                   │
User Query ──────────→  │  System Prompt (static base)     │
                        │  + RAG chunks (retrieved policy)  │
                        │  + Session memory (kv_state)      │
                        │  + Episodic profile (user prefs)  │
                        │  + CV signals (if image present)  │
                        │  + Fraud context (if risky)       │
                        │  + NQE answered fields            │
                        │  + Playbook context (if active)   │
                        │                                   │
                        └─────────────────────────────────┘
                                        │
                                        ▼
                              LLM Inference (Ollama)
                                        │
                                        ▼
                              Response + Bitemporal Trace
```

### Injection Sources

1. **RAG chunks** — Retrieved policy documents (warranty, shipping, return policy)
2. **Session structured state** — `session:{uid}:structured_state` → confirmed slots injected as "User has confirmed: budget=$1500, brand=Lenovo"
3. **Episodic profile** — Returning user's `preferred_brands`, `typical_use_cases`, `last_session_summary`
4. **CV signals** — If image uploaded: `detected_labels=["laptop","scratch","hinge_damage"]` injected as evidence
5. **Fraud context** — If risk > threshold: "Note: This session has elevated risk signals: [ip_velocity_spike, device_fingerprint_mismatch]"
6. **NQE answered fields** — After user answers disambiguation question: injected as hard constraints
7. **Playbook context** — If a playbook is running: playbook state + current step injected for continuity

### Atomic Agent Pattern

Each "atomic agent" is a self-contained prompt unit:
```python
# Each agent builds its own context fragment, not the full prompt
class ProductRankingAgent:
    def build_context_fragment(self, candidates, constraints, cv_signals):
        return f"""
Products to rank: {json.dumps(candidates)}
User constraints: {json.dumps(constraints)}
Visual evidence: {json.dumps(cv_signals)}
Task: Rank products listwise. For each, provide a WHY explanation.
"""
```

The orchestrator **assembles** these fragments in order before passing to the LLM. This means:
- Each agent's prompt is independently testable
- Agents can be swapped without touching others
- Context budget is managed per-fragment (each fragment has a token budget)
- Injections can be audited individually in the decision trace

---

## 20. Learned Tier Router & GLM-Style Recursive Learning

**Files:** `src/app/services/tier_router.py` + `src/app/services/tier_router_learned.py`

### Base Tier Router

The base `TierRouter` uses a **scoring-based classification** to route queries to small/medium/large models:

```python
# src/app/services/llm_provider.py — complexity scoring
signals = {
    "length": 0–2 pts,
    "comparison_keywords": 0–2 pts,
    "technical_keywords": 0–2 pts,
    "conjunctions": 0–1 pt,
    "multi_turn_depth": 0–1 pt,
    "multimodal": 0–1 pt,
    "visual_similarity_intent": 0–2 pts,
    "follow_up_explain": 0–1 pt,
    "fully_constrained": 0–1 pt,
    "negation_constraints": 0–1 pt,
    "explicit_budget": 0–1 pt,
}
score = sum(signals.values())  # 0–10
```

| Score | Tier | Model |
|-------|------|-------|
| 0–4 | small | llama3.3:8b (`prefer_small`) |
| 5–6 | medium | mixtral:8x7b |
| 7–10 | large | mixtral:8x7b (extended) or Anthropic |

### Learned Tier Router (`tier_router_learned.py`)

The `LearnedTierRouter` sits as an **optional layer on top** of the base `TierRouter`. It uses **outcome feedback** to recursively refine routing decisions:

```python
class LearnedTierRouter:
    base_router: TierRouter
    feedback_store: Redis key "learned_tier:{query_hash}:outcome"

    def route(query, context):
        base_decision = self.base_router.route(query, context)
        past_outcomes = self.feedback_store.get(hash(query_semantics))

        if past_outcomes:
            # Adjust tier based on historical outcomes for similar queries
            # If small model consistently failed on this query type → bump to medium
            adjusted = self._adjust_tier(base_decision, past_outcomes)
            return adjusted

        return base_decision

    def record_outcome(query_hash, tier_used, quality_score, latency_ms):
        # Store outcome for future routing decisions
        # quality_score from RAGAS eval or human feedback
```

### Relationship to GLM 4.7 Recursive Learning

ShopSquire does not directly integrate GLM-4 (Zhipu AI's series). However, the `tier_router_learned.py` architecture implements the same **recursive self-improvement** principle:

1. **Observation:** Record routing decisions + quality outcomes
2. **Reflection:** Compare predicted tier vs. required quality
3. **Adjustment:** Shift routing thresholds based on error signal
4. **Recursion:** Use adjusted thresholds to produce better routing decisions

This is analogous to GLM-4's recursive training loop where the model's own outputs are used as training signal. In ShopSquire's case:
- The "model" is the tier classification function
- The "training signal" is quality scores (RAGAS eval + human feedback)
- The "recursive update" is a Redis-backed moving average of per-query-type performance

The **nightly `train_recommend_cf_nightly` Celery task** provides the collaborative filtering layer — it trains on user interaction outcomes (click-through, purchase conversion, NQE answer acceptance rate) to improve ranking quality. This is the "GLM-style recursive" component: the CF model observes its own recommendations' outcomes and refines itself every 24 hours.

---

## 21. Session & Episodic Memory Architecture

```
MEMORY ARCHITECTURE (3 Tiers)

Tier 1 — Working Memory (in-process dict, <1ms)
  ├─ L1 cache: Python dict with threading.Lock
  ├─ TTL: LRU eviction (no explicit TTL)
  └─ Contents: single-request context, in-flight agent state

Tier 2 — Session Memory (Redis, ~1ms)
  ├─ session:{uid}:summary          24h TTL — conversation summary
  ├─ session:{uid}:kv_state         24h TTL — slot accumulation
  ├─ session:{uid}:recent_retrieval 600s TTL — RAG retrieval results
  ├─ session:{uid}:agent_steps      24h TTL — orchestrator trace
  ├─ session:{uid}:structured_state 24h TTL — confirmed slots (budget, brand, etc.)
  ├─ session:{uid}:product_memory_bank — observed product specs + images
  ├─ session:{uid}:observation_log  — episodic observation events
  ├─ session:{uid}:nqe_asked_ids    — NQE question dedup
  └─ session:{uid}:nqe_answered_fields — answered NQE field values

Tier 3 — Episodic Memory (Redis long-term, ~2ms)
  ├─ episodic:{uid}:episodes        24h TTL — List[Episode { turn, query, response, slots, products }]
  ├─ profile:{user_id}              30d TTL — UserProfile { brands, use_cases, budget_tier, history }
  ├─ chat_history:{user_id}:sessions 90d TTL — Full chat history sessions
  └─ session_summary:{uid}          — SessionSummary { turn_count, key_constraints, outcome }
```

### RAPTOR-Style Summarization

Long episodic histories are compressed using a RAPTOR-inspired recursive summary strategy:
- Turn 1–10: stored verbatim
- Turn 10–50: compressed to a per-session summary
- Turn 50+: compressed to a per-user profile update

This keeps Redis memory bounded while preserving the "feels like it knows me" quality for returning users.

---

## 22. Complexity Scoring & LLM Model Selection

See Section 20 for scoring table. Key additional logic:

**Multimodal Scoring (Fixed in recent commit):**
```python
# src/app/services/llm_provider.py:142-146
if ctx.get("has_image"):
    signals["multimodal"] = 1
    if _re.search(r"\b(similar|like this|alternatives?|compare|price range|same as|equivalent)\b", q):
        signals["visual_similarity_intent"] = 2
```

**Follow-up Explain Detection:**
```python
# Detects: "why is that?", "explain", "tell me more", "what does that mean?"
if _is_followup_explain_query(query, prior_message):
    signals["follow_up_explain"] = 1
    # Note: NQE should NOT fire on these queries (BUG-5)
```

---

## 23. Policy Gate & Playbook Engine

### Policy Gate (`src/app/policy/gate.py`)

5 deterministic rules evaluated in order:

1. **Sensitive field check** — Blocks requests containing credit card, CVV, SSN, passport keywords
2. **High-risk tool check** — `refund.issue`, `payout.send`, `chargeback.override`, `price.override` → always require review
3. **Order cancel after ship** — Blocks cancellation once shipping label created
4. **Refund threshold** — Auto-approve if amount < $150 (configurable via feature flag `POLICY_THRESHOLDS.auto_refund_limit`)
5. **Refund aggregate window** — Hourly aggregate limit per customer (prevents wash-sale patterns)

**Output:** `PolicyGateResult { decision, reasons, rule_hits, approval_required, compliance_tags }`

### Playbook Engine (`src/app/services/playbook_engine.py`)

Playbooks are YAML/JSON-configured automation runbooks that execute when policy conditions are met.

```json
// config/security/cv_playbooks.json
{
  "id": "high_risk_return_review",
  "name": "High Risk Return — Human Review Required",
  "trigger_logic": "any",
  "entry_conditions": { "fraud_score_min": 0.7 },
  "actions": [
    { "type": "create_ticket", "template": "high_risk_return" },
    { "type": "create_escalation_room", "sla_minutes": 240 },
    { "type": "notify_team", "channel": "fraud-alerts" },
    { "type": "freeze_refund", "duration_hours": 48 }
  ],
  "sla_minutes": 240,
  "risk_band_min": "high",
  "requires_approval_roles": ["ROLE_MERCHANT", "ROLE_OWNER"],
  "closure_criteria": ["human_review_complete", "decision_logged"]
}
```

**Execution lifecycle:**
```
start_playbook_run() → DB record created
  → execute_typed_actions() (email, ERP, shipping, IP block, rate limit)
    → append_playbook_step() for each action
  → complete_playbook_run() (success) or fail_playbook_run() (error)
```

Playbooks support **rollback** (`rollback.enabled`, `rollback.strategy`).

---

## 24. Compliance & Audit Chain

### Compliance Frameworks

| Framework | Implementation | Coverage |
|-----------|---------------|---------|
| GDPR | `security/compliance.py` middleware | Per-request data processing consent, DPO audit log |
| PCI DSS | `security/pci_boundary.py` | Card data redaction, CDE scope enforcement |
| SOC2 | `models/compliance_registry.py` | Control evidence collection |
| ISO42001 | `admin/admin_compliance_registry.py` | AI governance controls |
| MITRE ATLAS | `security/atlas_map.py` | Agentic AI threat event correlation |
| MAESTRO | `security/maestro_boundaries.py` | Agent action boundaries |
| OWASP LLM Top 10 | `security/owasp_map.py` | LLM threat mapping |
| NIST AI RMF | `admin/admin_grc.py` | Risk management controls |

### Audit Trail Structure

Every compliance-relevant action produces:
1. Decision log entry (bitemporal)
2. Audit chain update (Merkle hash)
3. Compliance tag in response metadata
4. Event log entry (outbox pattern for external SIEM)

```sql
-- decision_audit table (src/app/models/decision_audit.py)
id           TEXT PRIMARY KEY
decision_id  TEXT INDEXED
action       TEXT           -- immutable, never updated
actor        TEXT
metadata     TEXT (JSON)
created_at   TIMESTAMP
record_hash  TEXT (64)      -- SHA-256 of this record
prev_hash    TEXT (64)      -- SHA-256 chain link
```

---

## 25. User-Flow Walkthroughs (End-to-End)

### Flow A — First-Time Buyer (Cold Start)

```
Browser → port 5173
  App.tsx loads → fetch /api/v1/products → ProductGrid renders

User types: "gaming laptop under $1500"
  → App.tsx: PII check → clean
  → POST /api/v1/recommend/proposal
    → Session: uid generated, Redis session created
    → Complexity: 4 (small model)
    → NQE: 2 questions (gaming depth, touch screen)
  → Response: products + NQE questions
  → ChatOverlay: shows 3 products + DisambiguationButtons

User clicks "Mostly weekends" (NQE answer)
  → POST /api/v1/recommend/proposal (follow-up turn)
    → Session: nqe_answered_fields += { "gaming_depth": "casual" }
    → NQE: only 1 remaining question (touch screen)
    → Ranking refined: casual gaming → weight battery over GPU
  → ProductGrid: updated ranking

User uploads photo of a laptop they own
  → GET /api/v1/cv/nonce
  → POST /api/v1/cv/upload
    → CV Tier 1: labels=["laptop","Lenovo","ThinkPad","15inch"]
    → Product_Identity_Agent: brand=Lenovo, size=15, specs extracted
    → Complexity: +2 (visual similarity) → Tier: medium (mixtral)
  → Recommend re-runs with product identity constraints injected
  → Products now anchored to detected Lenovo specs
```

### Flow B — Returning Buyer (Profile Loaded)

```
User logs in → JWT token → uid = known user_id
  → Session load:
    profile:{user_id} → budget_tier=mid, preferred_brands=["Lenovo","ASUS"]
    episodic episodes → last bought: Lenovo IdeaPad 5 Pro (2024)

User types: "looking for an upgrade"
  → NLP: intent=upgrade, missing=[price, use_case]
  → BUT episodic profile injected:
    answered_fields.budget = "mid" (from profile)
    answered_fields.brand_preference = "Lenovo/ASUS" (from profile)
  → NQE: only asks about "what's changed in your needs since last time?"
  → 1 question instead of 4
```

### Flow C — Merchant Admin Reviews Fraud Alert

```
Celery beat: CrowdStrike poll → new threat intel ingested
  → ThreatFeedClient → ingest_security_event()
  → Security_Observer_Agent threshold exceeded
  → PlaybookEngine: trigger "threat_intel_review" playbook
    → Admin notification sent

Admin opens dashboard → /merchant/app/index.html?tab=merchant-bi
  → GET /api/v1/admin/bi/slo → SLO status: latency P95=240ms (ok)
  → GET /api/v1/admin/analytics → Active incidents: 3
  → Click incident → EscalationRoom WebSocket opened
    → Staff sees: fraud signals, CV analysis, buyer chat history
    → Admin updates: assign to fraud team, SLA = 4h

4h later: SLA breach → Celery alerts team lead
  Admin closes incident → playbook completes → decision logged
```

### Flow D — Email Threat Triage

```
Inbound email: "Invoice #4821 — please pay urgently" (BEC attempt)
  → POST /api/v1/email/analyze
    → Rate limit: OK
    → Header forensics: DMARC FAIL (spoofed sender domain)
    → NLP deception: urgency=high, authority=high → signals fired
    → IoC extraction: URL "invoice-payment.co" (new domain, 2 days old)
    → Threat enrichment: URLhaus → BLOCKED (known phishing)
    → Verdict: BLOCK (confidence=0.95)
    → Sender trust: update score -0.40
    → Playbook: "block_and_quarantine"
      → Email quarantined
      → Admin alert: /api/v1/admin/email_security
      → Incident created if sender_trust < -0.60
```

---

*Document generated: 2026-03-04 | ShopSquire Platform Architecture v2.0*
*Based on full codebase analysis: 482 Python files, ~100K lines, 23 React components*
