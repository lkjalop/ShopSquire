# ShopSquire Platform Diagnostic Analysis

**Date:** 2026-01-31
**Analyst:** Claude Code (Deep Codebase Analysis)
**Purpose:** Root cause analysis of frontend-backend-agent disconnection issues and industry context

---

## Executive Summary

After a thorough codebase analysis and review of the visual evidence (CV-no-verdict.png, refund-fake.png), I've identified **systemic architectural issues** that explain why:

1. **Chat queries return "0 products found"** for all queries
2. **CV Triage returns no verdict** (Verdict: —, Decision: —, Case: —)
3. **Agents appear unused** despite extensive agent code existing
4. **Decision Trace gear icon never appears**

**Root Cause:** This is NOT a simple bug—it's an **integration architecture problem** where components were built in isolation and never properly wired together. This is a common pattern with AI-assisted code generation.

---

## Part 1: Visual Evidence Analysis

### Screenshot: CV-no-verdict.png & refund-fake.png

**Observed Failures:**

| Issue | Symptom | Expected |
|-------|---------|----------|
| Chat "buy 15 laptops for AI engineering" | "I couldn't find products" | Product list with AI workstations |
| Chat "list laptops with 16 gb from 1200 to 1800" | "I couldn't find products" | Filtered laptop list |
| Chat "i want to return item" | "I couldn't find products" | Intent redirect to CV/returns flow |
| CV Triage Submit | Verdict: —, Decision: —, Case: — | Verdict: approve/deny/escalate with case ID |
| Right Panel | "Found 0 products" | Matching products displayed |
| Decision Trace | No gear icon | Gear icon with trace events |

**What IS Working:**
- Frontend renders correctly
- Chat UI accepts input and shows messages
- CV upload accepts images and displays thumbnails
- Products load in background (visible at bottom of page)
- Submit button is functional

---

## Part 2: Root Cause Analysis

### Issue #1: Policy Gate Blocks ALL Recommendations

**File:** `src/app/routers/recommend.py` (lines 226-257)

**Problem:** The policy gate evaluates EVERY recommendation request and returns `review_required` or `deny` for most queries because:

1. Default risk thresholds are too conservative
2. Low-confidence queries (no user history) trigger review
3. Keyword-based security heuristics flag legitimate queries

**Evidence:**
```python
gate_decision = evaluate_policy_gate(trace_id, analysis, constraints, ...)
if gate_decision.get("verdict") in ("deny", "review_required"):
    # Returns empty results
```

**Why it fails:**
- "buy 15 laptops" → triggers "bulk purchase" fraud heuristic
- "AI engineering" → no matching security rule, low confidence
- Price ranges → trigger "budget anomaly" check with no user baseline

**Fix Required:** The `TEST_BYPASS_POLICY_GATE=1` env flag exists but isn't set. Even in production, the gate logic needs adjustment for legitimate e-commerce queries.

---

### Issue #2: Chat Endpoint Response Mapping Incomplete

**Files:**
- `src/app/routers/chat.py` (lines 45-91)
- `src/app/routers/recommend.py` (lines 1201-1342)

**Problem:** Even when recommend.py returns results, the mapping in chat.py can lose the `decision_trace_id`:

```python
# chat.py extracts trace_id
decision_trace_id = data.get("decision_id") or data.get("trace_id")

# But recommend.py returns trace_id ONLY if results are non-empty
if not results:
    return {"results": [], "trace_id": None}  # Lost!
```

**Why the gear icon never appears:**
- No results → no trace_id in response
- Frontend checks: `setTraceId(data.decision_trace_id || null)`
- Gear icon condition: `{traceId && <GearIcon />}`

---

### Issue #3: CV Triage Endpoint Has Critical Bug

**File:** `src/app/routers/support_complaints.py` (lines 709, 806)

**Problem:** Variable reference before assignment:
```python
# Line 709 - USES case_id
fraud_score, fraud_level, signals = fraud.score_with_enrichment(
    case_id=case_id if 'case_id' in locals() else None,  # ALWAYS None!
)

# Line 806 - CREATES case_id (too late!)
case_id = create_case(...)
```

**Additional Issues:**
1. Guest submission flow (`/submit-guest`) references undefined `nlp_rules` variable (line 1147)
2. LLaVA model may not be loaded → CV analysis returns empty
3. Evidence bundle persistence happens AFTER trace events → race condition

**Why verdict is always empty:**
- If Ollama/LLaVA unavailable → `analysis = {}`
- No fallback verdict logic for empty analysis
- Frontend displays raw empty object: `Verdict: —`

---

### Issue #4: Agents Exist But Are Never Called

**Architecture Discovery:**

| Agent | Location | Actually Used? |
|-------|----------|---------------|
| RecommendationAgent | `src/agents/recommendation_agent.py` | NO - recommend.py has inline logic |
| InventoryAgent | `src/app/services/inventory_agent.py` | PARTIAL - instantiated fresh, not from factory |
| Orchestrator | `src/agents/orchestrator.py` | NO - pricing.py uses services/orchestrator.py |
| AuditEvidenceAgent | `src/app/services/audit_evidence_agent.py` | NO - only direct calls from audit router |
| AgentBus | `src/app/services/agent_bus.py` | NO - pub/sub exists but no subscribers |
| AgentHandoff | `src/app/services/agent_handoff.py` | NO - never imported by any router |

