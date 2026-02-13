# Employeeless Retail Systems: ShopSquire Alignment Analysis

**Generated:** 2026-01-22
**Source:** `Employeeless-Retail-Systems.pptx` Analysis
**Purpose:** Map ShopSquire capabilities to enterprise retail architecture patterns, identify gaps, and plan improvements

---

## Table of Contents

1. [Presentation Analysis](#presentation-analysis)
2. [ShopSquire Alignment Matrix](#shopsquire-alignment)
3. [File & Decision Log Segregation Strategy](#segregation-strategy)
4. [Truth Model Selection](#truth-model)
5. [Latency, Safety & Auditability Improvements](#improvements)
6. [Eight Data Domains Implementation](#data-domains)
7. [API & Service Mesh Strategy](#api-service-mesh)
8. [Governance & Observability Enhancements](#governance)
9. [Step-by-Step Implementation (Slide 10)](#implementation-steps)
10. [Architecture Decision Records](#adrs)

---

## Presentation Analysis

### Key Thesis

The presentation argues that **employeeless retail** (autonomous stores, AI-driven decisions) requires:

1. **Polyglot persistence** - No single database fits all needs
2. **Event-sourcing as truth model** - Immutable audit trail is non-negotiable
3. **Edge-cloud hybrid** - Local autonomy with cloud control plane
4. **Forensic-grade auditability** - "Who took what, when, can we charge them?"

### Core Constraints (Slide 2)

| Constraint | Requirement | ShopSquire Status |
|------------|-------------|-------------------|
| Latency (CV/IoT) | 10-200ms | ⚠️ Not applicable (no CV/IoT) |
| Latency (Auth/Payments) | 200-1500ms | ✅ Achievable |
| Offline Operation | Minutes to hours | ❌ Not implemented |
| No Single Point of Failure | Multi-region | ❌ Single instance |
| Immutable Event History | Full audit trail | ✅ **Bitemporal logging** |
| PCI Compliance | Payment scope | ⚠️ Stubbed payments |
| GDPR/CCPA | Privacy controls | ⚠️ Missing endpoints |

### My Assessment of the Presentation

**Strengths:**
- Comprehensive architecture framework for autonomous retail
- Correct emphasis on event-sourcing for auditability
- Realistic about polyglot persistence needs
- Good middleware coverage (often neglected)

**What Applies to ShopSquire:**
- Event-sourcing model (we have bitemporal, can extend)
- Eight data domains framework (map our data to these)
- Storage selection criteria (useful for scaling)
- Step-by-step implementation process

**What Doesn't Apply (Yet):**
- CV/IoT edge computing (we're web-first)
- Physical store constraints
- Video/blob processing at scale
- Multi-region store federation

---

## ShopSquire Alignment Matrix

### Current vs Presentation Framework

| Data Domain | Presentation Recommendation | ShopSquire Current | Gap | Priority |
|-------------|---------------------------|-------------------|-----|----------|
| **1. Transactional OLTP** | Aurora PostgreSQL, Spanner | PostgreSQL (single) | Read replicas | P2 |
| **2. Event Streams** | Kafka, Pulsar | ❌ None | Full implementation | P1 |
| **3. Time-Series** | TimescaleDB, InfluxDB | Prometheus only | Decision latency | P2 |
| **4. Searchable Docs** | Elasticsearch, OpenSearch | SQL LIKE queries | Full-text search | P2 |
| **5. Vector Embeddings** | Pinecone, pgvector | ❌ None | RAG implementation | P1 |
| **6. Graph Relations** | Neo4j, Neptune | ❌ None | Fraud detection | P3 |
| **7. Analytics OLAP** | Snowflake, BigQuery | PostgreSQL views | Dedicated OLAP | P3 |
| **8. Unstructured Blobs** | S3 + Iceberg | Local filesystem | Object storage | P2 |

### What We've Implemented Well

```
✅ ALIGNED WITH PRESENTATION:

1. Bitemporal Decision Logging
   - Exactly what event-sourcing recommends
   - valid_from/valid_to for business time
   - system_from/system_to for audit time
   - Enables time-travel queries

2. Idempotency Infrastructure
   - idempotency_key in orchestrator
   - Prevents duplicate decision execution
   - Matches "at-least-once with dedup" pattern

3. Schema Evolution Ready
   - JSON columns for flexible data
   - Policy versioning in decisions
   - Can add fields without migration

4. Audit Trail Completeness
   - decision_logs: Full context capture
   - decision_audits: Actor attribution
   - security_events: Threat logging
   - api_key_audits: Access tracking
```

### What We're Missing

```
❌ GAPS TO ADDRESS:

1. Event Backbone (Critical)
   - No Kafka/Pulsar equivalent
   - Events stored in tables, not streams
   - No replay capability
   - No cross-service event bus

2. Edge/Offline Support (Medium)
   - Single cloud deployment
   - No local-first patterns
   - No sync/conflict resolution

3. CDC Pipeline (Medium)
   - No change data capture
   - No real-time data movement
   - Manual ETL only

4. Vector Store (High)
   - No embeddings storage
   - No semantic search
   - Blocking LLM RAG features

5. Time-Series for Telemetry (Medium)
   - Prometheus metrics only
   - No decision latency tracking
   - No trend analysis on decisions
```

---

## File & Decision Log Segregation Strategy

### Why Segregate?

| Reason | Explanation |
|--------|-------------|
| **Query Performance** | Different access patterns need different indexes |
| **Retention Policies** | Security events: 1 year, decisions: 7 years, telemetry: 90 days |
| **Compliance Isolation** | PCI data separate from general analytics |
| **Cost Optimization** | Hot data in fast storage, cold in cheap storage |
| **Auditability** | Clear ownership and access controls |

### Proposed Segregation Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA SEGREGATION MODEL                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DOMAIN 1: TRANSACTIONAL (OLTP)                                │
│  ─────────────────────────────                                 │
│  Tables: customers, orders, products, inventory                │
│  Storage: PostgreSQL (primary)                                 │
│  Retention: Active records + 7 year archive                    │
│  Access: Read/Write by API, Read by analytics                  │
│                                                                 │
│  DOMAIN 2: DECISION AUDIT                                       │
│  ─────────────────────────────                                 │
│  Tables: decision_logs, decision_audits                        │
│  Storage: PostgreSQL (separate schema) → TimescaleDB           │
│  Retention: 7 years (regulatory)                               │
│  Access: Append-only by agents, Read by compliance             │
│  Partitioning: Monthly by created_at                           │
│                                                                 │
│  DOMAIN 3: SECURITY EVENTS                                      │
│  ─────────────────────────────                                 │
│  Tables: security_events, security_escalations, iam_events     │
│  Storage: PostgreSQL → Elasticsearch (search)                  │
│  Retention: 1-3 years                                          │
│  Access: Append by observer, Read by SOC                       │
│  Index: severity, category, mitre_atlas                        │
│                                                                 │
│  DOMAIN 4: TELEMETRY                                            │
│  ─────────────────────────────                                 │
│  Data: Prometheus metrics, decision latency, API latency       │
│  Storage: Prometheus → VictoriaMetrics (scale)                 │
│  Retention: 90 days hot, 1 year cold                           │
│  Access: Read by Grafana, alerts                               │
│                                                                 │
│  DOMAIN 5: SESSION/MEMORY                                       │
│  ─────────────────────────────                                 │
│  Data: User sessions, conversation memory, cache               │
│  Storage: Redis (ephemeral)                                    │
│  Retention: 3 hours (session), 24 hours (cache)                │
│  Access: Read/Write by API                                     │
│                                                                 │
│  DOMAIN 6: ANALYTICS                                            │
│  ─────────────────────────────                                 │
│  Data: Aggregated metrics, BI views, reports                   │
│  Storage: PostgreSQL views → ClickHouse (scale)                │
│  Retention: Indefinite (aggregated)                            │
│  Access: Read by dashboards, BI tools                          │
│                                                                 │
│  DOMAIN 7: BLOBS/ARTIFACTS                                      │
│  ─────────────────────────────                                 │
│  Data: Model artifacts, exports, evidence packs                │
│  Storage: Local → S3/MinIO                                     │
│  Retention: Varies by type                                     │
│  Access: Write by jobs, Read by compliance                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Database Schema Segregation

```sql
-- Create separate schemas for domain isolation
CREATE SCHEMA oltp;        -- Transactional data
CREATE SCHEMA audit;       -- Decision audit trail
CREATE SCHEMA security;    -- Security events
CREATE SCHEMA analytics;   -- Materialized views

-- Move tables to appropriate schemas
ALTER TABLE customers SET SCHEMA oltp;
ALTER TABLE orders SET SCHEMA oltp;
ALTER TABLE products SET SCHEMA oltp;

ALTER TABLE decision_logs SET SCHEMA audit;
ALTER TABLE decision_audits SET SCHEMA audit;

ALTER TABLE security_events SET SCHEMA security;
ALTER TABLE security_escalations SET SCHEMA security;
ALTER TABLE iam_events SET SCHEMA security;

-- Create role-based access
CREATE ROLE oltp_writer;
CREATE ROLE audit_appender;  -- INSERT only, no UPDATE/DELETE
CREATE ROLE security_reader;
CREATE ROLE analytics_reader;

GRANT ALL ON SCHEMA oltp TO oltp_writer;
GRANT INSERT ON ALL TABLES IN SCHEMA audit TO audit_appender;
GRANT SELECT ON SCHEMA security TO security_reader;
GRANT SELECT ON SCHEMA analytics TO analytics_reader;
```

### Why This Segregation Enables Auditability

| Benefit | Explanation |
|---------|-------------|
| **Clear Ownership** | Each schema has defined purpose and access |
| **Immutable Audit** | audit_appender can INSERT only, never UPDATE/DELETE |
| **Query Isolation** | OLTP queries don't impact audit reads |
| **Compliance Ready** | Can point auditors to specific schema |
| **Retention Automation** | Different policies per schema |
| **Cost Allocation** | Track storage costs by domain |

---

## Truth Model Selection

### Options Analysis

| Model | Description | Pros | Cons | Best For |
|-------|-------------|------|------|----------|
| **Event-Sourcing** | Events are truth, state is derived | Full audit, replayable, time-travel | Complex, eventual consistency | ShopSquire ✓ |
| **State-First OLTP** | Current state is truth, audit tables | Simple, ACID, familiar | Hard to replay, audit gaps | Simple CRUD |
| **CQRS** | Separate read/write models | Optimized queries, scalable | Complexity, sync lag | High-read systems |
| **Hybrid** | Event-sourced for audit, OLTP for state | Balance of benefits | Two systems to maintain | Most real systems |

### Recommended: Hybrid Event-Sourcing

```
┌─────────────────────────────────────────────────────────────────┐
│                    HYBRID TRUTH MODEL                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  WRITE PATH (Event-Sourced)                                     │
│  ──────────────────────────                                     │
│                                                                 │
│  User Action                                                    │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────┐                                            │
│  │ Validate &      │                                            │
│  │ Create Event    │                                            │
│  └────────┬────────┘                                            │
│           │                                                     │
│           ▼                                                     │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │ Event Log       │────▶│ Materialized    │                   │
│  │ (Immutable)     │     │ Views (OLTP)    │                   │
│  │ - decision_logs │     │ - order_state   │                   │
│  │ - security_evts │     │ - inventory     │                   │
│  └─────────────────┘     └─────────────────┘                   │
│           │                       │                             │
│           │                       │                             │
│           ▼                       ▼                             │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │ Cold Archive    │     │ Query APIs      │                   │
│  │ (S3/Parquet)    │     │ (Fast reads)    │                   │
│  └─────────────────┘     └─────────────────┘                   │
│                                                                 │
│  READ PATH (State-Based)                                        │
│  ───────────────────────                                        │
│                                                                 │
│  API Query → Materialized View → Response                       │
│  (No event replay needed for normal reads)                      │
│                                                                 │
│  AUDIT PATH (Event-Based)                                       │
│  ────────────────────────                                       │
│                                                                 │
│  Compliance Query → Event Log → Full History                    │
│  (Can replay to any point in time)                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation for ShopSquire

```python
# src/app/services/event_store.py

from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum
import json
import uuid
import time

class EventType(Enum):
    # Decision events
    DECISION_PROPOSED = "decision.proposed"
    DECISION_APPROVED = "decision.approved"
    DECISION_REJECTED = "decision.rejected"
    DECISION_EXECUTED = "decision.executed"

    # Order events
    ORDER_CREATED = "order.created"
    ORDER_PAID = "order.paid"
    ORDER_SHIPPED = "order.shipped"
    ORDER_DELIVERED = "order.delivered"
    ORDER_CANCELLED = "order.cancelled"

    # Security events
    THREAT_DETECTED = "security.threat_detected"
    THREAT_ESCALATED = "security.threat_escalated"
    THREAT_RESOLVED = "security.threat_resolved"

    # Inventory events
    INVENTORY_ADJUSTED = "inventory.adjusted"
    INVENTORY_RESERVED = "inventory.reserved"
    INVENTORY_RELEASED = "inventory.released"

@dataclass
class Event:
    id: str
    type: EventType
    aggregate_id: str  # e.g., order_id, decision_id
    aggregate_type: str  # e.g., "order", "decision"
    version: int  # Sequence within aggregate
    timestamp: float
    actor: str  # Who/what caused the event
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    idempotency_key: Optional[str] = None

class EventStore:
    """
    Append-only event store as source of truth.
    Materialized views are derived from this.
    """

    def __init__(self, db, redis):
        self.db = db
        self.redis = redis

    async def append(self, event: Event) -> bool:
        """Append event to store (idempotent)"""

        # Check idempotency
        if event.idempotency_key:
            if await self._is_duplicate(event.idempotency_key):
                return False  # Already processed

        # Get next version for aggregate
        current_version = await self._get_aggregate_version(
            event.aggregate_type,
            event.aggregate_id
        )

        if event.version != current_version + 1:
            raise OptimisticConcurrencyError(
                f"Expected version {current_version + 1}, got {event.version}"
            )

        # Append to event log
        self.db.execute("""
            INSERT INTO event_log
            (id, type, aggregate_id, aggregate_type, version, timestamp,
             actor, data, metadata, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.id,
            event.type.value,
            event.aggregate_id,
            event.aggregate_type,
            event.version,
            event.timestamp,
            event.actor,
            json.dumps(event.data),
            json.dumps(event.metadata),
            event.idempotency_key
        ))
        self.db.commit()

        # Mark idempotency key as processed
        if event.idempotency_key:
            self.redis.setex(
                f"idem:{event.idempotency_key}",
                86400 * 7,  # 7 days
                event.id
            )

        # Publish to subscribers
        await self._publish(event)

        return True

    async def get_events(
        self,
        aggregate_type: str,
        aggregate_id: str,
        from_version: int = 0
    ) -> list[Event]:
        """Get events for aggregate (for replay)"""

        rows = self.db.execute("""
            SELECT * FROM event_log
            WHERE aggregate_type = ? AND aggregate_id = ?
            AND version > ?
            ORDER BY version ASC
        """, (aggregate_type, aggregate_id, from_version)).fetchall()

        return [self._row_to_event(row) for row in rows]

    async def replay_to(
        self,
        aggregate_type: str,
        aggregate_id: str,
        point_in_time: float
    ) -> Dict[str, Any]:
        """Replay events to reconstruct state at point in time"""

        rows = self.db.execute("""
            SELECT * FROM event_log
            WHERE aggregate_type = ? AND aggregate_id = ?
            AND timestamp <= ?
            ORDER BY version ASC
        """, (aggregate_type, aggregate_id, point_in_time)).fetchall()

        # Apply events to build state
        state = {}
        for row in rows:
            event = self._row_to_event(row)
            state = self._apply_event(state, event)

        return state

    def _apply_event(self, state: Dict, event: Event) -> Dict:
        """Apply event to state (event handler)"""

        if event.type == EventType.ORDER_CREATED:
            return {
                **state,
                "id": event.aggregate_id,
                "status": "created",
                "items": event.data.get("items", []),
                "created_at": event.timestamp
            }

        elif event.type == EventType.ORDER_PAID:
            return {**state, "status": "paid", "paid_at": event.timestamp}

        elif event.type == EventType.ORDER_SHIPPED:
            return {**state, "status": "shipped", "shipped_at": event.timestamp}

        elif event.type == EventType.ORDER_DELIVERED:
            return {**state, "status": "delivered", "delivered_at": event.timestamp}

        elif event.type == EventType.ORDER_CANCELLED:
            return {**state, "status": "cancelled", "cancelled_at": event.timestamp}

        # Decision events
        elif event.type == EventType.DECISION_PROPOSED:
            return {
                "id": event.aggregate_id,
                "status": "proposed",
                "proposal": event.data
            }

        elif event.type == EventType.DECISION_APPROVED:
            return {**state, "status": "approved", "approved_by": event.actor}

        elif event.type == EventType.DECISION_EXECUTED:
            return {**state, "status": "executed", "executed_at": event.timestamp}

        return state

    async def _publish(self, event: Event):
        """Publish event to subscribers"""
        # For now, use Redis pub/sub
        # In production, use Kafka/Pulsar
        channel = f"events:{event.aggregate_type}"
        self.redis.publish(channel, json.dumps({
            "id": event.id,
            "type": event.type.value,
            "aggregate_id": event.aggregate_id,
            "timestamp": event.timestamp
        }))
```

---

## Latency, Safety & Auditability Improvements

### Latency Targets & Current State

| Operation | Target (Slide 2) | Current | Gap | Fix |
|-----------|------------------|---------|-----|-----|
| Recommendation | 200-500ms | ~100ms (rules) | ✅ Good | Maintain with LLM |
| Pricing decision | 200-500ms | ~50ms (rules) | ✅ Good | Maintain with LLM |
| Security check | <50ms | ~20-100ms | ⚠️ Varies | Optimize patterns |
| Payment auth | 200-1500ms | N/A (stubbed) | ❌ Unknown | Test with Stripe |
| Order creation | <500ms | ~200ms | ✅ Good | - |

### Latency Optimization Strategies

```python
# src/app/middleware/latency_optimization.py

class LatencyOptimizer:
    """Strategies to reduce latency"""

    # 1. CACHING FREQUENTLY ACCESSED DATA
    CACHE_CONFIG = {
        "product_details": {"ttl": 300, "stale_while_revalidate": True},
        "feature_flags": {"ttl": 60, "stale_while_revalidate": True},
        "user_tier": {"ttl": 3600, "stale_while_revalidate": False},
    }

    # 2. PARALLEL EXECUTION
    async def parallel_retrieve(self, uid: str, query: str):
        """Run independent operations in parallel"""
        tasks = [
            self.get_user_context(uid),
            self.get_product_candidates(query),
            self.get_feature_flags(uid),
            self.check_token_budget(uid),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    # 3. SPECULATIVE EXECUTION
    async def speculative_recommend(self, uid: str, query: str):
        """Start LLM call while doing validation"""
        # Start LLM call immediately (don't wait for validation)
        llm_task = asyncio.create_task(self.llm_rerank(query))

        # Do validation in parallel
        is_valid = await self.validate_request(uid, query)

        if not is_valid:
            llm_task.cancel()
            return {"error": "validation_failed"}

        # Wait for LLM result
        return await llm_task

    # 4. CONNECTION POOLING
    DB_POOL_CONFIG = {
        "min_connections": 5,
        "max_connections": 20,
        "connection_timeout": 5.0,
    }

    # 5. CIRCUIT BREAKER FOR SLOW DEPENDENCIES
    CIRCUIT_BREAKER_CONFIG = {
        "llm": {"timeout": 5.0, "failure_threshold": 3, "recovery_time": 30},
        "payment": {"timeout": 10.0, "failure_threshold": 5, "recovery_time": 60},
    }
```

### Safety Improvements

```python
# src/app/security/safety_layers.py

class SafetyLayers:
    """Defense in depth for AI safety"""

    # Layer 1: Input Validation
    async def validate_input(self, request: Request) -> ValidationResult:
        checks = [
            self.check_rate_limit(request),
            self.check_payload_size(request),
            self.check_content_type(request),
            self.check_authentication(request),
        ]
        results = await asyncio.gather(*checks)
        return all(results)

    # Layer 2: Threat Detection (Existing)
    async def detect_threats(self, payload: Dict) -> ThreatAnalysis:
        return await self.security_observer.analyze(payload)

    # Layer 3: Policy Enforcement (NEW)
    async def enforce_policy(self, decision: Decision) -> EnforcementResult:
        """Enforce business rules before execution"""
        violations = []

        # Hard limits
        if decision.discount_percent > 30:
            violations.append("discount_exceeds_limit")

        if decision.total_cents > 1000000:  # $10K
            violations.append("requires_manual_review")

        if decision.agent_confidence < 0.7:
            violations.append("low_confidence_requires_approval")

        return EnforcementResult(
            allowed=len(violations) == 0,
            violations=violations,
            requires_approval=len(violations) > 0
        )

    # Layer 4: Output Validation (Existing)
    async def validate_output(self, output: Any, context: Dict) -> bool:
        return await self.guardrails.validate_output(output, context)

    # Layer 5: Post-Execution Monitoring
    async def monitor_execution(self, decision_id: str, outcome: Dict):
        """Track execution outcomes for anomaly detection"""
        await self.telemetry.record_decision_outcome(decision_id, outcome)
        await self.anomaly_detector.check_pattern(decision_id, outcome)
```

### Auditability Improvements

```python
# src/app/audit/comprehensive_audit.py

class ComprehensiveAuditTrail:
    """Full audit trail for forensic reconstruction"""

    async def log_decision(
        self,
        decision_id: str,
        stage: str,
        data: Dict[str, Any],
        actor: str
    ):
        """Log every stage of decision lifecycle"""

        audit_entry = {
            "id": str(uuid.uuid4()),
            "decision_id": decision_id,
            "stage": stage,  # validate, retrieve, reason, policy, execute
            "timestamp": time.time(),
            "actor": actor,
            "data_hash": hashlib.sha256(json.dumps(data).encode()).hexdigest(),
            "data_summary": self._summarize(data),
            # Full data stored separately for privacy
        }

        # Store audit entry
        self.db.execute("""
            INSERT INTO decision_audit_trail
            (id, decision_id, stage, timestamp, actor, data_hash, data_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, tuple(audit_entry.values()))

        # Store full data in separate table (access controlled)
        self.db.execute("""
            INSERT INTO decision_audit_data
            (audit_id, data_encrypted)
            VALUES (?, ?)
        """, (audit_entry["id"], self._encrypt(json.dumps(data))))

        self.db.commit()

    async def reconstruct_decision(self, decision_id: str) -> Dict:
        """Reconstruct full decision history for audit"""

        stages = self.db.execute("""
            SELECT t.*, d.data_encrypted
            FROM decision_audit_trail t
            JOIN decision_audit_data d ON t.id = d.audit_id
            WHERE t.decision_id = ?
            ORDER BY t.timestamp ASC
        """, (decision_id,)).fetchall()

        return {
            "decision_id": decision_id,
            "timeline": [
                {
                    "stage": s["stage"],
                    "timestamp": s["timestamp"],
                    "actor": s["actor"],
                    "data": json.loads(self._decrypt(s["data_encrypted"]))
                }
                for s in stages
            ]
        }
```

---

## Eight Data Domains Implementation

### Domain Mapping for ShopSquire

Based on Slide 3, here's how to implement each domain:

### Domain 1: Transactional OLTP

**Current:** PostgreSQL (customers, orders, products, inventory)

**Improvements:**
```sql
-- Add proper constraints and indexes
ALTER TABLE orders ADD CONSTRAINT orders_customer_fk
    FOREIGN KEY (customer_id) REFERENCES customers(id);

CREATE INDEX idx_orders_customer_created
    ON orders(customer_id, created_at DESC);

CREATE INDEX idx_orders_status
    ON orders(status) WHERE status IN ('created', 'paid', 'shipped');

-- Add optimistic locking
ALTER TABLE inventory ADD COLUMN version INTEGER DEFAULT 1;
```

### Domain 2: Event Streams

**Current:** None

**Implementation:**
```python
# Option A: Redis Streams (Simple, good for MVP)
# Option B: Kafka (Production scale)

# For MVP: Redis Streams
class EventStream:
    def __init__(self, redis):
        self.redis = redis

    async def publish(self, stream: str, event: Dict):
        """Publish event to stream"""
        self.redis.xadd(stream, event, maxlen=100000)

    async def subscribe(self, stream: str, consumer_group: str):
        """Subscribe to stream"""
        try:
            self.redis.xgroup_create(stream, consumer_group, id='0', mkstream=True)
        except:
            pass  # Group exists

        while True:
            events = self.redis.xreadgroup(
                consumer_group,
                "consumer-1",
                {stream: ">"},
                count=10,
                block=1000
            )
            for event in events:
                yield event
```

### Domain 3: Time-Series Telemetry

**Current:** Prometheus metrics only

**Implementation:**
```python
# Add decision latency tracking
class DecisionTelemetry:
    def __init__(self, timescale_conn):
        self.conn = timescale_conn

    async def record_decision_latency(
        self,
        decision_id: str,
        agent_name: str,
        stage: str,
        latency_ms: float
    ):
        """Record decision latency to TimescaleDB"""
        self.conn.execute("""
            INSERT INTO decision_latency
            (time, decision_id, agent_name, stage, latency_ms)
            VALUES (NOW(), %s, %s, %s, %s)
        """, (decision_id, agent_name, stage, latency_ms))

# Create hypertable
# CREATE TABLE decision_latency (
#     time TIMESTAMPTZ NOT NULL,
#     decision_id TEXT,
#     agent_name TEXT,
#     stage TEXT,
#     latency_ms DOUBLE PRECISION
# );
# SELECT create_hypertable('decision_latency', 'time');
```

### Domain 4: Searchable Documents

**Current:** SQL LIKE queries

**Implementation:**
```python
# Add PostgreSQL full-text search (simple)
# Or Elasticsearch (production)

# PostgreSQL FTS
class ProductSearch:
    def search(self, query: str, limit: int = 10):
        return self.db.execute("""
            SELECT *, ts_rank(search_vector, query) as rank
            FROM products,
                 plainto_tsquery('english', %s) query
            WHERE search_vector @@ query
            ORDER BY rank DESC
            LIMIT %s
        """, (query, limit)).fetchall()

# Add search vector column
# ALTER TABLE products ADD COLUMN search_vector tsvector;
# UPDATE products SET search_vector =
#     to_tsvector('english', name || ' ' || coalesce(description, ''));
# CREATE INDEX idx_products_search ON products USING GIN(search_vector);
```

### Domain 5: Vector Embeddings

**Current:** None

**Implementation:**
```python
# pgvector extension for PostgreSQL
class VectorStore:
    def __init__(self, db):
        self.db = db

    async def store_embedding(
        self,
        id: str,
        text: str,
        embedding: list[float],
        metadata: Dict
    ):
        self.db.execute("""
            INSERT INTO embeddings (id, text, embedding, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET embedding = EXCLUDED.embedding
        """, (id, text, embedding, json.dumps(metadata)))

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 10
    ) -> list[Dict]:
        return self.db.execute("""
            SELECT id, text, metadata,
                   1 - (embedding <=> %s::vector) as similarity
            FROM embeddings
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (query_embedding, query_embedding, limit)).fetchall()

# Setup:
# CREATE EXTENSION vector;
# CREATE TABLE embeddings (
#     id TEXT PRIMARY KEY,
#     text TEXT,
#     embedding vector(384),  -- nomic-embed-text dimension
#     metadata JSONB
# );
# CREATE INDEX ON embeddings USING ivfflat (embedding vector_cosine_ops);
```

### Domain 6: Graph Relations

**Current:** None (P3 priority)

**For Future:**
```sql
-- PostgreSQL recursive CTEs for simple graphs
-- Or Apache AGE extension for full graph capabilities

-- Fraud ring detection example
WITH RECURSIVE fraud_network AS (
    -- Start from known fraud
    SELECT user_id, related_user_id, 1 as depth
    FROM user_relations
    WHERE user_id IN (SELECT user_id FROM fraud_flags)

    UNION ALL

    -- Traverse connections
    SELECT r.user_id, r.related_user_id, fn.depth + 1
    FROM user_relations r
    JOIN fraud_network fn ON r.user_id = fn.related_user_id
    WHERE fn.depth < 3  -- Limit depth
)
SELECT DISTINCT user_id FROM fraud_network;
```

### Domain 7: Analytics OLAP

**Current:** PostgreSQL views

**Improvements:**
```sql
-- Create materialized views for performance
CREATE MATERIALIZED VIEW analytics.daily_decisions AS
SELECT
    DATE(created_at) as date,
    agent_name,
    execution_status,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (executed_at - created_at))) as avg_latency_sec
FROM audit.decision_logs
GROUP BY DATE(created_at), agent_name, execution_status;

-- Refresh on schedule
CREATE INDEX idx_daily_decisions_date ON analytics.daily_decisions(date);

-- For scale: ClickHouse or DuckDB
```

### Domain 8: Unstructured Blobs

**Current:** Local filesystem

**Implementation:**
```python
# MinIO for S3-compatible object storage
import boto3

class BlobStore:
    def __init__(self, endpoint: str, access_key: str, secret_key: str):
        self.client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )

    async def store(
        self,
        bucket: str,
        key: str,
        data: bytes,
        metadata: Dict
    ) -> str:
        """Store blob and return URL"""
        self.client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            Metadata=metadata
        )
        return f"s3://{bucket}/{key}"

    async def get(self, bucket: str, key: str) -> bytes:
        """Retrieve blob"""
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()

# Buckets:
# - shopsquire-models (model artifacts)
# - shopsquire-exports (compliance exports)
# - shopsquire-evidence (audit evidence packs)
```

---

## API & Service Mesh Strategy

### Current State

```
Single FastAPI Application
├── 47 endpoints in one process
├── No service mesh
├── Basic middleware (CORS, auth)
└── Direct database connections
```

### Target Architecture (Based on Slide 7)

```
┌─────────────────────────────────────────────────────────────────┐
│                    API GATEWAY LAYER                             │
│              (Kong / NGINX / AWS API Gateway)                    │
├─────────────────────────────────────────────────────────────────┤
│ • Rate limiting per client/tier                                 │
│ • Authentication (API key validation)                           │
│ • Request routing                                               │
│ • SSL termination                                               │
│ • Request/response logging                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  API Service     │ │  Decision        │ │  Security        │
│  (Public)        │ │  Service         │ │  Service         │
├──────────────────┤ ├──────────────────┤ ├──────────────────┤
│ /recommend       │ │ /decisions       │ │ /security        │
│ /pricing         │ │ /approvals       │ │ /iam             │
│ /orders          │ │ /audit           │ │ /threats         │
│ /cart            │ │                  │ │                  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SERVICE MESH (Optional)                       │
│              (Istio / Linkerd - when >20 services)              │
├─────────────────────────────────────────────────────────────────┤
│ • mTLS between services                                         │
│ • Traffic management                                            │
│ • Observability (automatic tracing)                             │
│ • Circuit breaking                                              │
└─────────────────────────────────────────────────────────────────┘
```

### API Gateway Configuration

```yaml
# kong.yml - Example Kong configuration
_format_version: "2.1"

services:
  - name: shopsquire-api
    url: http://api:8080
    routes:
      - name: public-api
        paths:
          - /api/v1/recommend
          - /api/v1/pricing
          - /api/v1/orders
          - /api/v1/cart
        plugins:
          - name: rate-limiting
            config:
              minute: 100
              policy: local
          - name: key-auth
            config:
              key_names: ["x-api-key"]

  - name: shopsquire-admin
    url: http://api:8080
    routes:
      - name: admin-api
        paths:
          - /api/v1/admin
          - /api/v1/decisions
        plugins:
          - name: rate-limiting
            config:
              minute: 1000
          - name: key-auth
          - name: acl
            config:
              allow: ["admin-group"]

plugins:
  - name: prometheus
    config:
      per_consumer: true
  - name: correlation-id
    config:
      header_name: X-Request-ID
      generator: uuid
```

---

## Governance & Observability Enhancements

### Data Governance (Based on Slide 7)

```yaml
# Data Catalog Configuration (DataHub/OpenMetadata style)

datasets:
  - name: decision_logs
    schema: audit
    owner: ai-ops-team
    classification: internal
    pii_fields: []
    retention: 7 years
    lineage:
      upstream:
        - api.recommend.suggest
        - api.pricing.suggest
      downstream:
        - analytics.decision_metrics
        - compliance.audit_reports

  - name: security_events
    schema: security
    owner: security-team
    classification: confidential
    pii_fields:
      - source_ip  # Pseudonymize for GDPR
      - user_id    # Hash for analytics
    retention: 3 years
    lineage:
      upstream:
        - middleware.security_observer
      downstream:
        - grafana.security_dashboard
        - siem.export

  - name: orders
    schema: oltp
    owner: commerce-team
    classification: confidential
    pii_fields:
      - customer_email
      - shipping_address
      - payment_token
    retention: 7 years
    lineage:
      upstream:
        - api.orders.create
      downstream:
        - analytics.order_metrics
        - accounting.revenue
```

### Observability Stack Enhancement

```yaml
# docker-compose.observability-enhanced.yml

version: '3.8'

services:
  # Existing
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./config/observability/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./config/observability/prometheus_rules.yml:/etc/prometheus/rules.yml

  grafana:
    image: grafana/grafana:latest
    volumes:
      - ./config/observability/grafana:/etc/grafana/provisioning

  alertmanager:
    image: prom/alertmanager:latest
    volumes:
      - ./config/observability/alertmanager.yml:/etc/alertmanager/alertmanager.yml

  # NEW: Distributed Tracing
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "6831:6831/udp"  # Thrift
    environment:
      - COLLECTOR_OTLP_ENABLED=true

  # NEW: Log Aggregation
  loki:
    image: grafana/loki:latest
    command: -config.file=/etc/loki/config.yml
    volumes:
      - ./config/observability/loki/config.yml:/etc/loki/config.yml

  promtail:
    image: grafana/promtail:latest
    volumes:
      - ./logs:/var/log/shopsquire
      - ./config/observability/loki/promtail.yml:/etc/promtail/config.yml

  # NEW: Metrics for Time-Series Analysis
  victoriametrics:
    image: victoriametrics/victoria-metrics:latest
    command:
      - "--storageDataPath=/storage"
      - "--retentionPeriod=90d"
    volumes:
      - victoria-data:/storage

  # NEW: Data Lineage
  datahub:
    image: linkedin/datahub-gms:latest
    environment:
      - EBEAN_DATASOURCE_URL=jdbc:postgresql://postgres:5432/datahub

volumes:
  victoria-data:
```

### Enhanced Metrics

```python
# src/app/observability/enhanced_metrics.py

from prometheus_client import Counter, Histogram, Gauge, Info

# Decision Pipeline Metrics
decision_pipeline_duration = Histogram(
    'shopsquire_decision_pipeline_seconds',
    'Time spent in each pipeline stage',
    ['agent', 'stage'],  # validate, retrieve, reason, policy, execute
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

decision_outcome = Counter(
    'shopsquire_decision_outcome_total',
    'Decision outcomes',
    ['agent', 'outcome']  # executed, approved, rejected, error
)

# Data Domain Metrics
data_domain_operations = Counter(
    'shopsquire_data_domain_ops_total',
    'Operations by data domain',
    ['domain', 'operation']  # oltp, audit, security, telemetry
)

data_domain_latency = Histogram(
    'shopsquire_data_domain_latency_seconds',
    'Latency by data domain',
    ['domain', 'operation'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# Event Stream Metrics
event_stream_lag = Gauge(
    'shopsquire_event_stream_lag',
    'Consumer lag in event stream',
    ['stream', 'consumer_group']
)

event_stream_throughput = Counter(
    'shopsquire_event_stream_events_total',
    'Events processed',
    ['stream', 'event_type']
)

# Audit Completeness
audit_coverage = Gauge(
    'shopsquire_audit_coverage_percent',
    'Percentage of operations with complete audit trail',
    ['domain']
)
```

---

## Step-by-Step Implementation (Slide 10)

### Mapping to ShopSquire

| Step | Slide 10 Requirement | ShopSquire Status | Action |
|------|---------------------|-------------------|--------|
| 1 | Document SLOs & Constraints | ⚠️ Partial | Complete doc |
| 2 | Inventory Data Domains | ⚠️ Implicit | Explicit mapping |
| 3 | Define Edge/Cloud Split | ❌ Not done | Cloud-only for MVP |
| 4 | Select Truth Model | ✅ Bitemporal | Formalize event-sourcing |
| 5 | Map Storage Types | ⚠️ Single DB | Add polyglot plan |
| 6 | Score & Shortlist Brands | ❌ Not done | Create matrix |
| 7 | Design Data Movement | ⚠️ Basic | Add CDC plan |
| 8 | Execute PoCs | ⚠️ Some testing | Add load/chaos tests |
| 9 | Lock Operational Plan | ⚠️ Partial | Complete runbooks |
| 10 | Standardize & Govern | ⚠️ Informal | Create golden paths |

### Detailed Implementation Plan

#### Step 1: Document SLOs & Constraints

```markdown
# ShopSquire SLO Document

## Latency Targets
| Endpoint | P50 | P95 | P99 |
|----------|-----|-----|-----|
| /recommend | 100ms | 300ms | 500ms |
| /pricing | 50ms | 150ms | 300ms |
| /orders | 200ms | 500ms | 1000ms |
| /decisions | 100ms | 250ms | 500ms |

## Availability
- Overall: 99.9% (8.76 hours downtime/year)
- Decision APIs: 99.95%
- Admin APIs: 99.5%

## Compliance Scope
- PCI DSS: Payment data handling
- GDPR: EU user data
- CCPA: California user data
- SOC 2: All systems

## Retention Policies
| Data Type | Hot | Warm | Cold | Delete |
|-----------|-----|------|------|--------|
| Decision logs | 30d | 90d | 7yr | Never |
| Security events | 7d | 30d | 1yr | 3yr |
| Telemetry | 7d | 30d | 90d | 1yr |
| Orders | 30d | 1yr | 7yr | Never |
```

#### Step 2: Inventory Data Domains

```yaml
# data_domains.yml

domains:
  oltp:
    tables: [customers, orders, products, inventory, draft_orders]
    access_patterns:
      - point_lookups (by id)
      - range_scans (by customer, date)
    volume: ~10GB initial, 100GB/year growth
    consistency: strong

  audit:
    tables: [decision_logs, decision_audits, decision_audit_trail]
    access_patterns:
      - append_only writes
      - time_range queries
      - full_scan for compliance
    volume: ~50GB initial, 500GB/year growth
    consistency: strong

  security:
    tables: [security_events, security_escalations, iam_events]
    access_patterns:
      - high_write (append)
      - filtered_reads (severity, time)
      - aggregations
    volume: ~20GB initial, 200GB/year growth
    consistency: eventual_ok

  telemetry:
    storage: prometheus
    access_patterns:
      - time_range aggregations
      - downsampling
    volume: ~5GB/month
    retention: 90 days

  session:
    storage: redis
    access_patterns:
      - key_value lookups
      - ttl_based eviction
    volume: ~1GB (ephemeral)

  vectors:
    storage: pgvector (planned)
    access_patterns:
      - similarity search
      - batch inserts
    volume: ~10GB
```

#### Step 4: Formalize Truth Model

```python
# Create event_log table as primary source of truth

"""
CREATE TABLE event_log (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    version INTEGER NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT NOT NULL,
    data JSONB NOT NULL,
    metadata JSONB,
    idempotency_key TEXT UNIQUE,

    -- Ensure ordered events per aggregate
    CONSTRAINT unique_aggregate_version
        UNIQUE (aggregate_type, aggregate_id, version)
);

CREATE INDEX idx_event_log_aggregate
    ON event_log(aggregate_type, aggregate_id, version);

CREATE INDEX idx_event_log_timestamp
    ON event_log(timestamp);

CREATE INDEX idx_event_log_type
    ON event_log(type);

-- Trigger to prevent updates/deletes (immutable)
CREATE OR REPLACE FUNCTION prevent_event_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Event log is immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER event_log_immutable
    BEFORE UPDATE OR DELETE ON event_log
    FOR EACH ROW EXECUTE FUNCTION prevent_event_modification();
"""
```

#### Step 8: PoC Tests

```python
# tests/poc/test_load.py

import asyncio
import time
import httpx
from statistics import mean, quantiles

async def load_test_recommendations(concurrent: int, total: int):
    """Load test recommendation endpoint"""

    async def single_request(client):
        start = time.perf_counter()
        response = await client.get(
            "http://localhost:8080/api/v1/recommend/suggest",
            params={"uid": "test_user", "query": "gaming laptop"}
        )
        latency = (time.perf_counter() - start) * 1000
        return latency, response.status_code

    async with httpx.AsyncClient() as client:
        tasks = []
        for _ in range(total):
            tasks.append(single_request(client))
            if len(tasks) >= concurrent:
                results = await asyncio.gather(*tasks)
                yield results
                tasks = []

        if tasks:
            yield await asyncio.gather(*tasks)

async def run_load_test():
    latencies = []
    errors = 0

    async for batch in load_test_recommendations(concurrent=50, total=1000):
        for latency, status in batch:
            latencies.append(latency)
            if status != 200:
                errors += 1

    p50, p95, p99 = quantiles(latencies, n=100)[49], quantiles(latencies, n=100)[94], quantiles(latencies, n=100)[98]

    print(f"P50: {p50:.2f}ms")
    print(f"P95: {p95:.2f}ms")
    print(f"P99: {p99:.2f}ms")
    print(f"Errors: {errors}/{len(latencies)}")

    # Assert SLOs
    assert p50 < 100, f"P50 {p50}ms exceeds 100ms SLO"
    assert p95 < 300, f"P95 {p95}ms exceeds 300ms SLO"
    assert p99 < 500, f"P99 {p99}ms exceeds 500ms SLO"
```

```python
# tests/poc/test_chaos.py

async def test_database_failure_handling():
    """Test graceful degradation when DB fails"""

    # 1. Normal operation
    response = await client.get("/api/v1/recommend/suggest?uid=u1&query=laptop")
    assert response.status_code == 200

    # 2. Simulate DB failure
    await db.close()

    # 3. Should use fallback (rules-based)
    response = await client.get("/api/v1/recommend/suggest?uid=u1&query=laptop")
    assert response.status_code == 200
    assert response.json().get("degraded") == True

    # 4. Restore DB
    await db.connect()

    # 5. Should return to normal
    response = await client.get("/api/v1/recommend/suggest?uid=u1&query=laptop")
    assert response.status_code == 200
    assert response.json().get("degraded") == False
```

---

## Architecture Decision Records

### ADR-001: Event-Sourcing for Decision Audit

**Status:** Accepted

**Context:**
ShopSquire makes autonomous AI decisions that may be disputed. We need forensic-grade auditability.

**Decision:**
Adopt event-sourcing for all decision-related data. The event log is the source of truth; read models are projections.

**Consequences:**
- (+) Full audit trail, time-travel queries
- (+) Can replay with new policies
- (-) More complex than CRUD
- (-) Need to maintain projections

---

### ADR-002: Polyglot Persistence

**Status:** Proposed

**Context:**
Single PostgreSQL for all workloads creates performance bottlenecks and operational complexity.

**Decision:**
Adopt polyglot persistence with purpose-built stores:
- PostgreSQL: OLTP, audit logs
- Redis: Sessions, cache, event streams (MVP)
- pgvector: Embeddings (when needed)
- TimescaleDB: Telemetry (future)

**Consequences:**
- (+) Optimized for each workload
- (+) Independent scaling
- (-) More operational complexity
- (-) Data consistency across stores

---

### ADR-003: Cloud-Only for MVP

**Status:** Accepted

**Context:**
Edge computing adds significant complexity. ShopSquire is web-first e-commerce.

**Decision:**
Skip edge architecture for MVP. Design for cloud-only with future edge extensibility.

**Consequences:**
- (+) Simpler architecture
- (+) Faster to production
- (-) No offline support
- (-) Higher latency for global users

---

## Summary: What to Implement

### Immediate (This Week)

1. **Create SLO document** - Formalize latency/availability targets
2. **Add event_log table** - Formalize event-sourcing
3. **Schema segregation** - Separate OLTP, audit, security schemas
4. **Basic load test** - Validate P95 latency

### Short-Term (Next 2 Weeks)

1. **Redis Streams** - Simple event backbone
2. **pgvector setup** - Enable semantic search
3. **PostgreSQL FTS** - Full-text product search
4. **Chaos testing** - Validate degradation

### Medium-Term (Next Month)

1. **API Gateway** - Kong or NGINX
2. **Jaeger tracing** - Distributed tracing
3. **MinIO** - Object storage for exports
4. **Data lineage** - Document data flows

### Long-Term (Quarter)

1. **Kafka migration** - Production event backbone
2. **TimescaleDB** - Decision telemetry
3. **ClickHouse** - Analytics OLAP
4. **Service mesh** - If >20 services

---

*This document aligns ShopSquire with enterprise retail architecture patterns while maintaining pragmatic scope for current stage.*
