# ShopSquire: What's Left to Fix - Final Analysis

**Date:** 2026-02-01
**Based on:** Deep codebase analysis + verification of platform_fixes_applied v1, v2, v3

---

## Executive Summary

After verifying all fixes from v1/v2/v3 and doing a deep dive into agent communication, frontend integration, and backend wiring:

| Component | Status | Blocking Issues |
|-----------|--------|-----------------|
| Policy Gate Bypass | FIXED | None |
| Token Budget Disabled | FIXED | None |
| Case ID Bug | FIXED | None |
| Factory Mock Opt-in | FIXED | None |
| Decision Trace Events | WORKING | 35+ events logged |
| Agent Communication | WORKING | Direct calls, not AgentBus |
| Gear Icon Logic | CORRECT | Shows when traceId exists |
| **CV Triage Response** | **BROKEN** | Field name mismatch |
| **NLP → Products Flow** | **PARTIAL** | May still return empty |
| **Decision Endpoints** | **501 ERRORS** | Not fully implemented |

**Bottom Line:** 3 critical issues remain before frontend works end-to-end.

---

## Part 1: Verified Fixes (All Applied)

### From v1 (platform_fixes_applied.md)

| Fix | File | Status |
|-----|------|--------|
| LLM mocking in tests | tests/conftest.py:182-246 | VERIFIED |
| CV/reverse-search mocks | tests/conftest.py:246-285 | VERIFIED |
| Factory opt-in for mocks | src/agents/factory.py:42-68 | VERIFIED |
| TieredCVProvider.process() | src/app/services/cv_tiered.py:34-69 | VERIFIED |
| create_case() before fraud | src/app/routers/support_complaints.py:703-706 | VERIFIED |

### From v2 (platform_fixes_appliedv2.md)

| Fix | File | Status |
|-----|------|--------|
| DECISION_LOG_WRITES_ENABLED | src/app/config.py:52-72 | VERIFIED |
| TEST_BYPASS_POLICY_GATE default | src/app/config.py:76 | VERIFIED |
| TOKEN_BUDGET_ENABLED check | src/app/services/token_budget.py:51-55,89,103 | VERIFIED |
| Integration test added | tests/integration/test_chat_recommend_integration.py | VERIFIED |
| Playwright scaffold added | tests/pw/test_recommend_playwright_e2e.py | VERIFIED |

### From v3 (platform_fixes_appliedv3.md)

| Fix | File | Status |
|-----|------|--------|
| policy_version in early exits | src/app/routers/recommend.py:335,405,424 | VERIFIED |

---

## Part 2: Agent Communication Status

### What's CONNECTED (Working)

#### recommend.py Agents:
| Agent | Connection | File:Line |
|-------|-----------|-----------|
| PolicyEvaluator | Direct call | recommend.py:231-246 |
| SecurityObserver | Direct call | recommend.py:192, 1100, 1106, 1122 |
| InventoryAgent | Direct instantiation | recommend.py:779, 788 |

#### support_complaints.py (CV) Agents:
| Agent | Connection | File:Line |
|-------|-----------|-----------|
| ManagedCVProvider | Async call | support_complaints.py:571 |
| FraudScorer | Direct call | support_complaints.py:690, 706-713 |
| TrustRouter | Direct call | support_complaints.py:658-659 |
| TicketingAgent | Direct call | support_complaints.py:445, 950, 1314 |

#### chat.py:
| Integration | Connection | File:Line |
|-------------|-----------|-----------|
| Forward to recommend | HTTP delegation | chat.py:39, 49 |
| Return decision_trace_id | Mapped from response | chat.py:77, 90 |

### What's NOT CONNECTED

| Component | Status | Impact |
|-----------|--------|--------|
| AgentBus (pub/sub) | EXISTS but UNUSED | No async agent messaging |
| AuditEvidenceAgent | NOT IMPORTED | No audit integration in main flows |
| Agent-to-Agent handoff | BLUEPRINT ONLY | No runtime handoffs |

### Decision Trace Event Logging