**The Pattern:** Agents were designed but the routers implement their own inline logic instead of delegating. This is a **code duplication problem**—the agent infrastructure exists but routers bypass it.

---

### Issue #5: Factory Returns Mock Clients

**File:** `src/agents/factory.py` (lines 14-26)

```python
def default_clients() -> dict:
    return {
        "llm": MockLLMClient() if not os.getenv("ASTRALIS_API_KEY") else AstralisClient(),
        "inventory": MockInventoryAgent(),  # ALWAYS MOCK!
    }
```

**Problem:** Even if you call agents through the factory, you get mock implementations. Real inventory checking never happens.

---

### Issue #6: LLM Integration Disconnected from Main Pipeline

**Discovery:**

| LLM Component | Status |
|--------------|--------|
| `LLMProviderClient` | Real Ollama/OpenAI calls implemented |
| `LLMOrchestrator` | Real budget tracking implemented |
| `TokenBudget` | Real Redis-backed tracking |
| **Integration into pricing/recommend** | NOT CONNECTED |

The recommend.py endpoint has `select_ollama_model()` and `ollama_generate()` calls, but they're:
1. Wrapped in try/except that swallows failures
2. Fall back to rule-based scoring silently
3. Never surface LLM errors to the user

---

### Issue #7: Memory System Doesn't Store Agent State

**File:** `src/app/services/memory.py`

**What Memory Stores:**
- Session summaries
- User utterances
- Retrieval ranks
- Latency series

**What Memory DOESN'T Store:**
- Agent reasoning steps
- Multi-turn agent context
- Decision explanations
- Failed attempt history

**Result:** Each request starts fresh—no learning, no context continuity for agents.

---

## Part 3: Is This Common? Industry Context

### The Short Answer: **YES, this is extremely common.**

### Why This Happens

#### 1. AI Code Generation Pattern (Claude Code, Codex, Copilot)

AI coding assistants excel at generating **component-level code** but struggle with **integration**:

| AI Strength | AI Weakness |
|-------------|-------------|
| Generate agent class | Wire agent to router |
| Write endpoint handler | Connect to correct database |
| Create data model | Ensure data flows end-to-end |
| Implement algorithm | Handle edge cases across components |

**The Pattern You're Seeing:**
- Each file looks complete and professional
- Tests pass in isolation
- But components don't actually communicate
- Integration points have subtle mismatches

This is called **"Demo-Driven Development"**—code looks right, tests pass, but the full flow never works.

#### 2. E-commerce Platform Integration Is Hard

Even established platforms struggle:

| Platform | Known Integration Issues |
|----------|-------------------------|
| Shopify | App disconnections, webhook failures |
| Magento | Plugin conflicts, API version mismatches |
| WooCommerce | Theme/plugin incompatibilities |
| Salesforce Commerce | B2B/B2C data sync issues |

**Why?**
- Multiple data sources (catalog, inventory, pricing, users)
- Real-time requirements (stock, fraud, payments)
- Many moving parts (CDN, cache, DB, queues)

#### 3. Agentic AI Platforms Are New (2024-2026)

The "agentic" architecture (autonomous AI agents coordinating tasks) is bleeding-edge:

| Challenge | Status in Industry |
|-----------|-------------------|
| Agent orchestration | No standard framework |
| Agent memory/state | Research topic |
| Multi-agent communication | Early experiments |
| Production reliability | Largely unsolved |

**What ShopSquire is attempting:**
- Recommendation agents with LLM reasoning
- CV triage agents with vision models
- Policy gate agents with security rules
- Inventory agents with real-time stock

This is ambitious—most production systems use simpler architectures.

---

## Part 4: Specific Issues with AI-Generated Code

### Pattern 1: "Looks Complete But Isn't"

```python
# Agent class exists with all methods
class RecommendationAgent:
    def recommend(self, query, constraints):
        # Full implementation...
        return results

# Router IGNORES the agent and does inline:
@router.post("/suggest")
async def suggest(...):
    # 1300 lines of inline logic, never calls RecommendationAgent
```

### Pattern 2: "Error Handling Hides Failures"

```python
try:
    llm_response = await ollama_generate(prompt)
except Exception:
    llm_response = None  # Silently fails

if not llm_response:
    # Fall back to rules - user never knows LLM failed
    return rule_based_results()
```

### Pattern 3: "Tests Pass But Integration Fails"

```python
# test_recommendation_agent.py
def test_recommend():
    agent = RecommendationAgent()
    result = agent.recommend("laptops", {})
    assert len(result) > 0  # PASSES - agent works in isolation

# BUT: No test that /api/v1/chat/query actually uses the agent
```

### Pattern 4: "Configuration Drift"

```python
# recommend.py expects:
gate_decision = evaluate_policy_gate(trace_id, ...)

# policy_gate.py returns:
{"verdict": "allow", "confidence": 0.8}

# BUT: Real policy evaluator in src/app/policy/gate.py returns:
{"decision": "approve", "risk_score": 0.2}  # Different schema!
```

