# ShopSquire Comprehensive Fix Plan (Low-Tokens)

**Date:** 2026-01-31  
**Purpose:** Provide a single actionable plan to get the platform fully testable (frontend + backend + agents + Decision Trace + CV verdict), including exact files to edit and why.

---

## 0) Quick Answers (Current Reality)

### Which Vite frontend are we using?
- **Folder:** `D:\AI\agentLumen\ShopSquire\frontend`
- **Dev server command:** `npm run dev`
- **Current port:** **3001** (because 3000 was already in use)
- **Dev proxy target:** **8080** in `frontend/vite.config.ts`
- **Open URL:** `http://localhost:3001`

### Why agents appear “not used”
- **Policy gate is blocking** recommendation flow → results empty → no trace id in response → no Decision Trace gear icon.
- **CV endpoint returns no verdict** when model isn’t available or backend didn’t process → no verdict UI.
- **Decision Trace SSE path was mismatched** earlier; now fixed, but if trace id isn’t returned, it won’t show.

---

## 1) Top Blockers (Fix First)

### A) Policy Gate blocks recommendations
**Symptom:** “Found 0 products”, no gear icon.  
**Root cause:** policy gate returns `review_required` / `deny` for low-risk queries.

**Fix Options:**
1) **Dev bypass (fastest for validation):**
   - Set env: `TEST_BYPASS_POLICY_GATE=1`
   - Restart backend

2) **Adjust gate logic for dev:**
   - File: `src/app/routers/recommend.py`
   - Search: `evaluate_policy_gate(` and `gate_requires_review`
   - Lower risk thresholds or skip deny when `request_type == 'recommend'`.

**Expected result:** results returned, `decision_trace_id` present, gear icon visible.

---

### B) Decision Trace gear icon missing
**Symptom:** No gear icon in chat header.  
**Root cause:** `traceId` isn’t set because backend response didn’t include `decision_trace_id`.

**Fix Options:**
1) Ensure backend returns `decision_trace_id` in `/api/v1/chat/query`.  
   - File: `src/app/routers/chat.py`
   - Search: `decision_trace_id =` and output payload.

2) Optional: For dev, force `traceId` even on empty results.  
   - File: `frontend/src/App.tsx`
   - Search: `setTraceId(data.decision_trace_id || null)`

---

### C) Decision Trace SSE endpoint
**Symptom:** Trace doesn’t update dynamically.  
**Fix:** Already applied.
- Frontend SSE: `/api/v1/decisions/${traceId}/events/stream`
- Backend SSE: `src/app/routers/decisions.py` endpoint `/api/v1/decisions/{trace_id}/events/stream`

---

## 2) CV Verdict Issues (Need Real Output)

### Why verdict is empty
- The CV submit endpoint may return no analysis if the model is not loaded, or the CV pipeline fails.

### Where to inspect
- File: `src/app/routers/support_complaints.py`
- Endpoint: `/api/v1/support/complaints/submit`
- Check how `analysis` / `suggested_routing` / `decision_id` are computed.

### How to test with real model
1) Confirm Ollama is running:
   - `curl http://localhost:11434/api/tags`
2) Ensure model exists:
   - `ollama list`
3) Warm up CV model:
   - `ollama run llava:latest "warmup"`

### Test without model
- Add a dev fallback verdict if model call fails.
- File: `src/app/routers/support_complaints.py`
- Search: `analysis` or `suggested_routing`
- Example fallback:
  ```python
  if not analysis:
      analysis = {"verdict": "needs_review", "confidence": 0.1}
      suggested_routing = "human_review"
  ```

---

## 3) NLP Improvements (Already Implemented — Verify)

### Quantity extraction
- File: `src/app/services/recommendations.py`
- Search: `def _extract_quantity`
- Should match: `buy/want/need/order/get/purchase X` and `X laptops/computers`.

### AI/ML use-case detection
- File: `src/app/services/recommendations.py`
- Search: `# AI/ML use case detection`
- Should set:
  - `use_case = ai_ml_workstation`
  - `ram_gb_min = 32`
  - `gpu_class = discrete`

### Context pack (pre-LLM)
- File: `src/app/services/recommendations.py`
- Search: `context_pack = {`
- Ensure it is returned and logged in trace events.

---

## 4) Agent Trace Logging (Dynamic)

### Candidate retrieval + rerank
- File: `src/app/routers/recommend.py`
- Search: `event_type="candidate_retrieval"` and `event_type="rerank"`

### Inventory agent
- File: `src/app/routers/recommend.py`
- Search: `event_type="inventory_check"`
- Ensure `requested_qty`, `can_fulfill`, `insufficient_stock_skus` logged.

### Policy / security
- File: `src/app/routers/recommend.py`
- Search: `event_type="policy_gate"`

---

## 5) Frontend UI Fixes

### Right panel missing products
- Cause: backend returned empty results (policy gate / filtering).
- Fix: bypass policy gate (dev) or loosen constraints.

### Gear icon for Decision Trace
- Appears only when `traceId` is non-null.
- Fix: ensure backend returns `decision_trace_id`.

---

## 6) Ports / Services (Current Live Setup)

- **Backend:** `http://127.0.0.1:8080`
- **Frontend:** `http://localhost:3001`
- **Proxy:** `frontend/vite.config.ts` → 8080
- **Ollama:** `http://localhost:11434`

---

## 7) Recommended Dev Workflow (Validation)

1) Start backend:
   ```bash
   python -m uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8080
   ```

2) Start frontend:
   ```bash
   cd frontend
   npm run dev
   ```

3) Test query:
   ```
   buy 15 laptops for AI engineering between 1500 and 2000
   ```

4) Confirm:
   - products show on right panel
   - gear icon appears
   - Decision Trace shows events

5) Test CV:
   - Upload images in CV panel
   - Confirm `Verdict` is populated

---

## 8) Open Questions (If You Want Me to Patch Next)

1) Do you want **policy gate bypass** permanently in dev builds?
2) Should Decision Trace gear show even when results are empty?
3) Should CV endpoint return a **mock verdict** if model unavailable?
4) Which port do you want the frontend to always run on (3000 vs 3001)?

---

## 9) Files to Edit (Master List)

- `frontend/vite.config.ts` (proxy target)
- `frontend/src/App.tsx` (trace id usage / gear icon)
- `frontend/src/components/DecisionTrace.tsx` (SSE path, empty-state)
- `src/app/routers/recommend.py` (policy gate, trace logging)
- `src/app/routers/chat.py` (decision_trace_id)
- `src/app/services/recommendations.py` (quantity + AI use case + context_pack)
- `src/app/routers/support_complaints.py` (CV verdict logic)

---

## 10) Testing: With and Without LLaVA

### With LLaVA (`llava:latest`)
- Run: `ollama run llava:latest "warmup"`
- Submit CV images in UI
- Expect: `suggested_routing` + `decision_id` + `analysis`

### Without LLaVA
- Add fallback verdict in `support_complaints.py`
- Expect: always returns `human_review` or `needs_review`

---

End.