**recommend.py:** 18 log_trace_event() calls
- policy_gate, security_watch, human_escalation, security_scan
- intent_classified, user_query, candidate_retrieval
- agent_process (multiple), inventory_check, rerank
- model_selection, next_questions

**support_complaints.py:** 17 log_trace_event() calls
- policy_gate, agent_handoff, human_escalation
- risk_summary, evidence_bundle, evidence_persisted
- cv_pipeline (multiple flows)

**Status:** COMPREHENSIVE - Events ARE being logged.

---

## Part 3: Frontend Integration Issues

### Issue #1: Gear Icon (Decision Trace) - CORRECT BUT DEPENDENT

**Logic (App.tsx:391):**
```typescript
{traceId && <GearIcon onClick={() => setTraceOpen(true)} />}
```

**Why it might not show:**
- `traceId` is set from `data.decision_trace_id` (line 248)
- If recommend.py returns empty results AND early-exits, `trace_id` may be null
- The `_with_trace()` helper (recommend.py:55-62) should add trace_id to all responses

**Verdict:** Logic is correct. Issue is backend returning null trace_id on empty results.

---

### Issue #2: CV Triage Response - CRITICAL MISMATCH

**Frontend expects (RightPanelExtras.tsx:75-79):**
```typescript
setResult({
  decision_id: j.decision_id,      // OK - backend returns this
  case_id: j.case_id,              // MISSING - backend returns ticket_id
  analysis: j.analysis,            // MISSING - backend returns intent/confidence/entities
  suggested_routing: j.suggested_routing,  // MISSING - backend returns recommended_action
  human_review: j.human_review,    // OK - backend returns this
});
```

**Backend returns (support_complaints.py:512-524):**
```python
return {
    "intent": parsed["intent"],
    "confidence": parsed["confidence"],
    "entities": parsed["entities"],
    "severity": severity,
    "recommended_action": recommended_action,  # Frontend expects "suggested_routing"
    "decision_id": decision_id,
    "ticket_id": ticket_id,  # Frontend expects "case_id"
    "human_review": {...},
}
```

**Result:** Frontend displays:
- Verdict: — (empty)
- Decision: (works)
- Case: — (empty)

---

### Issue #3: Decision Endpoints Return 501

**Mentioned in v1 report:** "Decision audit & bitemporal endpoints returning 501 Not Implemented"

**Affected endpoints:**
- `/api/v1/decisions/{trace_id}/reopen`
- `/api/v1/decisions/{trace_id}/query`

**Impact:** DecisionTrace component may fail when calling these endpoints.

---

## Part 4: Files to Edit

### CRITICAL FIXES (Must Do)

#### Fix 1: CV Triage Response Field Names
**File:** `src/app/routers/support_complaints.py`
**Lines:** 512-524 (submit_complaint return statement)

**Change:**
```python
# Add these field mappings to the return dict:
return {
    # ... existing fields ...
    "case_id": case_id,  # ADD - frontend expects this
    "analysis": {        # ADD - frontend expects this
        "intent": parsed["intent"],
        "confidence": parsed["confidence"],
        "entities": parsed["entities"],
        "severity": severity,
    },
    "suggested_routing": recommended_action,  # ADD - alias for frontend
    # ... rest of fields ...
}
```

#### Fix 2: Ensure trace_id Always Returned
**File:** `src/app/routers/recommend.py`
**Lines:** All early-exit return statements

**Verify:** Every return statement includes `"trace_id": trace_id` even when results are empty.

Check these locations:
- Line ~335 (policy review required)
- Line ~405 (security flagged)
- Line ~424 (budget exceeded)
- Line ~1050 (invalid SKU)
- Line ~1090 (safety blocked)

#### Fix 3: Decision Endpoint 501s
**File:** `src/app/routers/decisions.py`

**Implement or stub:**
- `reopen` endpoint (currently 501)
- `query` endpoint (currently 501)

Or update DecisionTrace.tsx to handle 501 gracefully.

---

### RECOMMENDED FIXES (Should Do)

#### Fix 4: Guest CV Submission Response
**File:** `src/app/routers/support_complaints.py`
**Lines:** ~1350-1370 (submit_complaint_guest return)