---

## Part 5: Additions to COMPREHENSIVE_FIX_PLAN.md

The existing fix plan is good but missing these critical items:

### A) Add to Section 1 (Top Blockers):

```markdown
### D) Factory Returns Mock Agents
**Symptom:** Inventory checks always pass, no real stock validation.
**Root cause:** `factory.py` hardcodes `MockInventoryAgent()`.

**Fix:**
- File: `src/agents/factory.py`
- Add environment check for real inventory client
- Or: Set `USE_REAL_INVENTORY=1` and implement real client

### E) Agents Not Used by Routers
**Symptom:** Agent code exists but behavior is inline in routers.
**Root cause:** Routers were written independently, not using agent classes.

**Fix Options:**
1) Refactor routers to use agents (significant work)
2) Accept that "agents" are just service functions (rename for clarity)
3) Keep both paths and document which is authoritative
```

### B) Add New Section 11: Integration Testing

```markdown
## 11) Integration Test Gaps

Current test coverage: 202 tests
- Unit tests: PASS
- Component tests: PASS
- **End-to-end integration: GAPS**

### Missing Integration Tests:
1) Full flow: Chat query → Recommend → Products displayed
2) Full flow: CV upload → Triage → Verdict returned
3) Full flow: Decision trace → Events → SSE stream
4) Negative test: Policy gate deny → User sees meaningful error

### Recommended Test Additions:
- `tests/integration/test_chat_to_products_e2e.py`
- `tests/integration/test_cv_triage_full_flow.py`
- `tests/integration/test_agent_orchestration.py`
```

### C) Add New Section 12: Environment Setup Checklist

```markdown
## 12) Dev Environment Checklist

Before testing, verify:

### Backend
- [ ] `TEST_BYPASS_POLICY_GATE=1` in .env (for dev)
- [ ] Ollama running: `curl http://localhost:11434/api/tags`
- [ ] LLaVA model loaded: `ollama list | grep llava`
- [ ] Database seeded: products exist in catalog table
- [ ] Redis running (or accept DummyRedis fallback)

### Frontend
- [ ] Backend URL matches vite.config.ts proxy (port 8080)
- [ ] API key in localStorage: `local-merchant-key`
- [ ] No browser console errors

### Quick Smoke Test
```bash
# Test recommend endpoint directly
curl -X POST http://localhost:8080/api/v1/recommend/suggest \
  -H "Content-Type: application/json" \
  -H "x-api-key: local-merchant-key" \
  -d '{"query": "laptop", "constraints": {}}'

# Should return products, not empty results
```
```

---

## Part 6: Recommended Path Forward

### Immediate (Get It Working)

1. **Set `TEST_BYPASS_POLICY_GATE=1`** - Unblock recommendations
2. **Add CV fallback verdict** - Return "needs_review" if model unavailable
3. **Fix case_id bug** - Move `create_case()` before fraud scoring
4. **Force trace_id in response** - Return trace even on empty results

### Short-Term (Stabilize)

1. **Add integration tests** - Test full flows, not just components
2. **Document API contracts** - What each endpoint expects/returns
3. **Add error visibility** - Surface failures to UI instead of silent fallback
4. **Fix factory mocks** - Enable real clients via environment

### Medium-Term (Architecture)

1. **Decide: Agents vs. Services** - Pick one pattern, consolidate code
2. **Implement agent orchestration** - If agents matter, wire them properly
3. **Add observability** - Trace why requests fail end-to-end
4. **Production configuration** - Remove test bypasses, tune policy gates

---

## Part 7: Answering Your Question

> Is this common for ecommerce or agentic platforms out there for frontend not to work with backend and agents not working? Or is this a coding agents issue like Claude Code or Codex GPT?

### Answer: **Both, but primarily an AI-assisted development pattern.**

**Why this specific issue:**

1. **AI coding tools generate isolated components well** but don't maintain integration context across files
2. **Each piece looks correct** - the agent code is good, the router code is good, the frontend code is good
3. **The connections between them are wrong** - schema mismatches, missing calls, wrong endpoints
4. **Tests pass because they test isolation** - no end-to-end integration tests

**This is NOT:**
- A fundamental e-commerce problem (those platforms work)
- A language/framework limitation (Python/FastAPI/React are fine)
- A skill issue (the code quality is high)

**This IS:**
- The predictable result of generating code without maintaining a running, tested integration
- Common when using AI to generate "features" without manual integration verification
- Fixable with systematic integration testing and configuration validation

---

## Conclusion

ShopSquire has professional-quality component code but suffers from **integration debt**. The agents, services, routers, and frontend all work individually but aren't properly connected. This is the signature of AI-assisted development without continuous integration testing.

The fix isn't rewriting—it's:
1. Configuration (policy gate bypass, env vars)
2. Bug fixes (case_id reference, response mapping)
3. Integration tests (verify full flows work)
4. Documentation (what should connect to what)

**Estimated effort to reach "demo-ready":** Days, not weeks—if focused on integration, not features.

---

*End of Analysis*
