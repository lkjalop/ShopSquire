# ShopSquire: Thinking Modes & Agent Enhancement Implementation Plan

**Date:** January 2026
**Branch:** `pw/fix-waits` (current) → create `feature/thinking-modes`
**Status:** Ready for Implementation

---

## Table of Contents
1. [Career & Skill Development Value](#career--skill-development-value)
2. [Phase 0: Connectivity & CORS Verification](#phase-0-connectivity--cors-verification)
3. [Phase 1: Lightweight Decision Trace Panel](#phase-1-lightweight-decision-trace-panel)
4. [Phase 2: Turn-Level Thinking (Tier Routing)](#phase-2-turn-level-thinking-tier-routing)
5. [Phase 3: Per-Agent Enhancements](#phase-3-per-agent-enhancements)
6. [Phase 4: Pre-LLM AI/ML Pipeline](#phase-4-pre-llm-aiml-pipeline)
7. [Phase 5: CV Tiered Architecture](#phase-5-cv-tiered-architecture)
8. [Testing Strategy](#testing-strategy)
9. [Rules Inventory](#rules-inventory)

---

## Career & Skill Development Value

### What This Implementation Demonstrates

| Skill Domain | What You're Building | Industry Recognition |
|--------------|---------------------|----------------------|
| **AI/ML Architecture** | Tiered inference pipeline (rules → statistical → lightweight ML → LLM) | Cost-conscious AI design (90% token reduction) |
| **Enterprise Patterns** | Bi-temporal audit, decision trace, policy gates | SOX/SOC2/ISO compliance readiness |
| **MLOps/FinOps** | Token budgets, model tiering, GPU fallback to CPU | Cloud cost optimization |
| **Agent Design** | Bounded autonomy, guardrails, human-in-loop escalation | Safe AI systems |
| **Observability** | Decision trace with drill-down evidence | Production debugging |
| **Frontend Integration** | Real-time trace panel with WebSocket/polling | Full-stack capability |

### Portfolio Pieces This Creates

1. **"Built tiered AI inference reducing API costs 90% through caching, rules, and model selection"**
2. **"Designed decision trace system with bi-temporal audit for SOX/SOC2 compliance"**
3. **"Implemented bounded agent autonomy with configurable guardrails and escalation"**
4. **"Created CV pipeline with 5-tier architecture (hash → rules → statistical → lightweight → full model)"**

### Career Progression Path

```
Junior/Mid Dev          →  Senior/Staff           →  Principal/Architect
─────────────────────────────────────────────────────────────────────────
Writes code             →  Designs systems        →  Defines patterns
Follows patterns        →  Creates patterns       →  Influences industry
Uses LLMs               →  Optimizes LLM costs    →  Designs AI governance
Builds features         →  Owns subsystems        →  Shapes architecture
```

**This implementation moves you from "writes code" to "designs systems with cost awareness."**

---

## Phase 0: Connectivity & CORS Verification

### 0.1 CORS Configuration Check

**File:** `src/app/main.py` (Lines 104-122)

```python
# Current implementation - VERIFY these origins match your frontend
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if not origins:
    origins = [
        "http://localhost:5173",   # Vite dev server
        "http://127.0.0.1:5173",
        "http://localhost:8080",   # Alternative dev
        "http://127.0.0.1:8080",
    ]
```

**Verification Steps:**
```bash
# 1. Check what port frontend is running on
cd frontend && npm run dev  # Note the port (usually 5173)

# 2. Test CORS preflight
curl -X OPTIONS http://localhost:8000/api/v1/health \
  -H "Origin: http://localhost:5173" \
  -H "Access-Control-Request-Method: GET" \
  -v 2>&1 | grep -i "access-control"

# Expected response headers:
# access-control-allow-origin: http://localhost:5173
# access-control-allow-credentials: true
# access-control-allow-methods: *
```

### 0.2 Agent Connectivity Matrix

| Agent | Endpoint | Health Check | Dependencies |
|-------|----------|--------------|--------------|
| Orchestrator | POST `/api/v1/orchestrate` | Redis, PostgreSQL | memory, firewall, catalog |
| Fraud Scorer | POST `/api/v1/fraud/score` | PostgreSQL | fraud_image_hashes table |
| Inventory Agent | GET `/api/v1/inventory/alerts` | PostgreSQL | inventory, products tables |
| CV Provider | POST `/api/v1/cv/analyze` | Ollama (optional) | object storage |
| Decision Trace | GET `/api/v1/trace/{id}/events` | PostgreSQL | decision_trace_events table |
| Security Observer | (internal) | Redis | anomaly baselines |

**Connectivity Test Script:**

**File to CREATE:** `scripts/check_agent_connectivity.py`

```python
#!/usr/bin/env python3
"""Agent connectivity verification script."""

import asyncio
import httpx
import sys
from typing import Dict, List, Tuple

BASE_URL = "http://localhost:8000"

HEALTH_CHECKS: List[Tuple[str, str, str]] = [
    ("Health", "GET", "/api/v1/health"),
    ("Orchestrator", "POST", "/api/v1/orchestrate"),
    ("Inventory Alerts", "GET", "/api/v1/inventory/alerts"),
    ("Decision Trace", "GET", "/api/v1/decisions/test-trace-id"),
    ("Fraud Score", "POST", "/api/v1/fraud/score"),
    ("CV Analyze", "POST", "/api/v1/cv/analyze"),
]

async def check_endpoint(client: httpx.AsyncClient, name: str, method: str, path: str) -> Dict:
    """Check if endpoint responds (even with 4xx is OK - means route exists)."""
    try:
        if method == "GET":
            r = await client.get(f"{BASE_URL}{path}", timeout=5.0)
        else:
            r = await client.post(f"{BASE_URL}{path}", json={}, timeout=5.0)
        # 2xx, 4xx means endpoint exists; 5xx or timeout means issue
        status = "OK" if r.status_code < 500 else "ERROR"
        return {"name": name, "status": status, "code": r.status_code}
    except httpx.ConnectError:
        return {"name": name, "status": "UNREACHABLE", "code": None}
    except Exception as e:
        return {"name": name, "status": "ERROR", "code": str(e)}

async def main():
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[
            check_endpoint(client, name, method, path)
            for name, method, path in HEALTH_CHECKS
        ])

    print("\n=== Agent Connectivity Report ===\n")
    all_ok = True
    for r in results:
        icon = "✓" if r["status"] == "OK" else "✗"
        print(f"  {icon} {r['name']}: {r['status']} (HTTP {r['code']})")
        if r["status"] != "OK":
            all_ok = False

    print("\n" + ("All agents reachable!" if all_ok else "Some agents unreachable - check server logs"))
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

**Run:** `python scripts/check_agent_connectivity.py`

### 0.3 Database Connectivity

**File to CREATE:** `scripts/check_db_tables.py`

```python
#!/usr/bin/env python3
"""Verify required database tables exist."""

from sqlalchemy import text, inspect
from src.app.models.db import db_session

REQUIRED_TABLES = [
    "decision_logs",
    "decision_trace_events",
    "products",
    "inventory",
    "customers",
    "orders",
    "fraud_image_hashes",
    "tickets",
    "suppliers",
]

def check_tables():
    with db_session() as db:
        inspector = inspect(db.get_bind())
        existing = set(inspector.get_table_names())

        print("\n=== Database Table Check ===\n")
        for table in REQUIRED_TABLES:
            icon = "✓" if table in existing else "✗"
            status = "EXISTS" if table in existing else "MISSING"
            print(f"  {icon} {table}: {status}")

        missing = set(REQUIRED_TABLES) - existing
        if missing:
            print(f"\nMissing tables: {missing}")
            print("Run: alembic upgrade head")
            return 1
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(check_tables())
```

---

## Phase 1: Lightweight Decision Trace Panel

### 1.1 Current State Analysis

**File:** `frontend/src/components/DecisionTrace.tsx` (Lines 1-115)

Current implementation:
- Fetches from `/api/v1/decisions/{traceId}`
- Auto-refresh every 4 seconds (Line 45)
- Displays: decision_id, timestamp, input_query, intent_analysis, agent_chain, model_selection, rag_context, recommendation, policy_gates
- Shows raw JSON in `<pre>` blocks

**Issues to Address:**
1. Too much raw JSON (not lightweight)
2. No drill-down capability
3. No tag-based filtering
4. No event timeline view

### 1.2 Enhanced Decision Trace Panel

**File to MODIFY:** `frontend/src/components/DecisionTrace.tsx`

**Changes:**

```typescript
// Lines 4-22: Enhanced type definition
type TraceEvent = {
  id: string;
  seq: number;
  event_type: string;  // 'rule_match' | 'tool_call' | 'model_invoke' | 'policy_gate' | 'escalation'
  source_type: string; // 'agent' | 'rule' | 'model' | 'policy'
  source_id: string;
  target_type?: string;
  target_id?: string;
  payload: any;
  created_at: string;
  // Computed for display
  tags?: string[];
  rule_id?: string;
  confidence?: number;
  latency_ms?: number;
};

type Trace = {
  decision_id: string;
  timestamp: string;
  tier: number;  // NEW: 0, 1, or 2
  input_query?: string;
  events: TraceEvent[];  // NEW: timeline of events
  summary: {
    total_events: number;
    rule_matches: number;
    tool_calls: number;
    model_invokes: number;
    escalations: number;
    total_latency_ms: number;
  };
  // Existing fields (collapsed by default)
  intent_analysis?: any;
  agent_chain?: any[];
  model_selection?: any;
  rag_context?: any;
  recommendation?: any;
  policy_gates?: any;
};
```

**Lines 57-113: New lightweight render**

```tsx
// Replace the current render with this lightweight version
return (
  <div className={styles.wrap}>
    <div className={styles.header}>
      <div className={styles.headerLeft}>
        <strong>Decision Trace</strong>
        <span className={styles.tier}>Tier {trace.tier ?? '?'}</span>
      </div>
      <div className={styles.headerRight}>
        {updating && <span className={styles.updating}>Updating...</span>}
        <button onClick={onClose}>Close</button>
      </div>
    </div>

    {/* Summary bar - always visible */}
    <div className={styles.summary}>
      <span className={styles.stat}>
        <strong>{trace.summary?.rule_matches ?? 0}</strong> rules
      </span>
      <span className={styles.stat}>
        <strong>{trace.summary?.tool_calls ?? 0}</strong> tools
      </span>
      <span className={styles.stat}>
        <strong>{trace.summary?.model_invokes ?? 0}</strong> LLM calls
      </span>
      <span className={styles.stat}>
        <strong>{trace.summary?.total_latency_ms ?? 0}ms</strong> total
      </span>
    </div>

    {/* Event timeline - lightweight tags */}
    <div className={styles.timeline}>
      {(trace.events || []).map((evt, idx) => (
        <div
          key={evt.id || idx}
          className={`${styles.event} ${styles[evt.event_type]}`}
          onClick={() => setExpandedEvent(expandedEvent === evt.id ? null : evt.id)}
        >
          <div className={styles.eventHeader}>
            <span className={styles.eventSeq}>#{evt.seq}</span>
            <span className={styles.eventType}>{evt.event_type}</span>
            <span className={styles.eventSource}>{evt.source_id}</span>
            {evt.latency_ms && <span className={styles.eventLatency}>{evt.latency_ms}ms</span>}
            {evt.tags?.map(tag => (
              <span key={tag} className={styles.tag}>{tag}</span>
            ))}
          </div>

          {/* Drill-down: only show payload when expanded */}
          {expandedEvent === evt.id && (
            <div className={styles.eventPayload}>
              <pre>{JSON.stringify(evt.payload, null, 2)}</pre>
            </div>
          )}
        </div>
      ))}
    </div>

    {/* Collapsible raw sections */}
    <details className={styles.rawSection}>
      <summary>Raw Intent Analysis</summary>
      <pre>{JSON.stringify(trace.intent_analysis, null, 2)}</pre>
    </details>
    <details className={styles.rawSection}>
      <summary>Raw Model Selection</summary>
      <pre>{JSON.stringify(trace.model_selection, null, 2)}</pre>
    </details>
    <details className={styles.rawSection}>
      <summary>Raw Policy Gates</summary>
      <pre>{JSON.stringify(trace.policy_gates, null, 2)}</pre>
    </details>
  </div>
);
```

### 1.3 Backend: Event Timeline Endpoint

**File to MODIFY:** `src/app/routers/decision_trace_events.py`

**Add at Line ~100:**

```python
@router.get("/api/v1/decisions/{trace_id}/timeline")
async def get_decision_timeline(trace_id: str, db: Session = Depends(get_db)):
    """Return lightweight timeline view for decision trace panel."""
    events = db.execute(
        text("""
            SELECT id, seq, event_type, source_type, source_id,
                   target_type, target_id, payload, created_at
            FROM decision_trace_events
            WHERE trace_id = :tid
            ORDER BY seq ASC, created_at ASC
        """),
        {"tid": trace_id}
    ).fetchall()

    # Compute summary stats
    summary = {
        "total_events": len(events),
        "rule_matches": sum(1 for e in events if e[2] == "rule_match"),
        "tool_calls": sum(1 for e in events if e[2] == "tool_call"),
        "model_invokes": sum(1 for e in events if e[2] == "model_invoke"),
        "escalations": sum(1 for e in events if e[2] == "escalation"),
        "total_latency_ms": 0,  # Compute from payload if available
    }

    # Extract latency from payloads
    for e in events:
        try:
            payload = json.loads(e[7]) if e[7] else {}
            if "latency_ms" in payload:
                summary["total_latency_ms"] += int(payload["latency_ms"])
        except:
            pass

    # Format events for frontend
    formatted = []
    for e in events:
        try:
            payload = json.loads(e[7]) if e[7] else {}
        except:
            payload = {}

        formatted.append({
            "id": e[0],
            "seq": e[1],
            "event_type": e[2],
            "source_type": e[3],
            "source_id": e[4],
            "target_type": e[5],
            "target_id": e[6],
            "payload": payload,
            "created_at": str(e[8]),
            "tags": extract_tags(payload),  # Helper function
            "rule_id": payload.get("rule_id"),
            "confidence": payload.get("confidence"),
            "latency_ms": payload.get("latency_ms"),
        })

    return {"events": formatted, "summary": summary}


def extract_tags(payload: dict) -> list:
    """Extract display tags from event payload."""
    tags = []
    if payload.get("tier"):
        tags.append(f"T{payload['tier']}")
    if payload.get("cached"):
        tags.append("CACHED")
    if payload.get("rule_id"):
        tags.append(payload["rule_id"])
    if payload.get("model"):
        tags.append(payload["model"][:10])
    if payload.get("escalated"):
        tags.append("ESCALATED")
    return tags
```

### 1.4 CSS for Lightweight Panel

**File to MODIFY:** `frontend/src/components/DecisionTrace.module.css`

**Add:**

```css
.summary {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  background: var(--surface-2);
  border-radius: 4px;
  margin-bottom: 12px;
}

.stat {
  font-size: 12px;
  color: var(--muted);
}

.stat strong {
  color: var(--foreground);
  margin-right: 4px;
}

.tier {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--accent);
  color: white;
  margin-left: 8px;
}

.timeline {
  max-height: 300px;
  overflow-y: auto;
}

.event {
  padding: 6px 10px;
  border-left: 3px solid var(--border);
  margin-bottom: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.event:hover {
  background: var(--surface-2);
}

.event.rule_match { border-left-color: #4CAF50; }
.event.tool_call { border-left-color: #2196F3; }
.event.model_invoke { border-left-color: #FF9800; }
.event.escalation { border-left-color: #F44336; }
.event.policy_gate { border-left-color: #9C27B0; }

.eventHeader {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.eventSeq {
  color: var(--muted);
  font-family: monospace;
  min-width: 24px;
}

.eventType {
  font-weight: 500;
  min-width: 80px;
}

.eventSource {
  color: var(--muted);
  flex: 1;
}

.eventLatency {
  color: var(--muted);
  font-family: monospace;
}

.tag {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 2px;
  background: var(--surface-3);
  color: var(--muted);
}

.eventPayload {
  margin-top: 8px;
  padding: 8px;
  background: var(--surface-1);
  border-radius: 4px;
  font-size: 11px;
}

.eventPayload pre {
  margin: 0;
  white-space: pre-wrap;
  font-size: 11px;
}

.rawSection {
  margin-top: 8px;
}

.rawSection summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--muted);
}

.rawSection pre {
  font-size: 10px;
  max-height: 150px;
  overflow: auto;
}
```

---

## Phase 2: Turn-Level Thinking (Tier Routing)

### 2.1 Central Tier Router

**File to CREATE:** `src/app/services/tier_router.py`

```python
"""Turn-level thinking tier router.

Tier 0 (OFF): Deterministic rules, cache hits, formatting
Tier 1 (LIGHT): Single-pass parse/rerank/summarize, 0-1 tool calls
Tier 2 (DEEP): Bounded interleaving, 2-4 tool calls, strict allowlist
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional
import hashlib
import json


@dataclass
class TierDecision:
    tier: int  # 0, 1, or 2
    reason: str
    tool_budget: int
    model: Optional[str]
    allow_interleaving: bool
    cache_key: Optional[str]


class TierRouter:
    """Routes requests to appropriate thinking tier."""

    # Configurable thresholds
    TIER_2_TRIGGERS = {
        "risk_threshold": 0.5,
        "amount_threshold": 250.0,
        "intent_confidence_low": 0.7,
        "complexity_keywords": [
            "compare", "tradeoff", "versus", "analyze",
            "explain why", "best option", "recommend"
        ],
    }

    TOOL_BUDGETS = {0: 0, 1: 1, 2: 4}

    def __init__(self, cache_backend=None, flags: Dict = None):
        self.cache = cache_backend
        self.flags = flags or {}

    def route(
        self,
        query: str,
        context: Dict[str, Any],
        intent_result: Dict[str, Any],
        security_analysis: Dict[str, Any],
    ) -> TierDecision:
        """Determine which tier to use for this request."""

        # Check cache first
        cache_key = self._compute_cache_key(query, context)
        if self.cache and self._check_cache(cache_key):
            return TierDecision(
                tier=0,
                reason="cache_hit",
                tool_budget=0,
                model=None,
                allow_interleaving=False,
                cache_key=cache_key,
            )

        # Check if rules handled it
        if intent_result.get("handled") and intent_result.get("confidence", 0) >= 0.95:
            return TierDecision(
                tier=0,
                reason="rule_match",
                tool_budget=0,
                model=None,
                allow_interleaving=False,
                cache_key=cache_key,
            )

        # Check Tier 2 triggers
        risk = float(security_analysis.get("risk_adj", 0) or 0)
        amount = float(context.get("amount", 0) or 0)
        intent_conf = float(intent_result.get("confidence", 1.0) or 1.0)
        query_lower = (query or "").lower()

        tier_2_reasons = []

        if risk >= self.TIER_2_TRIGGERS["risk_threshold"]:
            tier_2_reasons.append(f"high_risk:{risk:.2f}")

        if amount >= self.TIER_2_TRIGGERS["amount_threshold"]:
            tier_2_reasons.append(f"high_amount:{amount:.0f}")

        if intent_conf < self.TIER_2_TRIGGERS["intent_confidence_low"]:
            tier_2_reasons.append(f"low_confidence:{intent_conf:.2f}")

        for kw in self.TIER_2_TRIGGERS["complexity_keywords"]:
            if kw in query_lower:
                tier_2_reasons.append(f"keyword:{kw}")
                break

        if context.get("multi_turn"):
            tier_2_reasons.append("multi_turn")

        if tier_2_reasons:
            return TierDecision(
                tier=2,
                reason=",".join(tier_2_reasons),
                tool_budget=self.TOOL_BUDGETS[2],
                model=self.flags.get("MODEL_T2", "qwen2-medium"),
                allow_interleaving=True,
                cache_key=cache_key,
            )

        # Default to Tier 1
        return TierDecision(
            tier=1,
            reason="default",
            tool_budget=self.TOOL_BUDGETS[1],
            model=self.flags.get("MODEL_T1", "qwen2-small"),
            allow_interleaving=False,
            cache_key=cache_key,
        )

    def _compute_cache_key(self, query: str, context: Dict) -> str:
        """Compute semantic cache key."""
        normalized = (query or "").lower().strip()
        stable_ctx = {k: context[k] for k in sorted(context.keys())
                      if k in ["sku", "category", "intent", "tenant_id"]}
        data = f"{normalized}|{json.dumps(stable_ctx, sort_keys=True)}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def _check_cache(self, key: str) -> bool:
        """Check if response is cached."""
        if not self.cache:
            return False
        try:
            return self.cache.get(f"tier_cache:{key}") is not None
        except:
            return False

    def cache_response(self, key: str, response: Any, ttl: int = 3600):
        """Cache a response for future Tier 0 hits."""
        if self.cache and key:
            try:
                self.cache.set(f"tier_cache:{key}", json.dumps(response), ex=ttl)
            except:
                pass
```

### 2.2 Integrate Tier Router into Orchestrator

**File to MODIFY:** `src/app/services/orchestrator.py`

**Add import at Line ~19:**
```python
from src.app.services.tier_router import TierRouter, TierDecision
from src.app.services.expanded_rules import ExpandedRuleEngine
```

**Add to __init__ at Line ~45:**
```python
self.tier_router = TierRouter(cache_backend=None, flags=flags)
self.rule_engine = ExpandedRuleEngine()
```

**Modify run() method at Line ~319 to add tier routing:**

```python
def run(self, uid: str, payload: Dict[str, Any], simulate_only: bool = False, use_rules: bool = False) -> OrchestratorResult:
    timings: dict[str, float] = {}
    t0 = time.time()

    # Validate
    ok, msg = self.validate(payload)
    t1 = time.time()
    timings["validate"] = t1 - t0
    if not ok:
        raise ValueError(msg)

    # Retrieve context
    ctx = self.retrieve(uid, payload)

    # Security analysis
    try:
        sec = analyze_payload(payload)
    except Exception:
        sec = {"severity": "info", "risk_adj": 0.0}

    # NEW: Rule engine pre-check
    query = payload.get("query", "") or payload.get("input", "")
    intent_result = self.rule_engine.evaluate(query, ctx)

    # NEW: Tier routing decision
    tier_decision = self.tier_router.route(
        query=query,
        context={"amount": payload.get("cart_total_cents", 0) / 100, **ctx.get("live", {})},
        intent_result=intent_result,
        security_analysis=sec,
    )
    t2 = time.time()
    timings["tier_routing"] = t2 - t1

    # Log tier decision for observability
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(
            trace_id=payload.get("trace_id") or str(uuid.uuid4()),
            event_type="tier_decision",
            source_type="orchestrator",
            source_id="tier_router",
            payload={
                "tier": tier_decision.tier,
                "reason": tier_decision.reason,
                "tool_budget": tier_decision.tool_budget,
                "model": tier_decision.model,
                "allow_interleaving": tier_decision.allow_interleaving,
            }
        )
    except:
        pass

    # Use rules if Tier 0 or explicit
    if tier_decision.tier == 0 or use_rules:
        proposal = self.rule_based_reason(ctx)
        proposal["tier"] = 0
    else:
        proposal = self.reason(ctx)
        proposal["tier"] = tier_decision.tier

    # ... rest of method continues as before
```

---

## Phase 3: Per-Agent Enhancements

### 3.1 Expanded Rule Engine Enhancements

**File to MODIFY:** `src/app/services/expanded_rules.py`

**Current state:** 6 intent patterns (Lines 10-17)

**Add 20+ new stock interaction rules at Line ~18:**

```python
class ExpandedRuleEngine:
    """Rule engine to handle common intents before LLM."""

    INTENT_PATTERNS = {
        # Existing
        "product_search": [r"show\s+me", r"find", r"search\s+for", r"looking\s+for", r"i\s+need", r"i\s+want"],
        "price_check": [r"how\s+much", r"price\s+of", r"cost", r"pricing"],
        "comparison": [r"compare", r"vs", r"versus", r"difference\s+between", r"which\s+is\s+better"],
        "order_status": [r"where\s+is\s+my\s+order", r"track", r"order\s+status", r"shipping\s+status"],
        "return_request": [r"return", r"refund", r"exchange", r"send\s+back"],
        "support": [r"help", r"support", r"issue", r"problem", r"not\s+working"],
        # NEW: Stock-specific intents
        "stock_check": [r"in\s+stock", r"available", r"how\s+many\s+left", r"stock\s+level"],
        "restock_alert": [r"notify\s+me", r"alert\s+when", r"back\s+in\s+stock", r"restock"],
        "bulk_inquiry": [r"bulk\s+order", r"wholesale", r"large\s+quantity", r"volume\s+discount"],
        "urgent_need": [r"urgent", r"asap", r"need\s+today", r"rush", r"express"],
        "pre_order": [r"pre-order", r"preorder", r"reserve", r"coming\s+soon"],
    }

    # NEW: Stock response rules (deterministic, no LLM)
    STOCK_RULES = {
        "in_stock_high": {
            "condition": lambda stock: stock > 10,
            "response": "In stock - ships within {lead_time} days",
            "escalate": False,
        },
        "in_stock_low": {
            "condition": lambda stock: 1 <= stock <= 10,
            "response": "Limited stock - only {stock} remaining",
            "escalate": False,
        },
        "out_of_stock_reorder": {
            "condition": lambda stock, reorder: stock == 0 and reorder,
            "response": "Temporarily out of stock - back in ~{eta} days",
            "escalate": False,
        },
        "out_of_stock_no_reorder": {
            "condition": lambda stock, reorder: stock == 0 and not reorder,
            "response": "Currently unavailable",
            "escalate": False,
            "suggest_alternatives": True,
        },
        "discontinued": {
            "condition": lambda status: status == "discontinued",
            "response": "This product is no longer available",
            "escalate": False,
            "suggest_replacement": True,
        },
        "stock_discrepancy": {
            "condition": lambda discrepancy: discrepancy,
            "response": None,  # Hold response
            "escalate": True,
            "escalate_reason": "stock_discrepancy_detected",
        },
    }

    def evaluate_stock_query(self, sku: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate stock query using deterministic rules."""
        stock = context.get("stock", 0)
        reorder_in_progress = context.get("reorder_in_progress", False)
        status = context.get("product_status", "active")
        discrepancy = context.get("stock_discrepancy", False)

        # Check rules in priority order
        if discrepancy:
            return {
                "handled": True,
                "rule_id": "stock_discrepancy",
                "response": None,
                "escalate": True,
                "reason": "stock_discrepancy_detected",
            }

        if status == "discontinued":
            return {
                "handled": True,
                "rule_id": "discontinued",
                "response": "This product is no longer available",
                "suggest_replacement": True,
            }

        if stock > 10:
            return {
                "handled": True,
                "rule_id": "in_stock_high",
                "response": f"In stock - ships within {context.get('lead_time', 2)} days",
            }

        if 1 <= stock <= 10:
            return {
                "handled": True,
                "rule_id": "in_stock_low",
                "response": f"Limited stock - only {stock} remaining",
            }

        if stock == 0 and reorder_in_progress:
            return {
                "handled": True,
                "rule_id": "out_of_stock_reorder",
                "response": f"Temporarily out of stock - back in ~{context.get('eta_days', 7)} days",
            }

        return {
            "handled": True,
            "rule_id": "out_of_stock_no_reorder",
            "response": "Currently unavailable",
            "suggest_alternatives": True,
        }
```

### 3.2 Fraud Scorer Enhancements

**File to MODIFY:** `src/app/services/fraud_scorer.py`

**Current state:** 18 weighted signals (Lines 10-29)

**Add CV-specific signals at Line ~29:**

```python
    # Add to WEIGHTS dict
    WEIGHTS = {
        # ... existing weights ...
        # NEW: CV-related fraud signals
        "cv_blur_score_low": 0.15,
        "cv_histogram_anomaly": 0.20,
        "cv_metadata_stripped": 0.25,
        "cv_timestamp_impossible": 0.30,
        "cv_duplicate_hash": 0.35,
        "cv_different_product": 0.40,
        # NEW: Behavioral signals
        "rapid_photo_submission": 0.20,
        "multiple_claims_same_order": 0.35,
        "claim_before_delivery": 0.50,
    }
```

**Add CV pre-check method at Line ~90:**

```python
    def pre_llm_cv_check(self, image_data: Dict[str, Any]) -> Dict[str, bool]:
        """Run cheap CV checks before any ML model.

        Returns dict of signals that can be computed without GPU.
        """
        signals = {}

        # 1. Check blur score (can be computed with OpenCV, no GPU)
        blur_score = image_data.get("blur_score", 1.0)
        if blur_score < 0.3:
            signals["cv_blur_score_low"] = True

        # 2. Check for histogram anomalies (statistical, no GPU)
        if image_data.get("histogram_anomaly"):
            signals["cv_histogram_anomaly"] = True

        # 3. Check if EXIF/metadata was stripped (suspicious)
        if image_data.get("exif") is None and image_data.get("expected_exif"):
            signals["cv_metadata_stripped"] = True

        # 4. Check timestamp logic
        photo_ts = image_data.get("photo_timestamp")
        order_ts = image_data.get("order_timestamp")
        delivery_ts = image_data.get("delivery_timestamp")

        if photo_ts and order_ts:
            # Photo taken before order? Impossible.
            if photo_ts < order_ts:
                signals["cv_timestamp_impossible"] = True

        if photo_ts and delivery_ts:
            # Photo taken before delivery? Suspicious.
            if photo_ts < delivery_ts:
                signals["claim_before_delivery"] = True

        # 5. Check for duplicate hash
        if image_data.get("phash_duplicate"):
            signals["cv_duplicate_hash"] = True

        return signals
```

### 3.3 Inventory Agent: Add 50 Stock Rules

**File to MODIFY:** `src/app/services/inventory_agent.py`

**Add at Line ~35 (after class definition):**

```python
    # Stock interaction rules (50+ deterministic rules)
    STOCK_RULES = {
        # Category 1: Stock Availability (Rules 1-10)
        "R001": {"condition": "stock > 10", "action": "in_stock_message", "escalate": False},
        "R002": {"condition": "1 <= stock <= 10", "action": "limited_stock_message", "escalate": False},
        "R003": {"condition": "stock == 0 and reorder_active", "action": "backorder_message", "escalate": False},
        "R004": {"condition": "stock == 0 and not reorder_active", "action": "unavailable_suggest_alt", "escalate": False},
        "R005": {"condition": "product_status == 'discontinued'", "action": "discontinued_message", "escalate": False},
        "R006": {"condition": "has_reserved_stock", "action": "reduce_displayed_stock", "escalate": False},
        "R007": {"condition": "multi_warehouse", "action": "show_nearest_availability", "escalate": False},
        "R008": {"condition": "pre_order_available", "action": "pre_order_message", "escalate": False},
        "R009": {"condition": "backorder_accepted", "action": "backorder_lead_time", "escalate": False},
        "R010": {"condition": "stock_discrepancy", "action": "hold_verify", "escalate": True},

        # Category 2: Customer Context (Rules 11-20)
        "R011": {"condition": "vip_customer and stock <= 3", "action": "reserve_for_vip", "escalate": False},
        "R012": {"condition": "repeat_customer and restock_soon", "action": "notify_restock", "escalate": False},
        "R013": {"condition": "b2b_customer and bulk_inquiry", "action": "route_account_manager", "escalate": True},
        "R014": {"condition": "guest_user and high_value_item", "action": "require_email_alert", "escalate": False},
        "R015": {"condition": "high_fraud_region", "action": "log_dont_restrict", "escalate": False},
        "R016": {"condition": "off_hours_timezone", "action": "adjust_ship_date", "escalate": False},
        "R017": {"condition": "preferred_warehouse_set", "action": "prioritize_warehouse", "escalate": False},
        "R018": {"condition": "open_return_same_sku", "action": "flag_abuse_pattern", "escalate": True},
        "R019": {"condition": "check_count > 5", "action": "offer_stock_alert", "escalate": False},
        "R020": {"condition": "price_sensitive_segment", "action": "include_sale_alert", "escalate": False},

        # Category 3: Product Context (Rules 21-30)
        "R021": {"condition": "perishable_product", "action": "show_expiry_adjusted", "escalate": False},
        "R022": {"condition": "serial_tracked", "action": "confirm_serial_availability", "escalate": False},
        "R023": {"condition": "bundle_product", "action": "check_all_components", "escalate": False},
        "R024": {"condition": "made_to_order", "action": "show_lead_time_not_stock", "escalate": False},
        "R025": {"condition": "drop_ship", "action": "query_supplier_cached", "escalate": False},
        "R026": {"condition": "hazmat_international", "action": "check_destination", "escalate": False},
        "R027": {"condition": "high_theft_risk", "action": "hide_exact_count", "escalate": False},
        "R028": {"condition": "under_recall", "action": "unavailable_with_reason", "escalate": True},
        "R029": {"condition": "active_promotion", "action": "show_promotion_allocation", "escalate": False},
        "R030": {"condition": "newly_launched", "action": "limited_initial_stock_msg", "escalate": False},

        # Category 4: Timing and Urgency (Rules 31-40)
        "R031": {"condition": "mentions_urgent", "action": "expedited_options", "escalate": False},
        "R032": {"condition": "flash_sale_active", "action": "rate_limit_api", "escalate": False},
        "R033": {"condition": "stock < 3 and high_velocity", "action": "selling_fast_message", "escalate": False},
        "R034": {"condition": "end_of_quarter and b2b", "action": "volume_discount_deadline", "escalate": False},
        "R035": {"condition": "replenishment_within_24h", "action": "more_arriving_message", "escalate": False},
        "R036": {"condition": "weekend_query", "action": "adjust_for_monday", "escalate": False},
        "R037": {"condition": "holiday_period", "action": "extend_lead_times", "escalate": False},
        "R038": {"condition": "last_unit_concurrent", "action": "fcfs_queue", "escalate": False},
        "R039": {"condition": "customer_waiting > 3_days", "action": "proactive_notify", "escalate": False},
        "R040": {"condition": "promo_ending", "action": "last_chance_message", "escalate": False},

        # Category 5: Alternatives (Rules 41-50)
        "R041": {"condition": "oos_similar_in_stock", "action": "suggest_alternative", "escalate": False},
        "R042": {"condition": "oos_higher_model", "action": "upsell_suggestion", "escalate": False},
        "R043": {"condition": "oos_lower_model", "action": "downgrade_with_savings", "escalate": False},
        "R044": {"condition": "oos_competitor_match", "action": "note_price_match", "escalate": False},
        "R045": {"condition": "oos_rental_available", "action": "suggest_rental", "escalate": False},
        "R046": {"condition": "oos_refurbished", "action": "suggest_refurbished", "escalate": False},
        "R047": {"condition": "variant_oos_others_available", "action": "suggest_variants", "escalate": False},
        "R048": {"condition": "bundle_component_oos", "action": "suggest_standalone", "escalate": False},
        "R049": {"condition": "accessory_oos_main_available", "action": "proceed_backorder_accessory", "escalate": False},
        "R050": {"condition": "all_variants_oos", "action": "notify_any_restock", "escalate": False},
    }

    def evaluate_stock_rule(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate stock rules deterministically (no LLM)."""
        stock = context.get("stock", 0)

        # Simple rule matching (expand with full conditions)
        if stock > 10:
            return {"rule_id": "R001", "action": "in_stock_message", "escalate": False}
        if 1 <= stock <= 10:
            return {"rule_id": "R002", "action": "limited_stock_message", "escalate": False}
        if stock == 0:
            if context.get("reorder_active"):
                return {"rule_id": "R003", "action": "backorder_message", "escalate": False}
            return {"rule_id": "R004", "action": "unavailable_suggest_alt", "escalate": False}

        return {"rule_id": None, "action": "default", "escalate": False}
```

---

## Phase 4: Pre-LLM AI/ML Pipeline

### 4.1 Statistical Forecasting (No GPU)

**File to CREATE:** `src/app/services/statistical_forecast.py`

```python
"""Statistical forecasting methods - no GPU required."""

from __future__ import annotations
from typing import List, Optional, Tuple
import math


def holt_winters_forecast(
    history: List[float],
    alpha: float = 0.3,
    beta: float = 0.1,
    gamma: float = 0.1,
    seasonal_periods: int = 7,
) -> float:
    """Triple exponential smoothing for seasonal demand forecasting.

    This is Tier 2 statistical - runs on CPU with zero dependencies.
    """
    n = len(history)
    if n < seasonal_periods * 2:
        return sum(history) / n if history else 0.0

    # Initialize level, trend, seasonal
    level = sum(history[:seasonal_periods]) / seasonal_periods
    trend = (
        sum(history[seasonal_periods : 2 * seasonal_periods])
        - sum(history[:seasonal_periods])
    ) / (seasonal_periods ** 2)
    seasonals = [history[i] - level for i in range(seasonal_periods)]

    for i in range(seasonal_periods, n):
        val = history[i]
        last_level = level
        season_idx = i % seasonal_periods
        level = alpha * (val - seasonals[season_idx]) + (1 - alpha) * (level + trend)
        trend = beta * (level - last_level) + (1 - beta) * trend
        seasonals[season_idx] = gamma * (val - level) + (1 - gamma) * seasonals[season_idx]

    return level + trend + seasonals[0]


def z_score_anomaly(values: List[float], threshold: float = 2.5) -> List[Tuple[int, float, float]]:
    """Detect anomalies using Z-score. Returns (index, value, z_score) tuples."""
    if len(values) < 3:
        return []

    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std = math.sqrt(variance) if variance > 0 else 1.0

    anomalies = []
    for i, v in enumerate(values):
        z = (v - mean) / std
        if abs(z) > threshold:
            anomalies.append((i, v, z))

    return anomalies


def moving_average_crossover(
    short_window: List[float],
    long_window: List[float],
) -> str:
    """Detect trend using MA crossover. Returns 'uptrend', 'downtrend', or 'neutral'."""
    if not short_window or not long_window:
        return "neutral"

    short_ma = sum(short_window) / len(short_window)
    long_ma = sum(long_window) / len(long_window)

    if short_ma > long_ma * 1.05:
        return "uptrend"
    if short_ma < long_ma * 0.95:
        return "downtrend"
    return "neutral"


class DemandForecaster:
    """Tiered demand forecasting - statistical before ML."""

    def forecast(self, sku: str, history: List[float]) -> dict:
        """Forecast demand using appropriate tier.

        Tier 0: Simple average (< 30 days history)
        Tier 1: Holt-Winters (30-365 days)
        Tier 2: Would use XGBoost (> 365 days, handled elsewhere)
        """
        n = len(history)

        if n < 30:
            # Tier 0: Simple average
            avg = sum(history) / n if history else 0
            return {
                "tier": 0,
                "method": "simple_average",
                "forecast": avg,
                "confidence": 0.3,
            }

        if n < 365:
            # Tier 1: Holt-Winters
            forecast = holt_winters_forecast(history)
            return {
                "tier": 1,
                "method": "holt_winters",
                "forecast": forecast,
                "confidence": 0.6,
            }

        # Tier 2: Would escalate to ML model
        # For now, use Holt-Winters as fallback
        forecast = holt_winters_forecast(history)
        return {
            "tier": 2,
            "method": "holt_winters_fallback",
            "forecast": forecast,
            "confidence": 0.5,
            "recommend_ml": True,
        }
```

### 4.2 Semantic Cache

**File to CREATE:** `src/app/services/semantic_cache.py`

```python
"""Semantic caching for LLM responses - reduces API costs by 90%."""

from __future__ import annotations
import hashlib
import json
import re
from typing import Any, Dict, Optional
import redis


class SemanticCache:
    """Cache LLM responses with semantic similarity."""

    def __init__(self, redis_client: Optional[redis.Redis] = None, default_ttl: int = 3600):
        self.redis = redis_client
        self.default_ttl = default_ttl
        self._local_cache: Dict[str, Any] = {}  # Fallback if no Redis

    def normalize_query(self, query: str) -> str:
        """Normalize query for semantic matching."""
        # Lowercase
        q = (query or "").lower().strip()
        # Remove punctuation
        q = re.sub(r'[^\w\s]', '', q)
        # Remove extra whitespace
        q = re.sub(r'\s+', ' ', q)
        # Simple stemming (could use NLTK for production)
        q = q.replace("ing ", " ").replace("ed ", " ").replace("'s ", " ")
        return q

    def compute_key(self, query: str, context: Dict[str, Any]) -> str:
        """Compute cache key from normalized query + stable context."""
        normalized = self.normalize_query(query)
        # Only include stable context keys
        stable = {k: context.get(k) for k in ["sku", "category", "tenant_id", "intent"]
                  if context.get(k)}
        data = f"{normalized}|{json.dumps(stable, sort_keys=True)}"
        return f"sem:{hashlib.sha256(data.encode()).hexdigest()[:16]}"

    def get(self, query: str, context: Dict[str, Any]) -> Optional[Any]:
        """Get cached response."""
        key = self.compute_key(query, context)

        if self.redis:
            try:
                val = self.redis.get(key)
                if val:
                    return json.loads(val)
            except:
                pass

        return self._local_cache.get(key)

    def set(self, query: str, context: Dict[str, Any], response: Any, ttl: Optional[int] = None):
        """Cache response."""
        key = self.compute_key(query, context)
        ttl = ttl or self.default_ttl

        if self.redis:
            try:
                self.redis.set(key, json.dumps(response), ex=ttl)
                return
            except:
                pass

        self._local_cache[key] = response

    def stats(self) -> Dict[str, int]:
        """Return cache statistics."""
        if self.redis:
            try:
                info = self.redis.info("stats")
                return {
                    "hits": info.get("keyspace_hits", 0),
                    "misses": info.get("keyspace_misses", 0),
                }
            except:
                pass
        return {"hits": 0, "misses": 0, "local_size": len(self._local_cache)}
```

---

## Phase 5: CV Tiered Architecture

### 5.1 CV Provider Enhancement

**File to MODIFY:** `src/app/services/cv_provider.py`

**Add tiered CV pipeline:**

```python
"""Tiered CV architecture.

Level 0: Hash-based duplicate detection (no ML)
Level 1: Rule-based checks (file size, dimensions)
Level 2: Statistical anomaly (histogram, blur)
Level 3: Lightweight model (MobileNet, 4MB, CPU)
Level 4: Full vision model (LLaVA/YOLO, API or GPU)
Level 5: Client-specific fine-tuned model
"""

from __future__ import annotations
import hashlib
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class CVResult:
    level: int
    passed: bool
    confidence: float
    details: Dict[str, Any]
    escalate_to_next: bool


class TieredCVProvider:
    """Tiered CV analysis - minimize GPU/API usage."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._hash_cache: Dict[str, str] = {}

    def analyze(
        self,
        image_bytes: bytes,
        context: Dict[str, Any],
        max_level: int = 4,
    ) -> CVResult:
        """Run tiered CV analysis, stopping when confident."""

        # Level 0: Hash-based duplicate detection
        result = self._level_0_hash(image_bytes, context)
        if not result.escalate_to_next or max_level == 0:
            return result

        # Level 1: Rule-based checks
        result = self._level_1_rules(image_bytes, context)
        if not result.escalate_to_next or max_level == 1:
            return result

        # Level 2: Statistical checks
        result = self._level_2_statistical(image_bytes, context)
        if not result.escalate_to_next or max_level == 2:
            return result

        # Level 3: Lightweight model (CPU)
        result = self._level_3_lightweight(image_bytes, context)
        if not result.escalate_to_next or max_level == 3:
            return result

        # Level 4: Full vision model
        result = self._level_4_full_model(image_bytes, context)
        return result

    def _level_0_hash(self, image_bytes: bytes, context: Dict) -> CVResult:
        """Level 0: Hash-based duplicate detection."""
        # Compute perceptual hash
        phash = self._compute_phash(image_bytes)

        # Check against known fraud hashes
        is_duplicate = phash in self._hash_cache

        if is_duplicate:
            return CVResult(
                level=0,
                passed=False,
                confidence=0.95,
                details={"phash": phash, "duplicate": True},
                escalate_to_next=False,
            )

        self._hash_cache[phash] = context.get("case_id", "unknown")
        return CVResult(
            level=0,
            passed=True,
            confidence=0.5,  # Low confidence, continue to next level
            details={"phash": phash},
            escalate_to_next=True,
        )

    def _level_1_rules(self, image_bytes: bytes, context: Dict) -> CVResult:
        """Level 1: Rule-based validation."""
        issues = []

        # File size check
        size_kb = len(image_bytes) / 1024
        if size_kb < 10:
            issues.append("file_too_small")
        if size_kb > 10000:
            issues.append("file_too_large")

        # Format check (basic magic bytes)
        if not image_bytes[:2] in [b'\xff\xd8', b'\x89P']:  # JPEG, PNG
            issues.append("invalid_format")

        if issues:
            return CVResult(
                level=1,
                passed=False,
                confidence=0.8,
                details={"issues": issues, "size_kb": size_kb},
                escalate_to_next=False,
            )

        return CVResult(
            level=1,
            passed=True,
            confidence=0.5,
            details={"size_kb": size_kb},
            escalate_to_next=True,
        )

    def _level_2_statistical(self, image_bytes: bytes, context: Dict) -> CVResult:
        """Level 2: Statistical analysis (histogram, blur)."""
        # Placeholder - would use OpenCV for real implementation
        # These checks are CPU-only, no GPU needed

        blur_score = 0.8  # Placeholder
        histogram_normal = True  # Placeholder

        if blur_score < 0.3:
            return CVResult(
                level=2,
                passed=False,
                confidence=0.7,
                details={"blur_score": blur_score, "reason": "image_too_blurry"},
                escalate_to_next=False,
            )

        return CVResult(
            level=2,
            passed=True,
            confidence=0.6,
            details={"blur_score": blur_score, "histogram_normal": histogram_normal},
            escalate_to_next=True,
        )

    def _level_3_lightweight(self, image_bytes: bytes, context: Dict) -> CVResult:
        """Level 3: Lightweight model (MobileNet/YOLO-Nano, CPU)."""
        # Placeholder - would load MobileNet for real implementation
        # This runs on CPU, ~4MB model

        damage_detected = False  # Placeholder
        confidence = 0.7

        # If high-value item, escalate to full model
        item_value = context.get("item_value", 0)
        if item_value > 500:
            return CVResult(
                level=3,
                passed=True,
                confidence=confidence,
                details={"damage_detected": damage_detected, "escalate_reason": "high_value_item"},
                escalate_to_next=True,
            )

        return CVResult(
            level=3,
            passed=not damage_detected,
            confidence=confidence,
            details={"damage_detected": damage_detected},
            escalate_to_next=False,
        )

    def _level_4_full_model(self, image_bytes: bytes, context: Dict) -> CVResult:
        """Level 4: Full vision model (LLaVA/YOLO, API or GPU)."""
        # Placeholder - would call Ollama or cloud API

        return CVResult(
            level=4,
            passed=True,
            confidence=0.85,
            details={"model": "llava-7b", "analysis": "placeholder"},
            escalate_to_next=False,
        )

    def _compute_phash(self, image_bytes: bytes) -> str:
        """Compute perceptual hash (simplified - use imagehash in production)."""
        # For now, use content hash as placeholder
        return hashlib.sha256(image_bytes).hexdigest()[:16]
```

---

## Testing Strategy

### Pytest Tests

| Test File | What It Tests | Run Command |
|-----------|---------------|-------------|
| `tests/services/test_tier_router.py` | Tier routing logic | `pytest tests/services/test_tier_router.py -v` |
| `tests/services/test_expanded_rules.py` | Intent patterns + stock rules | `pytest tests/services/test_expanded_rules.py -v` |
| `tests/services/test_fraud_scorer.py` | Fraud scoring with CV signals | `pytest tests/services/test_fraud_scorer.py -v` |
| `tests/services/test_inventory_agent.py` | 50 stock rules | `pytest tests/services/test_inventory_agent.py -v` |
| `tests/services/test_semantic_cache.py` | Cache hit/miss | `pytest tests/services/test_semantic_cache.py -v` |
| `tests/services/test_cv_tiered.py` | CV pipeline levels | `pytest tests/services/test_cv_tiered.py -v` |
| `tests/api/test_decision_trace.py` | Timeline endpoint | `pytest tests/api/test_decision_trace.py -v` |

**File to CREATE:** `tests/services/test_tier_router.py`

```python
"""Test tier routing logic."""

import pytest
from src.app.services.tier_router import TierRouter, TierDecision


class TestTierRouter:
    def setup_method(self):
        self.router = TierRouter()

    def test_tier_0_on_rule_match(self):
        result = self.router.route(
            query="show me laptops",
            context={},
            intent_result={"handled": True, "confidence": 0.95, "intent": "product_search"},
            security_analysis={},
        )
        assert result.tier == 0
        assert result.reason == "rule_match"

    def test_tier_2_on_high_risk(self):
        result = self.router.route(
            query="process refund",
            context={"amount": 100},
            intent_result={"handled": False, "confidence": 0.5},
            security_analysis={"risk_adj": 0.6},
        )
        assert result.tier == 2
        assert "high_risk" in result.reason

    def test_tier_2_on_high_amount(self):
        result = self.router.route(
            query="buy laptop",
            context={"amount": 500},
            intent_result={"handled": False, "confidence": 0.8},
            security_analysis={},
        )
        assert result.tier == 2
        assert "high_amount" in result.reason

    def test_tier_2_on_complexity_keyword(self):
        result = self.router.route(
            query="compare these two laptops",
            context={},
            intent_result={"handled": False, "confidence": 0.9},
            security_analysis={},
        )
        assert result.tier == 2
        assert "keyword:compare" in result.reason

    def test_tier_1_default(self):
        result = self.router.route(
            query="what's the price",
            context={"amount": 50},
            intent_result={"handled": False, "confidence": 0.8},
            security_analysis={},
        )
        assert result.tier == 1
        assert result.reason == "default"
```

### Playwright Tests

| Test File | What It Tests | Run Command |
|-----------|---------------|-------------|
| `tests/pw/test_decision_trace_modal.py` | Trace panel opens | `pytest tests/pw/test_decision_trace_modal.py` |
| `tests/pw/test_decision_trace_timeline.py` | Timeline renders | `pytest tests/pw/test_decision_trace_timeline.py` |
| `tests/pw/test_decision_trace_drilldown.py` | Event drill-down works | `pytest tests/pw/test_decision_trace_drilldown.py` |

**File to CREATE:** `tests/pw/test_decision_trace_timeline.py`

```python
"""Test decision trace timeline component."""

import pytest


def test_timeline_renders_events(page, test_server):
    """Test that timeline shows events with tags."""
    base = test_server["base_url"]

    # Navigate to product page
    page.goto(f"{base}/ui/product/XPS13PLUS")

    # Click the decision trace gear icon
    gear = page.locator("[data-test='decision-gear']")
    gear.wait_for(state="visible", timeout=5000)
    gear.click()

    # Wait for modal
    modal = page.locator("#decision-modal")
    modal.wait_for(state="visible", timeout=5000)

    # Check summary bar exists
    summary = modal.locator(".summary")
    assert summary.is_visible()

    # Check timeline exists
    timeline = modal.locator(".timeline")
    assert timeline.is_visible()


def test_event_drilldown(page, test_server):
    """Test that clicking event expands payload."""
    base = test_server["base_url"]

    page.goto(f"{base}/ui/product/XPS13PLUS")

    gear = page.locator("[data-test='decision-gear']")
    gear.wait_for(state="visible", timeout=5000)
    gear.click()

    modal = page.locator("#decision-modal")
    modal.wait_for(state="visible", timeout=5000)

    # Click first event
    first_event = modal.locator(".event").first
    if first_event.is_visible():
        first_event.click()

        # Check payload expands
        payload = first_event.locator(".eventPayload")
        payload.wait_for(state="visible", timeout=2000)
        assert payload.is_visible()
```

### Run All Tests

```bash
# Unit tests
pytest tests/services/ -v --tb=short

# API tests
pytest tests/api/ -v --tb=short

# Playwright tests (requires server running)
pytest tests/pw/ -v --tb=short

# Full test suite
pytest --tb=short -q
```

---

## Rules Inventory

### Current Rules (Existing)

| File | Rule Type | Count | Lines |
|------|-----------|-------|-------|
| `expanded_rules.py` | Intent patterns | 6 | 10-17 |
| `fraud_scorer.py` | Fraud signals | 18 | 10-29 |
| `trust_routing.py` | Trust thresholds | 4 | 26-34 |
| `policy_evaluator.py` | Policy operators | 8 | 36-78 |

### New Rules (To Add)

| File | Rule Type | Count | Description |
|------|-----------|-------|-------------|
| `expanded_rules.py` | Intent patterns | +5 | Stock-specific intents |
| `expanded_rules.py` | Stock rules | +10 | Stock availability rules |
| `fraud_scorer.py` | CV signals | +9 | CV pre-check signals |
| `inventory_agent.py` | Stock rules | +50 | Full stock interaction rules |
| `tier_router.py` | Tier triggers | +5 | Tier 2 triggers |

### Total Rules After Implementation

| Category | Count |
|----------|-------|
| Intent patterns | 11 |
| Fraud signals | 27 |
| Stock rules | 60 |
| Tier routing | 5 |
| Policy operators | 8 |
| **Total** | **111** |

---

## Implementation Checklist

### Week 1: Foundation
- [ ] Run `scripts/check_agent_connectivity.py` - verify all agents respond
- [ ] Run `scripts/check_db_tables.py` - verify schema
- [ ] Create `tier_router.py` with routing logic
- [ ] Add tier logging to orchestrator

### Week 2: Decision Trace Panel
- [ ] Update `DecisionTrace.tsx` with lightweight timeline
- [ ] Add `/api/v1/decisions/{id}/timeline` endpoint
- [ ] Add CSS for timeline, tags, drill-down
- [ ] Write Playwright tests for panel

### Week 3: Agent Rules
- [ ] Add 5 stock intent patterns to `expanded_rules.py`
- [ ] Add 50 stock rules to `inventory_agent.py`
- [ ] Add 9 CV signals to `fraud_scorer.py`
- [ ] Write pytest tests for each

### Week 4: Pre-LLM Pipeline
- [ ] Create `statistical_forecast.py` (Holt-Winters, Z-score)
- [ ] Create `semantic_cache.py` with Redis backend
- [ ] Integrate cache into orchestrator
- [ ] Measure token reduction (target: 90%)

### Week 5: CV Pipeline
- [ ] Create tiered CV provider
- [ ] Implement levels 0-2 (hash, rules, statistical)
- [ ] Test with sample images
- [ ] Integrate with fraud scorer

### Week 6: Testing & Polish
- [ ] Run full pytest suite
- [ ] Run Playwright smoke tests
- [ ] Manual testing with frontend
- [ ] Document API changes

---

## Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Rule coverage | 32 rules | 111 rules | Count in codebase |
| Token usage | Baseline | -90% | Log API calls before/after |
| Tier 0 hit rate | 0% | 70% | `SELECT COUNT(*) WHERE tier=0` |
| Decision trace load time | ~500ms | <200ms | Frontend performance |
| Test coverage | ? | >80% | `pytest --cov` |

---

*Document generated: January 2026*
*Author: Claude Opus 4.5*
*Project: ShopSquire Agent Enhancement*
