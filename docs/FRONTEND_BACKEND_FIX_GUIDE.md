# ShopSquire Frontend-Backend Fix Guide

**Date:** 2026-01-30
**Author:** Claude Code Investigation
**Priority:** HIGH - Multiple critical issues affecting user experience

---

## Executive Summary

The ShopSquire frontend appears functional but the backend is running in a **deeply degraded mode**. The NLP assistant shows no intelligence because:

1. **LLM is disabled** - All queries processed via regex/keyword matching
2. **Price filtering is broken** - Products outside requested range appear
3. **Price sorting not implemented** - Products appear in arbitrary order
4. **Decision trace is empty** - Feature flag disabled by default
5. **Agents are unused** - 11+ agents defined but not connected to pipelines
6. **No model prewarming** - Cold starts on every request

---

## Visual Evidence

### Issue 1: NLP Not Intelligent
**Screenshot:** `dump/laptop-smart.png`

![laptop-smart.png](../dump/laptop-smart.png)

**User Queries:**
- "compare apple mac versus laptop i can use for gaming. what specs should I need?"
- "why is my mac cant do gaming in ultra max graphics?"

**Expected:** Intelligent comparison explaining GPU requirements, VRAM, thermal throttling, etc.

**Actual:** "Found 12 products matching your criteria" or "No products found matching those criteria"

**Root Cause:** LLM is NOT being called. System uses only keyword extraction.

---

### Issue 2: Price Filtering & Sorting Broken
**Screenshot:** `dump/laptop-pricewrong.png`

![laptop-pricewrong.png](../dump/laptop-pricewrong.png)

**User Query:** "show me products between 1200 to 2100"

**Expected:** Products priced $1,200-$2,100, sorted from cheapest to most expensive.

**Actual:**
- Products shown: $1,099, $1,999, $1,799, $1,449, $1,649, $1,899, $2,799, **$849**, $1,599, $1,299
- **$849 and $2,799 are OUTSIDE the requested range**
- Products are NOT sorted by price

---

## Root Cause Analysis

### 1. LLM Integration is DISABLED

**Location:** `src/app/routers/recommend.py`

**Line 472:**
```python
if flags.get("USE_OLLAMA_INTENT", False):  # <-- DEFAULT IS FALSE
```

**Line 760:**
```python
use_llm = bool(flags.get("USE_LLM_RERANK", False))  # <-- DEFAULT IS FALSE
```

**Fix Required:**
```python
# config/feature_flags.json - Enable LLM features
{
  "USE_OLLAMA_INTENT": true,
  "USE_LLM_RERANK": true,
  "DECISION_LOG_WRITES_ENABLED": true
}
```

**Files to Update:**
| File | Line | Change |
|------|------|--------|
| `config/feature_flags.json` | N/A | Add `"USE_OLLAMA_INTENT": true` |
| `config/feature_flags.json` | N/A | Add `"USE_LLM_RERANK": true` |
| `src/app/routers/recommend.py` | 472 | Change default to `True` |
| `src/app/routers/recommend.py` | 760 | Change default to `True` |

---

### 2. NLP is Rule-Based, Not AI

**Location:** `src/app/services/recommendations.py`

**Lines 442-545:** `analyze_query()` method

**Current Implementation:**
```python
# Line 443-450: ALL extraction is regex-based
budget_min, budget_max, budget = self._extract_price_range(text)  # regex
spec_slots = self._extract_specs(text)  # regex for "16gb ram"
brand_includes, brand_excludes = self._extract_brands(text)  # substring matching
```

**Fix Required:**

Add LLM-based intent understanding before regex extraction:

```python
# In src/app/services/recommendations.py - Line ~443
async def analyze_query(self, text: str, ...) -> dict:
    # NEW: Call LLM for semantic understanding
    from src.app.services.llm_provider import analyze_query_with_llm

    llm_analysis = await analyze_query_with_llm(text)
    if llm_analysis:
        # Use LLM-extracted intents, entities, price ranges
        return llm_analysis

    # Fallback to regex if LLM unavailable
    budget_min, budget_max, budget = self._extract_price_range(text)
    ...
```

**New Function to Add in `src/app/services/llm_provider.py`:**

