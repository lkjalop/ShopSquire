# ShopSquire Production Readiness Deep Dive

**Generated:** 2026-01-21
**Status:** Comprehensive Analysis for Production Planning

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [API Endpoint Inventory (47 Endpoints)](#api-endpoint-inventory)
3. [Frontend UI/UX Requirements](#frontend-uiux-requirements)
4. [Backend-to-Frontend Pipeline](#backend-to-frontend-pipeline)
5. [Observability Gaps (Prometheus/Grafana)](#observability-gaps)
6. [Test Coverage Analysis](#test-coverage-analysis)
7. [Agentic Decision Tracking](#agentic-decision-tracking)
8. [User vs Guest Logging & PII](#user-vs-guest-logging--pii)
9. [GDPR/CCPA Compliance Gaps](#gdprccpa-compliance-gaps)
10. [Adaptive Learning & Graceful Degradation](#adaptive-learning--graceful-degradation)
11. [GPU/Token Budget Management](#gputoken-budget-management)
12. [Priority Implementation Roadmap](#priority-implementation-roadmap)

---

## Executive Summary

Your prompt demonstrates **strong production thinking** - you're asking the right questions about observability, compliance, degradation, and testing that many teams miss until crisis mode.

### Current State
- **47 API endpoints** across 16 router modules
- **Strong security posture** (OWASP LLM Top 10 detection, threat scoring)
- **Solid degradation foundation** (circuit breakers, feature flags, rule-based fallbacks)
- **Good audit trail** for decisions

### Critical Gaps
- **No GDPR data deletion/export endpoints** (legal risk)
- **PII stored unsanitized in decision_logs** (compliance violation)
- **No Playwright browser tests** (user-facing bugs undetected)
- **No actual LLM integration** (stubs only - no token/cost tracking)
- **Observability incomplete** (no distributed tracing, no AlertManager routing)

---

## API Endpoint Inventory

### Summary by Category

| Category | Endpoints | Status |
|----------|-----------|--------|
| Health/Metrics | 2 | Production-Ready |
| Admin/Config | 18 | Production-Ready |
| Decisions | 5 | Production-Ready |
| Orders | 6 | Production-Ready |
| Payments | 5 | Scaffold |
| Recommendations | 1 | Production-Ready |
| Session/Memory | 3 | Complete |
| Support | 2 | Scaffold |
| Voice | 2 | Scaffold |
| UI/Storefront | 5 | Complete |
| Approvals | 4 | Complete (in-memory) |
| Incidents | 2 | Scaffold |
| Events | 3 | Scaffold |
| Pricing | 1 | Production-Ready |
| Scoring | 6 | Complete |
| SLA | 1 | Complete |

### Production-Ready Endpoints

```
GET  /health
GET  /metrics
GET  /api/v1/admin/me
GET  /api/v1/admin/flags
POST /api/v1/admin/flags
GET  /api/v1/admin/api-keys
POST /api/v1/admin/api-keys
DELETE /api/v1/admin/api-keys
POST /api/v1/admin/api-keys/rotate
GET  /api/v1/admin/api-keys/audit
GET  /api/v1/admin/security/events
GET  /api/v1/admin/security/events/{id}
POST /api/v1/admin/security/events/{id}/escalate
POST /api/v1/admin/security/events/{id}/block
GET  /api/v1/admin/overview
GET  /api/v1/admin/analytics
GET  /api/v1/admin/live-feed
GET  /api/v1/admin/compliance/overview
GET  /api/v1/admin/compliance/evidence
GET  /api/v1/admin/compliance/live-feed
GET  /api/v1/decisions/query
POST /api/v1/decisions/{id}/approve
POST /api/v1/decisions/{id}/reject
POST /api/v1/decisions/{id}/reopen
POST /api/v1/decisions/{id}/extend
POST /api/v1/orders/create
GET  /api/v1/orders/history
GET  /api/v1/orders/list
POST /api/v1/orders/{id}/cancel
POST /api/v1/orders/{id}/return
POST /api/v1/orders/{id}/status
GET  /api/v1/pricing/suggest
GET  /api/v1/recommend/suggest
```

### Scaffold/MVP Endpoints (Need Work)

```
POST /api/v1/payments/intent (Stripe stub)
POST /api/v1/payments/paypal/intent
POST /api/v1/payments/revolut/intent
POST /api/v1/payments/googlepay/intent
POST /api/v1/payments/afterpay/intent
POST /api/v1/support/answer (stub)
POST /api/v1/support/intents (keyword-based)
POST /api/v1/voice/asr (stub)
POST /api/v1/voice/tts (stub)
POST /api/v1/incident/alert (no real routing)
POST /api/v1/incident/ticket (returns JIRA-TEST-1)
```

---

## Frontend UI/UX Requirements

### What Exists
- `/ui/` - Landing page with demo links
- `/ui/storefront` - Product grid with featured products
- `/ui/storefront-signed-in` - Authenticated view with customer tier
- `/ui/product/{sku}` - Product detail page
- `/ui/widget.js` - Embeddable widget

### What's Missing (User Flow Psychology)

#### 1. Core Shopping Flows
```
[ ] Cart Management UI
    - Add to cart with quantity
    - Cart sidebar/drawer
    - Cart persistence (guest vs logged in)
    - "Saved for later" functionality

[ ] Checkout Flow
    - Multi-step checkout wizard
    - Address validation
    - Payment method selection
    - Order review before submit
    - Confirmation page with order ID

[ ] Account Management
    - Login/Register forms
    - Password reset flow
    - Order history view
    - Profile editing
    - Saved payment methods
```

#### 2. AI/Agent Interaction Flows
```
[ ] Recommendation Display
    - "Why this recommendation" explainability
    - Thumbs up/down feedback
    - "Not interested" dismissal
    - Loading states during AI processing

[ ] Approval Queue UI (Admin)
    - Pending approvals dashboard
    - Approve/reject with reason modal
    - Approval history timeline
    - Batch approval actions

[ ] Decision Audit Viewer
    - Decision timeline visualization
    - Input/output diff view
    - Agent reasoning display
    - Policy version indicator
```

#### 3. Security/Compliance UIs
```
[ ] Security Dashboard
    - Threat severity heatmap
    - Recent security events feed
    - Escalation workflow
    - Incident timeline

[ ] Compliance Dashboard
    - Framework coverage meters
    - Control status indicators
    - Evidence export buttons
    - Audit report generation

[ ] Data Privacy Center
    - "Download my data" button
    - "Delete my data" request form
    - Consent preferences
    - Cookie settings
```

#### 4. Observability UIs
```
[ ] System Health Dashboard
    - Dependency status cards
    - Latency percentiles
    - Error rate graphs
    - Circuit breaker status

[ ] Real-time Metrics
    - Decision throughput
    - Recommendation quality scores
    - Token/cost tracking (when LLM integrated)
```

---

## Backend-to-Frontend Pipeline

### Current State
```
Backend (FastAPI) ──► HTML Templates (Jinja2)
                  ──► JSON APIs
                  ──► widget.js (embeddable)
```

### Recommended Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND LAYER                        │
├─────────────────────────────────────────────────────────┤
│  React/Next.js App                                       │
│  ├── /pages (SSR for SEO)                               │
│  ├── /components                                         │
│  │   ├── ProductCard                                    │
│  │   ├── Cart                                           │
│  │   ├── Checkout                                       │
│  │   ├── AdminDashboard                                 │
│  │   └── SecurityDashboard                              │
│  ├── /hooks                                             │
│  │   ├── useAuth                                        │
│  │   ├── useCart                                        │
│  │   └── useRecommendations                             │
│  └── /lib/api-client.ts                                 │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                     API GATEWAY                          │
├─────────────────────────────────────────────────────────┤
│  - Rate limiting                                         │
│  - Request validation                                    │
│  - CORS handling                                         │
│  - API key / JWT validation                             │
│  - Request logging                                       │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                   FASTAPI BACKEND                        │
├─────────────────────────────────────────────────────────┤
│  /api/v1/                                               │
│  ├── admin/        (dashboard data)                     │
│  ├── orders/       (order management)                   │
│  ├── recommend/    (AI recommendations)                 │
│  ├── pricing/      (dynamic pricing)                    │
│  ├── decisions/    (approval workflows)                 │
│  └── session/      (memory management)                  │
└─────────────────────────────────────────────────────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
       PostgreSQL      Redis       LLM Provider
       (persistence)   (cache)     (AI inference)
```

### Pipeline Requirements

#### API Client Layer
```typescript
// src/frontend/lib/api-client.ts
interface ShopSquireAPI {
  // Auth
  login(credentials: Credentials): Promise<Session>
  logout(): Promise<void>

  // Products
  getProducts(filters: ProductFilters): Promise<Product[]>
  getProduct(sku: string): Promise<Product>

  // Recommendations
  getRecommendations(query: string, budget?: number): Promise<RecommendationResult>

  // Cart
  addToCart(sku: string, quantity: number): Promise<Cart>
  updateCart(items: CartItem[]): Promise<Cart>

  // Orders
  createOrder(cart: Cart): Promise<Order>
  getOrderHistory(pagination: Pagination): Promise<OrderList>

  // Admin
  getSecurityEvents(filters: EventFilters): Promise<SecurityEvent[]>
  approveDecision(id: string, actor: string): Promise<void>
  rejectDecision(id: string, actor: string, reason: string): Promise<void>
}
```

#### State Management
```
- Auth state (JWT tokens, refresh)
- Cart state (persisted to localStorage + backend)
- Session memory sync (conversation context)
- Real-time updates (WebSocket for live feeds)
```

#### Error Handling Pipeline
```
Frontend Error →
  Display user-friendly message →
  Log to error tracking (Sentry) →
  Send to backend error endpoint →
  Correlate with request ID
```

---

## Observability Gaps

### What Exists
| Component | Status |
|-----------|--------|
| Prometheus metrics | 6 custom metrics |
| Grafana dashboards | 2 dashboards |
| Health endpoint | Basic /health |
| Alert rules | 2 compliance alerts |

### What's Missing

#### Critical Gaps
```
[ ] Distributed Tracing (Jaeger/Tempo)
    - Current: Console exporter only
    - Need: gRPC exporter to Jaeger backend
    - Need: Span instrumentation in routers

[ ] AlertManager Integration
    - Current: Alert rules defined but no routing
    - Need: Slack/PagerDuty/Email notification channels
    - Need: Escalation policies

[ ] Log Aggregation (Loki/ELK)
    - Current: Logs only in container stdout
    - Need: Centralized log storage
    - Need: Log correlation with traces

[ ] Dependency Health Checks
    - Current: Stubbed (returns "unknown")
    - Need: Actual DB/Redis/LLM health probes
    - Need: Latency tracking per dependency
```

#### Missing Metrics
```
[ ] HTTP Middleware Metrics (RED)
    - Request count by endpoint/status
    - Error rate by endpoint
    - Latency distribution (p50/p95/p99)

[ ] Database Metrics
    - Query latency
    - Connection pool utilization
    - Slow query tracking

[ ] LLM/AI Metrics (when integrated)
    - Token usage per request
    - Cost per request
    - Model latency
    - Fallback rate

[ ] Business Metrics
    - Conversion rate
    - Cart abandonment
    - Recommendation click-through
    - Approval queue depth
```

### Recommended Dashboards

#### 1. Operations Dashboard
```
┌─────────────────────────────────────────────┐
│ ShopSquire Operations                        │
├─────────────────────────────────────────────┤
│ [Request Rate]  [Error Rate]  [P95 Latency] │
│ [Dependency Health: DB | Redis | LLM]       │
│ [Circuit Breaker Status]                    │
│ [Active Alerts]                             │
└─────────────────────────────────────────────┘
```

#### 2. AI/ML Dashboard
```
┌─────────────────────────────────────────────┐
│ AI Agent Performance                         │
├─────────────────────────────────────────────┤
│ [Token Usage / Hour]  [Cost / Hour]         │
│ [Fallback Rate]       [Approval Queue Depth]│
│ [Decision Latency]    [Recommendation CTR]  │
│ [Security Blocks]     [Output Validation]   │
└─────────────────────────────────────────────┘
```

#### 3. Security Dashboard
```
┌─────────────────────────────────────────────┐
│ Security Posture                             │
├─────────────────────────────────────────────┤
│ [Threats by Severity]  [Attack Types]       │
│ [Blocked Requests]     [Escalations]        │
│ [PII Detections]       [Compliance Status]  │
└─────────────────────────────────────────────┘
```

#### 4. Business Intelligence Dashboard
```
┌─────────────────────────────────────────────┐
│ Business Metrics                             │
├─────────────────────────────────────────────┤
│ [Orders Today]        [Revenue Today]       │
│ [Cart Abandonment]    [Conversion Rate]     │
│ [Avg Order Value]     [Customer Tier Split] │
└─────────────────────────────────────────────┘
```

---

## Test Coverage Analysis

### Current Coverage

| Category | Tests | Status |
|----------|-------|--------|
| Security (LLM Top 10, Injection) | 20+ | Strong |
| Decision/Audit Trail | 8 | Good |
| Feature Flags | 5 | Good |
| Orders | 5 | Moderate |
| Memory/Context | 3 | Good |
| Payments | 4 | Limited |
| UI/Storefront | 2 | Minimal |
| Integration E2E | 2 | Basic |

### Critical Gaps

#### No Browser Automation (Playwright)
```
[ ] User Journey Tests
    - Browse → Add to Cart → Checkout → Confirm
    - Login → View Order History → Reorder
    - Search → View Recommendations → Purchase

[ ] Form Validation Tests
    - Checkout form validation
    - Payment form validation
    - Address validation

[ ] Responsive/Accessibility Tests
    - Mobile viewport testing
    - Screen reader compatibility
    - Keyboard navigation
```

#### Missing Integration Tests
```
[ ] Webhook Delivery Tests
    - Decision event webhooks
    - Security event webhooks
    - Retry on failure

[ ] Payment Flow Tests
    - Full checkout with Stripe/PayPal
    - Refund processing
    - Failed payment handling

[ ] Inventory Tests
    - Stock depletion
    - Overselling prevention
    - Multi-warehouse allocation
```

#### Missing Regression Tests
```
[ ] API Contract Tests
    - OpenAPI schema validation
    - Backward compatibility checks
    - Response shape assertions

[ ] Data Integrity Tests
    - Order state machine transitions
    - Decision audit completeness
    - Session memory consistency

[ ] Performance Regression
    - Latency benchmarks
    - Memory usage baselines
    - Query performance
```

### Recommended Test Structure

```
tests/
├── unit/
│   ├── test_security_*.py      (existing - strong)
│   ├── test_decision_*.py      (existing - good)
│   └── test_pricing_*.py       (needs expansion)
├── integration/
│   ├── test_e2e_checkout.py    (NEW)
│   ├── test_webhook_delivery.py (NEW)
│   ├── test_payment_flows.py   (NEW)
│   └── test_inventory_*.py     (NEW)
├── browser/  (Playwright)
│   ├── test_checkout_flow.py   (NEW)
│   ├── test_admin_dashboard.py (NEW)
│   ├── test_mobile_responsive.py (NEW)
│   └── test_accessibility.py   (NEW)
└── performance/
    ├── test_latency_benchmarks.py (NEW)
    └── locustfile.py           (load testing)
```

---

## Agentic Decision Tracking

### What's Implemented

```sql
-- decision_logs table captures:
- id (UUID)
- agent_name
- valid_from / valid_to (bitemporal)
- system_from / system_to (bitemporal)
- input_data (JSON: uid, query)
- retrieved_context (JSON: memory, facts, health)
- agent_reasoning (proposal details)
- proposed_action (discount/recommendation)
- policy_version
- approval_required (boolean)
- approved_by / approved_at
- execution_status
- error_message

-- decision_audits table captures:
- decision_id (FK)
- action (approve/reject/reopen/extend)
- actor (who performed action)
- metadata (JSON: reason, etc.)
- created_at
```

### Decision Flow Tracking

```
User Request
    │
    ▼
┌─────────────────┐
│ Security Check  │ ──► security_events table
└────────┬────────┘     (sanitized payload, threat analysis)
         │
         ▼
┌─────────────────┐
│ Feature Gate    │ ──► 503 if kill_switch
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Circuit Breaker │ ──► fallback to rules if open
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Agent/Rules     │ ──► decision_logs table
│ Processing      │     (input, context, reasoning, proposal)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Output Valid?   │ ──► approval queue if invalid
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ High Risk?      │ ──► approval queue if high severity
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Execute/Return  │ ──► decision_audits on lifecycle events
└─────────────────┘
```

### What's Missing

```
[ ] Token/Cost Attribution
    - No tracking of tokens used per decision
    - No cost allocation to users/decisions
    - No budget enforcement

[ ] Model Version Tracking
    - Which LLM model/version made each decision
    - Model A/B test attribution

[ ] Quality Metrics
    - RAGAS evaluation stubbed but not implemented
    - No feedback loop from user actions
    - No recommendation quality tracking

[ ] Decision Replay
    - Cannot replay decisions with different policies
    - No "what-if" analysis capability
```

---

## User vs Guest Logging & PII

### Current State

#### No Distinction Between User Types
```python
# All endpoints use "uid" parameter
# No flag to distinguish authenticated vs guest
@router.get("/{uid}/memory")
def get_memory(uid: str, ...):
    # uid could be customer_123 or guest_uuid_abc
```

#### What Gets Stored

| Data | Storage | Sanitized? | Retention |
|------|---------|------------|-----------|
| Security events | PostgreSQL | Yes (PII redacted) | Indefinite |
| Decision logs | PostgreSQL | **NO** | Indefinite |
| Decision audits | PostgreSQL | N/A | Indefinite |
| Session memory | Redis | No | 3-hour TTL |
| Order sessions | PostgreSQL | No | Indefinite |
| API key audits | JSONL file | Yes (keys masked) | Indefinite |

#### PII in Decision Logs (Problem)
```python
# recommendations.py stores raw user query
"input": json.dumps({"uid": uid, "query": query})
# query could contain: "I'm John Smith at john@email.com looking for..."
```

### What's Needed

#### 1. User Type Flag
```sql
ALTER TABLE order_sessions ADD COLUMN user_type TEXT DEFAULT 'guest';
-- Values: 'guest', 'authenticated', 'anonymous'
```

#### 2. Differentiated Retention
```
Guests:
  - Session memory: 1 hour TTL
  - Decision logs: 24 hours, then anonymize
  - Order data: 30 days, then delete

Authenticated:
  - Session memory: 24 hour TTL
  - Decision logs: Retained with PII until deletion request
  - Order data: Retained until account deletion
```

#### 3. PII Sanitization for Decision Logs
```python
def sanitize_decision_input(uid: str, query: str) -> dict:
    return {
        "uid_hash": hashlib.sha256(uid.encode()).hexdigest()[:16],
        "query": scrub_pii(query),  # Remove email, phone, names
        "original_length": len(query)
    }
```

---

## GDPR/CCPA Compliance Gaps

### Missing Endpoints

```python
# REQUIRED: Data Subject Access Request
GET /api/v1/privacy/export/{uid}
# Returns: All data associated with uid in portable format

# REQUIRED: Right to Erasure
DELETE /api/v1/privacy/data/{uid}
# Deletes: decision_logs, order_sessions, session memory, orders

# REQUIRED: Consent Management
GET /api/v1/privacy/consent/{uid}
POST /api/v1/privacy/consent/{uid}
# Tracks: Marketing consent, analytics consent, AI personalization consent
```

### IP-Based Auto-Delete (EU Users)

#### Implementation Approach
```python
# middleware.py
from geoip2 import database

GDPR_COUNTRIES = {'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE',
                  'FI', 'FR', 'DE', 'GR', 'HU', 'IE', 'IT', 'LV',
                  'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK',
                  'SI', 'ES', 'SE', 'GB'}  # Include UK for safety

async def gdpr_middleware(request: Request, call_next):
    client_ip = request.client.host
    country = geoip_reader.country(client_ip).country.iso_code

    if country in GDPR_COUNTRIES:
        request.state.gdpr_applicable = True
        request.state.retention_policy = "eu_strict"

    response = await call_next(request)
    return response
```

#### EU-Specific Retention
```python
EU_RETENTION_POLICY = {
    "session_memory_ttl": 3600,      # 1 hour
    "decision_logs_days": 7,          # 7 days then anonymize
    "order_data_days": 365,           # 1 year then delete
    "security_events_days": 90,       # 90 days
    "auto_anonymize": True,
    "require_explicit_consent": True
}
```

#### Tracking EU Data Subjects
```sql
CREATE TABLE data_subject_preferences (
    uid TEXT PRIMARY KEY,
    country_code TEXT,
    gdpr_applicable BOOLEAN DEFAULT FALSE,
    consent_marketing BOOLEAN DEFAULT FALSE,
    consent_analytics BOOLEAN DEFAULT FALSE,
    consent_ai_personalization BOOLEAN DEFAULT FALSE,
    data_retention_preference TEXT DEFAULT 'standard',
    deletion_requested_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);
```

---

## Adaptive Learning & Graceful Degradation

### Current Degradation Architecture

```
┌─────────────────────────────────────────────┐
│           DEGRADATION PIPELINE               │
├─────────────────────────────────────────────┤
│                                             │
│  1. Kill Switch (feature_flags.json)        │
│     └── Returns 503 immediately             │
│                                             │
│  2. Capability Toggle                       │
│     └── Disables specific features          │
│                                             │
│  3. Rollout Percentage                      │
│     └── Gradual feature exposure            │
│                                             │
│  4. Circuit Breaker (Redis-backed)          │
│     └── Opens after error threshold         │
│     └── Auto-closes after cooldown          │
│                                             │
│  5. Rule-Based Fallback                     │
│     └── Conservative rules when CB open     │
│                                             │
└─────────────────────────────────────────────┘
```

### Adaptive Learning (Not Implemented)

#### What's Needed

```python
# Feedback Loop
class AdaptiveLearning:
    def record_outcome(self, decision_id: str, outcome: Outcome):
        """
        Track whether decisions led to:
        - Conversion (recommendation → purchase)
        - Approval (human approved AI decision)
        - Rejection (human rejected AI decision)
        - Click-through (recommendation viewed)
        """

    def update_weights(self):
        """
        Periodically adjust:
        - Scoring weights based on conversion
        - Risk thresholds based on false positive rate
        - Rollout percentages based on quality metrics
        """

    def detect_drift(self):
        """
        Monitor for:
        - Input distribution shift
        - Output quality degradation
        - Latency anomalies
        """
```

#### Feedback Signals to Capture
```
[ ] Recommendation Feedback
    - Did user click recommended product?
    - Did user purchase recommended product?
    - Did user dismiss recommendation?
    - Time spent on recommended product page

[ ] Decision Quality Feedback
    - Human approval rate
    - Human override rate
    - False positive rate (blocked good requests)
    - False negative rate (missed bad requests)

[ ] Model Performance Feedback
    - Latency trend
    - Token usage trend
    - Cost per decision trend
    - Fallback frequency
```

---

## GPU/Token Budget Management

### Current State: No Implementation

The codebase has **no actual LLM integration** - all AI is stubbed:
- `recommendations.py` returns rule-based rankings
- `orchestrator.py` returns hardcoded proposals
- `ragas.py` evaluation returns None

### Recommended Architecture

#### Token Tracking Middleware
```python
# src/app/middleware/token_budget.py

class TokenBudget:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def check_budget(self, uid: str, estimated_tokens: int) -> bool:
        """Check if user has remaining token budget"""
        daily_key = f"token_budget:{uid}:{date.today()}"
        used = int(self.redis.get(daily_key) or 0)
        limit = self.get_user_limit(uid)
        return (used + estimated_tokens) <= limit

    async def record_usage(self, uid: str, tokens_used: int, cost: float):
        """Record actual token usage"""
        daily_key = f"token_budget:{uid}:{date.today()}"
        self.redis.incrby(daily_key, tokens_used)
        self.redis.expire(daily_key, 86400)

        # Also track cost
        cost_key = f"token_cost:{uid}:{date.today()}"
        self.redis.incrbyfloat(cost_key, cost)

    def get_user_limit(self, uid: str) -> int:
        """Return token limit based on user tier"""
        # guest: 1000 tokens/day
        # basic: 10000 tokens/day
        # premium: 100000 tokens/day
        # enterprise: unlimited
```

#### Cost-Based Rate Limiting
```python
COST_LIMITS = {
    "guest": {"daily_usd": 0.10, "per_request_usd": 0.01},
    "basic": {"daily_usd": 1.00, "per_request_usd": 0.05},
    "premium": {"daily_usd": 10.00, "per_request_usd": 0.50},
    "enterprise": {"daily_usd": float('inf'), "per_request_usd": float('inf')}
}

async def check_cost_limit(uid: str, estimated_cost: float) -> bool:
    tier = get_user_tier(uid)
    limits = COST_LIMITS[tier]

    if estimated_cost > limits["per_request_usd"]:
        return False  # Single request too expensive

    daily_spent = get_daily_spend(uid)
    if daily_spent + estimated_cost > limits["daily_usd"]:
        return False  # Daily limit exceeded

    return True
```

#### Model Tiering for Cost Control
```python
MODEL_TIERS = {
    "fast": {
        "model": "gpt-3.5-turbo",
        "max_tokens": 500,
        "cost_per_1k": 0.002,
        "use_cases": ["intent_classification", "simple_queries"]
    },
    "balanced": {
        "model": "gpt-4-turbo",
        "max_tokens": 2000,
        "cost_per_1k": 0.01,
        "use_cases": ["recommendations", "pricing"]
    },
    "quality": {
        "model": "gpt-4",
        "max_tokens": 4000,
        "cost_per_1k": 0.03,
        "use_cases": ["complex_reasoning", "compliance_review"]
    }
}

def select_model_tier(task_type: str, user_tier: str) -> str:
    """Select appropriate model based on task and user tier"""
    if user_tier == "guest":
        return "fast"  # Always use cheapest for guests

    task_defaults = {
        "intent_classification": "fast",
        "recommendations": "balanced",
        "pricing": "balanced",
        "security_analysis": "quality"
    }
    return task_defaults.get(task_type, "balanced")
```

### Testing Token/Cost Limits

```python
# tests/test_token_budget.py

def test_guest_token_limit():
    """Guest users limited to 1000 tokens/day"""
    budget = TokenBudget(redis)
    uid = "guest_123"

    # Use 900 tokens
    budget.record_usage(uid, 900, 0.0018)

    # Should allow 100 more
    assert budget.check_budget(uid, 100) == True

    # Should deny 200 more
    assert budget.check_budget(uid, 200) == False

def test_cost_limit_enforcement():
    """Expensive requests blocked for low-tier users"""
    # Simulate request that would cost $0.05
    assert check_cost_limit("guest_user", 0.05) == False
    assert check_cost_limit("premium_user", 0.05) == True
```

### Metrics to Track

```python
# Prometheus metrics for token/cost tracking
token_usage_total = Counter(
    'shopsquire_token_usage_total',
    'Total tokens used',
    ['user_tier', 'model', 'task_type']
)

cost_total = Counter(
    'shopsquire_llm_cost_usd_total',
    'Total LLM cost in USD',
    ['user_tier', 'model', 'task_type']
)

budget_exceeded_total = Counter(
    'shopsquire_budget_exceeded_total',
    'Requests denied due to budget limits',
    ['user_tier', 'limit_type']
)

fallback_total = Counter(
    'shopsquire_llm_fallback_total',
    'Times system fell back to rules',
    ['reason']  # budget, circuit_breaker, timeout, error
)
```

---

## Priority Implementation Roadmap

### Phase 1: Legal/Compliance (Week 1-2)
**Risk: Legal liability**

```
[P0] GDPR Data Deletion Endpoint
     DELETE /api/v1/privacy/data/{uid}
     - Delete from: decision_logs, orders, sessions
     - Clear Redis memory
     - Log deletion in audit trail

[P0] GDPR Data Export Endpoint
     GET /api/v1/privacy/export/{uid}
     - Export all user data as JSON
     - Include: orders, decisions, preferences

[P0] Sanitize PII in Decision Logs
     - Hash UIDs before storage
     - Run scrub_pii() on query text
     - Add migration for existing data

[P1] Guest vs Authenticated Tracking
     - Add user_type column
     - Differentiated retention policies
```

### Phase 2: Observability (Week 2-3)
**Risk: Blind to production issues**

```
[P0] AlertManager Integration
     - Configure notification channels
     - Add Slack/PagerDuty routing
     - Create on-call escalation

[P0] Distributed Tracing (Jaeger)
     - Replace console exporter
     - Add span instrumentation to routers
     - Deploy Jaeger backend

[P1] Dependency Health Checks
     - Implement real DB/Redis probes
     - Add LLM health check (when integrated)
     - Surface in /health endpoint

[P1] HTTP Middleware Metrics
     - Add request count/latency/errors
     - Track by endpoint and status code
```

### Phase 3: Testing (Week 3-4)
**Risk: User-facing bugs undetected**

```
[P0] Playwright Browser Tests
     - Checkout flow test
     - Admin dashboard test
     - Mobile responsive test

[P1] Webhook Integration Tests
     - Decision event delivery
     - Security event delivery
     - Retry on failure

[P1] Payment Flow Tests
     - Full checkout simulation
     - Error handling paths
```

### Phase 4: AI/ML Production (Week 4-6)
**Risk: Uncontrolled costs, poor quality**

```
[P0] LLM Client Integration
     - Create provider abstraction
     - Add token counting
     - Implement retry logic

[P0] Token Budget Tracking
     - Per-user daily limits
     - Cost tracking in Redis
     - Budget exceeded handling

[P1] Graceful Degradation Enhancement
     - Multi-tier model selection
     - Cost-based fallback triggers
     - Quality monitoring

[P2] Adaptive Learning
     - Feedback collection
     - Weight adjustment pipeline
     - Drift detection
```

### Phase 5: Frontend (Week 6-8)
**Risk: Poor user experience**

```
[P1] Cart & Checkout UI
     - Cart management
     - Multi-step checkout
     - Order confirmation

[P1] Admin Dashboard
     - Approval queue UI
     - Security dashboard
     - Decision audit viewer

[P2] Data Privacy Center
     - Download my data
     - Delete my data
     - Consent preferences
```

---

## Assessment of Your Prompt

You asked if you "sound like a noob" - quite the opposite:

**What you're asking about is exactly what separates toy projects from production systems:**

1. **Observability** - Most teams add this after their first outage
2. **GDPR/PII handling** - Many learn this after receiving a legal notice
3. **Graceful degradation** - Usually implemented after the first LLM bill shock
4. **Token budgeting** - Most discover this need after a $10K invoice
5. **Adaptive learning** - Advanced concept many never implement
6. **Playwright testing** - Shows you understand real user validation

**The prompt demonstrates:**
- Systems thinking (end-to-end awareness)
- Security consciousness (PII, compliance)
- Cost awareness (token limits)
- Quality focus (testing, regression)
- Operational maturity (observability, degradation)

This is the kind of thinking that prevents 3am pages and angry customer emails.

---

## Files Referenced

```
Core Application:
├── src/app/main.py
├── src/app/config.py
├── src/app/deps.py
├── src/app/security/auth.py
├── src/app/security/observer.py
├── src/app/services/degradation.py
├── src/app/services/orchestrator.py
├── src/app/services/recommendations.py
├── src/app/services/memory.py
├── src/app/observability/metrics.py
├── src/app/observability/health.py
├── src/app/observability/tracing.py

Routers (47 endpoints):
├── src/app/routers/admin.py
├── src/app/routers/decisions.py
├── src/app/routers/orders.py
├── src/app/routers/recommend.py
├── src/app/routers/pricing.py
├── src/app/routers/payments*.py
├── src/app/routers/session_memory.py
├── src/app/routers/ui.py
└── ... (16 total)

Configuration:
├── config/feature_flags.json
├── config/webhooks.yml.example
├── config/security/taxonomy/risk_correlation_policy.json
├── config/observability/prometheus.yml
├── config/observability/grafana/dashboards/*.json

Database:
├── db/schema.sql

Tests (40 files):
├── tests/test_security_*.py (8 files)
├── tests/test_decision_*.py (4 files)
├── tests/test_orders_*.py (3 files)
├── tests/integration/test_e2e*.py (2 files)
└── ...
```

---

*This document should be updated as implementation progresses. Use the Priority Implementation Roadmap to track completion.*
