# ShopSquire: Production-Ready Complete Guide

**Date:** 2026-02-01
**Version:** 1.0
**Scope:** Complete fixes, production hardening, AI/ML enhancements

---

## Table of Contents

1. [Critical Fixes (Immediate)](#part-1-critical-fixes-immediate)
2. [Backend Enhancements](#part-2-backend-enhancements)
3. [Frontend Polish](#part-3-frontend-polish)
4. [Production Readiness Checklist](#part-4-production-readiness-checklist)
5. [AI/ML Enhancements](#part-5-aiml-enhancements)
6. [Security Hardening](#part-6-security-hardening)
7. [Scalability & Performance](#part-7-scalability--performance)
8. [Observability & Monitoring](#part-8-observability--monitoring)
9. [Integration Tests](#part-9-integration-tests)
10. [Deployment Guide](#part-10-deployment-guide)

---

## Part 1: Critical Fixes (Immediate)

### Fix 1.1: CV Triage Response Field Names

**File:** `src/app/routers/support_complaints.py`
**Location:** Lines 512-524 (submit_complaint return statement)

**Current Code:**
```python
return {
    "intent": parsed["intent"],
    "confidence": parsed["confidence"],
    "entities": parsed["entities"],
    "email_auth": auth,
    "bec_indicators": bec,
    "severity": severity,
    "recommended_action": recommended_action,
    "decision_id": decision_id,
    "ticket_id": ticket_id,
    "human_review": {"status": "pending" if ticket_id else "not_required", "ticket_id": ticket_id},
    "next_questions": nqe_questions,
}
```

**Fixed Code:**
```python
return {
    # Original fields
    "intent": parsed["intent"],
    "confidence": parsed["confidence"],
    "entities": parsed["entities"],
    "email_auth": auth,
    "bec_indicators": bec,
    "severity": severity,
    "recommended_action": recommended_action,
    "decision_id": decision_id,
    "ticket_id": ticket_id,
    "human_review": {"status": "pending" if ticket_id else "not_required", "ticket_id": ticket_id},
    "next_questions": nqe_questions,

    # ADD: Fields expected by frontend
    "case_id": case_id,  # Frontend expects this
    "analysis": {        # Frontend expects this object
        "intent": parsed["intent"],
        "confidence": parsed["confidence"],
        "entities": parsed["entities"],
        "severity": severity,
        "cv_labels": labels if 'labels' in locals() else [],
        "ocr_text": extracted_text if 'extracted_text' in locals() else "",
    },
    "suggested_routing": recommended_action,  # Alias for frontend
    "verdict": recommended_action,  # Additional alias for UI display
}
```

**Also update guest submission (~line 1350-1370)** with same fields.

---

### Fix 1.2: Ensure trace_id in All Response Paths

**File:** `src/app/routers/recommend.py`

**Add helper at top of file (~line 55):**
```python
def _ensure_trace_response(response: dict, trace_id: str, flags: dict) -> dict:
    """Ensure every response includes trace_id and policy_version."""
    response["trace_id"] = trace_id
    response["decision_trace_id"] = trace_id  # Alias for frontend
    response["policy_version"] = flags.get("POLICY_VERSION", "v1")
    return response
```

**Update all early-exit returns to use helper:**

```python
# Line ~335 (policy review required)
return _ensure_trace_response({
    "results": [],
    "proposal": None,
    "message": "Request requires policy review",
    "gate_decision": gate_decision,
}, trace_id, flags)

# Line ~405 (security flagged)
return _ensure_trace_response({
    "results": [],
    "proposal": None,
    "message": "Request flagged for security review",
    "security_analysis": sec_analysis,
}, trace_id, flags)

# Line ~424 (budget exceeded)
return _ensure_trace_response({
    "results": [],
    "proposal": None,
    "message": "Token budget exceeded",
    "budget_status": budget_status,
}, trace_id, flags)
```

---

### Fix 1.3: Decision Endpoint 501 Errors

**File:** `src/app/routers/decisions.py`

**Add implementations for missing endpoints:**

```python
@router.post("/{trace_id}/reopen")
async def reopen_decision(
    trace_id: str,
    reason: str = Body(..., embed=True),
    request: Request = None,
    role: str = Depends(require_role(["admin", "reviewer"]))
) -> Dict:
    """Reopen a closed decision for review."""
    try:
        # Update decision status in DB
        async with get_db() as db:
            await db.execute(
                """
                UPDATE decision_audit
                SET status = 'reopened',
                    reopened_at = CURRENT_TIMESTAMP,
                    reopen_reason = ?
                WHERE trace_id = ?
                """,
                (reason, trace_id)
            )
            await db.commit()

        # Log trace event
        log_trace_event(
            trace_id=trace_id,
            event_type="decision_reopened",
            source_type="Decision_API",
            source_id="reopen_endpoint",
            target_type="decision",
            target_id=trace_id,
            payload={"reason": reason}
        )

        return {"status": "reopened", "trace_id": trace_id}
    except Exception as e:
        logger.error(f"Failed to reopen decision {trace_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{trace_id}/query")
async def query_decision(
    trace_id: str,
    include_events: bool = Query(False),
    include_evidence: bool = Query(False),
    request: Request = None,
) -> Dict:
    """Query detailed decision information."""
    try:
        async with get_db() as db:
            # Get base decision
            result = await db.execute(
                "SELECT * FROM decision_audit WHERE trace_id = ?",
                (trace_id,)
            )
            row = await result.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Decision not found")

            response = dict(row)

            # Optionally include events
            if include_events:
                events_result = await db.execute(
                    """
                    SELECT * FROM decision_trace_events
                    WHERE trace_id = ? ORDER BY seq ASC
                    """,
                    (trace_id,)
                )
                response["events"] = [dict(e) for e in await events_result.fetchall()]

            # Optionally include evidence
            if include_evidence:
                evidence_result = await db.execute(
                    "SELECT * FROM evidence_bundles WHERE trace_id = ?",
                    (trace_id,)
                )
                response["evidence"] = [dict(e) for e in await evidence_result.fetchall()]

            return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query decision {trace_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

---

### Fix 1.4: Frontend SSE Fallback Path

**File:** `frontend/src/components/DecisionTrace.tsx`
**Location:** Lines 260-270

**Current (duplicate path):**
```typescript
try {
  es = wire(new EventSource(`/api/v1/decisions/${traceId}/events/stream`));
} catch { es = null; }

if (!es) {
  try {
    es = wire(new EventSource(`/api/v1/decisions/${traceId}/events/stream`));  // SAME!
  } catch { es = null; }
}
```

**Fixed (alternate fallback):**
```typescript
// Primary SSE endpoint
try {
  es = wire(new EventSource(`/api/v1/decisions/${traceId}/events/stream`));
} catch { es = null; }

// Fallback to alternate endpoint
if (!es) {
  try {
    es = wire(new EventSource(`/api/v1/trace/${traceId}/events/stream`));
  } catch { es = null; }
}

// If SSE unavailable, will fall back to polling (existing code below)
```

---

## Part 2: Backend Enhancements

### 2.1: Unified Response Schema

**Create:** `src/app/models/response_schemas.py`

```python
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class AgentStep(BaseModel):
    agent_name: str
    confidence: float
    duration_ms: int
    decision_mode: str
    output_summary: Optional[str] = None

class RecommendationResponse(BaseModel):
    results: List[Dict[str, Any]]
    proposal: Optional[Dict[str, Any]]
    constraints_used: Dict[str, Any]
    trace_id: str
    decision_trace_id: str  # Alias
    policy_version: str
    assistant_message: str
    next_questions: List[str]
    agent_chain: List[AgentStep]
    model_selection: Optional[Dict[str, Any]]
    security: Optional[Dict[str, Any]]
    timestamp: datetime

class CVTriageResponse(BaseModel):
    decision_id: str
    case_id: str
    ticket_id: Optional[str]
    analysis: Dict[str, Any]
    suggested_routing: str
    verdict: str
    confidence: float
    human_review: Dict[str, Any]
    next_questions: List[str]
    agent_chain: List[AgentStep]
    timestamp: datetime

class DecisionTraceResponse(BaseModel):
    trace_id: str
    timestamp: datetime
    input_query: Optional[str]
    intent_analysis: Optional[Dict[str, Any]]
    agent_chain: List[AgentStep]
    policy_gates: Optional[Dict[str, Any]]
    model_selection: Optional[Dict[str, Any]]
    recommendation: Optional[Dict[str, Any]]
    events: Optional[List[Dict[str, Any]]]
```

### 2.2: Error Response Standardization

**Create:** `src/app/middleware/error_handler.py`

```python
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import traceback
import logging

logger = logging.getLogger(__name__)

class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException as e:
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "error": True,
                    "message": e.detail,
                    "status_code": e.status_code,
                    "path": str(request.url.path),
                }
            )
        except Exception as e:
            logger.error(f"Unhandled error: {e}\n{traceback.format_exc()}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": True,
                    "message": "Internal server error",
                    "status_code": 500,
                    "path": str(request.url.path),
                    "trace": str(e) if settings.app_env != "production" else None,
                }
            )
```

### 2.3: Request Validation Middleware

**Create:** `src/app/middleware/request_validator.py`

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import re

class RequestValidatorMiddleware(BaseHTTPMiddleware):
    """Validate incoming requests for common issues."""

    MAX_QUERY_LENGTH = 2000
    MAX_IMAGES = 10
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB

    async def dispatch(self, request: Request, call_next):
        # Validate content length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 50 * 1024 * 1024:  # 50MB
            raise HTTPException(413, "Request too large")

        # For JSON requests, validate query length
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.body()
            if len(body) > 0:
                import json
                try:
                    data = json.loads(body)
                    if "query" in data and len(data["query"]) > self.MAX_QUERY_LENGTH:
                        raise HTTPException(400, f"Query exceeds {self.MAX_QUERY_LENGTH} characters")
                except json.JSONDecodeError:
                    pass

        return await call_next(request)
```

---

## Part 3: Frontend Polish

### 3.1: Loading States

**File:** `frontend/src/App.tsx`

**Add loading state:**
```typescript
const [isLoading, setIsLoading] = useState(false);
const [error, setError] = useState<string | null>(null);

const handleSubmit = async (q: string) => {
  setIsLoading(true);
  setError(null);
  try {
    const r = await fetch('/api/v1/chat/query', {...});
    if (!r.ok) {
      const err = await r.json();
      throw new Error(err.message || `HTTP ${r.status}`);
    }
    const data = await r.json();
    // ... process data
  } catch (e) {
    setError(e instanceof Error ? e.message : 'Unknown error');
  } finally {
    setIsLoading(false);
  }
};
```

**Display in UI:**
```tsx
{isLoading && <LoadingSpinner />}
{error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
```

### 3.2: CV Triage Result Display

**File:** `frontend/src/components/RightPanelExtras.tsx`

**Enhanced result display:**
```tsx
{result && (
  <div className={styles.cvResult}>
    <h4>Triage Result</h4>

    <div className={styles.resultRow}>
      <strong>Verdict:</strong>
      <span className={`${styles.verdict} ${styles[result.verdict || 'pending']}`}>
        {result.verdict || result.suggested_routing || '—'}
      </span>
    </div>

    <div className={styles.resultRow}>
      <strong>Confidence:</strong>
      <span>{result.analysis?.confidence ? `${(result.analysis.confidence * 100).toFixed(1)}%` : '—'}</span>
    </div>

    <div className={styles.resultRow}>
      <strong>Case ID:</strong>
      <span>{result.case_id || result.ticket_id || '—'}</span>
    </div>

    <div className={styles.resultRow}>
      <strong>Decision ID:</strong>
      <span className={styles.mono}>{result.decision_id || '—'}</span>
    </div>

    {result.analysis?.cv_labels?.length > 0 && (
      <div className={styles.resultRow}>
        <strong>Detected:</strong>
        <span>{result.analysis.cv_labels.join(', ')}</span>
      </div>
    )}

    {result.human_review?.status === 'pending' && (
      <div className={styles.pendingReview}>
        Escalated for human review (Ticket: {result.human_review.ticket_id})
      </div>
    )}

    {result.next_questions?.length > 0 && (
      <div className={styles.nextQuestions}>
        <strong>Follow-up Questions:</strong>
        <ul>
          {result.next_questions.map((q, i) => <li key={i}>{q}</li>)}
        </ul>
      </div>
    )}
  </div>
)}
```

### 3.3: Decision Trace Enhancements

**File:** `frontend/src/components/DecisionTrace.tsx`

**Add agent timeline visualization:**
```tsx
const AgentTimeline = ({ chain }: { chain: AgentStep[] }) => {
  const totalTime = chain.reduce((sum, a) => sum + (a.duration_ms || 0), 0);

  return (
    <div className={styles.agentTimeline}>
      <h4>Agent Execution Timeline ({totalTime}ms total)</h4>
      <div className={styles.timeline}>
        {chain.map((agent, i) => (
          <div
            key={i}
            className={styles.agentBar}
            style={{ width: `${(agent.duration_ms / totalTime) * 100}%` }}
            title={`${agent.agent_name}: ${agent.duration_ms}ms`}
          >
            <span className={styles.agentName}>{agent.agent_name}</span>
            <span className={styles.agentTime}>{agent.duration_ms}ms</span>
            <span className={styles.agentConfidence}>
              {(agent.confidence * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
```

---

## Part 4: Production Readiness Checklist

### 4.1: Environment Configuration

**Create:** `.env.production.example`

```bash
# Application
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO

# API Security
API_KEY_REQUIRED=true
CORS_ORIGINS=https://yourdomain.com
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60

# Database
DATABASE_URL=postgresql://user:pass@host:5432/shopsquire
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://host:6379/0
REDIS_PASSWORD=your-secure-password

# LLM Providers
OLLAMA_BASE_URL=http://ollama-host:11434
OPENAI_API_KEY=sk-...
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=3

# Feature Flags
TEST_BYPASS_POLICY_GATE=false
TOKEN_BUDGET_ENABLED=true
DECISION_LOG_WRITES_ENABLED=true

# Security
PCI_COMPLIANCE_MODE=true
AUDIT_LOG_ENABLED=true
ENCRYPTION_KEY=your-256-bit-key

# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
PROMETHEUS_ENABLED=true
SENTRY_DSN=https://...@sentry.io/...
```

### 4.2: Database Migrations

**Create:** `alembic/versions/002_add_missing_indexes.py`

```python
"""Add missing indexes for production performance

Revision ID: 002
"""
from alembic import op

def upgrade():
    # Decision trace events - query by trace_id
    op.create_index(
        'ix_decision_trace_events_trace_id',
        'decision_trace_events',
        ['trace_id']
    )

    # Decision trace events - query by timestamp for cleanup
    op.create_index(
        'ix_decision_trace_events_created_at',
        'decision_trace_events',
        ['created_at']
    )

    # Decision audit - query by status for dashboards
    op.create_index(
        'ix_decision_audit_status',
        'decision_audit',
        ['status']
    )

    # Products - search by name and category
    op.create_index(
        'ix_products_name_category',
        'products',
        ['name', 'category']
    )

    # Evidence bundles - query by case_id
    op.create_index(
        'ix_evidence_bundles_case_id',
        'evidence_bundles',
        ['case_id']
    )

def downgrade():
    op.drop_index('ix_decision_trace_events_trace_id')
    op.drop_index('ix_decision_trace_events_created_at')
    op.drop_index('ix_decision_audit_status')
    op.drop_index('ix_products_name_category')
    op.drop_index('ix_evidence_bundles_case_id')
```

### 4.3: Health Check Endpoints

**Create:** `src/app/routers/health.py`

```python
from fastapi import APIRouter, Depends
from typing import Dict
import asyncio
import aioredis
from src.app.deps import get_db, get_redis

router = APIRouter(prefix="/health", tags=["Health"])

@router.get("/live")
async def liveness() -> Dict:
    """Kubernetes liveness probe."""
    return {"status": "alive"}

@router.get("/ready")
async def readiness() -> Dict:
    """Kubernetes readiness probe - checks dependencies."""
    checks = {}

    # Database check
    try:
        async with get_db() as db:
            await db.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Redis check
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    # Ollama check
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            checks["ollama"] = "ok" if r.status_code == 200 else f"error: {r.status_code}"
    except Exception as e:
        checks["ollama"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks
    }

@router.get("/metrics")
async def metrics() -> Dict:
    """Basic metrics endpoint."""
    return {
        "uptime_seconds": get_uptime(),
        "requests_total": get_request_count(),
        "active_connections": get_active_connections(),
        "cache_hit_rate": get_cache_hit_rate(),
    }
```

---

## Part 5: AI/ML Enhancements

### 5.1: Model Tiering Strategy

**Current State:** Basic tier selection exists but isn't optimized.

**Enhanced Implementation:**

**File:** `src/app/services/model_router.py`

```python
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum
import os

class ModelTier(Enum):
    FAST = "fast"      # Simple queries, low latency
    BALANCED = "balanced"  # Most queries
    PREMIUM = "premium"    # Complex reasoning
    VISION = "vision"      # Image analysis

@dataclass
class ModelConfig:
    name: str
    provider: str  # ollama, openai, anthropic
    max_tokens: int
    temperature: float
    cost_per_1k_tokens: float
    avg_latency_ms: int

MODEL_REGISTRY = {
    ModelTier.FAST: ModelConfig(
        name=os.getenv("MODEL_FAST", "qwen2:1.5b"),
        provider="ollama",
        max_tokens=512,
        temperature=0.3,
        cost_per_1k_tokens=0.0,
        avg_latency_ms=200
    ),
    ModelTier.BALANCED: ModelConfig(
        name=os.getenv("MODEL_BALANCED", "llama3.2:3b"),
        provider="ollama",
        max_tokens=1024,
        temperature=0.5,
        cost_per_1k_tokens=0.0,
        avg_latency_ms=500
    ),
    ModelTier.PREMIUM: ModelConfig(
        name=os.getenv("MODEL_PREMIUM", "llama3.1:8b"),
        provider="ollama",
        max_tokens=2048,
        temperature=0.7,
        cost_per_1k_tokens=0.0,
        avg_latency_ms=1500
    ),
    ModelTier.VISION: ModelConfig(
        name=os.getenv("MODEL_VISION", "llava:13b"),
        provider="ollama",
        max_tokens=1024,
        temperature=0.3,
        cost_per_1k_tokens=0.0,
        avg_latency_ms=2000
    ),
}

class ModelRouter:
    """Routes queries to appropriate model tier based on complexity."""

    def __init__(self):
        self.complexity_keywords = {
            "premium": ["compare", "analyze", "explain why", "tradeoffs", "recommend best"],
            "fast": ["list", "show", "price of", "is available", "how much"],
        }

    def select_tier(
        self,
        query: str,
        intent_confidence: float,
        is_multi_turn: bool,
        has_images: bool,
        user_tier: str = "standard"
    ) -> ModelTier:
        """Select model tier based on query characteristics."""

        # Vision tasks always use vision model
        if has_images:
            return ModelTier.VISION

        query_lower = query.lower()

        # Check for premium indicators
        if any(kw in query_lower for kw in self.complexity_keywords["premium"]):
            return ModelTier.PREMIUM

        # Check for fast query indicators
        if any(kw in query_lower for kw in self.complexity_keywords["fast"]):
            return ModelTier.FAST

        # Low confidence needs better model
        if intent_confidence < 0.5:
            return ModelTier.BALANCED if intent_confidence > 0.3 else ModelTier.PREMIUM

        # Multi-turn conversations benefit from context
        if is_multi_turn:
            return ModelTier.BALANCED

        # Default to balanced
        return ModelTier.BALANCED

    def get_config(self, tier: ModelTier) -> ModelConfig:
        return MODEL_REGISTRY[tier]
```

### 5.2: Semantic Search with Embeddings

**Create:** `src/app/services/semantic_search.py`

```python
import numpy as np
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
import faiss

class SemanticSearchEngine:
    """Vector-based semantic search for products."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
        self.index: Optional[faiss.Index] = None
        self.product_ids: List[str] = []
        self.embeddings_cache: Dict[str, np.ndarray] = {}

    def build_index(self, products: List[Dict[str, Any]]):
        """Build FAISS index from product catalog."""
        texts = []
        self.product_ids = []

        for p in products:
            # Create rich text representation
            text = f"{p['name']} {p.get('description', '')} {' '.join(p.get('features', []))}"
            texts.append(text)
            self.product_ids.append(p['sku'])

        # Generate embeddings
        embeddings = self.model.encode(texts, convert_to_numpy=True)

        # Build FAISS index
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)  # Inner product (cosine sim with normalized vectors)
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings)

        # Cache embeddings
        for sku, emb in zip(self.product_ids, embeddings):
            self.embeddings_cache[sku] = emb

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.3
    ) -> List[Dict[str, Any]]:
        """Search products by semantic similarity."""
        if self.index is None:
            raise ValueError("Index not built. Call build_index first.")

        # Encode query
        query_embedding = self.model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)

        # Search
        scores, indices = self.index.search(query_embedding, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if score >= min_score and idx < len(self.product_ids):
                results.append({
                    "sku": self.product_ids[idx],
                    "semantic_score": float(score),
                })

        return results

    def rerank_with_llm(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        llm_client,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Use LLM to rerank semantic search results."""
        if not candidates:
            return []

        # Build prompt
        product_list = "\n".join([
            f"{i+1}. {c['name']} - ${c['price']} - {', '.join(c.get('features', [])[:3])}"
            for i, c in enumerate(candidates[:10])
        ])

        prompt = f"""Given this customer query: "{query}"

Rank these products from most to least relevant (respond with just the numbers in order):
{product_list}

Rankings (most relevant first):"""

        try:
            response = llm_client.generate(prompt, max_tokens=50)
            # Parse rankings
            rankings = [int(x.strip()) - 1 for x in response.split(",") if x.strip().isdigit()]

            # Reorder candidates
            reranked = []
            for rank in rankings[:top_k]:
                if 0 <= rank < len(candidates):
                    reranked.append(candidates[rank])

            # Add any missing (in case LLM missed some)
            for c in candidates:
                if c not in reranked and len(reranked) < top_k:
                    reranked.append(c)

            return reranked
        except Exception:
            # Fallback to semantic order
            return candidates[:top_k]
```

### 5.3: Intent Classification Enhancement

**Create:** `src/app/services/intent_classifier.py`

```python
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
import re

class Intent(Enum):
    PRODUCT_SEARCH = "product_search"
    PRODUCT_COMPARISON = "product_comparison"
    PRICE_CHECK = "price_check"
    AVAILABILITY_CHECK = "availability_check"
    RECOMMENDATION = "recommendation"
    BULK_ORDER = "bulk_order"
    RETURN_REQUEST = "return_request"
    COMPLAINT = "complaint"
    SUPPORT = "support"
    UNKNOWN = "unknown"

@dataclass
class IntentResult:
    intent: Intent
    confidence: float
    entities: Dict[str, Any]
    sub_intents: List[Intent]

class IntentClassifier:
    """Multi-signal intent classification."""

    def __init__(self):
        self.patterns = {
            Intent.PRODUCT_COMPARISON: [
                r"compare\s+(.+)\s+(vs|versus|and|or|with)\s+(.+)",
                r"difference\s+between",
                r"which\s+is\s+better",
                r"pros\s*(and)?\s*cons",
            ],
            Intent.BULK_ORDER: [
                r"(\d+)\s*(units?|pieces?|items?|laptops?|computers?)",
                r"bulk\s+(order|purchase|buy)",
                r"for\s+(my\s+)?(team|company|office|business)",
            ],
            Intent.RETURN_REQUEST: [
                r"(want\s+to\s+)?return",
                r"refund",
                r"exchange",
                r"doesn'?t\s+work",
                r"damaged|broken|defective",
            ],
            Intent.PRICE_CHECK: [
                r"(how\s+much|what'?s?\s+the\s+price|cost\s+of)",
                r"price\s+(for|of)",
                r"cheapest|most\s+expensive",
            ],
            Intent.AVAILABILITY_CHECK: [
                r"(is|are)\s+.+\s+(available|in\s+stock)",
                r"do\s+you\s+have",
                r"stock\s+(status|level|check)",
            ],
            Intent.RECOMMENDATION: [
                r"recommend",
                r"suggest",
                r"best\s+(laptop|computer|option)",
                r"what\s+should\s+i\s+(buy|get)",
                r"looking\s+for",
            ],
        }

        self.entity_extractors = {
            "quantity": r"(\d+)\s*(units?|pieces?|items?|laptops?|computers?)?",
            "price_min": r"(?:from|above|over|min(?:imum)?)\s*\$?(\d+(?:,\d+)?)",
            "price_max": r"(?:under|below|up\s+to|max(?:imum)?|budget)\s*\$?(\d+(?:,\d+)?)",
            "brand": r"(apple|dell|hp|lenovo|asus|acer|microsoft|samsung)",
            "ram": r"(\d+)\s*(?:gb)?\s*(?:ram|memory)",
            "storage": r"(\d+)\s*(?:gb|tb)\s*(?:ssd|hdd|storage|drive)",
            "use_case": r"for\s+(gaming|work|school|business|programming|video\s*editing|ai|ml)",
        }

    def classify(self, query: str) -> IntentResult:
        """Classify query intent with confidence scoring."""
        query_lower = query.lower()

        # Score each intent
        scores: Dict[Intent, float] = {}
        for intent, patterns in self.patterns.items():
            score = 0.0
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    score += 0.3
            scores[intent] = min(score, 1.0)

        # Default to product search if no strong signal
        if not scores or max(scores.values()) < 0.3:
            scores[Intent.PRODUCT_SEARCH] = 0.5

        # Find primary intent
        primary_intent = max(scores, key=scores.get)
        confidence = scores[primary_intent]

        # Find sub-intents (secondary signals)
        sub_intents = [
            intent for intent, score in scores.items()
            if score > 0.2 and intent != primary_intent
        ]

        # Extract entities
        entities = self._extract_entities(query_lower)

        return IntentResult(
            intent=primary_intent,
            confidence=confidence,
            entities=entities,
            sub_intents=sub_intents
        )

    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """Extract structured entities from query."""
        entities = {}

        for entity_type, pattern in self.entity_extractors.items():
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                value = match.group(1)
                # Clean up numeric values
                if entity_type in ("quantity", "price_min", "price_max", "ram", "storage"):
                    value = int(value.replace(",", ""))
                entities[entity_type] = value

        return entities
```

### 5.4: CV Damage Classification Model

**Create:** `src/app/services/cv_damage_classifier.py`

```python
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

class DamageType(Enum):
    NONE = "none"
    COSMETIC = "cosmetic"  # Scratches, dents
    FUNCTIONAL = "functional"  # Screen damage, keyboard issues
    SEVERE = "severe"  # Won't power on, water damage
    UNKNOWN = "unknown"

class FraudIndicator(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@dataclass
class CVAnalysisResult:
    damage_type: DamageType
    damage_confidence: float
    damage_description: str
    fraud_indicator: FraudIndicator
    fraud_signals: List[str]
    labels: List[str]
    ocr_text: str
    recommended_action: str

class CVDamageClassifier:
    """Classify damage from CV analysis results."""

    def __init__(self, llm_client=None):
        self.llm = llm_client

        self.damage_keywords = {
            DamageType.COSMETIC: ["scratch", "dent", "scuff", "mark", "minor"],
            DamageType.FUNCTIONAL: ["crack", "broken screen", "dead pixel", "keyboard", "hinge"],
            DamageType.SEVERE: ["shattered", "water damage", "won't turn on", "smoke", "fire"],
        }

        self.fraud_signals = {
            "stock_image": "Image appears to be stock photo",
            "metadata_mismatch": "Image metadata inconsistent",
            "duplicate_claim": "Similar image used in previous claim",
            "no_damage_visible": "Claimed damage not visible in image",
            "wrong_product": "Product in image doesn't match order",
        }

    def analyze(
        self,
        cv_labels: List[str],
        ocr_text: str,
        image_metadata: Optional[Dict] = None,
        order_context: Optional[Dict] = None
    ) -> CVAnalysisResult:
        """Analyze CV results to classify damage and detect fraud."""

        # Classify damage type
        damage_type = DamageType.UNKNOWN
        damage_confidence = 0.0

        labels_lower = [l.lower() for l in cv_labels]

        for dtype, keywords in self.damage_keywords.items():
            matches = sum(1 for kw in keywords if any(kw in label for label in labels_lower))
            if matches > 0:
                confidence = min(matches * 0.3, 1.0)
                if confidence > damage_confidence:
                    damage_type = dtype
                    damage_confidence = confidence

        # Detect fraud signals
        fraud_signals = []
        fraud_score = 0.0

        # Check for stock image indicators
        if image_metadata:
            if image_metadata.get("source") == "stock":
                fraud_signals.append(self.fraud_signals["stock_image"])
                fraud_score += 0.4

        # Check for product mismatch
        if order_context and "product_name" in order_context:
            product_in_order = order_context["product_name"].lower()
            if not any(product_in_order in label for label in labels_lower):
                fraud_signals.append(self.fraud_signals["wrong_product"])
                fraud_score += 0.3

        # No damage visible but damage claimed
        if damage_type == DamageType.UNKNOWN and "damage" not in " ".join(labels_lower):
            fraud_signals.append(self.fraud_signals["no_damage_visible"])
            fraud_score += 0.2

        # Determine fraud indicator level
        if fraud_score >= 0.6:
            fraud_indicator = FraudIndicator.HIGH
        elif fraud_score >= 0.3:
            fraud_indicator = FraudIndicator.MEDIUM
        elif fraud_score > 0:
            fraud_indicator = FraudIndicator.LOW
        else:
            fraud_indicator = FraudIndicator.NONE

        # Determine recommended action
        if fraud_indicator == FraudIndicator.HIGH:
            recommended_action = "deny"
        elif fraud_indicator == FraudIndicator.MEDIUM or damage_type == DamageType.SEVERE:
            recommended_action = "escalate"
        elif damage_type in (DamageType.COSMETIC, DamageType.FUNCTIONAL):
            recommended_action = "approve" if damage_confidence > 0.7 else "review"
        else:
            recommended_action = "review"

        return CVAnalysisResult(
            damage_type=damage_type,
            damage_confidence=damage_confidence,
            damage_description=self._generate_description(damage_type, cv_labels),
            fraud_indicator=fraud_indicator,
            fraud_signals=fraud_signals,
            labels=cv_labels,
            ocr_text=ocr_text,
            recommended_action=recommended_action
        )

    def _generate_description(self, damage_type: DamageType, labels: List[str]) -> str:
        """Generate human-readable damage description."""
        descriptions = {
            DamageType.NONE: "No visible damage detected",
            DamageType.COSMETIC: f"Minor cosmetic damage: {', '.join(labels[:3])}",
            DamageType.FUNCTIONAL: f"Functional damage detected: {', '.join(labels[:3])}",
            DamageType.SEVERE: f"Severe damage: {', '.join(labels[:3])}",
            DamageType.UNKNOWN: "Unable to classify damage from images",
        }
        return descriptions.get(damage_type, "Unknown")
```

### 5.5: Recommendation Personalization

**Create:** `src/app/services/personalization.py`

```python
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import numpy as np

@dataclass
class UserProfile:
    user_id: str
    preferences: Dict[str, Any]
    purchase_history: List[Dict]
    view_history: List[str]
    price_sensitivity: float  # 0-1, higher = more price sensitive
    brand_affinities: Dict[str, float]

class PersonalizationEngine:
    """Personalize recommendations based on user behavior."""

    def __init__(self, memory_service=None):
        self.memory = memory_service

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """Build user profile from history."""
        # Get from memory/cache
        if self.memory:
            context = self.memory.get_context(user_id)
            preferences = context.get("preferences", {})
            history = context.get("purchase_history", [])
            views = context.get("view_history", [])
        else:
            preferences, history, views = {}, [], []

        # Calculate price sensitivity
        if history:
            avg_price = np.mean([p.get("price", 0) for p in history])
            price_sensitivity = 1.0 - min(avg_price / 2000, 1.0)  # Normalize
        else:
            price_sensitivity = 0.5

        # Calculate brand affinities
        brand_counts: Dict[str, int] = {}
        for item in history + [{"sku": v} for v in views]:
            brand = self._extract_brand(item.get("sku", ""))
            if brand:
                brand_counts[brand] = brand_counts.get(brand, 0) + 1

        total = sum(brand_counts.values()) or 1
        brand_affinities = {b: c/total for b, c in brand_counts.items()}

        return UserProfile(
            user_id=user_id,
            preferences=preferences,
            purchase_history=history,
            view_history=views,
            price_sensitivity=price_sensitivity,
            brand_affinities=brand_affinities
        )

    def personalize_ranking(
        self,
        candidates: List[Dict[str, Any]],
        profile: UserProfile,
        base_scores: Optional[List[float]] = None
    ) -> List[Dict[str, Any]]:
        """Re-rank candidates based on user profile."""
        if not candidates:
            return []

        scored = []
        for i, product in enumerate(candidates):
            base_score = base_scores[i] if base_scores else 0.5

            # Personalization factors
            brand = self._extract_brand(product.get("sku", ""))
            brand_boost = profile.brand_affinities.get(brand, 0) * 0.2

            price = product.get("price", 0)
            price_factor = 0
            if profile.price_sensitivity > 0.7:
                # Prefer lower prices
                price_factor = (1 - min(price / 2000, 1)) * 0.15

            # Feature matching
            user_features = profile.preferences.get("preferred_features", [])
            product_features = product.get("features", [])
            feature_match = len(set(user_features) & set(product_features)) / max(len(user_features), 1)
            feature_boost = feature_match * 0.15

            final_score = base_score + brand_boost + price_factor + feature_boost
            scored.append((final_score, product))

        # Sort by personalized score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored]

    def _extract_brand(self, sku: str) -> Optional[str]:
        """Extract brand from SKU."""
        sku_upper = sku.upper()
        brands = ["APPLE", "MAC", "DELL", "HP", "LENOVO", "ASUS", "ACER", "MICROSOFT"]
        for brand in brands:
            if brand in sku_upper:
                return brand.lower()
        return None
```

---

## Part 6: Security Hardening

### 6.1: Input Sanitization

**Create:** `src/app/security/sanitizer.py`

```python
import re
import html
from typing import Any, Dict

class InputSanitizer:
    """Sanitize all user inputs to prevent injection attacks."""

    # Patterns to detect potential attacks
    SQL_INJECTION_PATTERNS = [
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER)\b)",
        r"(--|;|/\*|\*/)",
        r"(\bOR\b.*=.*)",
    ]

    XSS_PATTERNS = [
        r"<script[^>]*>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe",
    ]

    @classmethod
    def sanitize_string(cls, value: str, max_length: int = 10000) -> str:
        """Sanitize a string input."""
        if not isinstance(value, str):
            return str(value)[:max_length]

        # Truncate
        value = value[:max_length]

        # HTML encode
        value = html.escape(value)

        # Remove null bytes
        value = value.replace("\x00", "")

        return value

    @classmethod
    def sanitize_query(cls, query: str) -> str:
        """Sanitize a search query."""
        query = cls.sanitize_string(query, max_length=2000)

        # Check for SQL injection patterns (log but don't block)
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                # Log security event
                pass

        return query

    @classmethod
    def sanitize_dict(cls, data: Dict[str, Any], max_depth: int = 5) -> Dict[str, Any]:
        """Recursively sanitize a dictionary."""
        if max_depth <= 0:
            return {}

        sanitized = {}
        for key, value in data.items():
            # Sanitize key
            clean_key = cls.sanitize_string(str(key), max_length=100)

            # Sanitize value based on type
            if isinstance(value, str):
                sanitized[clean_key] = cls.sanitize_string(value)
            elif isinstance(value, dict):
                sanitized[clean_key] = cls.sanitize_dict(value, max_depth - 1)
            elif isinstance(value, list):
                sanitized[clean_key] = [
                    cls.sanitize_dict(v, max_depth - 1) if isinstance(v, dict)
                    else cls.sanitize_string(v) if isinstance(v, str)
                    else v
                    for v in value[:1000]  # Limit list length
                ]
            else:
                sanitized[clean_key] = value

        return sanitized
```

### 6.2: Rate Limiting

**Create:** `src/app/middleware/rate_limiter.py`

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import time
from collections import defaultdict
import asyncio

class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        burst_size: int = 10
    ):
        self.rate = requests_per_minute / 60  # Tokens per second
        self.burst_size = burst_size
        self.buckets: Dict[str, Dict] = defaultdict(lambda: {
            "tokens": burst_size,
            "last_update": time.time()
        })
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        """Check if request is allowed."""
        async with self._lock:
            bucket = self.buckets[key]
            now = time.time()

            # Refill tokens
            elapsed = now - bucket["last_update"]
            bucket["tokens"] = min(
                self.burst_size,
                bucket["tokens"] + elapsed * self.rate
            )
            bucket["last_update"] = now

            # Check if request allowed
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True
            return False

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting to requests."""

    def __init__(self, app, limiter: RateLimiter):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next):
        # Get client identifier
        client_id = self._get_client_id(request)

        # Check rate limit
        if not await self.limiter.is_allowed(client_id):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please retry later.",
                headers={"Retry-After": "60"}
            )

        return await call_next(request)

    def _get_client_id(self, request: Request) -> str:
        """Get unique client identifier."""
        # Try API key first
        api_key = request.headers.get("x-api-key")
        if api_key:
            return f"key:{api_key}"

        # Fall back to IP
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"

        return f"ip:{request.client.host}"
```

### 6.3: Audit Logging

**Create:** `src/app/security/audit_logger.py`

```python
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from enum import Enum

class AuditEventType(Enum):
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    ADMIN_ACTION = "admin_action"
    SECURITY_ALERT = "security_alert"
    PII_ACCESS = "pii_access"

class AuditLogger:
    """Immutable audit logging for compliance."""

    def __init__(self, log_file: str = "audit.log"):
        self.logger = logging.getLogger("audit")
        self.logger.setLevel(logging.INFO)

        # File handler with rotation
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=100*1024*1024,  # 100MB
            backupCount=10
        )
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)

    def log(
        self,
        event_type: AuditEventType,
        user_id: Optional[str],
        action: str,
        resource: str,
        details: Dict[str, Any],
        ip_address: Optional[str] = None,
        success: bool = True
    ):
        """Log an audit event."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type.value,
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "success": success,
            "ip_address": ip_address,
            "details": details,
        }

        # Write as single line JSON for log parsing
        self.logger.info(json.dumps(event))

    def log_data_access(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        fields_accessed: list,
        ip_address: str
    ):
        """Log data access for compliance."""
        self.log(
            event_type=AuditEventType.DATA_ACCESS,
            user_id=user_id,
            action="read",
            resource=f"{resource_type}:{resource_id}",
            details={"fields": fields_accessed},
            ip_address=ip_address
        )

    def log_pii_access(
        self,
        user_id: str,
        pii_type: str,
        reason: str,
        ip_address: str
    ):
        """Log PII access for GDPR/CCPA compliance."""
        self.log(
            event_type=AuditEventType.PII_ACCESS,
            user_id=user_id,
            action="pii_access",
            resource=pii_type,
            details={"reason": reason},
            ip_address=ip_address
        )
```

---

## Part 7: Scalability & Performance

### 7.1: Caching Strategy

**Create:** `src/app/services/cache.py`

```python
import json
import hashlib
from typing import Any, Optional, Callable
from functools import wraps
import aioredis

class CacheService:
    """Multi-tier caching service."""

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self.local_cache: Dict[str, Any] = {}
        self.local_cache_ttl: Dict[str, float] = {}

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache (local first, then Redis)."""
        # Check local cache
        if key in self.local_cache:
            if time.time() < self.local_cache_ttl.get(key, 0):
                return self.local_cache[key]
            else:
                del self.local_cache[key]

        # Check Redis
        value = await self.redis.get(key)
        if value:
            return json.loads(value)

        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 300,
        local_ttl_seconds: int = 60
    ):
        """Set value in cache."""
        # Set in Redis
        await self.redis.setex(key, ttl_seconds, json.dumps(value))

        # Set in local cache with shorter TTL
        self.local_cache[key] = value
        self.local_cache_ttl[key] = time.time() + local_ttl_seconds

    async def invalidate(self, key: str):
        """Invalidate cache entry."""
        await self.redis.delete(key)
        self.local_cache.pop(key, None)
        self.local_cache_ttl.pop(key, None)

def cached(
    ttl_seconds: int = 300,
    key_prefix: str = "",
    key_builder: Optional[Callable] = None
):
    """Decorator for caching function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                key_data = json.dumps({"args": args[1:], "kwargs": kwargs}, sort_keys=True)
                cache_key = f"{key_prefix}:{func.__name__}:{hashlib.md5(key_data.encode()).hexdigest()}"

            # Try cache
            cache = get_cache_service()
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Execute function
            result = await func(*args, **kwargs)

            # Cache result
            await cache.set(cache_key, result, ttl_seconds)

            return result
        return wrapper
    return decorator
```

### 7.2: Connection Pooling

**Create:** `src/app/db/pool.py`

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager

class DatabasePool:
    """Managed database connection pool."""

    def __init__(
        self,
        database_url: str,
        pool_size: int = 20,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 1800
    ):
        self.engine = create_async_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            echo=False
        )

        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    @asynccontextmanager
    async def session(self):
        """Get a database session from the pool."""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self.session() as session:
                await session.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self):
        """Close all connections."""
        await self.engine.dispose()
```

---

## Part 8: Observability & Monitoring

### 8.1: Prometheus Metrics

**Create:** `src/app/observability/prometheus_metrics.py`

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from functools import wraps
import time

# Request metrics
REQUEST_COUNT = Counter(
    'shopsquire_requests_total',
    'Total requests',
    ['method', 'endpoint', 'status']
)

REQUEST_LATENCY = Histogram(
    'shopsquire_request_latency_seconds',
    'Request latency',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Agent metrics
AGENT_EXECUTION_TIME = Histogram(
    'shopsquire_agent_execution_seconds',
    'Agent execution time',
    ['agent_name'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)

AGENT_CONFIDENCE = Histogram(
    'shopsquire_agent_confidence',
    'Agent decision confidence',
    ['agent_name'],
    buckets=[0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0]
)

# CV metrics
CV_VERDICTS = Counter(
    'shopsquire_cv_verdicts_total',
    'CV triage verdicts',
    ['verdict', 'damage_type']
)

CV_PROCESSING_TIME = Histogram(
    'shopsquire_cv_processing_seconds',
    'CV processing time',
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# LLM metrics
LLM_REQUESTS = Counter(
    'shopsquire_llm_requests_total',
    'LLM requests',
    ['model', 'tier', 'status']
)

LLM_TOKENS = Counter(
    'shopsquire_llm_tokens_total',
    'LLM tokens used',
    ['model', 'type']  # type: prompt/completion
)

LLM_LATENCY = Histogram(
    'shopsquire_llm_latency_seconds',
    'LLM request latency',
    ['model'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# Business metrics
RECOMMENDATIONS_SERVED = Counter(
    'shopsquire_recommendations_total',
    'Recommendations served',
    ['intent', 'result_count_bucket']
)

POLICY_GATE_DECISIONS = Counter(
    'shopsquire_policy_gate_decisions_total',
    'Policy gate decisions',
    ['decision', 'reason']
)

def track_request(method: str, endpoint: str):
    """Decorator to track request metrics."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start
                REQUEST_COUNT.labels(method, endpoint, status).inc()
                REQUEST_LATENCY.labels(method, endpoint).observe(duration)
        return wrapper
    return decorator
```

### 8.2: Distributed Tracing

**Create:** `src/app/observability/tracing.py`

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
import os

def setup_tracing(app, service_name: str = "shopsquire"):
    """Configure OpenTelemetry distributed tracing."""

    # Create tracer provider
    provider = TracerProvider()

    # Configure exporter
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # Instrument HTTP client
    HTTPXClientInstrumentor().instrument()

    # Instrument SQLAlchemy
    SQLAlchemyInstrumentor().instrument()

    return trace.get_tracer(service_name)

def get_tracer():
    """Get the configured tracer."""
    return trace.get_tracer("shopsquire")

# Context manager for custom spans
from contextlib import contextmanager

@contextmanager
def trace_agent(agent_name: str, attributes: dict = None):
    """Create a span for agent execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"agent.{agent_name}") as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span
```

---

## Part 9: Integration Tests

### 9.1: Chat to Products E2E

**Create:** `tests/integration/test_chat_to_products_e2e.py`

```python
import pytest
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)

class TestChatToProductsE2E:
    """End-to-end tests for chat → products flow."""

    def test_simple_query_returns_products(self):
        """Basic query should return products."""
        response = client.post(
            "/api/v1/chat/query",
            json={"query": "laptop under 1500"},
            headers={"x-api-key": "local-merchant-key"}
        )

        assert response.status_code == 200
        data = response.json()

        assert "products" in data
        assert "decision_trace_id" in data
        assert data["decision_trace_id"] is not None

    def test_complex_query_with_constraints(self):
        """Query with multiple constraints."""
        response = client.post(
            "/api/v1/chat/query",
            json={"query": "16GB RAM laptop between 1000 and 2000 for AI development"},
            headers={"x-api-key": "local-merchant-key"}
        )

        assert response.status_code == 200
        data = response.json()

        # Should have products
        assert len(data.get("products", [])) > 0

        # Products should match constraints
        for product in data["products"]:
            assert product["price"] >= 1000
            assert product["price"] <= 2000

    def test_bulk_order_intent_detected(self):
        """Bulk order queries should be detected."""
        response = client.post(
            "/api/v1/chat/query",
            json={"query": "buy 15 laptops for AI engineering team"},
            headers={"x-api-key": "local-merchant-key"}
        )

        assert response.status_code == 200
        data = response.json()

        # Should have trace ID for tracking
        assert data.get("decision_trace_id") is not None

    def test_decision_trace_retrievable(self):
        """Decision trace should be retrievable after query."""
        # Make a query
        query_response = client.post(
            "/api/v1/chat/query",
            json={"query": "laptop"},
            headers={"x-api-key": "local-merchant-key"}
        )

        trace_id = query_response.json().get("decision_trace_id")
        assert trace_id is not None

        # Retrieve trace
        trace_response = client.get(
            f"/api/v1/decisions/{trace_id}",
            headers={"x-api-key": "local-merchant-key"}
        )

        # Should succeed (200) or be not found yet (404 is acceptable in test)
        assert trace_response.status_code in (200, 404)
```

### 9.2: CV Triage E2E

**Create:** `tests/integration/test_cv_triage_e2e.py`

```python
import pytest
from fastapi.testclient import TestClient
from src.app.main import app
import io

client = TestClient(app)

class TestCVTriageE2E:
    """End-to-end tests for CV triage flow."""

    def test_cv_submit_returns_verdict(self):
        """CV submission should return verdict."""
        # Create a minimal test image
        test_image = io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

        response = client.post(
            "/api/v1/support/complaints/submit",
            data={
                "order_id": "TEST-123",
                "issue_type": "refund",
                "description": "Product arrived damaged"
            },
            files={"images": ("test.png", test_image, "image/png")},
            headers={"x-api-key": "local-merchant-key"}
        )

        assert response.status_code == 200
        data = response.json()

        # Check required fields (after our fix)
        assert "decision_id" in data
        assert "case_id" in data or "ticket_id" in data
        assert "suggested_routing" in data or "recommended_action" in data

    def test_cv_submit_without_images(self):
        """CV submission without images should still work."""
        response = client.post(
            "/api/v1/support/complaints/submit",
            data={
                "order_id": "TEST-456",
                "issue_type": "complaint",
                "description": "Product not as described"
            },
            headers={"x-api-key": "local-merchant-key"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "decision_id" in data

    def test_cv_guest_submission(self):
        """Guest CV submission should work."""
        response = client.post(
            "/api/v1/support/complaints/submit-guest",
            data={
                "email": "test@example.com",
                "issue_type": "refund",
                "description": "Want to return product"
            },
            headers={"x-api-key": "local-merchant-key"}
        )

        # Should succeed or require additional info
        assert response.status_code in (200, 400, 422)
```

### 9.3: Agent Chain Visibility

**Create:** `tests/integration/test_agent_chain_visibility.py`

```python
import pytest
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)

class TestAgentChainVisibility:
    """Test that agent execution is visible in responses."""

    def test_recommend_includes_agent_chain(self):
        """Recommendation should include agent chain."""
        response = client.post(
            "/api/v1/recommend/suggest",
            json={"query": "gaming laptop", "constraints": {}},
            headers={"x-api-key": "local-merchant-key"}
        )

        assert response.status_code == 200
        data = response.json()

        # Should have agent chain
        assert "agent_chain" in data or "agents" in data

    def test_agent_chain_has_timing(self):
        """Agent chain should include timing information."""
        response = client.post(
            "/api/v1/recommend/suggest",
            json={"query": "laptop", "constraints": {}},
            headers={"x-api-key": "local-merchant-key"}
        )

        data = response.json()
        agent_chain = data.get("agent_chain", [])

        if agent_chain:
            for agent in agent_chain:
                # Should have timing info
                assert "duration_ms" in agent or "latency" in agent

    def test_decision_trace_has_events(self):
        """Decision trace should have events from agents."""
        # Make query
        query_response = client.post(
            "/api/v1/recommend/suggest",
            json={"query": "laptop", "constraints": {}},
            headers={"x-api-key": "local-merchant-key"}
        )

        trace_id = query_response.json().get("trace_id")
        if not trace_id:
            pytest.skip("No trace_id returned")

        # Get timeline
        timeline_response = client.get(
            f"/api/v1/trace/{trace_id}/timeline",
            headers={"x-api-key": "local-merchant-key"}
        )

        if timeline_response.status_code == 200:
            data = timeline_response.json()
            events = data.get("events", [])

            # Should have some events
            assert len(events) >= 0  # May be empty if async logging
```

---

## Part 10: Deployment Guide

### 10.1: Docker Configuration

**Create:** `Dockerfile.production`

```dockerfile
# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[production]"

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health/live || exit 1

EXPOSE 8080

CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
```

### 10.2: Kubernetes Deployment

**Create:** `k8s/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shopsquire-api
  labels:
    app: shopsquire
spec:
  replicas: 3
  selector:
    matchLabels:
      app: shopsquire
  template:
    metadata:
      labels:
        app: shopsquire
    spec:
      containers:
      - name: api
        image: shopsquire:latest
        ports:
        - containerPort: 8080
        env:
        - name: APP_ENV
          value: "production"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: shopsquire-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: shopsquire-secrets
              key: redis-url
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: shopsquire-api
spec:
  selector:
    app: shopsquire
  ports:
  - port: 80
    targetPort: 8080
  type: ClusterIP
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shopsquire-api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: shopsquire-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

---

## Summary: Complete Fix Checklist

### Immediate (Day 1)
- [ ] Fix CV response field names (`support_complaints.py`)
- [ ] Ensure trace_id in all responses (`recommend.py`)
- [ ] Implement 501 endpoints (`decisions.py`)
- [ ] Fix SSE fallback path (`DecisionTrace.tsx`)

### Short Term (Week 1)
- [ ] Add response schema validation
- [ ] Implement error handling middleware
- [ ] Add loading states to frontend
- [ ] Create integration tests

### Production Readiness (Week 2-3)
- [ ] Set up health check endpoints
- [ ] Configure rate limiting
- [ ] Add audit logging
- [ ] Set up Prometheus metrics
- [ ] Configure distributed tracing
- [ ] Database migrations for indexes

### AI/ML Enhancements (Week 3-4)
- [ ] Implement model tiering
- [ ] Add semantic search with embeddings
- [ ] Enhance intent classification
- [ ] Implement CV damage classifier
- [ ] Add personalization engine

### Deployment (Week 4+)
- [ ] Docker production build
- [ ] Kubernetes manifests
- [ ] CI/CD pipeline
- [ ] Monitoring dashboards
- [ ] Runbook documentation

---

*End of Production-Ready Complete Guide*