```python
async def analyze_query_with_llm(query: str) -> dict | None:
    """Use Ollama to semantically analyze user query."""
    prompt = f"""Analyze this shopping query and extract:
- intent: (search, compare, recommend, question)
- price_min: number or null
- price_max: number or null
- brands: list of brands mentioned
- specs: list of specs (RAM, storage, etc.)
- sort_preference: (price_asc, price_desc, rating, relevance)

Query: {query}

Return JSON only."""

    try:
        response = await call_ollama(prompt)
        return json.loads(response)
    except Exception:
        return None
```

---

### 3. Price Filtering Bug

**Location:** `src/app/repositories/catalog.py`

**Lines 86-117:** `search_products()` method

**Problem:** Database query does NOT filter by price. It only matches keywords.

```python
# Line 104-107: No price filter in SQL
clauses = []
for col in search_cols:
    clauses.append(col.ilike(f"%{kw}%"))
# Missing: AND price_cents BETWEEN :min AND :max
```

**Fix Required:**

```python
# src/app/repositories/catalog.py - Line ~107
def search_products(self, keywords: list[str], min_price: int = None, max_price: int = None, ...):
    clauses = []
    for kw in keywords:
        for col in search_cols:
            clauses.append(col.ilike(f"%{kw}%"))

    query = select(Product).where(or_(*clauses))

    # ADD PRICE FILTERING AT DATABASE LEVEL
    if min_price is not None:
        query = query.where(Product.price_cents >= min_price * 100)
    if max_price is not None:
        query = query.where(Product.price_cents <= max_price * 100)

    return session.execute(query).scalars().all()
```

**Also Update:** `src/app/routers/recommend.py` lines 559-573 to pass price params:

```python
# Line ~565: Pass price range to repository
candidates = repo.search_products(
    keywords=keywords,
    min_price=budget_min,  # ADD
    max_price=budget_max,  # ADD
    limit=limit
)
```

---

### 4. Price Sorting Not Implemented

**Location:** `src/app/services/recommendations.py`

**Lines 652-744:** `rerank_candidates_with_factors()`

**Current:** Products sorted by composite score (availability + budget fit + brand).

**Line 738:**
```python
scored.sort(key=lambda x: x["score"], reverse=True)  # By score, NOT price
```

**Fix Required:**

Add sort_preference parameter and sorting logic:

```python
# src/app/services/recommendations.py - Line ~744
def rerank_candidates_with_factors(self, candidates, ..., sort_preference: str = "relevance"):
    # ... existing scoring logic ...

    scored.sort(key=lambda x: x["score"], reverse=True)

    # ADD: Apply user's sort preference after initial scoring
    if sort_preference == "price_asc":
        scored.sort(key=lambda x: x.get("price_cents", 0))
    elif sort_preference == "price_desc":
        scored.sort(key=lambda x: x.get("price_cents", 0), reverse=True)
    elif sort_preference == "rating":
        scored.sort(key=lambda x: x.get("rating", 0), reverse=True)
    # else: keep relevance/score sorting

    return scored[:top_n]
```

**Update Frontend** - `frontend/src/App.tsx` line ~77:

```typescript
const handleSend = async () => {
  // Detect sort preference from query
  const sortPref = /cheap|lowest|least expensive|ascending/i.test(q) ? 'price_asc' :
                   /expensive|highest|most expensive|descending/i.test(q) ? 'price_desc' :
                   'relevance';

  // Pass to API
  body: JSON.stringify({ query: q, sort_preference: sortPref })
}
```

---

### 5. Decision Trace is Empty

**Location:** `src/app/routers/decisions.py`

**Lines 119-121:**
```python
if not flags.get("DECISION_LOG_WRITES_ENABLED", False):  # <-- DEFAULT FALSE
    raise HTTPException(status_code=501, detail="Decision reads disabled")
```

**Fix Required:**

1. **Enable in feature flags:**
```json
// config/feature_flags.json
{
  "DECISION_LOG_WRITES_ENABLED": true
}
```

2. **Ensure database table exists:**
```sql
-- db/schema.sql - Add if missing
CREATE TABLE IF NOT EXISTS decision_trace_events (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    seq INTEGER NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    source_id VARCHAR(64),
    payload JSONB,
    latency_ms INTEGER,
    tags TEXT[],
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_trace_events_trace_id ON decision_trace_events(trace_id);
```

3. **Verify trace logging is called:**

**Location:** `src/app/services/decision_log.py` lines 132-210

