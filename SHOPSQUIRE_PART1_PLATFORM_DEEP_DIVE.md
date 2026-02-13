# ShopSquire Platform Deep Dive & Technical Assessment

> Full codebase audit | February 2026 | v1.0

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Architecture & Stack](#2-architecture--stack)
3. [Agent Inventory (All 20+ Agents)](#3-agent-inventory)
4. [Service Layer (90+ Services)](#4-service-layer)
5. [Router/API Surface (75+ Endpoints)](#5-routerapi-surface)
6. [NLP Capabilities](#6-nlp-capabilities)
7. [Computer Vision (CV) Tiering](#7-computer-vision-cv-tiering)
8. [Model Tiering & LLM Orchestration](#8-model-tiering--llm-orchestration)
9. [Context Awareness & Session Memory](#9-context-awareness--session-memory)
10. [Interleaved Thinking](#10-interleaved-thinking)
11. [Parallel Agent & Parallel Tooling](#11-parallel-agent--parallel-tooling)
12. [Integration Points (Bolt-On Capabilities)](#12-integration-points)
13. [Security & Compliance Controls](#13-security--compliance-controls)
14. [Agentic AI Threat Modeling](#14-agentic-ai-threat-modeling)
15. [Observability, Dashboards & Metrics](#15-observability-dashboards--metrics)
16. [Bitemporal Decision Trace](#16-bitemporal-decision-trace)
17. [Auto-Scale & Resilience](#17-auto-scale--resilience)
18. [Frontend & Backend Dashboards](#18-frontend--backend-dashboards)
19. [Production Readiness: Demo Today vs. Left To Do](#19-production-readiness)
20. [Test Coverage & CI/CD](#20-test-coverage--cicd)

---

## 1. Platform Overview

**ShopSquire** is a modular, autonomous agentic AI e-commerce platform built on FastAPI/Python. It provides an end-to-end AI-augmented commerce stack encompassing:

- **Conversational commerce** (NLP chat, voice, query understanding)
- **Visual commerce** (computer vision for product damage, returns triage, fraud)
- **Autonomous pricing & discounting** (rule + ML engine)
- **Multi-provider payment orchestration** (Stripe, PayPal, Revolut, Google Pay, Afterpay)
- **Security-first architecture** (PCI-DSS, OWASP LLM/Agentic/API Top 10, MITRE ATT&CK, STRIDE/DREAD)
- **Inventory & supply chain management** (real-time stock, reorder, ERP/EDI)
- **Incident management & SLA enforcement**
- **Multi-tenant architecture** with tenant-scoped config, quotas, and isolation

The platform follows a **Retrieve-Reason-Act (RRA) orchestration pattern** with full decision traceability, guardrails, policy gates, and human-in-the-loop escalation.

---

## 2. Architecture & Stack

### Core Stack
| Layer | Technology |
|-------|-----------|
| **API Framework** | FastAPI + ORJSONResponse (high-perf) |
| **Database** | PostgreSQL (prod) / SQLite (test) via SQLAlchemy ORM |
| **Migrations** | Alembic with pre/post migration hooks |
| **Cache/PubSub** | Redis (semantic cache, agent bus, session state) |
| **LLM Runtime** | Ollama (local), configurable model tiers |
| **CV Pipeline** | ONNX Runtime, OpenCV, Tesseract OCR |
| **Observability** | OpenTelemetry, Prometheus, Grafana, Loki, Datadog |
| **Containerization** | Docker + Docker Compose |
| **CI/CD** | GitHub Actions (unit, integration, Playwright, Prometheus) |
| **Frontend** | Vite + vanilla JS storefront + admin dashboards |

### Key Design Patterns
- **Middleware Stack**: 7+ middleware layers (security observer, rate limiting, backpressure, PCI boundary, idempotency, admin MFA, webhook security, request logging, metrics)
- **Plugin Registry**: YAML-based plugin system (`config/plugins.yml`) loaded at startup
- **Feature Flags**: JSON-driven feature flags for progressive rollout and killswitch
- **Event Sourcing**: Event log + decision trace events tables
- **Graceful Degradation**: Rule-based fallback when LLM/CV services unavailable

---

## 3. Agent Inventory

ShopSquire implements **20+ distinct autonomous agents**, each with specialized capabilities:

### Core Commerce Agents
| Agent | File(s) | Capability | Status |
|-------|---------|------------|--------|
| **Orchestrator Agent** | `services/orchestrator.py` | Central coordinator; RRA pipeline, tier routing, parallel dispatch | Production |
| **Pricing Agent** | `routers/pricing.py` | Dynamic pricing, tiered discounts, policy enforcement | Production |
| **Inventory Agent** | `services/inventory_agent.py`, `routers/inventory.py` | Stock monitoring, reorder recommendations, background worker loop | Production |
| **Payment Agent** | `services/payments.py`, `routers/payments*.py` | Multi-provider payment orchestration (Stripe, PayPal, Revolut, GPay, Afterpay) | Production |
| **Cart Agent** | `routers/cart.py` | Shopping cart management, draft orders | Production |
| **Orders Agent** | `routers/orders.py` | Order lifecycle management | Production |
| **Returns Agent** | `services/returns.py`, `routers/returns.py` | Returns processing, RMA workflow | Production |
| **Recommendation Agent** | `services/recommendations.py`, `routers/recommend.py` | Candidate retrieval, reranking, semantic search | Production |

### AI/ML Agents
| Agent | File(s) | Capability | Status |
|-------|---------|------------|--------|
| **NLP Support Agent** | `routers/support.py`, `services/nlp_complaints.py` | Intent classification, complaint handling, sentiment | Production |
| **Voice Agent** | `routers/voice.py` | Voice-to-text, voice commerce | MVP |
| **Vision/CV Agent** | `routers/vision.py`, `routers/cv.py`, `services/cv_provider.py` | Image analysis, damage classification, OCR, serial extraction | Production |
| **CV Triage Agent** | `services/cv_triage_basic.py`, `services/cv_tier2_pipeline.py` | Tiered CV analysis (basic -> advanced), evidence tagging | Production |
| **Fraud Scoring Agent** | `services/fraud_scorer.py`, `routers/fraud.py` | Multi-signal fraud detection, Isolation Forest anomaly | Production |
| **Anomaly Detection Agent** | `services/anomaly_detector.py`, `analytics/anomaly.py` | Statistical anomaly detection, DDOS/model-poison signals | Production |
| **Semantic Search Agent** | `services/semantic_search.py`, `services/embeddings.py` | Vector embeddings, similarity search | MVP |

### Operational Agents
| Agent | File(s) | Capability | Status |
|-------|---------|------------|--------|
| **Security Observer Agent** | `security/observer.py` | Real-time request analysis, OWASP detection, severity tagging | Production |
| **Firewall Agent** | `security/firewall.py` | Transaction firewall, pricing policy enforcement | Production |
| **Ticketing Agent** | `services/ticketing.py`, `routers/tickets.py` | Auto-ticket creation, escalation, connector integrations | Production |
| **Incident Agent** | `routers/incident.py` | Incident routing, SLA enforcement, severity classification | Production |
| **Audit Evidence Agent** | `services/audit_evidence_agent.py`, `routers/audit.py` | Audit trail generation, evidence collection | Production |
| **Policy Gate Agent** | `services/policy_gate.py` | LLM/rules-based policy evaluation, approval workflows | Production |
| **Escalation Room Agent** | `routers/escalation_room.py` | Admin-to-shopper real-time chat stream per incident | MVP |

### Infrastructure Agents
| Agent | File(s) | Capability | Status |
|-------|---------|------------|--------|
| **Agent Bus** | `services/agent_bus.py` | Redis-backed inter-agent messaging and handoffs | Production |
| **Agent Handoff** | `services/agent_handoff.py` | Best-effort agent-to-agent delegation | Production |
| **Retention Agent** | `services/retention.py` | TTL enforcement, data lifecycle management | Production |
| **Webhook Dispatcher** | `services/webhook_dispatcher.py` | Persistent outbound webhook delivery with retry | Production |
| **DMARC Poller** | `jobs/dmarc_poll.py` | Email security DMARC ingestion | MVP |

---

## 4. Service Layer (90+ Services)

The `src/app/services/` directory contains **90+ service modules** organized by domain:

### AI/ML Services
- `llm.py` / `llm_provider.py` / `ollama_client.py` - LLM orchestration with Ollama backend
- `llm_guardrails.py` / `security_aware_llm.py` - LLM safety and guardrails
- `tier_router.py` - Model tier routing (T1/T2/T3 text, V0/V1/V2 vision)
- `interleaving_controller.py` - Interleaved thinking orchestration
- `confidence_calibration.py` - Confidence score calibration
- `semantic_cache.py` - Redis-backed semantic response caching
- `embeddings.py` - Vector embedding generation
- `semantic_search.py` - Similarity search over product catalog
- `recommendations.py` - Candidate retrieval + reranking pipeline
- `nlp_complaints.py` / `nlp_contract.py` / `nlp_query_clustering.py` - NLP processing
- `conversational_query.py` - Multi-turn conversational state
- `ragas_eval.py` - RAGAS evaluation framework integration
- `posthoc_labeling.py` - Post-hoc decision labeling for training
- `demand_forecast.py` - Demand forecasting service

### Computer Vision Services
- `cv_provider.py` - Managed CV provider (ONNX, OpenCV)
- `cv_triage_basic.py` - Basic image triage
- `cv_tier2_pipeline.py` - Advanced CV analysis pipeline
- `cv_damage_classifier.py` - Product damage classification
- `cv_object_detector.py` - Object detection
- `cv_ocr.py` / `ocr_embedded.py` - OCR text extraction
- `cv_quality.py` - Image quality assessment
- `cv_evidence.py` - Evidence extraction from images
- `cv_explain.py` - Explainable CV decisions
- `cv_model_pack.py` - Model pack management
- `cv_warmup.py` - Model warm-up on startup
- `cv_tiered.py` - Tiered CV routing
- `image_forensics.py` - Image forensics (pHash, tampering detection)
- `image_intake.py` - Image ingestion pipeline
- `reverse_image_search.py` - Reverse image search for fraud
- `serial_extractor.py` - Serial number extraction from images
- `supply_chain_cv.py` - Supply chain visual inspection

### Security Services
- `fraud_scorer.py` - Multi-signal fraud scoring
- `security_playbooks.py` - Automated security playbook execution
- `forensics_policy.py` - Forensics policy engine
- `geoip.py` - GeoIP lookup
- `trust_routing.py` - Trust-based request routing
- `agent_behavior_anomaly.py` - Agent behavior anomaly detection
- `dmarc_ingest.py` - DMARC email security ingestion
- `jwks.py` - JWKS key management

### Business Logic Services
- `payments.py` - Multi-provider payment processing
- `returns.py` - Returns processing
- `cases.py` - Case management
- `order_serials.py` - Order serial tracking
- `shipping_stub.py` - Shipping integration stub
- `erp_edi.py` - ERP/EDI integration
- `inventory_agent.py` / `inventory_rules.py` - Inventory management
- `warehouse_verification.py` - Warehouse verification
- `risk.py` / `risk_quantification.py` - Risk assessment
- `ethical_ai.py` - Ethical AI guardrails
- `faq_bank.py` - FAQ knowledge base

### Infrastructure Services
- `agent_bus.py` - Inter-agent Redis pub/sub bus
- `agent_handoff.py` - Agent-to-agent handoff protocol
- `agent_metrics.py` - Agent-level metrics collection
- `parallel_agent_executor.py` / `parallel_executor.py` - Parallel execution engines
- `event_dispatcher.py` - Event dispatch
- `webhook_dispatcher.py` - Outbound webhook delivery
- `decision_log.py` - Bitemporal decision logging
- `trace_broker.py` - Distributed trace brokering
- `persistence.py` - Data persistence layer
- `degradation.py` - Graceful degradation controller
- `dependency_resilience.py` - Dependency health and circuit breaking
- `tenant_quota.py` - Multi-tenant quota enforcement
- `db_read_routing.py` - Read replica routing
- `retention.py` - Data retention/TTL enforcement
- `rule_store.py` - Rule persistence
- `expanded_rules.py` - Extended rule evaluation
- `search_events.py` - Search event tracking
- `drift_daily_metrics.py` - Model drift daily metrics
- `notification.py` - Notification dispatch
- `ticketing.py` / `ticketing_connectors.py` - Ticketing system with external connectors

---

## 5. Router/API Surface (75+ Endpoints)

### Endpoint Categories

**Commerce** (15 routers):
`admin`, `pricing`, `inventory`, `cart`, `orders`, `payments` (x5 providers), `recommend`, `products_compare`, `returns`, `fraud`

**AI/ML** (10 routers):
`support`, `voice`, `vision`, `cv`, `cv_readiness`, `scoring`, `decisions`, `intent`, `query`, `query_clusters`

**Security** (8 routers):
`auth`, `security_integrations`, `email_security`, `email_security_admin`, `dmarc`, `admin_dmarc`, `connectors_auth`, `connectors_admin`

**Operations** (12 routers):
`incident`, `sla`, `tickets`, `approvals`, `escalation_room`, `audit`, `posthoc`, `jobs`, `rules`, `tenant_config`, `admin_chat_tools`, `data_readiness`

**Observability** (6 routers):
`metrics`, `health`, `graph`, `analytics`, `admin_analytics`, `admin_drift`, `trace_debug`, `admin_grafana_proxy`

**User Experience** (8 routers):
`ui`, `ui_storefront`, `chat`, `session_memory`, `session_events`, `consumer_signals`, `preferences`, `account`, `privacy`, `demo`

**Data & Events** (5 routers):
`events`, `decision_trace_events`, `merchant_dashboard`, `admin_inventory`, `admin_webhooks`

---

## 6. NLP Capabilities

### Intent Classification
- **Rule-Based Engine** (`rules/engine.py`): Pattern matching with configurable rules from `config/rules/`
- **XGBoost Classifier** (`analytics/xgb_intent.py`): ML-based intent classification with probability scores
- **Hybrid Approach**: Rule engine runs first, XGBoost augments with `xgb_intent` and `xgb_proba` fields
- Supported intents: `return_request`, `support`, `order_issue_report`, `order_status`, `product_inquiry`, `pricing_query`

### Conversational Query
- `services/conversational_query.py` - Multi-turn conversation state management
- `services/nlp_query_clustering.py` - Query clustering for analytics
- `services/faq_bank.py` - FAQ retrieval for common queries

### NLP Processing Pipeline
1. **Guardrails** applied to input (`security/guardrails.py`)
2. **Security scan** via observer (`security/observer.py`)
3. **Intent classification** (rule engine + XGBoost)
4. **Constraint parsing** from natural language queries
5. **Candidate retrieval** via semantic search
6. **Reranking** with multi-factor scoring
7. **Confidence calibration** post-scoring

### Complaints NLP
- `services/nlp_complaints.py` - Specialized complaint text analysis
- Damage description extraction, severity classification
- Integrated with CV pipeline for multi-modal complaint handling

---

## 7. Computer Vision (CV) Tiering

### 3-Tier Vision Pipeline

| Tier | Name | Capability | Trigger |
|------|------|-----------|---------|
| **V0** | Basic | Image quality check, blur detection | Default for all images |
| **V1** | Standard | Label classification, OCR, damage detection | Standard complaints |
| **V2** | Advanced | Serial extraction, forensics, pHash matching, tampering detection | High-risk / high-value |

### CV Services Stack
- **ManagedCVProvider** (`cv_provider.py`): ONNX-based label + OCR extraction
- **BasicCVTriage** (`cv_triage_basic.py`): First-pass damage classification
- **Tier2Pipeline** (`cv_tier2_pipeline.py`): Advanced analysis with object detection
- **CVDamageClassifier** (`cv_damage_classifier.py`): Specialized damage type classification
- **CVObjectDetector** (`cv_object_detector.py`): Product/defect object detection
- **ImageForensics** (`image_forensics.py`): pHash comparison, tampering detection
- **SerialExtractor** (`serial_extractor.py`): Serial number extraction + verification
- **CVExplain** (`cv_explain.py`): Explainable AI for CV decisions
- **CVQuality** (`cv_quality.py`): Image quality scoring
- **ReverseImageSearch** (`reverse_image_search.py`): Fraud detection via reverse search

### CV Configuration
- `config/cv_model_packs.json` - Model pack definitions (ONNX models per tier)
- `config/cv/` - CV-specific configuration
- Warm-up on startup (`CV_WARMUP_ON_START` env var)
- CV readiness endpoint (`/api/v1/cv/readiness`)

---

## 8. Model Tiering & LLM Orchestration

### Text Model Tiering (3-Tier)

| Tier | Model | Trigger Conditions |
|------|-------|--------------------|
| **T1** (Fast) | `qwen2-small` (configurable via `MODEL_T1`) | High intent confidence (>=0.85), single-turn, low risk |
| **T2** (Balanced) | `qwen2-medium` (configurable via `MODEL_T2`) | Low intent confidence (<0.85) OR multi-turn conversation |
| **T3** (Powerful) | `qwen2-large` (configurable via `MODEL_T3`) | High security risk (>=50) OR high-value transaction (>=250) |

### Tier Router (`services/tier_router.py`)
- Evaluates query complexity, amount, multi-turn state, tenant ID, intent result, security analysis
- Assigns `tier`, `tool_budget`, and `cache_key`
- Supports speculative caching of tier decisions

### LLM Orchestration (`services/llm.py`)
- **LLMOrchestrator** class with rerank, budget-aware calling
- **Ollama client** (`services/ollama_client.py`) for local model inference
- **Token budget** enforcement (`services/token_budget.py`)
- **Semantic cache** (`services/semantic_cache.py`) - Redis-backed response caching
- **Guardrails** (`services/llm_guardrails.py`) - Safety filtering
- **Security-aware LLM** (`services/security_aware_llm.py`) - Risk-adjusted model selection

### Confidence Calibration
- `services/confidence_calibration.py` - Post-hoc calibration of model confidence scores
- `config/confidence_calibration.json` - Calibration parameters
- Applied after scoring to normalize confidence across tiers

---

## 9. Context Awareness & Session Memory

### Memory Architecture (`services/memory.py`)
- **Per-user context**: Stores conversation history, preferences, past interactions
- **KV State**: Key-value store for draft cart IDs, session state
- **Recent Retrieval**: Last retrieval results cached for context continuity
- **Redis-backed**: Persistent session state via Redis when available

### Session Memory Router (`routers/session_memory.py`)
- CRUD endpoints for session memory
- Multi-turn conversation state
- Conversation context window management

### Context Flow in Orchestrator
1. `memory.get_context(uid)` - Retrieve full user context
2. KV state extraction (draft cart, preferences)
3. Live data merge (stock, pricing, product info)
4. Dependency health snapshot included in context
5. Retrieved context = `{memory, live, dependency_health}`
6. Context passed through entire RRA pipeline

### Session Events (`routers/session_events.py`)
- Privacy-safe session event ingestion
- Consumer signal tracking (`routers/consumer_signals.py`)
- Behavioral data for personalization

---

## 10. Interleaved Thinking

### InterleavingController (`services/interleaving_controller.py`)
- Implements **interleaved reasoning** pattern (similar to Claude's extended thinking)
- `run_interleaved()` function for step-by-step reasoning with intermediate checkpoints
- Evidence-based decision building with tagged reasoning steps

### How It Works
1. Security scan produces initial context
2. Intent classification adds reasoning layer
3. CV analysis (if images) interleaves with NLP
4. Fraud scoring overlays risk assessment
5. Each step produces `log_trace_event` entries
6. Evidence tags accumulated across steps
7. Final proposal includes all interleaved reasoning

### AB Testing Integration
- Variant B can force interleaving (`AB_VARIANT_B_ENABLE_CV_INTERLEAVING`)
- Controlled rollout of interleaved vs. sequential reasoning
- Metrics tracked per variant (`record_ab_assignment`)

---

## 11. Parallel Agent & Parallel Tooling

### Parallel Agent Executor (`services/parallel_agent_executor.py`)
- **`run_parallel_checks()`**: Executes CV, inventory, and fraud checks concurrently
- K2-style speculative execution for Tier 2+ queries
- Parallel outputs merged back into main proposal

### Parallel Executor (`services/parallel_executor.py`)
- Generic parallel task execution engine
- Used for independent agent checks that don't depend on each other

### How Parallel Execution Is Triggered
```
Tier Router decision (tier >= 2)
    OR images present
    OR complaint intent detected
    OR AB variant B force_parallel=True
        -> run_parallel_checks(payload, ranked_results, base_signals)
            -> CV analysis   ]
            -> Inventory check ] -- concurrent
            -> Fraud scoring  ]
```

### Speculative Caching
- Parallel outputs cached with `tier_decision.cache_key`
- TTL configurable via `PARALLEL_CACHE_TTL` (default 600s)
- T0/T1 cache hits avoid re-execution

### Agent Bus (`services/agent_bus.py`)
- Redis pub/sub based inter-agent communication
- Supports agent-to-agent handoff (`agent_handoff.py`)
- Event-driven agent coordination

---

## 12. Integration Points (Bolt-On Capabilities)

### Database Integration
| Component | Status | Notes |
|-----------|--------|-------|
| PostgreSQL | Production | Primary datastore, pool_pre_ping, future=True |
| SQLite | Test/Dev | StaticPool for test fixtures |
| Alembic migrations | Production | Pre/post migration hooks, autogenerate |
| Read replica routing | MVP | `services/db_read_routing.py` |

### Payment Providers
| Provider | Router | Status |
|----------|--------|--------|
| Stripe | `payments.py` | Production |
| PayPal | `payments_paypal.py` | Production |
| Revolut | `payments_revolut.py` | Production |
| Google Pay | `payments_googlepay.py` | Production |
| Afterpay | `payments_afterpay.py` | Production |

### ERP/EDI Integration
- `services/erp_edi.py` - EDI message handling
- `config/erp_edi_stub.json` - EDI configuration stub
- `config/erp/` - ERP configuration directory
- **Status**: Stub/skeleton - needs real ERP connector implementation

### Email Integration
- Gmail webhook ingestion (`routers/ingest_gmail.py`)
- Microsoft 365 webhook ingestion (`routers/ingest_m365.py`)
- DMARC ingestion & dashboard (`routers/dmarc.py`, `routers/admin_dmarc.py`)
- Email security evaluation (`routers/email_security.py`)
- **Status**: MVP - webhook structure in place, needs production credentials

### Supply Chain
- `config/security/supply_chain_baselines.json` - Supply chain security baselines
- `services/supply_chain_cv.py` - Visual inspection for supply chain
- `services/warehouse_verification.py` - Warehouse verification
- `services/shipping_stub.py` - Shipping integration stub
- **Status**: Baseline config + stubs, needs real carrier/3PL integration

### Object Storage
- Static file serving via FastAPI StaticFiles (`/static` mount)
- Image intake pipeline (`services/image_intake.py`)
- **Status**: Local filesystem only; needs S3/Azure Blob/GCS integration

### Ticketing/Helpdesk Connectors
- `services/ticketing_connectors.py` - External ticketing system integration
- `services/ticketing.py` - Internal ticketing agent
- **Status**: Connector framework exists, needs Zendesk/Freshdesk/Jira adapters

### Plugin System
- `config/plugins.yml` - Plugin registry configuration
- `services/registry.py` - Plugin loader
- **Status**: Framework exists, can load external plugins at startup

---

## 13. Security & Compliance Controls

### Security Middleware Stack (7 layers)
1. **WebhookSecurityMiddleware** - Webhook signature + replay protection
2. **IdempotencyMiddleware** - Idempotent write operations (POST/PUT/PATCH)
3. **AdminMfaMiddleware** - MFA enforcement for admin routes
4. **PciBoundaryMiddleware** - PCI boundary header enforcement for payment endpoints
5. **SecurityObserverMiddleware** - Real-time request analysis + anomaly detection
6. **RateLimitMiddleware** - Token-bucket rate limiting per IP
7. **BackpressureMiddleware** - Concurrency limiting + tenant isolation

### Security Observer (`security/observer.py`)
- Analyzes every request payload (method, path, headers, body)
- Detects OWASP LLM Top 10, Agentic Top 10, API Top 10 patterns
- MITRE ATT&CK / ATLAS mapping
- STRIDE threat categorization
- DREAD risk scoring
- GDPR-aware processing (x-gdpr-user header)
- Header sanitization (API keys redacted)

### Transaction Firewall (`security/firewall.py`)
- Pricing policy enforcement
- Discount limit checks
- Escalation role assignment
- Policy version tracking

### PCI-DSS Compliance (`security/pci.py`)
- PCI boundary middleware
- Payment endpoint isolation
- Sensitive data handling controls

### Risk Correlation (`config/security/taxonomy/risk_correlation_policy.json`)
- Comprehensive risk taxonomy with versioned policies
- 300+ versioned policy snapshots in `config/security/versions/`
- Correlation rules across threat categories

### Guardrails (`security/guardrails.py`)
- Input sanitization
- Prompt injection detection
- Output filtering
- Applied at orchestrator entry point

### Additional Security
- `config/security/bad_asn.json` - Known bad ASN blocklist
- `config/security/geoip_overrides.json` - GeoIP policy overrides
- `config/security/kev_catalog.json` - Known Exploited Vulnerabilities tracking
- `services/geoip.py` - GeoIP lookup service
- `services/trust_routing.py` - Trust-based request routing

---

## 14. Agentic AI Threat Modeling

### OWASP Coverage
The security observer implements detection for:

**OWASP LLM Top 10**:
- LLM01: Prompt Injection
- LLM02: Insecure Output Handling
- LLM03: Training Data Poisoning signals
- LLM06: Sensitive Information Disclosure
- LLM09: Overreliance

**OWASP Agentic Top 10**:
- Agent autonomy boundaries (policy gate)
- Agent-to-agent trust (agent bus with handoff protocols)
- Tool use restrictions (tool budget per tier)
- Memory poisoning detection (anomaly detector)

**OWASP API Top 10**:
- API1: Broken Object Level Authorization
- API2: Broken Authentication
- API3: Excessive Data Exposure (redaction middleware)
- API4: Lack of Resources & Rate Limiting (implemented)

### MITRE ATT&CK / ATLAS
- Technique mapping in security analysis payloads
- `mitre_atlas` field in trace events
- Mapped to e-commerce specific attack patterns

### STRIDE/DREAD
- `stride_categories` per security event
- `dread_avg` risk scoring
- Integrated into decision trace for audit

### Agent Behavior Anomaly (`services/agent_behavior_anomaly.py`)
- Monitors agent behavior patterns
- Detects deviation from expected agent actions
- Auto-generates security tickets for high-severity anomalies

### Isolation Forest Fraud (`analytics/isolation_forest.py`)
- Unsupervised anomaly detection for fraud
- Features: velocity, geo mismatch, device change, device fingerprint drift, serial mismatch
- Labels: low/medium/high
- Evidence tags propagated to playbooks

---

## 15. Observability, Dashboards & Metrics

### Prometheus Metrics (`observability/metrics.py`)
- HTTP request duration histograms
- Error counters by path
- Rate limit exceeded counters
- Chaos injection counters
- In-flight request gauges
- Security event counters
- CV auto-decision / escalation counters
- Agent invocation / escalation counters
- AB variant assignment counters
- Decision events counter
- Exception counters

### Grafana Dashboards
- `config/observability/grafana_dashboard.json` - Pre-built dashboard definitions
- `config/observability/grafana/` - Additional Grafana provisioning
- Grafana proxy endpoint for secure embedding (`admin_grafana_proxy.py`)

### Alerting
- `config/observability/alertmanager.yml` - AlertManager configuration
- `config/observability/alertmanager_rules.yml` - Alert rules
- `config/observability/alerts.yml` - Alert definitions
- `config/observability/prometheus_rules.yml` - Prometheus recording rules
- `config/observability/rules/` - Additional rule definitions

### Tracing (`observability/tracing.py`)
- OpenTelemetry integration
- `init_tracer("shopsquire-api")` at startup
- Request ID propagation via middleware
- Span-level tracing for key operations

### Logging (`observability/logging.py`)
- Structured JSON logging
- Request ID binding
- Log request lines with method/path/status/duration
- Exception logging to `runs/request_exceptions.log`

### Additional Observability
- Loki log aggregation (`config/observability/loki/`)
- Datadog integration (`config/observability/datadog/`)
- Health endpoints (`/health`, `/healthz`, `/readyz`)
- Dependency health snapshots
- Nginx reverse proxy config (`config/observability/nginx.conf`)
- Cron-based monitoring (`config/observability/cron/`)

---

## 16. Bitemporal Decision Trace

### Decision Logging (`services/decision_log.py`)
- **`log_decision()`**: Records full decision with bitemporal timestamps
  - `valid_time`: When the decision applies (business time)
  - `transaction_time`: When the decision was recorded (system time)
- Fields: agent_name, input_data, retrieved_context, proposed_action, agent_reasoning, policy_version, approval_required, execution_status, tenant_id, actor_id, actor_role, event_type

### Trace Events (`services/decision_log.py` -> `log_trace_event()`)
- Fine-grained trace events within a decision
- Fields: trace_id, event_type, source_type, source_id, target_type, target_id, payload
- Event types: `security_scan`, `ab_assignment`, `inventory_check`, `cv_analysis`, `fraud_score`, `fraud_isolation_forest`, `policy_verdict`

### Decision Trace Events Table
- Dedicated `decision_trace_events` table (created at startup)
- Router: `routers/decision_trace_events.py`
- Queryable via API for audit/compliance

### Time Travel
- `routers/decision_time_travel.py` - Query decisions at any point in time
- Replay decision state at historical valid_time + transaction_time
- Essential for regulatory compliance and dispute resolution

### Post-hoc Labeling (`services/posthoc_labeling.py`)
- Label past decisions with ground truth outcomes
- Training data generation for model improvement
- Router: `routers/posthoc.py`

---

## 17. Auto-Scale & Resilience

### Concurrency Management
- `MAX_CONCURRENCY` env var - Hard concurrency limit
- `TENANT_MAX_CONCURRENCY` - Per-tenant concurrency limits
- `DEGRADE_ON_CONCURRENCY` + `DEGRADE_CONCURRENCY_THRESHOLD` - Graceful degradation under load
- `x-degraded-mode: true` header added when degraded

### Rate Limiting
- `RATE_LIMIT_PER_IP_PER_MIN` - Per-IP rate limiting
- `RATE_LIMIT_WINDOW_SECONDS` - Rate limit window (default 60s)
- Token-bucket algorithm implementation

### Resilience Patterns
- `services/degradation.py` - Degradation controller
- `services/dependency_resilience.py` - Circuit breaking for dependencies
- Rule-based fallback when LLM unavailable (`rule_based_reason()`)
- Redis fast-fail with short connect timeouts
- PostgreSQL connect timeout configuration
- `pool_pre_ping=True` for database connection validation

### Chaos Engineering
- `CHAOS_ERROR_PROB` - Injected error probability
- `CHAOS_ERROR_PREFIXES` - Path prefixes for targeted chaos
- Chaos metrics recorded (`record_chaos_error`)
- Tests: `test_chaos.py`

### Health Checks
- `/health` - Full dependency health with status aggregation
- `/healthz` - Lightweight liveness probe
- `/readyz` - Readiness probe with DB connectivity check
- Dependency health snapshots cached and included in context

### Docker Scaling
- Docker Compose with service definitions
- Uvicorn workers configurable
- Horizontal scaling via container orchestration (K8s-ready)

---

## 18. Frontend & Backend Dashboards

### Storefront UI (`routers/ui_storefront.py`)
- Product listing and detail pages
- Shopping cart interface
- Checkout flow
- Served via Vite dev server or static files

### Admin Dashboard (`routers/admin.py`)
- System overview and stats
- Feature flag management
- User/tenant management
- Scoring model configuration

### Merchant Dashboard (`routers/merchant_dashboard.py`)
- Merchant-specific analytics
- Order management views
- Revenue and performance metrics

### Admin Analytics (`routers/admin_analytics.py`)
- Deep analytics views
- Query clustering visualization
- Drift metrics dashboard

### Admin Chat Tools (`routers/admin_chat_tools.py`)
- Rules evaluation interface
- Policy management
- Ticket management

### Grafana Proxy (`routers/admin_grafana_proxy.py`)
- Secure Grafana dashboard embedding
- API key abstraction

### Case Cockpit (`routers/case_cockpit.py`)
- Unified case management view
- Evidence review interface
- Decision audit trail

### Demo Router (`routers/demo.py`)
- Demo-specific endpoints
- Seed data visualization
- Feature showcase mode

---

## 19. Production Readiness

### Ready to Demo Today

| Capability | Confidence | Notes |
|-----------|------------|-------|
| Core orchestrator (RRA pipeline) | High | Full retrieve-reason-act with policy gate |
| Multi-provider payments (5 providers) | High | Stripe, PayPal, Revolut, GPay, Afterpay |
| NLP intent classification (rules + XGBoost) | High | Hybrid approach with fallbacks |
| CV image analysis (3-tier) | High | ONNX-based, damage classification, OCR |
| Fraud detection (multi-signal + Isolation Forest) | High | Production-grade fraud scoring |
| Security observer (OWASP/MITRE/STRIDE/DREAD) | High | Comprehensive threat detection |
| Transaction firewall | High | Pricing policy enforcement |
| Bitemporal decision trace | High | Full audit trail with time travel |
| Feature flags & rollout/killswitch | High | JSON-based with test coverage |
| Rate limiting & backpressure | High | Token-bucket with tenant isolation |
| Prometheus + Grafana observability | High | Pre-built dashboards + alerts |
| Health/readiness probes | High | K8s-ready health endpoints |
| Multi-tenant architecture | High | Tenant-scoped config, quotas, isolation |
| Session memory & context | High | Redis-backed with conversation state |
| CI/CD (GitHub Actions) | High | Unit, integration, Playwright, Prometheus |
| Incident management & SLA | High | Severity-based routing and tracking |
| Ticketing & escalation | High | Auto-ticket creation + escalation rooms |
| Admin dashboard | Medium | Basic admin with analytics |
| Storefront UI | Medium | Functional but basic styling |
| Agent bus & handoffs | Medium | Redis-based, needs more agent types |

### Needs Work Before Production

| Capability | Gap | Priority |
|-----------|-----|----------|
| **ERP/EDI integration** | Stub only, needs real SAP/Oracle/NetSuite connector | High |
| **Object storage** | Local filesystem only, needs S3/Azure Blob/GCS | High |
| **Email notifications** | SMTP/SendGrid not wired up | Medium |
| **Shipping integration** | Stub, needs FedEx/UPS/DHL API | Medium |
| **Real LLM models** | Ollama local only; needs production model hosting | High |
| **Vector database** | In-memory; needs Pinecone/Weaviate/pgvector | High |
| **Production Redis** | Configured but needs production cluster | Medium |
| **Kubernetes manifests** | Docker Compose only; needs K8s Helm charts | Medium |
| **Authentication** | Basic auth router exists; needs OAuth2/OIDC | High |
| **Helpdesk connectors** | Framework exists; needs Zendesk/Freshdesk adapters | Medium |
| **Demand forecasting** | Service exists; needs real ML model training | Low |
| **Voice processing** | MVP; needs production ASR/TTS integration | Low |
| **Escalation room** | MVP; needs WebSocket real-time chat | Medium |
| **Frontend polish** | Functional but needs UX/design work | Medium |

---

## 20. Test Coverage & CI/CD

### Test Suite
- `tests/test_admin_scoring.py` - Admin scoring configuration tests
- `tests/test_chaos.py` - Chaos engineering tests
- `tests/test_flags.py` - Feature flag tests
- `tests/test_firewall_rules.py` - Firewall rule tests
- `tests/test_incident_routing_policy.py` - Incident routing tests
- `tests/test_metrics.py` - Observability metrics tests
- `tests/test_observer_severity.py` - Security observer severity tests
- `tests/test_openapi_contract.py` - OpenAPI contract validation
- `tests/test_owasp_scenarios.py` - OWASP security scenario tests
- `tests/test_payments_providers.py` - Payment provider tests
- `tests/test_rollout_and_killswitch.py` - Feature rollout tests
- `tests/test_sla_api.py` - SLA API tests
- `tests/test_support_intents.py` - Support intent classification tests
- `tests/test_voice_flags.py` - Voice feature flag tests
- `tests/test_anomaly.py` - Anomaly detection tests
- `tests/integration/test_e2e.py` - End-to-end integration tests

### CI/CD Pipelines (GitHub Actions)
- `ci-tests.yml` - Core test suite
- `ci.yml` - Full CI pipeline
- `ci_prometheus.yml` - Prometheus metrics validation
- `ci_smoke.yml` - Smoke tests
- `playwright-smoke.yml` - Playwright browser smoke tests
- `playwright-tests.yml` - Full Playwright test suite
- `playwright-ui-smoke.yml` - UI-specific Playwright tests

### Build & Dev Tools
- `Makefile` - Build/dev commands
- `pyproject.toml` - Python project configuration
- `docker-compose.yml` - Local development stack
- `scripts/seed_demo_data.py` - Demo data seeder
- `scripts/send_test_webhook.py` - Webhook testing

---

*End of Part 1 - See Part 2 for Strategic Analysis, SWOT/PESTEL, Competitive Landscape, Claude Architecture Lessons, and Roadmap*
