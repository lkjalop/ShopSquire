# ShopSquire Technical Deep Dive

**Generated:** 2026-01-25
**Status:** 7-Day Sprint Complete - Production-MVP Architecture
**Codebase:** 18,406 LOC Python | 92 Test Files | 155 API Endpoints

---

## Table of Contents

1. [Progress Summary](#1-progress-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Services Deep Dive](#3-services-deep-dive)
4. [Security Implementation](#4-security-implementation)
5. [NLP & Computer Vision](#5-nlp--computer-vision)
6. [Admin Dashboard & PowerBI Integration](#6-admin-dashboard--powerbi-integration)
7. [Database Strategy](#7-database-strategy)
8. [Enterprise Integration Considerations](#8-enterprise-integration-considerations)
9. [Supply Chain Security](#9-supply-chain-security)
10. [Gaps & Improvement Roadmap](#10-gaps--improvement-roadmap)

---

## 1. Progress Summary

### 7-Day Build Statistics

| Metric | Count |
|--------|-------|
| **Total Python Modules** | 108 |
| **Lines of Code** | 18,406 |
| **API Endpoints** | 155 |
| **Test Files** | 92 |
| **Services** | 36 |
| **Security Modules** | 12 |
| **Routers** | 37 |

### Component Breakdown

```
src/app/
├── services/      36 modules   4,239 LOC   Core business logic
├── routers/       37 modules   9,707 LOC   API endpoints
├── security/      12 modules   1,867 LOC   Threat detection & access control
├── models/         6 modules     500 LOC   ORM & schemas
├── observability/  4 modules     450 LOC   Metrics & tracing
└── main.py         1 file        800 LOC   App bootstrap

frontend/
└── src/            7 files       454 LOC   React storefront

tests/
└── **/            92 files     3,780 LOC   Comprehensive test suite
```

### What's Production-Ready

| Component | Status | Notes |
|-----------|--------|-------|
| E-Commerce Core | ✅ Production | Orders, cart, products, inventory |
| Payment Integrations | ✅ Production | Stripe, PayPal, Revolut, Google Pay, Afterpay |
| Security Observer | ✅ Production | 9/10 OWASP LLM Top 10, MITRE ATLAS |
| Decision Logging | ✅ Production | Bi-temporal audit trail |
| API Rate Limiting | ✅ Production | IP-based, configurable thresholds |
| Webhook Security | ✅ Production | HMAC validation, replay protection |
| Observability | ✅ Production | Prometheus, Grafana, Jaeger, Loki |

### What's MVP/Partial

| Component | Status | Notes |
|-----------|--------|-------|
| LLM Integration | 🟡 MVP | Ollama working, cloud APIs configurable |
| Computer Vision | 🟡 MVP | LLaVA integration, evidence collection stub |
| NLP Complaints | 🟡 MVP | Classification working, BEC detection |
| Graph Context | 🟡 MVP | Schema defined, Neo4j optional |
| Frontend | 🟡 MVP | React dashboard functional |

---

## 2. Architecture Overview

### Core Decision Flow (5-Stage Orchestrator)

```
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR PIPELINE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  REQUEST                                                         │
│     │                                                            │
│     ▼                                                            │
│  ┌──────────────────┐                                           │
│  │ 1. VALIDATE      │ ← Input sanitization, PII masking         │
│  │                  │   Unicode normalization, schema check      │
│  └────────┬─────────┘                                           │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                           │
│  │ 2. RETRIEVE      │ ← CacheRAG memory, DB context             │
│  │                  │   Customer history, product data           │
│  └────────┬─────────┘                                           │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                           │
│  │ 3. REASON        │ ← LLM inference (if enabled)              │
│  │                  │   Rules fallback if degraded               │
│  └────────┬─────────┘                                           │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                           │
│  │ 4. POLICY        │ ← PolicyGraph evaluation                  │
│  │                  │   Risk scoring, approval checks            │
│  └────────┬─────────┘                                           │
│           │                                                      │
│           ├────────────────┐                                     │
│           ▼                ▼                                     │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │ 5a. EXECUTE  │  │ 5b. ESCALATE │                             │
│  │ Auto-approve │  │ Human review │                             │
│  └──────────────┘  └──────────────┘                             │
│           │                │                                     │
│           └────────┬───────┘                                     │
│                    ▼                                             │
│  ┌──────────────────────────────────────┐                       │
│  │ DECISION LOG (Bi-temporal)           │                       │
│  │ + Security Event Emission            │                       │
│  │ + Telemetry (Prometheus)             │                       │
│  └──────────────────────────────────────┘                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Security Architecture (Defense-in-Depth)

```
┌─────────────────────────────────────────────────────────────────┐
│                    SECURITY LAYERS                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  LAYER 1: PERIMETER                                             │
│  ─────────────────────                                          │
│  • Webhook signature validation (HMAC-SHA256)                   │
│  • Replay attack prevention (nonce + timestamp)                 │
│  • TLS termination                                              │
│                                                                  │
│  LAYER 2: APPLICATION                                           │
│  ─────────────────────                                          │
│  • Rate limiting (IP-based, configurable)                       │
│  • Backpressure middleware (concurrency limits)                 │
│  • CORS configuration                                           │
│                                                                  │
│  LAYER 3: SECURITY OBSERVER                                     │
│  ─────────────────────                                          │
│  • Unicode normalization (homograph attacks)                    │
│  • PII detection & masking (email, phone, SSN, IP)              │
│  • API key detection (test/live keys)                           │
│  • PCI data detection (card numbers, CVV)                       │
│  • Jailbreak patterns (35+ regex)                               │
│  • Prompt injection detection                                   │
│  • Tool abuse detection                                         │
│  • Data exfiltration detection                                  │
│                                                                  │
│  LAYER 4: ACCESS CONTROL                                        │
│  ─────────────────────                                          │
│  • JWT validation                                               │
│  • Role-based access (Owner, Merchant, Developer)               │
│  • Per-endpoint authorization                                   │
│  • Tenant isolation                                             │
│                                                                  │
│  LAYER 5: TRANSACTION FIREWALL                                  │
│  ─────────────────────                                          │
│  • Idempotency enforcement                                      │
│  • Circuit breaker (degradation)                                │
│  • Caps/thresholds (discount %, order value)                    │
│  • Approval tier routing                                        │
│                                                                  │
│  LAYER 6: AUDIT & COMPLIANCE                                    │
│  ─────────────────────                                          │
│  • Bi-temporal decision logs                                    │
│  • Security event persistence                                   │
│  • Incident escalation                                          │
│  • Evidence pack generation                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Services Deep Dive

### Core Services (Production-Ready)

#### Orchestrator (`orchestrator.py` - 409 LOC)

```python
# Key capabilities:
class Orchestrator:
    async def run(self, payload, uid, path) -> dict:
        # 1. Security pre-check
        sec_result = await self.observer.analyze(payload)
        if sec_result.get("blocked"):
            return self._blocked_response(sec_result)

        # 2. Retrieve context (CacheRAG + DB)
        context = await self._retrieve_context(uid, payload)

        # 3. Apply policies
        policy_result = await self.policy_evaluator.evaluate(
            payload, context, self.policy_version
        )

        # 4. Reason (LLM or rules fallback)
        if self.llm_enabled and not degraded:
            reasoning = await self.llm.reason(payload, context)
        else:
            reasoning = self._rules_fallback(payload, context)

        # 5. Execute or escalate
        if policy_result.requires_approval:
            return await self._escalate(payload, reasoning, policy_result)
        else:
            return await self._execute(payload, reasoning)
```

**Features:**
- Idempotency via Redis keys
- Graceful degradation (rules fallback)
- Token budget enforcement
- Dependency health checking
- Policy version tracking

#### Recommendations (`recommendations.py` - 519 LOC)

```python
# Tiered approach: fast path (rules) vs enhanced path (LLM reranking)
class RecommendationService:
    async def suggest(self, uid, query, limit=5):
        # 1. Candidate retrieval (SQL + embeddings)
        candidates = await self.catalog.search(query, limit=20)

        # 2. Fast path: rule-based scoring
        if not self.llm_enabled or await self._should_fast_path(query):
            return self._rules_rerank(candidates, query)

        # 3. Enhanced path: LLM reranking
        return await self._llm_rerank(candidates, query, uid)

    def _rules_rerank(self, candidates, query):
        # Keyword matching + price/popularity scoring
        for c in candidates:
            c["score"] = self._compute_score(c, query)
        return sorted(candidates, key=lambda x: x["score"], reverse=True)
```

**Features:**
- Embedding-based retrieval (SimpleEmbeddings)
- LRU cache for embeddings (256 entries)
- SKU validation (no hallucinated products)
- Constrained output ("only reorder provided candidates")

#### Policy Evaluator (`policy_evaluator.py` - 143 LOC)

```python
class PolicyEvaluator:
    async def evaluate(self, decision, context, policy_version):
        # Load active policies for tenant
        policies = await self._load_policies(context.tenant_id)

        violations = []
        for policy in policies:
            for control in policy.controls:
                for rule in control.rules:
                    result = self._eval_rule(rule, decision, context)
                    if not result.passed:
                        violations.append({
                            "policy": policy.name,
                            "control": control.key,
                            "severity": control.severity,
                            "reason": result.reason
                        })

        return PolicyResult(
            requires_approval=len(violations) > 0,
            violations=violations,
            policy_version=policy_version
        )
```

**Features:**
- Per-tenant policy isolation
- Control severity levels (critical, high, medium, low)
- Rule priority ordering
- Evaluation persistence (pg_evaluations)

#### Fraud Scorer (`fraud_scorer.py` - 106 LOC)

```python
class FraudScorer:
    WEIGHTS = {
        "image_hash_match_fraud_db": 0.35,
        "exif_date_mismatch": 0.15,
        "serial_mismatch": 0.40,
        "high_return_frequency": 0.15,
        "previous_fraud_flag": 0.30,
        "account_age_under_30_days": 0.10,
        # ... 11 total signals
    }

    def calculate_score(self, signals: dict) -> float:
        score = sum(
            self.WEIGHTS.get(sig, 0.1)
            for sig, detected in signals.items()
            if detected
        )
        return min(1.0, score / sum(self.WEIGHTS.values()))
```

**Features:**
- 11 weighted fraud signals
- Perceptual hash (pHash) for image similarity
- Serial number verification
- Customer history analysis
- Risk level categorization (minimal/low/medium/high)

### LLM Services (Data Sovereignty Focus)

#### Ollama Client (`ollama_client.py` - 81 LOC)

```python
class OllamaClient:
    """Local LLM inference via Ollama CLI."""

    async def generate(self, prompt, model="llama3:8b", temperature=0.2):
        # Subprocess call to ollama CLI
        result = await asyncio.create_subprocess_exec(
            "ollama", "run", model, prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()
        return stdout.decode()

    async def is_available(self) -> bool:
        """Check if Ollama is running."""
        try:
            result = await asyncio.create_subprocess_exec(
                "ollama", "list",
                stdout=asyncio.subprocess.PIPE
            )
            return result.returncode == 0
        except:
            return False
```

**Tiered Model Selection:**
```python
# llm_provider.py
def select_model(query: str) -> str:
    """Select model based on query complexity."""
    if len(query) > 140 or "compare" in query or "policy" in query:
        return "mixtral:8x7b"  # Complex reasoning
    return "llama3:8b"  # Fast response
```

**Benefits of Ollama:**
- Full data sovereignty (no data leaves your infrastructure)
- Zero API costs after hardware
- GDPR/privacy compliance by default
- Predictable latency (no network variability)
- Works offline

---

## 4. Security Implementation

### Security Observer (`observer.py` - 530 LOC)

The most comprehensive module in the codebase. Detects:

| Threat Category | Patterns | OWASP LLM Mapping |
|-----------------|----------|-------------------|
| **Jailbreak** | 35+ regex patterns | LLM01 (Prompt Injection) |
| **Unicode Obfuscation** | Homograph detection | LLM01 |
| **PII Leakage** | Email, phone, SSN, IP | LLM06 (Sensitive Info) |
| **API Key Exposure** | sk_, rk_, pk_ prefixes | LLM06 |
| **PCI Data** | Card numbers, CVV | LLM06 |
| **Prompt Injection** | System override attempts | LLM01 |
| **Tool Abuse** | Malicious function calls | LLM08 (Excessive Agency) |
| **Data Exfiltration** | Secret dumping patterns | LLM10 (Model Theft) |

```python
# Key detection patterns
JAILBREAK_PATTERNS = [
    r"ignore.*previous.*instructions",
    r"disregard.*all.*prior",
    r"you are now.*(?:jailbroken|DAN|evil)",
    r"pretend.*you.*have.*no.*restrictions",
    r"respond.*without.*safety",
    # ... 30+ more patterns
]

PII_PATTERNS = {
    "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
}
```

### Threat Framework Mappings

```python
# MITRE ATT&CK for ML (ATLAS)
MITRE_MAPPINGS = {
    "jailbreak": "AML.T0043",  # Craft Adversarial Data
    "evasion": "AML.T0015",    # Model Evasion
    "exfiltration": "AML.T0048",  # Exfiltration via ML
}

# OWASP LLM Top 10
OWASP_MAPPINGS = {
    "prompt_injection": "LLM01",
    "sensitive_info": "LLM06",
    "excessive_agency": "LLM08",
    "model_theft": "LLM10",
}

# Risk scoring frameworks
RISK_FRAMEWORKS = {
    "CVSS": compute_cvss_score,
    "DREAD": compute_dread_score,
    "STRIDE": classify_stride_category,
    "PASTA": compute_pasta_risk,
}
```

### Supply Chain Security (`supply_chain.py` - 248 LOC)

```python
class SupplyChainMonitor:
    """Monitor for CVE/KEV vulnerabilities in dependencies."""

    def __init__(self, kev_catalog_path):
        self.kev_catalog = self._load_kev(kev_catalog_path)
        self.baselines = self._load_baselines()

    async def check_dependency(self, package, version) -> dict:
        """Check if dependency has known vulnerabilities."""
        # Check KEV catalog
        kev_match = self._check_kev(package, version)
        if kev_match:
            return {
                "vulnerable": True,
                "severity": "critical",
                "cve": kev_match["cve_id"],
                "action": "upgrade_immediately"
            }

        # Check baseline drift
        baseline = self.baselines.get(package)
        if baseline and version < baseline["min_safe_version"]:
            return {
                "vulnerable": True,
                "severity": "high",
                "reason": "below_baseline",
                "action": "upgrade_recommended"
            }

        return {"vulnerable": False}
```

---

## 5. NLP & Computer Vision

### Current NLP Capabilities

#### Complaint Classification (`nlp_complaints.py`)

```python
class ComplaintNLP:
    """Classify customer complaints and extract entities."""

    INTENT_PATTERNS = {
        "damage": ["damaged", "broken", "cracked", "dent", "scratch"],
        "wrong_item": ["wrong", "different", "not what I ordered"],
        "missing": ["missing", "incomplete", "not included"],
        "defective": ["doesn't work", "defective", "malfunction", "dead"],
        "shipping": ["late", "delayed", "lost", "tracking"],
    }

    async def classify(self, text: str) -> dict:
        # 1. Intent classification
        intent = self._match_intent(text)

        # 2. Entity extraction
        entities = self._extract_entities(text)

        # 3. Severity estimation
        severity = self._estimate_severity(text, intent)

        # 4. LLM enhancement (if enabled)
        if self.llm_enabled:
            enhanced = await self._llm_enhance(text, intent, entities)
            return {**enhanced, "method": "llm_enhanced"}

        return {
            "intent": intent,
            "entities": entities,
            "severity": severity,
            "confidence": self._confidence(text, intent),
            "method": "rules_based"
        }
```

#### BEC Detection (`email_validation.py`)

```python
class BECDetector:
    """Detect Business Email Compromise patterns."""

    BEC_PATTERNS = [
        r"wire transfer.*urgent",
        r"change.*bank.*account",
        r"ceo.*requesting",
        r"confidential.*do not share",
        r"bypass.*approval",
        r"act immediately",
        r"keep this between us",
    ]

    def analyze(self, email_body: str, sender_domain: str) -> dict:
        matches = [p for p in self.BEC_PATTERNS
                   if re.search(p, email_body, re.I)]

        risk = "high" if len(matches) >= 2 else "medium" if matches else "low"

        return {
            "bec_risk": risk,
            "patterns_matched": matches,
            "domain_verified": self._verify_dmarc(sender_domain),
            "recommendation": "escalate_legal" if risk == "high" else "review"
        }
```

### Computer Vision Pipeline

#### CV Provider (`cv_provider.py` - 97 LOC)

```python
class CVProvider:
    """Vision analysis via LLaVA or cloud APIs."""

    async def analyze_image(self, image_bytes: bytes, prompt: str) -> dict:
        if self.provider == "llava":
            return await self._llava_analyze(image_bytes, prompt)
        elif self.provider == "google_vision":
            return await self._google_vision(image_bytes)
        elif self.provider == "azure_vision":
            return await self._azure_vision(image_bytes)

    async def _llava_analyze(self, image_bytes, prompt):
        """Local LLaVA model for data sovereignty."""
        # Encode image to base64
        encoded = base64.b64encode(image_bytes).decode()

        # Call Ollama with LLaVA
        result = await self.ollama.generate(
            prompt=f"[IMAGE:{encoded}]\n{prompt}",
            model="llava:13b"
        )
        return self._parse_llava_response(result)
```

#### Basic CV Triage (`cv_triage_basic.py` - 88 LOC)

```python
class BasicCVTriage:
    """Keyword-based damage classification from CV labels."""

    DAMAGE_KEYWORDS = {
        "physical": ["crack", "broken", "dent", "scratch", "shattered"],
        "cosmetic": ["scuff", "mark", "stain", "discolor"],
        "functional": ["error", "black screen", "dead pixels"],
        "packaging": ["box", "torn", "crushed", "wet"],
    }

    async def analyze(self, labels: list) -> dict:
        """Classify damage from detected labels."""
        damage_type = self._classify_damage(labels)
        severity = self._estimate_severity(labels)

        return {
            "damage_type": damage_type,
            "severity": severity,
            "confidence": self._calculate_confidence(labels, damage_type),
            "needs_human_review": severity == "critical" or confidence < 0.6,
            "ai_disclaimer": "preliminary"
        }
```

### Improvement: NLP on Admin Dashboard

**Current Gap:** Admin queries data via SQL/forms, not natural language.

**Proposed Enhancement:**

```python
# src/app/services/admin_nlp_query.py

class AdminNLPQuery:
    """Natural language queries for admin dashboard."""

    QUERY_TYPES = {
        "security": [
            r"show.*security.*events",
            r"threats.*last.*(\d+).*days",
            r"blocked.*requests",
        ],
        "decisions": [
            r"why.*rejected",
            r"decision.*history",
            r"approval.*rate",
        ],
        "inventory": [
            r"low.*stock",
            r"inventory.*below",
            r"reorder.*needed",
        ],
        "sales": [
            r"revenue.*today",
            r"top.*selling",
            r"orders.*last.*week",
        ],
    }

    async def query(self, natural_query: str, user_role: str) -> dict:
        """Translate natural language to structured query."""

        # 1. Classify query type
        query_type = self._classify(natural_query)

        # 2. Check permissions
        if not self._has_permission(user_role, query_type):
            return {"error": "permission_denied"}

        # 3. Execute appropriate handler
        handlers = {
            "security": self._query_security_events,
            "decisions": self._query_decisions,
            "inventory": self._query_inventory,
            "sales": self._query_sales,
        }

        return await handlers[query_type](natural_query)

    async def _query_security_events(self, query: str) -> dict:
        """Query security events with natural language."""
        # Extract time range
        days = self._extract_time_range(query) or 7

        # Query TimescaleDB
        events = await self.db.execute("""
            SELECT severity, COUNT(*) as count,
                   time_bucket('1 hour', event_time) as hour
            FROM security_events
            WHERE event_time > NOW() - INTERVAL '%s days'
            GROUP BY severity, hour
            ORDER BY hour DESC
        """, (days,))

        return {
            "summary": f"Security events in last {days} days",
            "data": events,
            "chart_type": "time_series"
        }
```

---

## 6. Admin Dashboard & PowerBI Integration

### Current React Dashboard Components

| Component | Purpose | Status |
|-----------|---------|--------|
| `App.tsx` | Main shell, routing | Working |
| `ProductGrid.tsx` | Product catalog | Working |
| `ProductComparison.tsx` | Side-by-side compare | Working |
| `ChatOverlay.tsx` | AI chat interface | Working |
| `DecisionTrace.tsx` | Audit trail viewer | Working |
| `SecurityDemo.tsx` | Staff security panel | Working |

### PowerBI Integration

**BI Views (`db/views/shopSquire_bi_views.sql`):**

```sql
-- Daily decision metrics
CREATE OR REPLACE VIEW bi_decision_metrics_daily AS
SELECT
    DATE(valid_from) as date,
    agent_name,
    execution_status,
    COUNT(*) as decision_count,
    AVG(EXTRACT(EPOCH FROM (executed_at - created_at))) as avg_latency_sec,
    SUM(CASE WHEN approval_required THEN 1 ELSE 0 END) as escalations
FROM decision_logs
WHERE valid_from > NOW() - INTERVAL '90 days'
GROUP BY DATE(valid_from), agent_name, execution_status;

-- Revenue by day
CREATE OR REPLACE VIEW bi_revenue_daily AS
SELECT
    DATE(created_at) as date,
    COUNT(*) as order_count,
    SUM(total_cents) / 100.0 as revenue,
    AVG(total_cents) / 100.0 as avg_order_value
FROM orders
WHERE status NOT IN ('cancelled', 'refunded')
GROUP BY DATE(created_at);

-- Security events heatmap
CREATE OR REPLACE VIEW bi_security_heatmap AS
SELECT
    EXTRACT(HOUR FROM event_time) as hour,
    EXTRACT(DOW FROM event_time) as day_of_week,
    severity,
    COUNT(*) as event_count
FROM security_events
WHERE event_time > NOW() - INTERVAL '30 days'
GROUP BY hour, day_of_week, severity;
```

**PowerBI Connection:**

```yaml
# PowerBI DirectQuery Configuration
connection:
  type: PostgreSQL
  server: your-shopsquire-db.example.com
  port: 5432
  database: shopsquire

views:
  - bi_decision_metrics_daily
  - bi_revenue_daily
  - bi_security_heatmap
  - bi_inventory_status
  - bi_fraud_signals

refresh:
  mode: DirectQuery  # Real-time
  # OR
  mode: Import
  schedule: "0 */6 * * *"  # Every 6 hours
```

### Human Takeover for Escalated Tickets

**Proposed Flow:**

```
┌─────────────────────────────────────────────────────────────────┐
│  HUMAN TAKEOVER WORKFLOW                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  AI Agent Conversation                                          │
│       │                                                         │
│       ├── Confidence < threshold?                               │
│       ├── Customer requests human?                              │
│       ├── Complex issue detected?                               │
│       ├── High-value order?                                     │
│       └── Fraud signals detected?                               │
│               │                                                  │
│               ▼                                                  │
│  ┌─────────────────────────────────────────┐                    │
│  │ ESCALATION TRIGGER                      │                    │
│  │ • Context package created               │                    │
│  │ • Conversation history preserved        │                    │
│  │ • Decision trace attached               │                    │
│  │ • Customer notified                     │                    │
│  └─────────────────────────────────────────┘                    │
│               │                                                  │
│               ▼                                                  │
│  ┌─────────────────────────────────────────┐                    │
│  │ ADMIN DASHBOARD - LIVE QUEUE            │                    │
│  │                                          │                    │
│  │ ┌─────────────────────────────────────┐ │                    │
│  │ │ TICKET #4567 - URGENT               │ │                    │
│  │ │ Customer: john@example.com          │ │                    │
│  │ │ Issue: Fraud flagged return         │ │                    │
│  │ │ AI Confidence: 0.45                 │ │                    │
│  │ │ Decision Trace: [View]              │ │                    │
│  │ │ [Take Over] [Reassign] [Escalate]   │ │                    │
│  │ └─────────────────────────────────────┘ │                    │
│  └─────────────────────────────────────────┘                    │
│               │                                                  │
│               ▼                                                  │
│  ┌─────────────────────────────────────────┐                    │
│  │ HUMAN AGENT INTERFACE                    │                    │
│  │                                          │                    │
│  │ • Full conversation history             │                    │
│  │ • Customer profile & history            │                    │
│  │ • AI reasoning explanation              │                    │
│  │ • Suggested responses                   │                    │
│  │ • One-click actions (refund, replace)   │                    │
│  │ • Live chat with customer               │                    │
│  └─────────────────────────────────────────┘                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation:**

```python
# src/app/routers/support_live.py

@router.websocket("/ws/support/queue/{agent_id}")
async def support_agent_queue(websocket: WebSocket, agent_id: str):
    """WebSocket for live support agent queue."""
    await websocket.accept()

    # Subscribe to escalation events
    async for ticket in escalation_stream.subscribe(agent_id):
        await websocket.send_json({
            "type": "new_escalation",
            "ticket": {
                "id": ticket.id,
                "customer": ticket.customer_email,
                "summary": ticket.ai_summary,
                "confidence": ticket.ai_confidence,
                "decision_trace_url": f"/decisions/{ticket.decision_id}",
                "conversation": ticket.messages,
                "priority": ticket.priority,
            }
        })

@router.post("/support/takeover/{ticket_id}")
async def takeover_conversation(
    ticket_id: str,
    agent: Agent = Depends(get_current_agent)
):
    """Human agent takes over AI conversation."""
    ticket = await get_ticket(ticket_id)

    # Mark as human-handled
    await ticket.assign_to(agent.id)

    # Notify customer
    await notify_customer(
        ticket.customer_id,
        f"Agent {agent.name} has joined your conversation."
    )

    # Log takeover
    await log_decision(
        decision_id=ticket.decision_id,
        action="human_takeover",
        actor=agent.id,
        reason="manual_escalation"
    )

    return {"status": "assigned", "agent": agent.name}
```

---

## 7. Database Strategy

### Current: PostgreSQL + Optional Extensions

```
┌─────────────────────────────────────────────────────────────────┐
│  CURRENT DATABASE ARCHITECTURE                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PostgreSQL (Primary)                                           │
│  ├── OLTP Schema                                                │
│  │   ├── customers, orders, products, inventory                 │
│  │   └── draft_orders, payment_methods                          │
│  │                                                               │
│  ├── Audit Schema                                               │
│  │   ├── decision_logs (bi-temporal)                            │
│  │   ├── decision_audits                                        │
│  │   └── ragas_eval_results                                     │
│  │                                                               │
│  ├── Security Schema                                            │
│  │   ├── security_events                                        │
│  │   ├── iam_events                                             │
│  │   └── incidents                                              │
│  │                                                               │
│  └── Extensions                                                 │
│      ├── TimescaleDB (optional) → Hypertables for time-series  │
│      ├── pgvector (optional) → Embedding similarity search      │
│      └── pg_cron (optional) → Scheduled jobs                   │
│                                                                  │
│  Redis (Cache/Session)                                          │
│  ├── session:{uid}:summary → Rolling conversation summary       │
│  ├── session:{uid}:kv_state → User state (cart, locale)        │
│  ├── session:{uid}:recent_retrieval → CacheRAG results          │
│  └── idem:{key} → Idempotency keys (7-day TTL)                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### PolicyGraph vs ContextGraph vs PolicyRAG

| Approach | Purpose | When to Use | Implementation |
|----------|---------|-------------|----------------|
| **PolicyGraph** | Deterministic rule evaluation | Compliance, approvals | PostgreSQL tables |
| **ContextGraph** | Relationship reasoning | Fraud rings, product similarity | PostgreSQL (simple) or Neo4j (complex) |
| **PolicyRAG** | LLM-assisted policy lookup | Complex rule interpretation | Embeddings + LLM |
| **TimescaleDB** | Time-series analytics | Decision metrics, security events | PostgreSQL extension |

**Recommended Progression:**

```
Phase 1 (Now):     PostgreSQL + PolicyGraph tables
Phase 2 (Month 2): + TimescaleDB hypertables
Phase 3 (Month 3): + pgvector for embeddings
Phase 4 (Scale):   + ContextGraph in Neo4j (if edges > 10M)
Phase 5 (If Needed): PolicyRAG for complex rule interpretation
```

### Enterprise Data Integration

When bolting onto customer environments with large data:

```
┌─────────────────────────────────────────────────────────────────┐
│  ENTERPRISE INTEGRATION ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CUSTOMER ENVIRONMENT                                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ERP (SAP, Oracle)        CRM (Salesforce, HubSpot)      │   │
│  │ WMS (Warehouse)          Shipping (ShipStation)         │   │
│  │ Accounting (QuickBooks)  E-commerce (Shopify, Magento)  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              INTEGRATION LAYER                           │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │                                                          │   │
│  │  Option A: Direct Database Access                        │   │
│  │  • Read-only connection to customer DB                   │   │
│  │  • Real-time sync via CDC (Debezium)                     │   │
│  │  • Concern: Security, VPN requirements                   │   │
│  │                                                          │   │
│  │  Option B: API Integration (Preferred)                   │   │
│  │  • Customer exposes REST/GraphQL APIs                    │   │
│  │  • Webhook callbacks for events                          │   │
│  │  • OAuth 2.0 authentication                              │   │
│  │                                                          │   │
│  │  Option C: Data Lake Sync                                │   │
│  │  • Periodic export to S3/Azure Blob                      │   │
│  │  • ShopSquire reads from data lake                       │   │
│  │  • Best for batch analytics                              │   │
│  │                                                          │   │
│  │  Option D: Event Streaming                               │   │
│  │  • Kafka/Pulsar topics                                   │   │
│  │  • Real-time event consumption                           │   │
│  │  • Best for high-volume operations                       │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              SHOPSQUIRE DATA LAYER                       │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │                                                          │   │
│  │  Staging Tables (Customer Data)                          │   │
│  │  • stg_orders, stg_products, stg_customers               │   │
│  │  • Incremental sync, last_sync_at tracking               │   │
│  │  • PII masking during ingestion                          │   │
│  │                                                          │   │
│  │  Operational Tables (ShopSquire)                         │   │
│  │  • decision_logs, security_events                        │   │
│  │  • Agent-generated data                                  │   │
│  │                                                          │   │
│  │  Analytics Tables (Aggregates)                           │   │
│  │  • bi_* views for PowerBI                               │   │
│  │  • Continuous aggregates via TimescaleDB                 │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Lake/Warehouse Considerations

| Scale | Solution | When |
|-------|----------|------|
| **< 100 GB** | PostgreSQL + TimescaleDB | Current stage |
| **100 GB - 1 TB** | PostgreSQL + ClickHouse (OLAP) | High-volume analytics |
| **1 TB - 10 TB** | Data Lake (S3 + Parquet + Trino) | Enterprise customers |
| **> 10 TB** | Databricks / Snowflake | Data warehouse native |

```python
# Data lake integration example
class DataLakeConnector:
    """Connect to customer data lake."""

    async def sync_from_s3(self, bucket: str, prefix: str):
        """Incremental sync from S3 parquet files."""
        # List new files since last sync
        new_files = await self.s3.list_objects(
            Bucket=bucket,
            Prefix=prefix,
            Marker=self.last_sync_marker
        )

        for file in new_files:
            # Read parquet with PyArrow
            df = pq.read_table(f"s3://{bucket}/{file['Key']}")

            # Mask PII
            df = self._mask_pii(df)

            # Load to staging
            await self.db.copy_from_dataframe(
                df, "stg_orders",
                if_exists="append"
            )

        self.last_sync_marker = new_files[-1]["Key"]
```

---

## 8. Enterprise Integration Considerations

### Shipping Agent Integration (ShipStation)

```python
# connectors/shipstation.py

class ShipStationConnector:
    """Integrate with ShipStation for fulfillment."""

    async def create_shipment(self, order: Order) -> dict:
        """Create shipment in ShipStation."""
        response = await self.client.post("/shipments", json={
            "orderId": order.id,
            "carrierCode": self._select_carrier(order),
            "serviceCode": self._select_service(order),
            "packageCode": "package",
            "weight": {"value": order.weight_lbs, "units": "pounds"},
            "shipTo": order.shipping_address.to_dict(),
        })
        return response.json()

    async def get_tracking(self, shipment_id: str) -> dict:
        """Get tracking updates."""
        return await self.client.get(f"/shipments/{shipment_id}/tracking")

    async def webhook_handler(self, event: dict):
        """Handle ShipStation webhook events."""
        if event["resource_type"] == "SHIP_NOTIFY":
            # Update order status
            await self.update_order_shipped(
                order_id=event["resource"]["orderId"],
                tracking=event["resource"]["trackingNumber"]
            )
            # Notify customer
            await self.notify_customer_shipped(event["resource"])
```

### Agentic Inventory Ordering

```python
# src/app/services/inventory_agent.py

class InventoryAgent:
    """Autonomous inventory management agent."""

    async def check_and_reorder(self):
        """Check inventory levels and trigger reorders."""
        low_stock = await self.db.execute("""
            SELECT p.sku, p.name, i.stock, p.reorder_point, p.reorder_quantity
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            WHERE i.stock < p.reorder_point
            AND p.auto_reorder = true
        """)

        for item in low_stock:
            # Create decision record
            decision = await self.orchestrator.propose(
                action="reorder_inventory",
                payload={
                    "sku": item["sku"],
                    "quantity": item["reorder_quantity"],
                    "supplier_id": item["preferred_supplier_id"],
                }
            )

            # If approved (or auto-approved), place order
            if decision["approved"]:
                await self._place_supplier_order(item, decision)

    async def _place_supplier_order(self, item, decision):
        """Place order with supplier via API or email."""
        supplier = await self.get_supplier(item["preferred_supplier_id"])

        if supplier.api_enabled:
            # API-based ordering
            response = await supplier.client.post("/orders", json={
                "sku": item["sku"],
                "quantity": item["reorder_quantity"],
                "delivery_address": self.warehouse_address,
            })
        else:
            # Email-based ordering (with human review)
            await self.email_service.send(
                to=supplier.order_email,
                subject=f"Purchase Order - {item['sku']}",
                body=self._generate_po(item, decision),
                require_confirmation=True
            )

        # Log the order
        await self.log_supplier_order(item, decision, response)
```

### Supplier Communication Agent

```python
class SupplierCommunicationAgent:
    """AI agent for supplier interactions."""

    async def handle_supplier_email(self, email: InboundEmail):
        """Process incoming supplier emails."""
        # 1. Security check (BEC detection)
        bec_result = await self.bec_detector.analyze(email.body)
        if bec_result["bec_risk"] == "high":
            return await self.escalate_to_security(email, bec_result)

        # 2. Classify email type
        email_type = await self.classify_email(email.body)

        handlers = {
            "order_confirmation": self._handle_order_confirmation,
            "shipping_notification": self._handle_shipping,
            "price_change": self._handle_price_change,
            "out_of_stock": self._handle_out_of_stock,
            "inquiry": self._handle_inquiry,
        }

        return await handlers.get(email_type, self._escalate)(email)

    async def _handle_price_change(self, email):
        """Handle supplier price change notification."""
        # Extract new prices
        prices = await self.extract_prices(email.body)

        # Compare to current prices
        changes = await self.compare_prices(prices)

        # If significant change (>10%), escalate
        if any(c["change_pct"] > 10 for c in changes):
            return await self.escalate_to_procurement(email, changes)

        # Otherwise, auto-update with audit trail
        for change in changes:
            await self.update_supplier_price(
                supplier_id=email.sender_id,
                sku=change["sku"],
                new_price=change["new_price"],
                effective_date=change["effective_date"],
                decision_id=self.current_decision_id
            )
```

---

## 9. Supply Chain Security

### Threat Vectors

| Vector | Attack | Detection | Response |
|--------|--------|-----------|----------|
| **API Poisoning** | Malicious data in API responses | Schema validation, anomaly detection | Block, alert |
| **Webhook Hijacking** | Fake webhooks with valid signatures | Timestamp validation, source IP allowlist | Block, investigate |
| **Supply Chain Compromise** | Compromised supplier API | Behavioral analysis, response validation | Degrade to manual |
| **Data Exfiltration** | Sensitive data in supplier requests | PII detection, data classification | Redact, alert |
| **Invoice Fraud** | Fake invoices via email | BEC detection, amount anomaly | Escalate to finance |

### Security Agent for Supply Chain

```python
class SupplyChainSecurityAgent:
    """Monitor and secure supply chain interactions."""

    async def validate_supplier_response(self, supplier_id: str, response: dict):
        """Validate supplier API response for security threats."""
        threats = []

        # 1. Schema validation
        if not self._validate_schema(response, self.expected_schemas[supplier_id]):
            threats.append({
                "type": "schema_mismatch",
                "severity": "medium",
                "details": "Response schema differs from expected"
            })

        # 2. Anomaly detection
        anomalies = await self._detect_anomalies(supplier_id, response)
        threats.extend(anomalies)

        # 3. PII check (shouldn't be in supplier responses)
        pii_found = self.pii_detector.scan(json.dumps(response))
        if pii_found:
            threats.append({
                "type": "unexpected_pii",
                "severity": "high",
                "details": f"PII types found: {pii_found}"
            })

        # 4. Injection check
        injection = self._check_injection(response)
        if injection:
            threats.append({
                "type": "injection_attempt",
                "severity": "critical",
                "details": injection
            })

        # Decision: block or allow
        if any(t["severity"] == "critical" for t in threats):
            await self.block_and_escalate(supplier_id, threats)
            return {"status": "blocked", "threats": threats}

        if threats:
            await self.log_and_alert(supplier_id, threats)

        return {"status": "allowed", "threats": threats}

    async def validate_webhook(self, request: Request) -> bool:
        """Validate incoming webhook from supplier."""
        # 1. HMAC signature validation
        signature = request.headers.get("X-Webhook-Signature")
        if not self._verify_hmac(request.body, signature):
            await self.log_security_event("webhook_signature_invalid")
            return False

        # 2. Timestamp check (prevent replay)
        timestamp = request.headers.get("X-Webhook-Timestamp")
        if self._is_replay(timestamp):
            await self.log_security_event("webhook_replay_attempt")
            return False

        # 3. Source IP validation
        if request.client.host not in self.allowed_webhook_ips:
            await self.log_security_event("webhook_unknown_source")
            return False

        return True
```

### When to Block vs Escalate

```python
SUPPLY_CHAIN_RESPONSE_MATRIX = {
    "critical": {
        "action": "block",
        "escalate_to": ["security", "executive"],
        "auto_degrade": True,
        "examples": [
            "injection_attempt",
            "malware_signature",
            "credential_theft"
        ]
    },
    "high": {
        "action": "block_pending_review",
        "escalate_to": ["security", "procurement"],
        "auto_degrade": False,
        "examples": [
            "unexpected_pii",
            "schema_major_change",
            "suspicious_pricing"
        ]
    },
    "medium": {
        "action": "allow_with_monitoring",
        "escalate_to": ["procurement"],
        "alert": True,
        "examples": [
            "schema_minor_change",
            "unusual_quantity",
            "new_field_added"
        ]
    },
    "low": {
        "action": "allow",
        "log": True,
        "examples": [
            "timing_anomaly",
            "response_size_unusual"
        ]
    }
}
```

---

## 10. Gaps & Improvement Roadmap

### Current Gaps

| Gap | Priority | Effort | Impact |
|-----|----------|--------|--------|
| **Real-time human takeover UI** | P0 | 3 days | High - enables live support |
| **NLP query on admin dashboard** | P0 | 2 days | High - differentiator |
| **ShipStation integration** | P1 | 2 days | Medium - enterprise feature |
| **Supplier agent** | P1 | 5 days | Medium - autonomous ordering |
| **Data lake connector** | P1 | 3 days | High - enterprise customers |
| **Field-level encryption** | P2 | 2 days | Medium - compliance |
| **Secrets vault integration** | P2 | 1 day | Medium - security posture |
| **Full GraphDB integration** | P3 | 5 days | Low - defer until needed |

### Week 1 Priorities

```
1. Admin NLP Query Layer
   - Natural language queries for security, decisions, inventory
   - PowerBI-like "ask a question" interface

2. Human Takeover UI
   - WebSocket for live queue
   - Agent assignment and handoff
   - Context package (conversation + decision trace)

3. Supplier Webhook Security
   - HMAC validation for supplier callbacks
   - Behavioral anomaly detection
```

### Month 1 Roadmap

```
Week 1: Admin NLP + Human Takeover
Week 2: ShipStation + Supplier Agent
Week 3: Data Lake Connector + Enterprise Auth (SSO)
Week 4: Security Hardening + Compliance Documentation
```

### Scaling Considerations

| Users | Infrastructure | Database |
|-------|---------------|----------|
| 100 | Single node | PostgreSQL |
| 1,000 | 3-node cluster + Redis Sentinel | PostgreSQL + read replica |
| 10,000 | Kubernetes + HPA | PostgreSQL HA + TimescaleDB |
| 100,000 | Multi-region | CockroachDB or Citus + Redis Cluster |

---

## Summary

ShopSquire is a **production-grade agentic commerce platform** built in 7 days with:

- **155 API endpoints** covering e-commerce, payments, support, security
- **Comprehensive security** (9/10 OWASP LLM Top 10, MITRE ATLAS)
- **Bi-temporal audit trails** for compliance
- **Data sovereignty** via Ollama (local LLM)
- **Modular architecture** for easy "bolt-on" integration

**Key Differentiators:**
1. Security-first design (not bolted on)
2. Decision explainability (bi-temporal audit)
3. Local LLM option (data sovereignty)
4. Enterprise integration ready (API-first, webhook-secure)

**Next Steps:**
1. Complete admin NLP query layer
2. Build human takeover UI
3. Add supplier/shipping integrations
4. Package for enterprise deployment

---

*This document provides a comprehensive technical overview of ShopSquire's architecture, capabilities, and improvement roadmap.*