The `log_trace_event()` function exists and is called from recommend.py, but silently fails if table doesn't exist.

---

### 6. Agents Not Connected

**Location:** `src/agents/` directory (10 agent files exist but unused)

**Problem:** Agents are defined but NOT imported/invoked in the recommend/chat pipelines.

**Current (Non-functional):** `src/app/routers/recommend.py` lines 823-828
```python
# These are just STRING LABELS, not actual agent invocations
agent_chain = [
    {"agent": "Security_Observer_Agent", ...},
    {"agent": "NLP_Search_Agent", ...},
]
```

**Fix Required:**

Create an actual agent orchestration layer:

```python
# src/app/services/agent_orchestrator.py (NEW FILE)
from src.agents.factory import create_agent
from src.agents.recommendation_agent import RecommendationAgent
from src.agents.inventory_agent import MockInventoryAgent

class AgentOrchestrator:
    def __init__(self):
        self.agents = {
            "security": create_agent("security_observer"),
            "nlp": create_agent("nlp_search"),
            "retrieval": create_agent("candidate_retrieval"),
            "inventory": MockInventoryAgent(),
            "recommendation": RecommendationAgent(),
            "ranking": create_agent("product_ranking"),
            "policy": create_agent("policy_gate"),
        }

    async def process_query(self, query: str, trace_id: str) -> dict:
        result = {"trace_id": trace_id, "agent_chain": []}

        # 1. Security check
        security_result = await self.agents["security"].check(query)
        result["agent_chain"].append({"agent": "security", "result": security_result})

        # 2. NLP analysis
        nlp_result = await self.agents["nlp"].analyze(query)
        result["agent_chain"].append({"agent": "nlp", "result": nlp_result})

        # ... continue for all agents

        return result
```

**Update recommend.py to use orchestrator:**
```python
# src/app/routers/recommend.py - Line ~200
from src.app.services.agent_orchestrator import AgentOrchestrator

orchestrator = AgentOrchestrator()

@router.get("/suggest")
async def suggest(query: str, ...):
    result = await orchestrator.process_query(query, trace_id)
    return result
```

---

### 7. No Model Prewarming

**Problem:** No warmup code found. Ollama models load on first request (cold start).

**Fix Required:**

Add startup event in `src/app/main.py`:

```python
# src/app/main.py - Add near line 50
from src.app.services.llm_provider import warmup_models

@app.on_event("startup")
async def warmup_llm():
    """Prewarm Ollama models on startup."""
    import asyncio
    asyncio.create_task(warmup_models())

# src/app/services/llm_provider.py - Add new function
async def warmup_models():
    """Send dummy request to load models into memory."""
    models = ["llama3.2:3b", "mistral:7b"]
    for model in models:
        try:
            await call_ollama("Hello", model=model)
            logger.info(f"Prewarmed model: {model}")
        except Exception as e:
            logger.warning(f"Failed to prewarm {model}: {e}")
```

---

## Frontend Fixes

### 8. Decision Trace Popup Should Be Draggable

**Location:** `frontend/src/components/DecisionTrace.tsx`

**Current:** Fixed modal overlay, not draggable.

**Fix Required:**

Add drag functionality:

```typescript
// frontend/src/components/DecisionTrace.tsx - Add state and handlers
const [position, setPosition] = useState({ x: 100, y: 100 });
const [isDragging, setIsDragging] = useState(false);
const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

const handleMouseDown = (e: React.MouseEvent) => {
  setIsDragging(true);
  setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
};

const handleMouseMove = (e: React.MouseEvent) => {
  if (!isDragging) return;
  setPosition({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
};

const handleMouseUp = () => setIsDragging(false);

// Update modal div
<div
  className={styles.modal}
  style={{ position: 'fixed', left: position.x, top: position.y }}
  onMouseDown={handleMouseDown}
  onMouseMove={handleMouseMove}
  onMouseUp={handleMouseUp}
>
```

**CSS Update:** `frontend/src/components/DecisionTrace.module.css`

```css
.modal {
  position: fixed;  /* Change from centered to fixed position */
  cursor: move;
  user-select: none;
}

.header {
  cursor: grab;
}

.header:active {
  cursor: grabbing;
}
```

---

### 9. Detach to New Window

**Location:** `frontend/src/components/DecisionTrace.tsx`

**Add detach functionality:**

