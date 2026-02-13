# ShopSquire Agentic AI Architecture

> **Complete Reference**: Agent ecosystem, decision flows, AI/ML techniques, thresholds, and function documentation
> **Version**: 2.0 | **Date**: January 2026

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [User Flow Diagrams](#2-user-flow-diagrams)
3. [Agent Catalog](#3-agent-catalog)
4. [Tier Router & Decision Making](#4-tier-router--decision-making)
5. [AI/ML Techniques by Agent](#5-aiml-techniques-by-agent)
6. [Thresholds & Weights Reference](#6-thresholds--weights-reference)
7. [Function Documentation](#7-function-documentation)

---

## 1. Architecture Overview

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    USER LAYER                                           │
│   ┌─────────────────────┐                           ┌─────────────────────┐             │
│   │   BUYER (Consumer)  │                           │   ADMIN (Merchant)  │             │
│   │   - Browse/Search   │                           │   - Dashboard       │             │
│   │   - Chat/NLP        │                           │   - Approvals       │             │
│   │   - Checkout        │                           │   - Analytics       │             │
│   │   - Returns/Support │                           │   - Policy Config   │             │
│   └──────────┬──────────┘                           └──────────┬──────────┘             │
└──────────────┼──────────────────────────────────────────────────┼───────────────────────┘
               │                                                  │
               ▼                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              GATEWAY LAYER (FastAPI)                                    │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                    │
│   │ CORS/Auth   │  │ Rate Limit  │  │ API Key     │  │ Request     │                    │
│   │ Middleware  │  │ Middleware  │  │ Validation  │  │ Logging     │                    │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                    │
└──────────┼────────────────┼────────────────┼────────────────┼───────────────────────────┘
           │                │                │                │
           ▼                ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           SECURITY LAYER (Pre-Processing)                               │
│                                                                                         │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                      SECURITY OBSERVER (Read-Only)                              │   │
│   │   • PII Detection (8 types)    • Prompt Injection (OWASP LLM01)                │   │
│   │   • Jailbreak Patterns (35+)   • MITRE ATLAS Tagging                           │   │
│   │   • Unicode Homograph          • Risk Scoring (0-100)                          │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                               │
│                          severity, risk_adj, details                                    │
└─────────────────────────────────────────┼───────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              TIER ROUTER (Decision Point)                               │
│                                                                                         │
│   ┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐             │
│   │   TIER 0 (T0)     │     │   TIER 1 (T1)     │     │   TIER 2 (T2)     │             │
│   │   Cache/Rules     │     │   Single LLM      │     │   Interleaved     │             │
│   │   0 tokens        │     │   1 tool budget   │     │   4 tool budget   │             │
│   │   <50ms latency   │     │   <500ms latency  │     │   <2s latency     │             │
│   └─────────┬─────────┘     └─────────┬─────────┘     └─────────┬─────────┘             │
└─────────────┼─────────────────────────┼─────────────────────────┼───────────────────────┘
              │                         │                         │
              ▼                         ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              AGENT ORCHESTRATION LAYER                                  │
│                                                                                         │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                           ORCHESTRATOR (Central Hub)                            │   │
│   │   • Validate → Retrieve → Reason → Policy → Execute/Escalate                   │   │
│   │   • Model Tiering Selection • Token Budget Enforcement                         │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                               │
│              ┌──────────────────────────┼──────────────────────────┐                    │
│              ▼                          ▼                          ▼                    │
│   ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐              │
│   │ Domain Agents    │      │ Policy Agents    │      │ Support Agents   │              │
│   │ • Recommendation │      │ • Policy Eval    │      │ • NLP Complaints │              │
│   │ • Inventory      │      │ • Firewall       │      │ • Ticketing      │              │
│   │ • Fraud Scorer   │      │ • Audit Evidence │      │ • Returns        │              │
│   │ • CV Provider    │      │ • Trust Routing  │      │                  │              │
│   └──────────────────┘      └──────────────────┘      └──────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                 DATA LAYER                                              │
│                                                                                         │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐            │
│   │  PostgreSQL   │  │    Redis      │  │   Ollama      │  │  TimescaleDB  │            │
│   │  (OLTP/PII)   │  │  (Cache/RAG)  │  │  (LLM/VLM)    │  │   (Events)    │            │
│   └───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘            │
│                                                                                         │
│   ┌───────────────────────────────────────────────────────────────────────────────┐     │
│   │                    DECISION TRACE (Bi-Temporal Audit)                         │     │
│   │   • decision_logs • decision_trace_events • security_events • worm_audit      │     │
│   └───────────────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Architectural Principles

| Principle | Implementation | Rationale |
|-----------|----------------|-----------|
| **Rules-First** | 85+ pre-LLM rules across agents | 90% cost reduction, <50ms latency |
| **Tiered Inference** | T0/T1/T2 routing | Progressive complexity handling |
| **Explainability** | Bi-temporal decision trace | EU AI Act Art-14 compliance |
| **Least Privilege** | Agent proposes, Firewall approves | No direct agent execution |
| **Graceful Degradation** | Rules fallback on LLM timeout | Service continuity |
| **Token Budgeting** | Per-user daily limits | Cost control, fair usage |

---

## 2. User Flow Diagrams

### 2.1 Buyer (Consumer) Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              BUYER USER JOURNEY                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
  │  BROWSE  │────▶│  SEARCH  │────▶│   CART   │────▶│ CHECKOUT │────▶│ SUPPORT  │
  └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
       │                │                │                │                │
       ▼                ▼                ▼                ▼                ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                              AGENT INTERACTIONS                                     │
  └─────────────────────────────────────────────────────────────────────────────────────┘

  BROWSE/SEARCH:
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │ User Query: "I need a gaming laptop under $1500 with RTX graphics"                  │
  │                                                                                     │
  │ 1. Security Observer                                                                │
  │    └── Scan for PII/injection → severity: "info", risk_adj: 0.0                    │
  │                                                                                     │
  │ 2. Tier Router                                                                      │
  │    └── Check cache/rules → No hit                                                  │
  │    └── Evaluate triggers → keyword:"recommend" detected                            │
  │    └── Decision: T1 (single LLM pass, tool_budget: 1)                              │
  │                                                                                     │
  │ 3. Expanded Rule Engine                                                             │
  │    └── Intent: "product_search" (confidence: 0.9)                                  │
  │    └── Matched patterns: ["i need", "looking for"]                                 │
  │                                                                                     │
  │ 4. Recommendation Service                                                           │
  │    └── analyze_query() → Extract: budget_max=$1500, specs=[gpu:discrete]           │
  │    └── retrieve_candidates() → DB query + TF-IDF ranking                           │
  │    └── rerank_candidates() → Score by: stock(+10), budget(+5), brand(+3)           │
  │    └── Return: [Dell XPS 15, Lenovo Legion 5, ASUS ROG]                            │
  │                                                                                     │
  │ 5. Decision Log                                                                     │
  │    └── Persist: decision_id, intent, candidates, factors, policy_version           │
  └─────────────────────────────────────────────────────────────────────────────────────┘

  CART/CHECKOUT:
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │ Action: Add to cart, proceed to checkout                                            │
  │                                                                                     │
  │ 1. Orchestrator.run()                                                               │
  │    └── validate(payload) → cart_total_cents present                                │
  │    └── retrieve(uid, payload) → Get context, stock status                          │
  │                                                                                     │
  │ 2. Inventory Agent                                                                  │
  │    └── evaluate_stock_rule() → R001: "In stock - ships within 2 days"              │
  │                                                                                     │
  │ 3. Orchestrator.reason()                                                            │
  │    └── Tiered discount: <$100=5%, <$250=10%, >$250=15%                             │
  │                                                                                     │
  │ 4. Transaction Firewall                                                             │
  │    └── check_pricing() → cart=$1200, discount=10%                                  │
  │    └── Result: allowed=True, approval_required=False                               │
  │                                                                                     │
  │ 5. Payment Provider (Stripe/PayPal/etc.)                                            │
  │    └── Create payment intent, handle webhook                                       │
  │                                                                                     │
  │ 6. Decision Trace                                                                   │
  │    └── Log: all steps with bi-temporal timestamps                                  │
  └─────────────────────────────────────────────────────────────────────────────────────┘

  SUPPORT/RETURNS:
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │ User: "My laptop screen is cracked, I want a refund"                                │
  │                                                                                     │
  │ 1. Security Observer                                                                │
  │    └── No threats detected                                                         │
  │                                                                                     │
  │ 2. NLP Complaints Service                                                           │
  │    └── Sentiment: negative, Urgency: high                                          │
  │    └── Category: "product_damage"                                                  │
  │                                                                                     │
  │ 3. Fraud Scorer                                                                     │
  │    └── pre_llm_cv_check() on uploaded image                                        │
  │    └── Signals: cv_blur_score_low=False, cv_duplicate_hash=False                   │
  │    └── score_with_enrichment() → risk_level: "low"                                 │
  │                                                                                     │
  │ 4. CV Provider (if image uploaded)                                                  │
  │    └── get_labels_and_text() → labels: ["screen", "crack"], text: "SN-ABC123"     │
  │                                                                                     │
  │ 5. Transaction Firewall                                                             │
  │    └── Refund amount > $250 → approval_required: True                              │
  │    └── Escalation to: "owner"                                                      │
  │                                                                                     │
  │ 6. Ticketing Agent                                                                  │
  │    └── Create ticket for admin review                                              │
  └─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Admin (Merchant) Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              ADMIN USER JOURNEY                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
  │DASHBOARD │────▶│APPROVALS │────▶│INVENTORY │────▶│ SECURITY │────▶│ REPORTS  │
  └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
       │                │                │                │                │
       ▼                ▼                ▼                ▼                ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                              AGENT INTERACTIONS                                     │
  └─────────────────────────────────────────────────────────────────────────────────────┘

  DASHBOARD:
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │ Admin views: KPIs, alerts, pending actions                                          │
  │                                                                                     │
  │ 1. Analytics Aggregation                                                            │
  │    └── Prometheus metrics: tier_hit_counter, rule_match_counter                    │
  │    └── Decision summary: 85% T0, 12% T1, 3% T2                                     │
  │                                                                                     │
  │ 2. Inventory Agent Alerts                                                           │
  │    └── monitor_stock_levels() → List[StockAlert]                                   │
  │    └── Alert types: low_stock, out_of_stock, overstock                             │
  │                                                                                     │
  │ 3. Security Observer Summary                                                        │
  │    └── security_observer_timeseries: severity distribution                         │
  │    └── Recent high/critical events flagged                                         │
  └─────────────────────────────────────────────────────────────────────────────────────┘

  APPROVALS:
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │ Pending items requiring human decision                                              │
  │                                                                                     │
  │ 1. Transaction Firewall Escalations                                                 │
  │    └── Refunds > $250: review fraud score, CV evidence, customer history           │
  │    └── High discounts (>25%): verify business justification                        │
  │                                                                                     │
  │ 2. Inventory Reorder Approvals                                                      │
  │    └── estimated_cost > $5000: require approval ticket                             │
  │    └── InventoryAgent.execute_reorder(approval=ticket_id)                          │
  │                                                                                     │
  │ 3. Security Incident Review                                                         │
  │    └── auto_route_security_event() creates incidents                               │
  │    └── Admin reviews, updates status: open→investigating→resolved                  │
  │                                                                                     │
  │ 4. Decision Trace Viewer                                                            │
  │    └── /api/v1/decisions/{id} → Full trace with evidence                           │
  │    └── /api/v1/trace/{id}/timeline → Event sequence with latency                   │
  └─────────────────────────────────────────────────────────────────────────────────────┘

  INVENTORY MANAGEMENT:
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │ Stock monitoring and reorder management                                             │
  │                                                                                     │
  │ 1. InventoryAgent.monitor_stock_levels()                                            │
  │    └── Query: stock <= reorder_point                                               │
  │    └── Returns: List[StockAlert]                                                   │
  │                                                                                     │
  │ 2. InventoryAgent.generate_reorder_recommendations()                                │
  │    └── _get_best_supplier() → Weighted scoring:                                    │
  │        - w_cost: 0.4 (lower is better)                                             │
  │        - w_lead: 0.25 (shorter is better)                                          │
  │        - w_on_time: 0.2 (higher is better)                                         │
  │        - w_reliability: 0.1 (higher is better)                                     │
  │        - w_moq: 0.05 (lower is better)                                             │
  │    └── _calculate_eoq() → EWMA demand forecast                                     │
  │    └── _determine_urgency() → critical/urgent/normal                               │
  │                                                                                     │
  │ 3. Stocktake Reconciliation                                                         │
  │    └── reconcile_stocktake(counted_stock)                                          │
  │    └── Flag variances > 5% for review                                              │
  └─────────────────────────────────────────────────────────────────────────────────────┘

  SECURITY MONITORING:
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │ Security Observer dashboard and incident management                                 │
  │                                                                                     │
  │ 1. Real-time Event Stream                                                           │
  │    └── security_events table: path, severity, verdict_score, details               │
  │    └── WORM audit trail: append-only, immutable                                    │
  │                                                                                     │
  │ 2. Compliance Tags                                                                  │
  │    └── MITRE ATLAS: AML.T0043, AML.T0015, AML.T0048                               │
  │    └── OWASP LLM: LLM01-09                                                         │
  │    └── ISO: 27001, 42001                                                           │
  │    └── EU AI Act: Art-14, Art-17, Art-20                                           │
  │                                                                                     │
  │ 3. Audit Evidence Agent                                                             │
  │    └── 50 deterministic rules across 6 categories                                  │
  │    └── Categories: log_integrity, privacy, access_control,                         │
  │                    change_mgmt, financial_controls, ai_governance                  │
  │    └── Compliance tags: SOX, SOC2, GDPR, EUAI, ISO42001                            │
  └─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agent Catalog

### 3.1 Core Agents Summary

| Agent | File | Lines | Purpose | Thinking Tier | Pre-LLM Rules |
|-------|------|-------|---------|---------------|---------------|
| **Orchestrator** | `orchestrator.py` | 527 | Central coordination, model selection | T0/T1/T2 | Intent routing |
| **Tier Router** | `tier_router.py` | 107 | Tier decision, cache management | Meta | Complexity triggers |
| **Security Observer** | `security/observer.py` | 698 | Threat detection, risk scoring | T0 only | 8 PII + 35 jailbreak |
| **Transaction Firewall** | `security/firewall.py` | 53 | Transaction approval/escalation | T0 | Amount thresholds |
| **Expanded Rules** | `expanded_rules.py` | 86 | Intent classification | T0 | 11 intent patterns |
| **Inventory Agent** | `inventory_agent.py` | 511 | Stock management, reorder | T0/T1 | 50 STOCK_RULES |
| **Fraud Scorer** | `fraud_scorer.py` | 193 | Fraud risk assessment | T0/T1 | 24 fraud signals |
| **Recommendation** | `recommendations.py` | 836 | Product recommendations | T1/T2 | 117 intent phrases |
| **CV Provider** | `cv_provider.py` | 98 | Image analysis | T1 | Hash/dimension checks |
| **Policy Evaluator** | `policy_evaluator.py` | 144 | Rule evaluation, compliance | T0 | Policy rules |
| **Token Budget** | `token_budget.py` | 121 | Usage limits enforcement | N/A | Tier limits |
| **Audit Evidence** | `audit_evidence_agent.py` | 269 | Compliance verification | T0 | 50 audit rules |

### 3.2 Detailed Agent Specifications

#### 3.2.1 Orchestrator
**Location**: `src/app/services/orchestrator.py`

```python
class Orchestrator:
    """Central hub for request processing and agent coordination."""

    # METHODS:
    def validate(payload) -> Tuple[bool, str]
        # Validates required fields (cart_total_cents)

    def retrieve(uid, payload) -> Dict[str, Any]
        # Retrieves context: memory, live data, stock status, draft orders
        # Returns: {memory, live, retrieved_context, dependency_health}

    def reason(ctx) -> Dict[str, Any]
        # MVP pricing logic based on cart total
        # <$100: 5% discount, <$250: 10%, >$250: 15%

    def rule_based_reason(ctx) -> Dict[str, Any]
        # Conservative fallback for degradation
        # <$100: 10%, <$250: 5%, >$250: 0%

    def choose_model_tier(payload, retrieved, security) -> Dict
        # Selects text tier (T1/T2/T3) and vision tier (V0/V1/V2)
        # Based on: intent_confidence, multi_turn, amount, risk_adj

    def policy(proposal) -> Dict[str, Any]
        # Delegates to TransactionFirewall.check_pricing()

    def execute_or_escalate(uid, proposal, policy, ...) -> bool
        # Persists decision, checks idempotency, handles approval

    def run(uid, payload, simulate_only, use_rules) -> OrchestratorResult
        # Main entry: validate → retrieve → reason → policy → execute
```

**AI/ML Techniques**:
- Intent classification via ExpandedRuleEngine
- Complexity scoring for tier routing
- LLM reranking (optional)
- RAGAS evaluation (optional)

**Architectural Reasons**:
- Single entry point prevents agent-to-agent calls
- Policy check before execution ensures least-privilege
- Bi-temporal logging enables audit replay

---

#### 3.2.2 Tier Router
**Location**: `src/app/services/tier_router.py`

```python
class TierRouter:
    """Decides processing tier: T0 (cache/rules), T1 (single LLM), T2 (interleaved)."""

    TIER_2_TRIGGERS = {
        "risk_threshold": 0.5,        # Security risk score
        "amount_threshold": 250.0,    # Transaction amount ($)
        "intent_confidence_low": 0.7, # Below this → T2
        "complexity_keywords": [
            "compare", "tradeoff", "versus", "analyze",
            "explain why", "best option", "recommend"
        ]
    }

    TOOL_BUDGETS = {0: 0, 1: 1, 2: 4}  # Max tool calls per tier

    def route(query, context, intent_result, security_analysis) -> TierDecision:
        # 1. Check cache hit → T0
        # 2. Check rule match with confidence >= 0.95 → T0
        # 3. Evaluate T2 triggers (risk, amount, confidence, keywords)
        # 4. Default → T1

    def _compute_cache_key(query, context) -> str:
        # SHA256 of normalized query + stable context keys
```

**Decision Logic**:
```
                    ┌──────────────┐
                    │  Incoming    │
                    │   Query      │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Cache Hit?   │──── Yes ───▶ T0 (0 tokens)
                    └──────┬───────┘
                           │ No
                    ┌──────▼───────┐
                    │ Rule Match   │──── Yes ───▶ T0 (0 tokens)
                    │ conf >= 0.95?│     (rule_match)
                    └──────┬───────┘
                           │ No
                    ┌──────▼───────┐
                    │ T2 Triggers? │
                    │ • risk >= 0.5│
                    │ • amt >= $250│──── Yes ───▶ T2 (4 tools)
                    │ • conf < 0.7 │     (interleaved)
                    │ • keywords   │
                    │ • multi_turn │
                    └──────┬───────┘
                           │ No
                           ▼
                      T1 (1 tool)
                      (default)
```

**Architectural Reasons**:
- Cache-first minimizes latency and cost
- Keyword triggers catch complex queries without LLM
- Tool budget prevents runaway agent loops
- Metrics (tier_hit_counter) enable optimization

---

#### 3.2.3 Security Observer
**Location**: `src/app/security/observer.py`

```python
def _detect_signals(payload) -> Dict[str, bool]:
    """Detect security signals in request payload."""
    # Returns booleans for:
    # - jailbreak (35+ patterns via JAILBREAK_PAT)
    # - unicode_obfuscation (normalized != original)
    # - pii (email, phone, SSN, IP)
    # - api_key (token patterns)
    # - pci (card numbers)
    # - prompt_injection (ignore all, override system, etc.)
    # - agentic_tool_abuse (call tool, execute shell, rm -rf)
    # - data_exfiltration (dump secrets, export keys)
    # - deception (via DeceptionDetector)
    # - authority_impersonation
    # - social_engineering

def compute_risk(payload, actor_context) -> Tuple[str, float, float, Dict]:
    """Compute multi-framework risk score."""
    # Frameworks:
    # - MITRE ATLAS: AML.T0043 (prompt injection), AML.T0015 (evasion), AML.T0048 (exfil)
    # - STRIDE: Information Disclosure, Tampering, Elevation of Privilege
    # - DREAD: average of damage, reproducibility, exploitability, affected, discoverability
    # - CVSS v3: LOW/MEDIUM/HIGH/CRITICAL mapping
    # - KEV (Known Exploited Vulnerabilities): CVE matching

    # Risk formula:
    # risk_raw = w_mitre * mitre_score + w_stride * stride_sum +
    #            w_dread * dread_avg + w_cvss * cvss_score + w_kev * kev_weight

    # Insider adjustments:
    # - unusual_hours: +10
    # - mass_approvals: +20
    # - privilege_escalation: +40
    # - admin/superuser role: 1.5x multiplier

    # Severity bands:
    # - info: risk_adj < 20
    # - warn: 20 <= risk_adj < 50
    # - high: 50 <= risk_adj < 80
    # - critical: risk_adj >= 80

def analyze_payload(payload) -> Dict[str, Any]:
    """Main entry point for security analysis."""
    # Returns: {severity, risk_raw, risk_adj, details, sanitized}

def emit_security_event(path, payload, event_time, request):
    """Persist security event to DB and WORM log."""
    # Background thread for non-blocking
    # Auto-routes to incident management if severity high/critical
```

**Thresholds**:
| Threshold | Value | Effect |
|-----------|-------|--------|
| Risk band: info | < 20 | Log only |
| Risk band: warn | 20-50 | Monitor |
| Risk band: high | 50-80 | Alert, potential block |
| Risk band: critical | >= 80 | Block, incident creation |
| Insider unusual_hours | +10 | Risk adjustment |
| Insider mass_approvals | +20 | Risk adjustment |
| Insider privilege_escalation | +40 | Risk adjustment |
| Admin role multiplier | 1.5x | Applied to insider score |

**Architectural Reasons**:
- Read-only: cannot modify payload, only observe
- Multi-framework: defense in depth
- Background persistence: non-blocking
- WORM logging: immutable audit trail

---

#### 3.2.4 Transaction Firewall
**Location**: `src/app/security/firewall.py`

```python
# CONSTANTS
HARD_CAP_DISCOUNT_PERCENT = 30
AUTO_APPROVE_THRESHOLD_CENTS = 25000  # $250
MAX_HOURLY_DISCOUNTS_CENTS = 500000   # $5,000

class TransactionFirewall:
    def check_pricing(cart_total_cents, proposed_discount_percent, actor_context) -> FirewallDecision:
        # Validation checks:
        # 1. cart_total_cents > 0
        # 2. 0 <= discount <= 100
        # 3. discount <= HARD_CAP (30%)

        # Escalation triggers:
        # - cart >= $5000 (MAX_HOURLY) → owner approval
        # - discounted price >= $250 → owner approval
        # - discount >= 25% (near cap) → merchant approval

        # Returns: FirewallDecision(allowed, approval_required, reason, escalation_role)

    def idempotency_ok(key_exists) -> Tuple[bool, str]:
        # Prevents duplicate execution
```

**Decision Matrix**:
| Condition | Allowed | Approval | Escalation |
|-----------|---------|----------|------------|
| Invalid cart | No | Yes | merchant |
| Invalid discount | No | Yes | owner |
| Discount > 30% | No | Yes | owner |
| Cart >= $5000 | Yes | Yes | owner |
| Price >= $250 | Yes | Yes | owner |
| Discount >= 25% | Yes | Yes | merchant |
| Within limits | Yes | No | None |

---

#### 3.2.5 Expanded Rule Engine
**Location**: `src/app/services/expanded_rules.py`

```python
class ExpandedRuleEngine:
    """Intent classification via regex patterns before LLM."""

    intent_patterns = {
        "product_search": [r"show\s+me", r"find", r"search\s+for", r"looking\s+for", r"i\s+need", r"i\s+want"],
        "price_check": [r"how\s+much", r"price\s+of", r"cost", r"pricing"],
        "comparison": [r"compare", r"vs", r"versus", r"difference\s+between", r"which\s+is\s+better"],
        "order_status": [r"where\s+is\s+my\s+order", r"track", r"order\s+status", r"shipping\s+status"],
        "return_request": [r"return", r"refund", r"exchange", r"send\s+back"],
        "support": [r"help", r"support", r"issue", r"problem", r"not\s+working"],
        "stock_check": [r"in\s+stock", r"available", r"how\s+many\s+left", r"stock\s+level"],
        "restock_alert": [r"notify\s+me", r"alert\s+when", r"back\s+in\s+stock", r"restock"],
        "bulk_inquiry": [r"bulk\s+order", r"wholesale", r"large\s+quantity", r"volume\s+discount"],
        "urgent_need": [r"urgent", r"asap", r"need\s+today", r"rush", r"express"],
        "pre_order": [r"pre-order", r"preorder", r"reserve", r"coming\s+soon"],
    }

    def evaluate(query, context) -> Dict[str, Any]:
        # 1. Try tenant-scoped DB rules first
        # 2. Fall back to internal patterns
        # 3. Return: {handled, intent, confidence, rule_id}
```

**Confidence Levels**:
| Match Type | Confidence |
|------------|------------|
| Single DB rule match | 0.95 |
| Multiple DB rules | 0.70 |
| Internal pattern match | 0.90 |
| No match | 0.0 |

---

#### 3.2.6 Inventory Agent
**Location**: `src/app/services/inventory_agent.py`

```python
class InventoryAgent:
    """Stock management with 50 deterministic rules."""

    STOCK_RULES = {
        "R001": {"condition": "stock > 10", "action": "in_stock_message"},
        "R002": {"condition": "1 <= stock <= 10", "action": "limited_stock_message"},
        "R003": {"condition": "stock == 0 and reorder_active", "action": "backorder_message"},
        "R004": {"condition": "stock == 0 and not reorder_active", "action": "unavailable_suggest_alt"},
        # ... R005-R050 covering:
        # - Product status (discontinued, variant_discontinued)
        # - Reservations (reserved_for_orders, reserved_for_b2b, allocated_to_project)
        # - Supply chain (in_transit, supplier_delay, customs_delay, damaged_in_transit)
        # - Quality (high_return_rate, recall_active, mislabelled_batch)
        # - Special handling (hazmat, temperature_sensitive, fragile)
        # - Compliance (restricted_item, authorization_required)
        # - Promotions (promotion_active, flash_sale_only, clearance)
    }

    def evaluate_stock_rule(sku, context) -> Dict[str, Any]:
        # Checks context flags in priority order
        # Returns: {rule_id, action, escalate, response}

    def monitor_stock_levels() -> List[StockAlert]:
        # Query: stock <= reorder_point

    def _get_best_supplier(sku) -> Dict[str, Any]:
        # Weighted scoring:
        # score = w_cost*(1-norm_cost) + w_lead*(1-norm_lead) +
        #         w_on_time*norm_on_time + w_reliability*norm_rel + w_moq*(1-norm_moq)

    def _calculate_eoq(sku, supplier) -> int:
        # EWMA demand smoothing: s_t = alpha * x_t + (1-alpha) * s_{t-1}
        # EOQ = avg_daily * lead_time + safety_stock

    def generate_reorder_recommendations(alerts) -> List[ReorderRecommendation]:
        # Creates recommendations with approval thresholds
        # > $5000 estimated_cost → approval_required

    def execute_reorder(recommendation, approval) -> Dict[str, Any]:
        # Validates approval ticket if cost > $5000
        # Creates purchase_order record
```

**Supplier Scoring Weights**:
| Factor | Weight | Direction |
|--------|--------|-----------|
| Cost | 0.40 | Lower is better |
| Lead time | 0.25 | Shorter is better |
| On-time rate | 0.20 | Higher is better |
| Reliability | 0.10 | Higher is better |
| MOQ | 0.05 | Lower is better |

**EWMA Parameters**:
- `INV_EWMA_DAYS`: 30 (lookback window)
- `INV_EWMA_ALPHA`: 0.3 (smoothing factor)

---

#### 3.2.7 Fraud Scorer
**Location**: `src/app/services/fraud_scorer.py`

```python
class FraudScorer:
    """Fraud risk assessment with weighted signals."""

    WEIGHTS = {
        "image_hash_match_fraud_db": 0.35,
        "exif_date_mismatch": 0.15,
        "stock_photo_detected": 0.25,
        "manipulation_detected": 0.20,
        "high_return_frequency": 0.15,
        "account_age_under_30_days": 0.10,
        "previous_fraud_flag": 0.30,
        "chargeback_history": 0.25,
        "serial_mismatch": 0.40,
        "product_category_mismatch": 0.30,
        "damage_not_visible": 0.20,
        "unusual_purchase_velocity": 0.25,
        "geographic_anomaly": 0.30,
        "device_fingerprint_mismatch": 0.35,
        "session_hijack_indicators": 0.40,
        "return_pattern_abuse": 0.30,
        "coupon_stacking_attempt": 0.20,
        "price_manipulation_attempt": 0.35,
    }

    CV_WEIGHTS = {
        "cv_blur_score_low": 0.15,       # Blur < 0.3
        "cv_histogram_anomaly": 0.20,
        "cv_metadata_stripped": 0.25,
        "cv_timestamp_impossible": 0.30,  # Photo before order
        "cv_duplicate_hash": 0.35,
        "rapid_photo_submission": 0.20,
    }

    def calculate_score(signals) -> float:
        # Weighted sum / max_possible, capped at 1.0

    def get_risk_level(score) -> str:
        # >= 0.7: "high"
        # >= 0.4: "medium"
        # >= 0.2: "low"
        # < 0.2: "minimal"

    def pre_llm_cv_check(image_data) -> Dict[str, bool]:
        # Cheap CV checks before any ML model
        # Checks: blur, histogram, EXIF, timestamp, phash, rapid submission

    def score_with_enrichment(base_signals, expected_serial, observed_serial,
                              image_phash, session_data, case_id) -> Tuple[float, str, Dict]:
        # Full scoring with DB enrichment (fraud_image_hashes table)
```

**Risk Level Thresholds**:
| Score Range | Risk Level |
|-------------|------------|
| >= 0.70 | high |
| 0.40 - 0.69 | medium |
| 0.20 - 0.39 | low |
| < 0.20 | minimal |

---

#### 3.2.8 Recommendation Service
**Location**: `src/app/services/recommendations.py`

```python
class RecommendationService:
    """Product recommendations with NLU + semantic search."""

    # 117 intent phrase categories for semantic matching
    _intent_phrases = {
        "product_discovery_open_ended": ["i need something for", "not sure what to buy", ...],
        "use_case_match": ["gaming laptop", "business laptop", "creative work", ...],
        "gift_recommendation": ["gift", "present", "for my friend", ...],
        # ... 30+ more categories
    }

    def analyze_query(query, prior) -> Dict[str, Any]:
        # 1. Extract price range (budget_min, budget_max)
        # 2. Extract specs (ram_gb_min, storage_gb_min, gpu_class, os)
        # 3. Extract brands (includes, excludes)
        # 4. Detect buyer type (consumer, business, enterprise, government)
        # 5. Infer intents (Tier 1: keyword rules, Tier 2: semantic embeddings)
        # Returns: {intent, intent_confidence, intent_chain, entities, preferences, slots}

    def retrieve_candidates(query, limit) -> List[Dict]:
        # 1. DB full-text search
        # 2. TF-IDF fallback with bigrams
        # 3. Batch stock lookup

    def rerank_candidates_with_factors(candidates, constraints) -> List[Dict]:
        # Scoring factors:
        # +10: in_stock
        # -6: out_of_stock
        # +5: within_budget
        # -5: over_budget
        # +3: brand_match
        # +1.5: spec_match (per spec)
        # +2*sim: embedding_similarity

    def _tfidf_rank(query, products, limit) -> List[Dict]:
        # TF-IDF with bigrams
        # TF: 1 + log(count)
        # IDF: log((1 + N) / (1 + df)) + 1
```

**Reranking Score Weights**:
| Factor | Weight |
|--------|--------|
| In stock | +10 |
| Out of stock | -6 |
| Within budget | +5 |
| Over budget | -5 |
| Brand match | +3 |
| Brand mismatch | -1 |
| Spec match (each) | +1.5 |
| Spec mismatch (each) | -0.5 |
| Embedding similarity | +2 * cosine_sim |

**Semantic Matching Threshold**: 0.35 cosine similarity

---

#### 3.2.9 Token Budget
**Location**: `src/app/services/token_budget.py`

```python
class TokenBudget:
    """Per-user daily token and cost limits."""

    limits = {
        "guest": {
            "daily_tokens": 1_000,
            "daily_usd": 0.10,
        },
        "basic": {
            "daily_tokens": 10_000,
            "daily_usd": 1.00,
        },
        "premium": {
            "daily_tokens": 100_000,
            "daily_usd": 10.00,
        },
        "enterprise": {
            "daily_tokens": 10**12,  # Effectively unlimited
            "daily_usd": 10**9,
        },
    }

    def estimate_tokens(text, response_tokens=500) -> int:
        # base = len(text) // 4 + response_tokens

    def estimate_cost(tokens) -> float:
        # (tokens / 1000) * TOKEN_COST_PER_1K (default: $0.002)

    def check_budget(uid, tier, estimated_tokens) -> Tuple[bool, str, Dict]:
        # Check daily_tokens and daily_usd limits
        # Returns: (allowed, reason, remaining)

    def record_usage(uid, tokens, cost):
        # Atomically increment Redis counters with 24h TTL
```

**Tier Limits**:
| Tier | Daily Tokens | Daily USD |
|------|--------------|-----------|
| guest | 1,000 | $0.10 |
| basic | 10,000 | $1.00 |
| premium | 100,000 | $10.00 |
| enterprise | 10^12 | $10^9 |

---

## 4. Tier Router & Decision Making

### 4.1 Decision Tree

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           TIER ROUTING DECISION TREE                                    │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                              Incoming Request
                                    │
                    ┌───────────────┴───────────────┐
                    │     Security Observer         │
                    │  severity, risk_adj, signals  │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │     Semantic Cache Check      │
                    │  key = SHA256(query+context)  │
                    └───────────────┬───────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │    Cache Hit?         │
                        └───────────┬───────────┘
                              Yes   │   No
                               │    │    │
                    ┌──────────┘    │    └──────────┐
                    │               │               │
                    ▼               │               ▼
            ┌───────────┐          │       ┌───────────────┐
            │  TIER 0   │          │       │ Expanded Rule │
            │ cache_hit │          │       │    Engine     │
            │ 0 tokens  │          │       └───────┬───────┘
            └───────────┘          │               │
                                   │   ┌───────────┴───────────┐
                                   │   │ Rule Match + conf≥0.95│
                                   │   └───────────┬───────────┘
                                   │         Yes   │   No
                                   │          │    │    │
                                   │   ┌──────┘    │    └──────┐
                                   │   │           │           │
                                   │   ▼           │           ▼
                            ┌───────────┐         │    ┌──────────────┐
                            │  TIER 0   │         │    │ T2 Triggers? │
                            │rule_match │         │    └──────┬───────┘
                            │ 0 tokens  │         │           │
                            └───────────┘         │   ┌───────┴───────┐
                                                  │   │ • risk ≥ 0.5  │
                                                  │   │ • amt ≥ $250  │
                                                  │   │ • conf < 0.7  │
                                                  │   │ • keywords    │
                                                  │   │ • multi_turn  │
                                                  │   └───────┬───────┘
                                                  │     Yes   │   No
                                                  │      │    │    │
                                                  │   ┌──┘    │    └──┐
                                                  │   │       │       │
                                                  │   ▼       │       ▼
                                            ┌───────────┐    │   ┌───────────┐
                                            │  TIER 2   │    │   │  TIER 1   │
                                            │interleaved│    │   │ default   │
                                            │ 4 tools   │    │   │ 1 tool    │
                                            └───────────┘    │   └───────────┘
                                                             │
                                                             ▼
                                                  ┌─────────────────────┐
                                                  │ Execute with tier   │
                                                  │ Model selection     │
                                                  │ Token budget check  │
                                                  │ Decision logging    │
                                                  └─────────────────────┘
```

### 4.2 Tier Characteristics

| Tier | Name | Tool Budget | Latency Target | Model | Use Case |
|------|------|-------------|----------------|-------|----------|
| T0 | Cache/Rules | 0 | <50ms | None | Repeated queries, simple intents |
| T1 | Single Pass | 1 | <500ms | llama3:8b | Standard queries |
| T2 | Interleaved | 4 | <2s | mixtral:8x7b | Complex analysis, comparisons |

### 4.3 Trigger Conditions

**T2 Escalation Triggers** (any one triggers T2):
```python
TIER_2_TRIGGERS = {
    "risk_threshold": 0.5,        # Security risk score from observer
    "amount_threshold": 250.0,    # Transaction amount in dollars
    "intent_confidence_low": 0.7, # Below this confidence
    "complexity_keywords": [
        "compare", "tradeoff", "versus", "analyze",
        "explain why", "best option", "recommend"
    ],
    # Also: multi_turn flag in context
}
```

---

## 5. AI/ML Techniques by Agent

### 5.1 Summary Table

| Agent | Technique | Purpose | Pre/Post LLM |
|-------|-----------|---------|--------------|
| **Tier Router** | SHA256 hashing | Cache key generation | Pre-LLM |
| **Security Observer** | Regex patterns (35+) | Jailbreak detection | Pre-LLM |
| **Security Observer** | Unicode normalization | Homograph detection | Pre-LLM |
| **Security Observer** | Multi-framework risk scoring | Threat assessment | Pre-LLM |
| **Expanded Rules** | Regex matching | Intent classification | Pre-LLM |
| **Inventory Agent** | EWMA (Exponential Weighted Moving Average) | Demand smoothing | Pre-LLM |
| **Inventory Agent** | Weighted multi-criteria scoring | Supplier selection | Pre-LLM |
| **Fraud Scorer** | Perceptual hashing (pHash) | Image duplicate detection | Pre-LLM |
| **Fraud Scorer** | Weighted signal scoring | Risk calculation | Pre-LLM |
| **Fraud Scorer** | Behavioral analysis | Session anomaly detection | Pre-LLM |
| **Recommendation** | TF-IDF with bigrams | Candidate retrieval | Pre-LLM |
| **Recommendation** | Cosine similarity | Embedding matching | Pre-LLM |
| **Recommendation** | Multi-factor scoring | Candidate reranking | Pre-LLM |
| **Recommendation** | Semantic embeddings | Intent matching | Pre-LLM |
| **CV Provider** | Google Vision API / Ollama VLM | Label + OCR extraction | Post-LLM |
| **Policy Evaluator** | Simple expression evaluation | Rule compliance | Pre-LLM |
| **Token Budget** | Redis counters + TTL | Usage tracking | Pre-LLM |

### 5.2 Detailed Technique Descriptions

#### 5.2.1 EWMA (Inventory Agent)
```python
# Exponential Weighted Moving Average for demand smoothing
# Formula: s_t = α * x_t + (1-α) * s_{t-1}
# Where: α = 0.3 (smoothing factor), x_t = daily sales

def _calculate_eoq(sku, supplier):
    days = 30  # lookback window
    alpha = 0.3  # smoothing factor

    # Fetch daily sales
    sales = [daily_sales for day in range(days)]

    # EWMA calculation
    s = float(sales[0])
    for x in sales[1:]:
        s = alpha * float(x) + (1.0 - alpha) * s

    avg_daily = max(0.1, s)
    lead_time = supplier["lead_time"]
    safety_stock = max(1, int(avg_daily * 2))

    return max(1, int(avg_daily * lead_time + safety_stock))
```

#### 5.2.2 TF-IDF with Bigrams (Recommendation)
```python
# TF-IDF ranking for product retrieval
# TF weight: 1 + log(term_frequency)
# IDF weight: log((1 + N) / (1 + document_frequency)) + 1

def _tfidf_rank(query, products, limit):
    # Tokenize and create bigrams
    def enrich(tokens):
        bigrams = [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
        return tokens + bigrams

    # Calculate TF-IDF vectors
    def tfidf_vec(tokens):
        tf = Counter(tokens)
        vec = {}
        for t, c in tf.items():
            idf = math.log((1 + n_docs) / (1 + df.get(t, 0))) + 1.0
            tf_weight = 1.0 + math.log(c)
            vec[t] = tf_weight * idf
        return vec

    # Cosine similarity for ranking
    scores = [(cosine(query_vec, doc_vec), product) for product, doc_vec in docs]
    return sorted(scores, reverse=True)[:limit]
```

#### 5.2.3 Multi-Framework Risk Scoring (Security Observer)
```python
# Risk score formula
risk_raw = (
    w_mitre * mitre_score +      # 0.30 weight
    w_stride * stride_sum * 10 + # 0.10 weight
    w_dread * dread_avg * 10 +   # 0.25 weight
    w_cvss * cvss_score * 100 +  # 0.20 weight
    w_kev * kev_weight           # 0.15 weight
)

# Context multiplier (default 1.0)
risk_adj = risk_raw * context_multiplier

# Insider threat adjustments
if actor_context.get("unusual_hours"):
    risk_adj += 10.0
if actor_context.get("mass_approvals"):
    risk_adj += 20.0
if actor_context.get("privilege_escalation"):
    risk_adj += 40.0
if actor_role in ("admin", "superuser"):
    insider_score *= 1.5
```

---

## 6. Thresholds & Weights Reference

### 6.1 Master Threshold Table

| Component | Threshold | Value | Description |
|-----------|-----------|-------|-------------|
| **Tier Router** | | | |
| | risk_threshold | 0.5 | T2 escalation |
| | amount_threshold | $250 | T2 escalation |
| | intent_confidence_low | 0.7 | T2 escalation |
| | T0 confidence required | 0.95 | Rule match confidence |
| **Transaction Firewall** | | | |
| | HARD_CAP_DISCOUNT_PERCENT | 30% | Maximum allowed discount |
| | AUTO_APPROVE_THRESHOLD | $250 | Requires owner approval |
| | MAX_HOURLY_DISCOUNTS | $5,000 | Requires owner approval |
| | Near-cap discount | 25% | Requires merchant approval |
| **Fraud Scorer** | | | |
| | High risk | ≥ 0.70 | Block/review |
| | Medium risk | 0.40-0.69 | Monitor |
| | Low risk | 0.20-0.39 | Log only |
| | Minimal risk | < 0.20 | Pass |
| | CV blur threshold | < 0.30 | Flag as suspicious |
| **Security Observer** | | | |
| | Info severity | < 20 | Log only |
| | Warn severity | 20-50 | Monitor |
| | High severity | 50-80 | Alert |
| | Critical severity | ≥ 80 | Block + incident |
| **Inventory Agent** | | | |
| | Reorder approval | > $5,000 | Requires approval ticket |
| | Variance alert | > 5% | Flag for review |
| | EWMA alpha | 0.3 | Demand smoothing |
| | EWMA days | 30 | Lookback window |
| **Recommendation** | | | |
| | Semantic match | ≥ 0.35 | Intent phrase matching |
| | LLM fallback | confidence < 0.45 | Triggers LLM reranking |
| | Multi-intent | > 3 intents | Triggers LLM |
| | Embedding cache | 256 entries | LRU cache size |
| **Token Budget** | | | |
| | Guest daily | 1,000 tokens / $0.10 | Default tier |
| | Basic daily | 10,000 tokens / $1.00 | Registered users |
| | Premium daily | 100,000 tokens / $10.00 | Paid tier |
| | Token cost | $0.002/1K | Default rate |

### 6.2 Weight Configurations

**Fraud Scorer Signal Weights**:
```python
WEIGHTS = {
    "serial_mismatch": 0.40,              # Highest - definitive fraud signal
    "session_hijack_indicators": 0.40,
    "cv_duplicate_hash": 0.35,
    "device_fingerprint_mismatch": 0.35,
    "image_hash_match_fraud_db": 0.35,
    "price_manipulation_attempt": 0.35,
    "geographic_anomaly": 0.30,
    "previous_fraud_flag": 0.30,
    "product_category_mismatch": 0.30,
    "return_pattern_abuse": 0.30,
    "cv_timestamp_impossible": 0.30,
    "chargeback_history": 0.25,
    "unusual_purchase_velocity": 0.25,
    "stock_photo_detected": 0.25,
    "cv_metadata_stripped": 0.25,
    "manipulation_detected": 0.20,
    "damage_not_visible": 0.20,
    "coupon_stacking_attempt": 0.20,
    "cv_histogram_anomaly": 0.20,
    "rapid_photo_submission": 0.20,
    "high_return_frequency": 0.15,
    "exif_date_mismatch": 0.15,
    "cv_blur_score_low": 0.15,
    "account_age_under_30_days": 0.10,
}
```

**Recommendation Scoring Weights**:
```python
SCORE_WEIGHTS = {
    "in_stock": +10.0,
    "out_of_stock": -6.0,
    "within_budget": +5.0,
    "over_budget": -5.0,
    "brand_match": +3.0,
    "brand_mismatch": -1.0,
    "spec_match": +1.5,    # per spec
    "spec_mismatch": -0.5, # per spec
    "embedding_similarity": 2.0,  # multiplied by cosine_sim
}
```

**Supplier Scoring Weights**:
```python
SUPPLIER_WEIGHTS = {
    "cost": 0.40,        # Lower is better
    "lead_time": 0.25,   # Shorter is better
    "on_time_rate": 0.20, # Higher is better
    "reliability": 0.10,  # Higher is better
    "moq": 0.05,         # Lower is better
}
```

**Security Risk Weights**:
```python
RISK_WEIGHTS = {
    "mitre": 0.30,
    "stride": 0.10,
    "dread": 0.25,
    "cvss": 0.20,
    "kev": 0.15,
}
```

---

## 7. Function Documentation

### 7.1 Function Index by Agent

#### Orchestrator Functions
| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `validate` | `(payload: Dict) -> Tuple[bool, str]` | Validation result | Check required fields |
| `retrieve` | `(uid: str, payload: Dict) -> Dict` | Context | Get memory + live data |
| `reason` | `(ctx: Dict) -> Dict` | Proposal | Generate pricing proposal |
| `rule_based_reason` | `(ctx: Dict) -> Dict` | Proposal | Fallback pricing |
| `choose_model_tier` | `(payload, retrieved, security) -> Dict` | Tier spec | Select model tier |
| `policy` | `(proposal: Dict) -> Dict` | Policy result | Check firewall |
| `execute_or_escalate` | `(uid, proposal, policy, ...) -> bool` | Success | Execute or escalate |
| `run` | `(uid, payload, ...) -> OrchestratorResult` | Full result | Main entry point |

#### Tier Router Functions
| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `route` | `(query, context, intent, security) -> TierDecision` | Tier decision | Determine tier |
| `_compute_cache_key` | `(query: str, context: Dict) -> str` | Cache key | Generate cache key |
| `cache_response` | `(key: str, response: Any, ttl: int)` | None | Store in cache |

#### Security Observer Functions
| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `_detect_signals` | `(payload: Dict) -> Dict[str, bool]` | Signal flags | Detect threats |
| `compute_risk` | `(payload, actor_context) -> Tuple` | Risk tuple | Calculate risk score |
| `analyze_payload` | `(payload: Dict) -> Dict` | Analysis | Main analysis entry |
| `emit_security_event` | `(path, payload, ...)` | None | Persist event |

#### Inventory Agent Functions
| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `evaluate_stock_rule` | `(sku: str, context: Dict) -> Dict` | Rule result | Evaluate stock rules |
| `monitor_stock_levels` | `() -> List[StockAlert]` | Alerts | Get low stock items |
| `_get_best_supplier` | `(sku: str) -> Dict` | Supplier | Select best supplier |
| `_calculate_eoq` | `(sku: str, supplier: Dict) -> int` | Quantity | Calculate reorder qty |
| `generate_reorder_recommendations` | `(alerts) -> List[ReorderRecommendation]` | Recommendations | Generate reorders |
| `execute_reorder` | `(recommendation, approval) -> Dict` | Result | Execute PO |
| `reconcile_stocktake` | `(counted_stock: Dict) -> Dict` | Variances | Reconcile inventory |

#### Fraud Scorer Functions
| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `calculate_score` | `(signals: Dict[str, bool]) -> float` | Score | Calculate fraud score |
| `get_risk_level` | `(score: float) -> str` | Level | Map score to level |
| `pre_llm_cv_check` | `(image_data: Dict) -> Dict[str, bool]` | CV signals | Cheap image checks |
| `score_with_enrichment` | `(...) -> Tuple[float, str, Dict]` | Full result | Score with DB lookup |
| `check_phash` | `(phash: str) -> Tuple` | Phash result | Check fraud DB |
| `serial_mismatch` | `(expected, observed) -> bool` | Match result | Compare serials |

#### Recommendation Functions
| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `analyze_query` | `(query: str, prior: Dict) -> Dict` | Analysis | Parse user query |
| `parse_constraints` | `(query: str) -> Dict` | Constraints | Extract constraints |
| `retrieve_candidates` | `(query: str, limit: int) -> List[Dict]` | Candidates | Get products |
| `rerank_candidates` | `(candidates, constraints) -> List[Dict]` | Ranked list | Rerank products |
| `rerank_candidates_with_factors` | `(candidates, constraints) -> List[Dict]` | Detailed ranking | Rerank with factors |
| `_tfidf_rank` | `(query, products, limit) -> List[Dict]` | Ranked list | TF-IDF ranking |
| `_infer_intents` | `(text, slots) -> Tuple[List, Dict]` | Intents | Detect intents |
| `log_decision` | `(...) -> str` | Decision ID | Persist decision |

#### Token Budget Functions
| Function | Signature | Returns | Purpose |
|----------|-----------|---------|---------|
| `estimate_tokens` | `(text: str, response_tokens: int) -> int` | Token count | Estimate usage |
| `estimate_cost` | `(tokens: int) -> float` | Cost | Calculate cost |
| `check_budget` | `(uid, tier, tokens) -> Tuple[bool, str, Dict]` | Check result | Verify budget |
| `record_usage` | `(uid: str, tokens: int, cost: float)` | None | Record usage |
| `get_remaining` | `(uid: str, tier: str) -> Dict` | Remaining | Get remaining budget |

---

## Appendix A: File Locations

```
src/app/
├── services/
│   ├── orchestrator.py          # Central orchestration (527 lines)
│   ├── tier_router.py           # Tier routing (107 lines)
│   ├── expanded_rules.py        # Intent rules (86 lines)
│   ├── inventory_agent.py       # Stock management (511 lines)
│   ├── fraud_scorer.py          # Fraud detection (193 lines)
│   ├── recommendations.py       # Product recommendations (836 lines)
│   ├── cv_provider.py           # Vision API wrapper (98 lines)
│   ├── policy_evaluator.py      # Rule evaluation (144 lines)
│   ├── token_budget.py          # Usage limits (121 lines)
│   ├── audit_evidence_agent.py  # Compliance checks (269 lines)
│   ├── semantic_search.py       # Semantic caching (74 lines)
│   ├── trust_routing.py         # Confidence routing (34 lines)
│   ├── decision_log.py          # Decision persistence
│   ├── ticketing.py             # Ticket management
│   └── nlp_complaints.py        # Complaint analysis
├── security/
│   ├── observer.py              # Security observer (698 lines)
│   ├── firewall.py              # Transaction firewall (53 lines)
│   ├── auth.py                  # Authentication
│   ├── iam.py                   # Role-based access
│   ├── idempotency.py           # Replay prevention
│   ├── owasp_map.py             # OWASP mapping
│   └── pci.py                   # PCI boundary
└── models/
    ├── decision_audit.py        # Audit models
    ├── decision_trace_events.py # Trace events
    └── event_log.py             # Event logging
```

---

*Document generated: January 2026*
*Platform version: ShopSquire v2.0*