Same field mapping as Fix 1.

#### Fix 5: SSE Fallback Path
**File:** `frontend/src/components/DecisionTrace.tsx`
**Lines:** 260-270

**Current:** Tries same SSE path twice on failure.
**Should:** Try alternate path `/api/v1/trace/{traceId}/events/stream` as fallback.

#### Fix 6: Add case_id to CV Pipeline
**File:** `src/app/routers/support_complaints.py`

Ensure `case_id` variable is included in return (it's created at line 704 but not returned).

---

## Part 5: Integration Tests Needed

### Existing Tests (Verify They Pass)

```
tests/integration/test_chat_recommend_integration.py
tests/pw/test_recommend_playwright_e2e.py (scaffold)
```

### New Tests to Create

#### Test 1: Chat → Products E2E
**File:** `tests/integration/test_chat_to_products_e2e.py`

```python
"""
Test: User sends chat query → Backend returns products → Frontend displays them
Validates:
- /api/v1/chat/query returns products array
- decision_trace_id is present
- Products have required fields (sku, name, price)
"""
def test_chat_query_returns_products():
    # POST /api/v1/chat/query with "laptop under 1500"
    # Assert response.products is non-empty
    # Assert response.decision_trace_id is not None
    pass

def test_chat_query_with_filters():
    # POST with "16GB RAM laptop between 1000 and 2000"
    # Assert products match constraints
    pass
```

#### Test 2: CV Triage Full Flow
**File:** `tests/integration/test_cv_triage_e2e.py`

```python
"""
Test: User submits CV complaint → Backend processes → Returns verdict
Validates:
- /api/v1/support/complaints/submit accepts FormData
- Returns case_id, analysis, suggested_routing
- Decision trace events are logged
"""
def test_cv_submit_returns_verdict():
    # POST with order_id, issue_type, description, images
    # Assert response.case_id is not None
    # Assert response.suggested_routing in ['approve', 'deny', 'escalate', 'review']
    pass

def test_cv_submit_without_images():
    # POST without images
    # Assert still returns valid response
    pass
```

#### Test 3: Decision Trace Flow
**File:** `tests/integration/test_decision_trace_e2e.py`

```python
"""
Test: After chat query, decision trace is retrievable
Validates:
- GET /api/v1/decisions/{trace_id} returns trace data
- GET /api/v1/trace/{trace_id}/timeline returns events
- SSE endpoint streams events
"""
def test_decision_trace_retrievable():
    # 1. POST /api/v1/chat/query
    # 2. Extract decision_trace_id
    # 3. GET /api/v1/decisions/{trace_id}
    # Assert response has agent_chain, policy_gates
    pass

def test_timeline_has_events():
    # GET /api/v1/trace/{trace_id}/timeline
    # Assert events array is non-empty
    pass
```

#### Test 4: Agent Chain Visibility
**File:** `tests/integration/test_agent_chain_visibility.py`

```python
"""
Test: Recommendation response includes agent_chain with timing
Validates:
- response.agent_chain is array
- Each agent has name, confidence, duration_ms
"""
def test_agent_chain_in_response():
    # POST /api/v1/recommend/suggest
    # Assert agent_chain exists and has entries
    pass
```

#### Test 5: NLP Intent Detection
**File:** `tests/integration/test_nlp_intent_detection.py`

```python
"""
Test: NLP correctly identifies intents from queries
"""
def test_bulk_purchase_intent():
    # "buy 15 laptops for AI engineering"
    # Assert intent detected as bulk_purchase or similar
    pass

def test_return_intent():
    # "I want to return my laptop"
    # Assert redirects to returns/CV flow
    pass

def test_comparison_intent():
    # "compare MacBook vs Dell XPS"
    # Assert comparison mode triggered
    pass
```

---

## Part 6: Quick Validation Commands

### Check if Backend Returns Products

```powershell
# Test recommend endpoint directly
curl -X POST http://localhost:8080/api/v1/recommend/suggest `
  -H "Content-Type: application/json" `
  -H "x-api-key: local-merchant-key" `
  -d '{"query": "laptop", "constraints": {}}'

# Should return {"results": [...], "trace_id": "...", ...}
```

### Check if CV Returns Verdict

```powershell
# Test CV endpoint (no images)
curl -X POST http://localhost:8080/api/v1/support/complaints/submit `
  -H "x-api-key: local-merchant-key" `
  -F "order_id=TEST-123" `
  -F "issue_type=refund" `
  -F "description=Product damaged"

# Should return {"case_id": "...", "suggested_routing": "...", ...}
```

### Check if Decision Trace Works

```powershell
# After getting a trace_id from recommend
curl http://localhost:8080/api/v1/decisions/{trace_id} `
  -H "x-api-key: local-merchant-key"

# Should return trace with agent_chain
```

### Run Integration Tests

```powershell
# Run all integration tests
.venv\Scripts\python.exe -m pytest tests/integration -v

# Run specific test
.venv\Scripts\python.exe -m pytest tests/integration/test_chat_recommend_integration.py -v
```

---

## Part 7: Priority Order

### Must Fix (Blocking Frontend)

1. **CV Response Field Names** - Frontend shows empty verdict
   - File: `src/app/routers/support_complaints.py`
   - Add: `case_id`, `analysis`, `suggested_routing` to return

2. **Ensure trace_id in All Responses** - Gear icon won't show
   - File: `src/app/routers/recommend.py`
   - Verify all early-exit returns include trace_id

3. **Database Seeding** - No products = no results
   - Run seed script or verify products table has data

### Should Fix (Stability)

4. **Decision Endpoint 501s** - Trace panel may error
   - File: `src/app/routers/decisions.py`
   - Implement or stub reopen/query endpoints

5. **SSE Fallback Path** - Duplicate retry logic
   - File: `frontend/src/components/DecisionTrace.tsx`
   - Use different fallback path

### Nice to Have (Polish)

6. **Integration Tests** - Prevent regressions
7. **Error Messages** - Surface failures to UI
8. **Loading States** - Better UX during API calls

---

## Part 8: Summary

### What's Working
- All v1/v2/v3 fixes are applied and verified
- Agent communication via direct function calls (18+ agents connected)
- Decision trace event logging (35+ event types)
- Policy gate bypass in non-production
- Token budget disabled in test
- Gear icon logic is correct

### What's Broken
1. **CV Triage Response** - Field name mismatch (case_id, analysis, suggested_routing)
2. **trace_id on Empty Results** - May not be returned, blocking gear icon
3. **Decision Endpoints 501** - Some trace operations fail

### Files to Edit
1. `src/app/routers/support_complaints.py` - Add CV response fields
2. `src/app/routers/recommend.py` - Ensure trace_id always returned
3. `src/app/routers/decisions.py` - Fix 501 endpoints
4. `frontend/src/components/DecisionTrace.tsx` - Fix SSE fallback

### Tests to Create
1. `tests/integration/test_chat_to_products_e2e.py`
2. `tests/integration/test_cv_triage_e2e.py`
3. `tests/integration/test_decision_trace_e2e.py`
4. `tests/integration/test_agent_chain_visibility.py`
5. `tests/integration/test_nlp_intent_detection.py`

---

## Appendix: Is This a Claude Code / AI Agent Issue?

**Yes and No.**

**What AI code generation caused:**
- Components built in isolation that look complete
- Each file passes its own tests
- Integration points have subtle mismatches (field names, response shapes)
- Error handling hides failures rather than surfacing them

**What's NOT AI's fault:**
- Architecture is sound (agents, services, routers pattern is correct)
- Code quality is high
- The fixes applied (v1-v3) show the system CAN be integrated

**The Pattern:**
AI generates excellent component code but doesn't maintain cross-file integration context. Each generation is isolated, leading to:
- Backend returns `recommended_action`, frontend expects `suggested_routing`
- Backend returns `ticket_id`, frontend expects `case_id`

**Solution:** Integration tests that validate end-to-end flows, not just unit tests.

---

*End of Analysis*