```typescript
const handleDetach = () => {
  const traceWindow = window.open('', 'DecisionTrace', 'width=700,height=600');
  if (traceWindow) {
    traceWindow.document.write(`
      <html>
        <head><title>Decision Trace - ${traceId}</title></head>
        <body>
          <div id="trace-root"></div>
          <script>
            // Fetch and display trace data
            fetch('/api/v1/decisions/${traceId}')
              .then(r => r.json())
              .then(data => {
                document.getElementById('trace-root').innerHTML =
                  '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
              });
          </script>
        </body>
      </html>
    `);
  }
};

// Update DetachIcon button
<button className={styles.iconBtn} onClick={handleDetach} title="Pop-out to new window">
  <DetachIcon />
</button>
```

---

## Quick Fix Checklist

| # | Issue | File | Line | Fix |
|---|-------|------|------|-----|
| 1 | Enable LLM intent | `config/feature_flags.json` | N/A | Add `"USE_OLLAMA_INTENT": true` |
| 2 | Enable LLM rerank | `config/feature_flags.json` | N/A | Add `"USE_LLM_RERANK": true` |
| 3 | Enable decision log | `config/feature_flags.json` | N/A | Add `"DECISION_LOG_WRITES_ENABLED": true` |
| 4 | Price filter at DB | `src/app/repositories/catalog.py` | 104 | Add price WHERE clause |
| 5 | Price sorting | `src/app/services/recommendations.py` | 738 | Add sort_preference logic |
| 6 | Model warmup | `src/app/main.py` | 50 | Add startup warmup event |
| 7 | Connect agents | `src/app/routers/recommend.py` | 200 | Import and use orchestrator |
| 8 | Draggable trace | `frontend/src/components/DecisionTrace.tsx` | All | Add drag handlers |

---

## Environment Requirements

```bash
# Ensure Ollama is running with required models
ollama pull llama3.2:3b
ollama pull mistral:7b
ollama serve  # Start Ollama server on port 11434

# Verify database schema
psql -d shopsquire -f db/schema.sql

# Enable feature flags
# Edit config/feature_flags.json to enable all flags listed above
```

---

## Testing After Fixes

```bash
# Test LLM is responding
curl -X POST http://localhost:11434/api/generate -d '{"model":"llama3.2:3b","prompt":"Hello"}'

# Test price filtering
curl "http://localhost:8080/api/v1/recommend/suggest?query=laptops%20between%201200%20and%202100"
# Should return ONLY products in $1200-$2100 range, sorted by price

# Test decision trace
curl "http://localhost:8080/api/v1/decisions/test-trace-123"
# Should return trace events, not empty

# Test NLP intelligence
curl "http://localhost:8080/api/v1/chat/query" -d '{"query":"why cant my mac do gaming?"}'
# Should return intelligent explanation about GPU limitations
```

---

## AI/ML Techniques Available But Not Active

The codebase includes these AI/ML capabilities that are **defined but not activated**:

| Technique | Location | Status |
|-----------|----------|--------|
| Sentence Embeddings | `src/app/services/embeddings.py` | Available, used for similarity |
| LLM Intent Classification | `src/app/services/llm_provider.py` | Gated behind flag |
| LLM Reranking | `src/app/services/llm.py` | Gated behind flag |
| RAG (Retrieval Augmented Generation) | `src/app/rag/` | Infrastructure only |
| RAGAS Evaluation | `src/app/analytics/ragas.py` | Available |
| Anomaly Detection | `src/app/analytics/anomaly.py` | Available |
| Fraud Scoring | `src/app/services/fraud_scorer.py` | Available |
| CV (Computer Vision) | `src/app/services/cv_*.py` | Available |

**To Activate AI/ML Features:**

1. Set all feature flags to `true` in `config/feature_flags.json`
2. Ensure Ollama server is running with models pulled
3. Run model warmup on startup
4. Connect agent orchestrator to pipelines

---

## Conclusion

The ShopSquire backend is architecturally sophisticated with 11+ agents, decision tracing, security layers, and AI/ML capabilities. However, it's running in a **conservative fallback mode** where all intelligence is disabled by feature flags.

**Immediate Actions:**
1. Enable feature flags
2. Fix price filtering in repository
3. Add price sorting
4. Make decision trace draggable
5. Add model prewarming

After these fixes, the frontend will show intelligent responses, correct price filtering, proper sorting, and live decision traces.
