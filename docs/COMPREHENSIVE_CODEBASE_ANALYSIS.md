# ShopSquire Comprehensive Codebase Analysis

> **Purpose**: Deep-dive technical assessment for production readiness
> **Generated**: February 2026
> **Scope**: 61 services, 19 security modules, 2 frontends, observability stack

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Production Readiness Matrix](#2-production-readiness-matrix)
3. [Agent Deep Dive](#3-agent-deep-dive)
4. [Camera Button - CV Architecture](#4-camera-button---cv-architecture)
5. [Backend NLP for Merchant/Admin](#5-backend-nlp-for-merchantadmin)
6. [Prometheus & Grafana Analysis](#6-prometheus--grafana-analysis)
7. [Merchant BI Requirements](#7-merchant-bi-requirements-from-powerbi-spec)
8. [AI/ML Techniques to Implement](#8-aiml-techniques-to-implement)
9. [Files to Edit](#9-files-to-edit)
10. [Files to Create](#10-files-to-create)
11. [Priority Roadmap](#11-priority-roadmap)

---

## 1. Executive Summary

### Current State (3-Week Sprint)

| Category | Count | Production Ready | Stubs | Notes |
|----------|-------|------------------|-------|-------|
| **Service Files** | 61 | 45 (74%) | 8 (13%) | 8 partial |
| **Security Modules** | 19 | 17 (89%) | 2 (11%) | Strong coverage |
| **Agents (Core)** | 12 | 10 (83%) | 2 (17%) | CV Tier 2, Trust Routing |
| **Frontend Components** | 20 | 18 (90%) | 2 (10%) | Camera button missing |
| **Prometheus Rules** | 11 | 11 (100%) | 0 | Production ready |
| **Grafana Dashboards** | 2 | 2 (100%) | 0 | Needs BI expansion |

### Critical Gaps

1. **Camera Button** - Not implemented in frontend (backend CV ready)
2. **CV Tier 2** - Placeholder wrapping Tier 1 (no advanced models)
3. **Merchant BI Views** - Schema exists but not populated
4. **Demand Forecasting** - Not implemented
5. **Real-time WebSocket** - Backend ready, frontend uses polling

---

## 2. Production Readiness Matrix

### PRODUCTION READY (Deploy Now)

| Component | File | Lines | Confidence |
|-----------|------|-------|------------|
| Orchestrator | `services/orchestrator.py` | 350+ | 95% |
| Security Observer | `security/observer.py` | 240+ | 95% |
| Decision Logging | `services/decision_log.py` | 115 | 95% |
| Policy Gate | `services/policy_gate.py` | 80 | 95% |
| Fraud Scorer | `services/fraud_scorer.py` | 74 | 95% |
| Recommendations | `services/recommendations.py` | 416 | 90% |
| Inventory Agent | `services/inventory_agent.py` | 316 | 98% |
| Audit Evidence Agent | `services/audit_evidence_agent.py` | 148 | 90% |
| Webhook Security | `security/webhook_security.py` | 146 | 95% |
| Transaction Firewall | `security/firewall.py` | 23 | 90% |
| Auth (API Key) | `security/auth.py` | 29 | 90% |
| Tier Router | `services/tier_router.py` | 49 | 95% |
| Token Budget | `services/token_budget.py` | 49 | 95% |
| LLM Orchestrator | `services/llm.py` | 173 | 90% |
| Guardrails | `security/guardrails.py` | 65 | 95% |
| CV Triage Basic | `services/cv_triage_basic.py` | 34 | 90% |
| CV Evidence | `services/cv_evidence.py` | 62 | 90% |

### PRODUCTION READY WITH FALLBACKS

| Component | File | Fallback Behavior |
|-----------|------|-------------------|
| Semantic Cache | `services/semantic_cache.py` | Works without Redis |
| CV Tiered | `services/cv_tiered.py` | Falls back to Tier 1 |
| LLM Provider | `services/llm_provider.py` | Falls back to small model |
| Memory/Session | `services/memory.py` | In-memory if Redis down |

### PARTIAL IMPLEMENTATION (Needs Work)

| Component | File | Status | What's Missing |
|-----------|------|--------|----------------|
| CV Damage Classifier | `services/cv_damage_classifier.py` | 30% | YOLO not integrated, returns placeholders |
| Image Forensics | `services/image_forensics.py` | 50% | ELA partial, splice detection incomplete |
| RAGAS Evaluation | `services/ragas_eval.py` | 40% | Scaffold only, not integrated |
| Trust Routing | `services/trust_routing.py` | 20% | Minimal logic |
| CV Tier 2 Enhanced | `services/cv_tiered.py` | 40% | Wraps Tier 1, no actual enhancement |

### STUBS (Not Implemented)

| Component | File | Purpose |
|-----------|------|---------|
| Reverse Image Search | `services/reverse_image_search.py` | Fraud detection via image matching |
| ERP/EDI Integration | `services/erp_edi.py` | Enterprise system integration |
| Shipping Integration | `services/shipping_stub.py` | Carrier API integration |
| Supply Chain CV | `services/supply_chain_cv.py` | Package/logistics vision |
| Contract NLP | `services/nlp_contract.py` | Contract analysis |

---

## 3. Agent Deep Dive

### Agent Status Table

| Agent | Purpose | Rules | LLM Tier | Status | Production Ready |
|-------|---------|-------|----------|--------|------------------|
| **Orchestrator** | Central coordination, intent routing | 30+ | T0/T1/T2 | COMPLETE | YES |
| **Security Observer** | PII, jailbreak, injection detection | 35+ | T0 only | COMPLETE | YES |
| **Fraud Scorer** | 24 fraud signals, velocity checks | 24 | T0/T1 | COMPLETE | YES |
| **Transaction Firewall** | $250 cap, discount limits, escalation | 12 | T0/T1 | COMPLETE | YES |
| **Inventory Agent** | Stock management, reorder triggers | 50+ | T0/T1 | COMPLETE | YES |
| **Recommendations** | Semantic search, intent detection | 20+ | T1/T2 | COMPLETE | YES |
| **Policy Evaluator** | Compliance rule matrix | 40+ | T0 | COMPLETE | YES |
| **Audit Evidence** | 50 compliance rules (SOX/SOC2/GDPR) | 50 | T0/T1 | COMPLETE | YES |
| **NLP Complaints** | Sentiment, urgency classification | 8 | T1 | COMPLETE | YES |
| **CV Triage (Tier 0/1)** | Damage type, serial extraction | 15 | T0/T1 | COMPLETE | YES |
| **CV Tier 2 Enhanced** | Advanced vision analysis | - | T2 | STUB | NO |
| **Trust Routing** | Confidence-based routing | 3 | T0 | STUB | NO |

### What Each Agent DOES vs SHOULD DO

#### Orchestrator (`services/orchestrator.py`)
**DOES:**
- Routes queries through tier router (T0/T1/T2)
- Coordinates security observer before processing
- Manages decision trace logging
- Handles graceful degradation

**SHOULD ADD:**
- WebSocket streaming for real-time updates
- Multi-agent interleaving for complex queries
- Context graph integration (Neo4j)

#### Security Observer (`security/observer.py`)
**DOES:**
- Detects 8 PII types (email, phone, SSN, IP, DOB, passport, CC, address)
- 35+ jailbreak patterns
- Prompt injection detection (OWASP LLM01)
- Unicode homograph detection
- API key detection
- OWASP/MITRE/STRIDE/DREAD mapping

**SHOULD ADD:**
- Model poisoning detection for CV inputs
- Agent-to-agent communication monitoring
- Embedding attack detection

#### CV Tiered Provider (`services/cv_tiered.py`)
**DOES:**
- Tier 0: Size, phash extraction
- Tier 1: Label-based classification, damage detection, serial extraction
- Tier 2: Wraps Tier 1 with `needs_human_review` flag

**SHOULD ADD (Tier 2 Enhancement):**
```python
# What Tier 2 SHOULD do:
- YOLO damage classification with severity scoring
- Multi-image forensics (ELA, splice detection)
- Serial number OCR with confidence
- Reverse image search for fraud detection
- Managed CV provider (Google Vision / Ollama llava)
```

---

## 4. Camera Button - CV Architecture

### Current State
**The camera button does NOT exist in the frontend.** The backend CV infrastructure is ready but the frontend integration is missing.

### Backend Infrastructure (Ready)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CV BACKEND (READY)                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   POST /api/v1/cv/analyze                                               │
│   ├── Input: labels[], extracted_text, images[] (sanitized metadata)   │
│   ├── Processing: TieredCVProvider → BasicCVTriage                     │
│   ├── Output: cv_analysis, evidence_id, case_id                        │
│   └── Persists: cv_analyses table, evidence_bundles table              │
│                                                                         │
│   POST /api/v1/vision/triage                                            │
│   ├── Input: image upload                                               │
│   ├── Processing: Query suggestion + analysis                           │
│   └── Output: suggested_query, analysis                                 │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Services Available:                                                   │
│   ├── cv_tiered.py       → Tier routing (T0/T1/T2)                     │
│   ├── cv_triage_basic.py → Damage classification, serial extraction    │
│   ├── cv_evidence.py     → Evidence bundle persistence                 │
│   ├── cv_provider.py     → Google Vision / Ollama integration          │
│   └── cv_damage_classifier.py → YOLO placeholder (STUB)                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Frontend Missing (To Build)

**File to Create:** `frontend/src/components/CameraButton.tsx`

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      CAMERA BUTTON FLOW (TO BUILD)                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   User Clicks Camera → Opens Modal → Capture/Upload Image               │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    CLIENT-SIDE PROCESSING                        │   │
│   │                                                                  │   │
│   │   1. Sanitize image (strip EXIF)                                │   │
│   │   2. Compute SHA256 hash                                         │   │
│   │   3. Compute perceptual hash (phash)                            │   │
│   │   4. Extract dimensions, size                                    │   │
│   │   5. DO NOT send raw image bytes to server                      │   │
│   │                                                                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                              │                                          │
│                              ▼                                          │
│   POST /api/v1/cv/analyze                                               │
│   {                                                                     │
│     "images": [{ "sha256": "...", "phash": "...", "size": 1024 }],     │
│     "description": "User description of issue",                        │
│     "issue_type": "refund|return|damage|fraud"                         │
│   }                                                                     │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    CV USE CASES TO SUPPORT                       │   │
│   │                                                                  │   │
│   │   REFUNDS:                                                       │   │
│   │   - "Product arrived damaged" → Damage classification            │   │
│   │   - "Wrong item received" → SKU verification via serial          │   │
│   │   - "Not as described" → Label/feature extraction                │   │
│   │                                                                  │   │
│   │   RETURNS:                                                       │   │
│   │   - "Item doesn't work" → Functional damage detection            │   │
│   │   - "Missing parts" → Component detection                        │   │
│   │                                                                  │   │
│   │   FRAUD DETECTION:                                               │   │
│   │   - Reverse image search (stock photo fraud)                     │   │
│   │   - ELA analysis (photoshopped damage)                           │   │
│   │   - Serial number validation (stolen goods)                      │   │
│   │                                                                  │   │
│   │   FAQ-RELATED:                                                   │   │
│   │   - "What ports does this have?" → Feature extraction            │   │
│   │   - "Is this compatible with X?" → Spec detection                │   │
│   │                                                                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    SECURITY CHECKS (CV-SPECIFIC)                 │   │
│   │                                                                  │   │
│   │   1. Image injection detection (malicious payloads in EXIF)     │   │
│   │   2. Prompt injection in OCR text                                │   │
│   │   3. Adversarial image detection (model poisoning attempts)     │   │
│   │   4. Size/dimension anomalies                                    │   │
│   │   5. Suspicious file type masquerading                          │   │
│   │                                                                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### CV Security Enhancements Needed

**File to Edit:** `security/observer.py`

Add these CV-specific detections:

```python
# CV-specific security signals to add:

CV_SECURITY_SIGNALS = {
    "cv_prompt_injection": {
        "description": "Prompt injection detected in OCR text",
        "patterns": [
            r"ignore.*previous.*instructions",
            r"you are now",
            r"disregard.*above",
            r"</?(system|user|assistant)>",
        ],
        "owasp": "LLM01",
        "severity": "high"
    },
    "cv_adversarial_image": {
        "description": "Potential adversarial perturbation detected",
        "triggers": ["unusual_noise_pattern", "pixel_patch_detected"],
        "mitre": "AML.T0043",
        "severity": "medium"
    },
    "cv_model_poisoning": {
        "description": "Image designed to poison CV model training",
        "triggers": ["backdoor_pattern", "trigger_patch"],
        "mitre": "AML.T0020",
        "severity": "critical"
    },
    "cv_exif_injection": {
        "description": "Malicious payload in image metadata",
        "patterns": ["<script>", "<?php", "eval(", "exec("],
        "owasp": "API09",
        "severity": "high"
    }
}
```

---

## 5. Backend NLP for Merchant/Admin

### Current NLP Services

| Service | File | Capability | Production Ready |
|---------|------|------------|------------------|
| Complaints NLP | `services/nlp_complaints.py` | Sentiment, urgency | YES |
| Deception Detection | `security/nlp_deception.py` | Authority impersonation | YES |
| Intent Classification | `services/expanded_rules.py` | 11 intent patterns | YES |
| Query Understanding | `services/conversational_query.py` | Entity extraction | YES |
| Contract NLP | `services/nlp_contract.py` | STUB | NO |

### NLP Gaps for Merchant/Admin

**Missing Capabilities:**

1. **Query Clustering** - Group similar customer queries for FAQ generation
2. **Trend Detection** - Identify emerging complaint patterns
3. **Sentiment Aggregation** - Daily/weekly sentiment scores
4. **Entity Extraction** - Product mentions, competitor mentions
5. **Contract Analysis** - Supplier contract parsing (stub exists)

**Files to Create:**

```
services/nlp_query_clustering.py    - Query deduplication and clustering
services/nlp_trend_detector.py      - Emerging pattern detection
services/nlp_entity_merchant.py     - Merchant-specific entity extraction
```

### Merchant Admin NLP Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MERCHANT NLP PIPELINE (TO BUILD)                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Customer Queries ────► Query Clustering ────► FAQ Candidate Pool      │
│          │                                              │               │
│          │                                              ▼               │
│          │                                     Merchant Review Queue    │
│          │                                                              │
│          ▼                                                              │
│   Sentiment Analysis ────► Daily Aggregation ────► BI Dashboard         │
│          │                        │                                     │
│          │                        ▼                                     │
│          │              Trend Detection ────► Alert if spike            │
│          │                                                              │
│          ▼                                                              │
│   Entity Extraction ────► Product Mentions ────► Inventory Agent        │
│                          │                                              │
│                          └─► Competitor Mentions ────► Pricing Agent    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Prometheus & Grafana Analysis

### Current Prometheus Rules (11 alerts)

| Alert | Severity | Threshold | Status |
|-------|----------|-----------|--------|
| HighRequestLatencyP95 | warning | >750ms for 5m | GOOD |
| ErrorRateHigh | critical | >5% 5xx for 5m | GOOD |
| PricingLatencyHighP95 | warning | >500ms for 10m | GOOD |
| ControlFailuresSpiking | warning | >10 failures/10m | GOOD |
| IncidentAlertsP1 | critical | any P1 incident | GOOD |
| WebhookSignatureFailureSpike | critical | >5 failures/5m | GOOD |
| WebhookSignatureFailures | warning | any failures | GOOD |
| RateLimitExceededSpike | warning | >20 exceeds/5m | GOOD |
| ChaosErrorInjectionDetected | info | any chaos errors | GOOD |
| ConcurrencySaturation | warning | >200 inflight | GOOD |
| SLOLatencyBreachedP95 | warning | >500ms for 10m | GOOD |

### Metrics Currently Tracked

```yaml
# HTTP Metrics
shopsquire_http_request_duration_seconds_bucket  # Histogram
shopsquire_http_requests_total                   # Counter by status

# Business Metrics
shopsquire_pricing_latency_seconds_bucket        # Histogram
shopsquire_control_failures_total                # Counter
shopsquire_incident_alerts_total                 # Counter by severity
shopsquire_tickets_created_total                 # Counter by priority
shopsquire_decision_events_total                 # Counter

# Security Metrics
shopsquire_webhook_verifications_total           # Counter by status
shopsquire_rate_limit_exceeded_total             # Counter

# Operational Metrics
shopsquire_chaos_errors_total                    # Counter
shopsquire_chaos_injected_total                  # Counter
shopsquire_inflight_requests                     # Gauge by service
```

### Missing Metrics (To Add)

**File to Edit:** `src/app/observability/metrics.py`

```python
# AI/ML Metrics to add:
MISSING_METRICS = {
    # LLM Metrics
    "shopsquire_llm_tokens_total": "Counter - tokens consumed by model/tier",
    "shopsquire_llm_latency_seconds": "Histogram - LLM response time",
    "shopsquire_llm_fallback_total": "Counter - fallbacks to rules",

    # Agent Metrics
    "shopsquire_agent_invocations_total": "Counter - agent calls by type",
    "shopsquire_agent_confidence_score": "Histogram - confidence distribution",
    "shopsquire_agent_escalations_total": "Counter - human escalations",

    # CV Metrics
    "shopsquire_cv_tier_selection_total": "Counter - tier 0/1/2 selections",
    "shopsquire_cv_processing_seconds": "Histogram - CV processing time",
    "shopsquire_cv_fraud_detected_total": "Counter - fraud detections",

    # Security Metrics
    "shopsquire_security_signals_total": "Counter - signals by type/severity",
    "shopsquire_pii_detected_total": "Counter - PII detections by type",
    "shopsquire_jailbreak_attempts_total": "Counter - jailbreak attempts",

    # Business Metrics
    "shopsquire_orders_total": "Counter - orders by status",
    "shopsquire_revenue_dollars": "Counter - revenue processed",
    "shopsquire_refunds_total": "Counter - refunds by reason"
}
```

### Missing Prometheus Alerts (To Add)

**File to Edit:** `config/observability/prometheus_rules.yml`

```yaml
# Add these rules:

- alert: LLMTokenBudgetExhausted
  expr: sum(rate(shopsquire_llm_tokens_total[1h])) by (user_id) > 10000
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "User token budget nearly exhausted"

- alert: AgentEscalationRateHigh
  expr: sum(rate(shopsquire_agent_escalations_total[5m])) / sum(rate(shopsquire_agent_invocations_total[5m])) > 0.3
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Agent escalation rate exceeds 30%"

- alert: CVFraudSpike
  expr: sum(rate(shopsquire_cv_fraud_detected_total[5m])) > 5
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "CV fraud detections spiking"

- alert: JailbreakAttemptSpike
  expr: sum(rate(shopsquire_jailbreak_attempts_total[5m])) > 10
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Multiple jailbreak attempts detected"

- alert: LLMLatencyHigh
  expr: histogram_quantile(0.95, sum(rate(shopsquire_llm_latency_seconds_bucket[5m])) by (le)) > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "LLM response time exceeds 5s"
```

### Grafana Dashboard Improvements

**Current Dashboards:**
1. `shopsquire-dashboard.json` - Operational metrics (7 panels)
2. `shopsquire-bi-views.json` - BI views from Postgres (3 panels)

**Missing Dashboards to Create:**

```
config/observability/grafana/dashboards/
├── shopsquire-llm-metrics.json       # LLM usage, tokens, latency
├── shopsquire-agent-analytics.json   # Agent performance, escalations
├── shopsquire-cv-analytics.json      # CV tier usage, fraud detections
├── shopsquire-security-soc.json      # Security operations center
└── shopsquire-merchant-bi.json       # Merchant business intelligence
```

---

## 7. Merchant BI Requirements (from PowerBI Spec)

### Event Model Required

From `dump/merchant-admin-powerbi.txt`, the merchant needs:

| Event Type | Data Points | Current Status |
|------------|-------------|----------------|
| **Search** | query, filters, result SKUs | NOT TRACKED |
| **Product View** | SKU, position, referrer, price | NOT TRACKED |
| **Cart/Checkout** | SKU, quantity, price, discount | PARTIAL |
| **Purchase** | order_id, SKUs, totals, status | YES |
| **Support/Returns** | reason, outcome, cost, time | YES |
| **Agent Actions** | proposals, decisions, escalations | YES (bi-temporal) |

### BI Views Needed (SQL)

**File to Create:** `db/migrations/xxx_bi_views.sql`

```sql
-- Daily order aggregates
CREATE MATERIALIZED VIEW bi_orders_daily AS
SELECT
    DATE(created_at) as day,
    status,
    COUNT(*) as order_count,
    SUM(total_cents) / 100.0 as revenue
FROM orders
GROUP BY DATE(created_at), status;

-- Daily decision aggregates
CREATE MATERIALIZED VIEW bi_decisions_daily AS
SELECT
    DATE(system_from) as day,
    action_type,
    COUNT(*) as decision_count,
    AVG(confidence) as avg_confidence
FROM decision_log
GROUP BY DATE(system_from), action_type;

-- Security events daily
CREATE MATERIALIZED VIEW bi_security_daily AS
SELECT
    DATE(created_at) as day,
    severity,
    signal_type,
    COUNT(*) as event_count
FROM security_events
GROUP BY DATE(created_at), severity, signal_type;

-- Search funnel (NEEDS EVENT TRACKING FIRST)
CREATE MATERIALIZED VIEW bi_search_funnel AS
SELECT
    DATE(timestamp) as day,
    query_cluster_id,
    COUNT(DISTINCT session_id) as searches,
    COUNT(DISTINCT CASE WHEN viewed_sku IS NOT NULL THEN session_id END) as views,
    COUNT(DISTINCT CASE WHEN added_to_cart THEN session_id END) as carts,
    COUNT(DISTINCT CASE WHEN purchased THEN session_id END) as purchases
FROM search_events
GROUP BY DATE(timestamp), query_cluster_id;
```

### Bi-Temporal Decision Trace (Already Implemented)

The spec requires these objects (status: **COMPLETE**):

| Object | Current Implementation | File |
|--------|------------------------|------|
| DecisionProposed | `decision_log.payload` | `services/decision_log.py` |
| EvidenceSnapshot | `evidence_bundles` table | `services/cv_evidence.py` |
| PolicyEvaluation | `policy_version`, `rules_fired` | `services/policy_evaluator.py` |
| ApprovalOutcome | `escalation` records | `security/escalation.py` |
| ActionExecuted | `decision_log.action_type` | `services/decision_log.py` |
| PostHocOutcome | NOT IMPLEMENTED | Need to add |

**Missing:** PostHocOutcome (later truth labels)

**File to Create:** `services/posthoc_labeling.py`

```python
# Track post-hoc outcomes:
# - Refund reversed
# - Fraud confirmed
# - Customer satisfied (survey)
# - Return accepted
```

---

## 8. AI/ML Techniques to Implement

### From PowerBI Spec Analysis

| Technique | Priority | Complexity | Business Value |
|-----------|----------|------------|----------------|
| **Demand Forecasting** | HIGH | Medium | Stock optimization |
| **Query Clustering** | HIGH | Low | FAQ automation |
| **Anomaly Detection** | HIGH | Medium | Fraud prevention |
| **Collaborative Filtering** | MEDIUM | Medium | Better recommendations |
| **Causal Inference** | LOW | High | Agent optimization |

### Implementation Recommendations

#### A. Demand Forecasting (PRIORITY: HIGH)

**File to Create:** `services/demand_forecast.py`

```python
# Start with: Hierarchical + Feature-based ML
# Features: price, promo, seasonality, stockouts
# Framework: LightGBM or Prophet

class DemandForecaster:
    """
    MVP: 3-month rolling forecast by SKU/category

    Features:
    - Historical sales (30/60/90 day)
    - Price changes
    - Active promotions
    - Seasonality (day of week, month)
    - Stockout history

    Output:
    - demand_forecast_daily (materialized view)
    - confidence intervals
    - anomaly flags
    """
```

#### B. Query Clustering (PRIORITY: HIGH)

**File to Create:** `services/nlp_query_clustering.py`

```python
# Approach: Embedding + HDBSCAN clustering

class QueryClusterer:
    """
    Purpose: Group similar queries for FAQ generation

    Pipeline:
    1. Embed queries (sentence-transformers)
    2. Cluster (HDBSCAN for noise handling)
    3. Extract centroid query as representative
    4. Track cluster growth for trending topics

    Output:
    - query_clusters table
    - faq_candidates queue
    """
```

#### C. Anomaly Detection (PRIORITY: HIGH)

**File to Create:** `services/anomaly_detector.py`

```python
# Approach: Statistical + ML ensemble

class AnomalyDetector:
    """
    Domains:
    - Refund velocity (user, merchant, product)
    - Order patterns (amount, frequency, geography)
    - Agent behavior (tool calls, escalations)

    Methods:
    - Z-score for simple metrics
    - Isolation Forest for multivariate
    - Time-series anomaly (Prophet)

    Output:
    - anomaly_events table
    - Real-time alerts
    """
```

#### D. Image Hash Matching (PRIORITY: HIGH for Fraud)

**File to Edit:** `services/reverse_image_search.py` (currently stub)

```python
# Approach: Perceptual hash + vector similarity

class ReverseImageSearch:
    """
    Purpose: Detect repeat fraud via image reuse

    Pipeline:
    1. Compute phash of uploaded image
    2. Query phash index for near-matches (hamming distance < 10)
    3. If match found, flag as potential fraud
    4. Store all claim images in phash index

    Integration:
    - cv_evidence.py calls this during evidence bundle creation
    - fraud_scorer.py uses matches as signal
    """
```

#### E. Prompt Injection Detection for OCR (PRIORITY: HIGH)

**File to Edit:** `security/observer.py`

```python
# Add OCR-specific prompt injection patterns

OCR_INJECTION_PATTERNS = [
    # Visible text attacks
    r"ignore.*previous",
    r"you are now",
    r"new instructions",
    r"system prompt",

    # Invisible text attacks (Unicode tricks)
    r"[\u200b-\u200f]",  # Zero-width characters
    r"[\u2028-\u2029]",  # Line/paragraph separators

    # Image-based attacks
    # (Detected via CV analysis, not regex)
]
```

---

## 9. Files to Edit

### High Priority Edits

| File | Change | Reason |
|------|--------|--------|
| `security/observer.py` | Add CV-specific security signals | Camera button needs injection detection |
| `services/cv_tiered.py` | Implement real Tier 2 | Current Tier 2 is just Tier 1 wrapper |
| `services/cv_damage_classifier.py` | Integrate YOLO | Currently returns placeholders |
| `services/reverse_image_search.py` | Implement phash search | Fraud detection needs this |
| `config/observability/prometheus_rules.yml` | Add AI/ML alerts | Missing LLM, agent, CV metrics |
| `src/app/observability/metrics.py` | Add missing metrics | LLM tokens, agent confidence, etc. |

### Medium Priority Edits

| File | Change | Reason |
|------|--------|--------|
| `frontend/src/components/ChatOverlay.tsx` | Add camera button | CV integration in chat |
| `services/image_forensics.py` | Complete ELA, splice | Fraud detection enhancement |
| `services/trust_routing.py` | Implement confidence routing | Currently minimal |
| `routers/chat.py` | Add WebSocket support | Real-time streaming |
| `services/ragas_eval.py` | Integrate with pipeline | Quality evaluation |

### Low Priority Edits

| File | Change | Reason |
|------|--------|--------|
| `services/nlp_contract.py` | Implement contract parsing | Supplier management |
| `services/shipping_stub.py` | Carrier API integration | Order fulfillment |
| `services/erp_edi.py` | ERP integration | Enterprise features |

---

## 10. Files to Create

### Critical (Camera Button & CV)

```
frontend/src/components/CameraButton.tsx          # Camera capture UI
frontend/src/components/CVResultsPanel.tsx        # CV analysis results display
frontend/src/utils/imageProcessing.ts             # Client-side sanitization
services/cv_security_scanner.py                   # CV-specific security checks
```

### High Priority (BI & Analytics)

```
services/demand_forecast.py                       # Demand forecasting
services/nlp_query_clustering.py                  # Query clustering
services/anomaly_detector.py                      # Anomaly detection
services/posthoc_labeling.py                      # Post-hoc outcome tracking
db/migrations/xxx_bi_views.sql                    # BI materialized views
db/migrations/xxx_search_events.sql               # Search event tracking
```

### Medium Priority (Observability)

```
config/observability/grafana/dashboards/
├── shopsquire-llm-metrics.json
├── shopsquire-agent-analytics.json
├── shopsquire-cv-analytics.json
├── shopsquire-security-soc.json
└── shopsquire-merchant-bi.json
```

### Low Priority (Future)

```
services/collaborative_filtering.py               # Enhanced recommendations
services/causal_inference.py                      # A/B test analysis
services/nlp_entity_merchant.py                   # Merchant entity extraction
```

---

## 11. Priority Roadmap

### Week 1: Camera Button MVP

```
Day 1-2: Frontend
├── Create CameraButton.tsx
├── Create CVResultsPanel.tsx
├── Add camera icon to ChatOverlay.tsx
└── Client-side image sanitization

Day 3-4: Backend CV Security
├── Add CV security signals to observer.py
├── Implement OCR prompt injection detection
└── Test with adversarial images

Day 5: Integration
├── Wire camera button to /api/v1/cv/analyze
├── Display CV results in chat
└── Add to decision trace
```

### Week 2: CV Tier 2 & Fraud

```
Day 1-2: CV Tier 2
├── Integrate YOLO in cv_damage_classifier.py
├── Complete image_forensics.py
└── Update cv_tiered.py to use enhanced analysis

Day 3-4: Fraud Detection
├── Implement reverse_image_search.py
├── Add phash index to database
└── Integrate with fraud_scorer.py

Day 5: Testing
├── Test with real damage images
├── Test fraud detection scenarios
└── Performance benchmarking
```

### Week 3: BI & Observability

```
Day 1-2: Metrics
├── Add missing Prometheus metrics
├── Add missing alert rules
└── Create Grafana dashboards

Day 3-4: BI Views
├── Create search event tracking
├── Create materialized views
└── Connect to Grafana BI dashboard

Day 5: NLP Enhancements
├── Implement query clustering
├── Add trend detection
└── FAQ candidate generation
```

### Week 4: Advanced AI/ML

```
Day 1-2: Demand Forecasting
├── Implement demand_forecast.py
├── Create forecast materialized views
└── Add to inventory agent

Day 3-4: Anomaly Detection
├── Implement anomaly_detector.py
├── Integrate with fraud scorer
└── Add real-time alerts

Day 5: Integration & Polish
├── End-to-end testing
├── Documentation
└── Performance optimization
```

---

## Appendix A: File Inventory

### Services (61 files)
```
src/app/services/
├── orchestrator.py (350+ lines) ✓ PRODUCTION
├── agent_bus.py (19 lines) ✓ PRODUCTION
├── agent_handoff.py (12 lines) ✓ PRODUCTION
├── audit_evidence_agent.py (148 lines) ✓ PRODUCTION
├── inventory_agent.py (316 lines) ✓ PRODUCTION
├── recommendations.py (416 lines) ✓ PRODUCTION
├── policy_gate.py (80 lines) ✓ PRODUCTION
├── policy_evaluator.py (66 lines) ✓ PRODUCTION
├── decision_log.py (115 lines) ✓ PRODUCTION
├── tier_router.py (49 lines) ✓ PRODUCTION
├── cv_tiered.py (64 lines) ~ PARTIAL (Tier 2 stub)
├── cv_triage_basic.py (34 lines) ✓ PRODUCTION
├── cv_evidence.py (62 lines) ✓ PRODUCTION
├── cv_damage_classifier.py (22 lines) ✗ STUB
├── cv_provider.py (39 lines) ✓ PRODUCTION
├── reverse_image_search.py (15 lines) ✗ STUB
├── image_forensics.py (41 lines) ~ PARTIAL
├── fraud_scorer.py (74 lines) ✓ PRODUCTION
├── llm.py (173 lines) ✓ PRODUCTION
├── llm_provider.py (36 lines) ✓ PRODUCTION
├── token_budget.py (49 lines) ✓ PRODUCTION
├── semantic_cache.py (22 lines) ✓ PRODUCTION
├── nlp_complaints.py (19 lines) ✓ PRODUCTION
├── nlp_contract.py (11 lines) ✗ STUB
├── trust_routing.py (11 lines) ✗ STUB
├── ... (36 more files)
```

### Security (19 files)
```
src/app/security/
├── observer.py (240+ lines) ✓ PRODUCTION
├── guardrails.py (65 lines) ✓ PRODUCTION
├── auth.py (29 lines) ✓ PRODUCTION
├── firewall.py (23 lines) ✓ PRODUCTION
├── escalation.py (65 lines) ✓ PRODUCTION
├── webhook_security.py (146 lines) ✓ PRODUCTION
├── pci_boundary.py (15 lines) ✓ PRODUCTION
├── pci.py (9 lines) ✓ PRODUCTION
├── iam.py (25 lines) ✓ PRODUCTION
├── kms.py (29 lines) ✓ PRODUCTION
├── idempotency.py (45 lines) ✓ PRODUCTION
├── nlp_deception.py (29 lines) ✓ PRODUCTION
├── supply_chain.py (91 lines) ✓ PRODUCTION
├── ... (6 more files)
```

---

*Document generated: February 2026*
*Codebase version: ShopSquire v2.0 (post 3-week sprint)*
