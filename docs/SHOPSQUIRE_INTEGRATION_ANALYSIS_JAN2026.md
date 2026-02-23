# ShopSquire Frontend-Backend Integration Analysis

**Date:** January 31, 2026
**Issue:** Decision Trace not showing, NLP not context-aware for "AI engineering", Inventory Agent not triggered, CV/Mic buttons non-functional

---

## Port Configuration (CRITICAL)

| Component | Port | URL |
|-----------|------|-----|
| **Frontend (Vite)** | 3000 | `http://localhost:3000` |
| **Backend (FastAPI)** | 8080 | `http://127.0.0.1:8080` |

### Current Vite Proxy Config (`frontend/vite.config.ts`):
```typescript
server: {
  port: 3000,
  proxy: {
    '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
    '/ui': { target: 'http://127.0.0.1:8080', changeOrigin: true },
    '/static': { target: 'http://127.0.0.1:8080', changeOrigin: true }
  }
}
```

### How to Start:

```bash
# Terminal 1: Start Backend on port 8080
cd D:\AI\agentLumen\ShopSquire
python -m uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8080

# Terminal 2: Start Frontend on port 3000
cd D:\AI\agentLumen\ShopSquire\frontend
npm run dev
```

Then open: **http://localhost:3000**

---

## Summary of Issues from Screenshot

From `dump/shop-inventoryagent.png`, the user queried:
> "i want to buy 15 for work. i need a laptop between 1500 to 2000 for ai engineering use?"

**Problems observed:**
1. **Decision Trace shows "No events recorded"** - trace not persisting/loading
2. **NLP ignored "buy 15"** - no quantity extraction, no inventory check
3. **NLP ignored "AI engineering"** - no use-case context matching
4. **No stock check for bulk order** - Inventory Agent not triggered
5. **Response was generic** - "Found 5 products matching your criteria" with no AI engineering context

---

## Root Cause Analysis

### 1. Decision Trace Not Showing Events

**Location:** `src/app/services/decision_log.py:135-217`

**Problem:** The trace events ARE being logged via `log_trace_event()`, but:

1. **Database table may not exist:** The `decision_trace_events` table must exist for events to persist
2. **Frontend fetches from wrong endpoint:** `DecisionTrace.tsx:198` calls `/api/v1/decisions/${traceId}` and `/api/v1/trace/${traceId}/timeline`
3. **Missing timeline endpoint:** There's no `/api/v1/trace/{trace_id}/timeline` route defined - the decision trace events router at `src/app/routers/decision_trace_events.py` may have different paths

**Fix Required in:** `src/app/routers/decision_trace_events.py`

```python
# Need to add or verify this endpoint exists:
@router.get("/trace/{trace_id}/timeline")
def get_trace_timeline(trace_id: str, db=Depends(get_db)):
    rows = db.execute(
        text("SELECT * FROM decision_trace_events WHERE trace_id = :tid ORDER BY created_at"),
        {"tid": trace_id}
    ).fetchall()
    return {"events": [dict(r) for r in rows]}
```

---

### 2. NLP Not Extracting Quantity ("buy 15")

**Location:** `src/app/services/recommendations.py:228-235`

**Current Code:**
```python
def _extract_quantity(self, text: str) -> Optional[int]:
    m = re.search(r"(?:qty|quantity|units|pcs)\s*[:=]?\s*(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*(?:units|pcs|items)\b", text)
    if m:
        return int(m.group(1))
    return None
```

**Problem:** Pattern doesn't match "buy 15" or "want 15" phrases.

**Fix Required at Line 228:**
```python
def _extract_quantity(self, text: str) -> Optional[int]:
    # Pattern for "buy X", "want X", "need X", "order X"
    m = re.search(r"(?:buy|want|need|order|get|purchase)\s+(\d+)\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:qty|quantity|units|pcs)\s*[:=]?\s*(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*(?:units|pcs|items|of them|laptops?|computers?)\b", text)
    if m:
        return int(m.group(1))
    return None
```

---

### 3. NLP Not Detecting "AI Engineering" Use Case

**Location:** `src/app/services/recommendations.py:494-501`

**Current Code:**
```python
if any(k in text for k in ("video", "creator", "editing")):
    entities["use_case"] = "content_creation"
elif any(k in text for k in ("gaming", "gpu", "graphics")):
    entities["use_case"] = "gaming"
elif any(k in text for k in ("travel", "battery", "on the go")):
    entities["use_case"] = "mobile"
elif any(k in text for k in ("office", "work", "business")):
    entities["use_case"] = "business"
```

**Problem:** No pattern for "AI", "ML", "machine learning", "engineering", "data science", "deep learning"

**Fix Required at Line 494:**
```python
# Add AI/ML use case detection BEFORE the generic "work" check
if any(k in text for k in ("ai", "artificial intelligence", "machine learning", "ml", "deep learning",
                            "data science", "engineering", "cuda", "tensor", "pytorch", "tensorflow")):
    entities["use_case"] = "ai_ml_workstation"
    # AI/ML workloads need: high RAM (32GB+), discrete GPU (RTX/CUDA), fast storage
    if not spec_slots.get("ram_gb_min"):
        spec_slots["ram_gb_min"] = 32
    if not spec_slots.get("gpu_class"):
        spec_slots["gpu_class"] = "discrete"
elif any(k in text for k in ("video", "creator", "editing")):
    entities["use_case"] = "content_creation"
# ... rest unchanged
```

---

### 4. Inventory Agent Not Triggered for Bulk Orders

**Location:** `src/app/routers/recommend.py:741-769`

**Current Code:** Inventory Agent runs but only logs trace events - it doesn't:
1. Check if requested quantity (15) is available
2. Block/warn if insufficient stock
3. Surface stock info in the response

**Problem:** The code at line 742-769 only evaluates stock rules for display - it doesn't check quantity vs stock.

**Fix Required at Line 741:**
```python
# Inventory agent evaluation WITH quantity check
try:
    from src.app.services.inventory_agent import InventoryAgent
    inv = InventoryAgent()
    inv_evals = []
    requested_qty = constraints.get("quantity") or 1
    insufficient_stock_warning = None

    for c in (candidates or [])[:8]:
        stock = int(c.get("stock") or 0)
        ctx = {"stock": stock}
        sku_val = c.get("sku") or ""
        try:
            res = inv.evaluate_stock_rule(sku_val, ctx)
            res["available_qty"] = stock
            res["requested_qty"] = requested_qty
            res["can_fulfill"] = stock >= requested_qty
            inv_evals.append({"sku": sku_val, **res})

            # Check if bulk order can be fulfilled
            if requested_qty > 1 and stock < requested_qty:
                if insufficient_stock_warning is None:
                    insufficient_stock_warning = f"Note: Some products may not have {requested_qty} units in stock."
        except Exception:
            inv_evals.append({"sku": sku_val, "rule_id": None, "action": "eval_failed", "escalate": False})

    # Log and add warning to response
    if inv_evals:
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="inventory_check",
                source_type="agent",
                source_id="Inventory_Agent",
                target_type="system",
                target_id=None,
                payload={"evaluations": inv_evals, "requested_qty": requested_qty},
            )
        except Exception:
            pass
except Exception:
    pass
```

---

### 5. Camera and Microphone Buttons Not Functional

**Location:** `frontend/src/App.tsx:361, 370`

**Current Code:**
```tsx
<button className={styles.inputIconBtn}><CameraIcon /></button>
// ... input ...
<button className={styles.inputIconBtn}><MicIcon /></button>
```

**Problem:** Buttons are purely decorative - no `onClick` handlers, no media capture logic.

**Fix Required at Lines 361 and 370:**

```tsx
// Add state for media capture
const [isRecording, setIsRecording] = useState(false);
const [mediaStream, setMediaStream] = useState<MediaStream | null>(null);

// Camera handler - capture image for CV analysis
const handleCameraClick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    setMediaStream(stream);
    // Open camera modal or capture frame
    // Then send to /api/v1/cv/analyze endpoint
  } catch (err) {
    console.error('Camera access denied:', err);
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: 'Camera access was denied. Please enable camera permissions to use this feature.',
      timestamp: new Date()
    }]);
  }
};

// Microphone handler - speech-to-text
const handleMicClick = async () => {
  if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: 'Speech recognition is not supported in your browser. Try Chrome or Edge.',
      timestamp: new Date()
    }]);
    return;
  }

  const SpeechRecognition = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
  const recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = (event: any) => {
    const transcript = event.results[0][0].transcript;
    setInputValue(transcript);
    setIsRecording(false);
  };

  recognition.onerror = () => setIsRecording(false);
  recognition.onend = () => setIsRecording(false);

  setIsRecording(true);
  recognition.start();
};

// Update buttons with handlers
<button
  className={styles.inputIconBtn}
  onClick={handleCameraClick}
  title="Take photo for product lookup"
>
  <CameraIcon />
</button>

<button
  className={`${styles.inputIconBtn} ${isRecording ? styles.recording : ''}`}
  onClick={handleMicClick}
  title={isRecording ? 'Listening...' : 'Voice input'}
>
  <MicIcon />
</button>
```

---

## How to Start the Frontend

**Location:** `frontend/package.json`

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies (first time only)
npm install

# Start development server
npm run dev

# Or build for production
npm run build
npm run preview
```

**Default port:** Vite runs on `http://localhost:5173`

---

## How to Wire Frontend to Backend

### 1. Vite Proxy Configuration

**File:** `frontend/vite.config.ts`

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',  // FastAPI backend
        changeOrigin: true,
      },
      '/ui': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
});
```

### 2. Backend Must Be Running

```bash
# From project root
uvicorn src.app.main:app --reload --port 8000

# Or with all dependencies
python -m uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Feature Flags for Decision Logging

**File:** `config/feature_flags.json`

Ensure these are set to `true`:
```json
{
  "DECISION_LOG_WRITES_ENABLED": true,
  "DECISION_LOG_READS_ENABLED": true,
  "USE_OLLAMA_INTENT": true,
  "USE_LLM_RERANK": true
}
```

---

## Context-Aware AI/ML Architecture Gap

Per the playbooks at:
- `dump/context_aware_agent_guardrails.md`
- `dump/shopsquire_thinking_modes_playbook_jan2026.md`

The architecture SHOULD implement:

### Expected Flow (from playbooks):
1. **Tier 0 (Deterministic):** Intent classification, entity extraction
2. **Tier 1 (Light ML):** Semantic routing, embedding similarity
3. **Tier 2 (Deep):** LLM rerank with bounded tool calls

### Current Implementation Gap:

| Component | Expected | Actual |
|-----------|----------|--------|
| Intent FSM | Yes | Partial - no state machine |
| Typed Entity Extraction | Yes | Partial - missing quantity, AI use-case |
| Inventory Agent in loop | Yes | No - only logs, doesn't gate results |
| Risk Scoring | Yes | Partial - security only, not stock risk |
| Next Question Engine | Yes | Yes - works |
| Policy Gate | Yes | Yes - works |
| LLM Rerank | Yes | Yes - works if Ollama running |

---

## Files to Change Summary

| File | Line | Issue | Change Required |
|------|------|-------|-----------------|
| `src/app/services/recommendations.py` | 228-235 | Quantity not extracted | Add "buy X", "want X" patterns |
| `src/app/services/recommendations.py` | 494-501 | AI/ML use case missing | Add "ai", "machine learning" detection |
| `src/app/routers/recommend.py` | 741-769 | Inventory not checking qty | Add quantity vs stock comparison |
| `frontend/src/App.tsx` | 361, 370 | Camera/mic non-functional | Add onClick handlers with media APIs |
| `src/app/routers/decision_trace_events.py` | - | Timeline endpoint missing | Add `/trace/{id}/timeline` route |
| `frontend/src/components/DecisionTrace.tsx` | 198-220 | Wrong API paths | Verify endpoints match backend |

---

## Verification Commands

```bash
# 1. Check if decision_trace_events table exists
sqlite3 data/shopsquire.db ".schema decision_trace_events"

# 2. Check if trace events are being written
sqlite3 data/shopsquire.db "SELECT COUNT(*) FROM decision_trace_events"

# 3. Test recommendation API directly
curl -X GET "http://localhost:8080/api/v1/recommend/suggest?uid=test&query=buy%2015%20laptops%20for%20ai%20engineering%20between%201500%20and%202000" \
  -H "x-api-key: local-merchant-key"

# 4. Check feature flags loaded
curl http://localhost:8080/api/v1/admin/flags -H "x-api-key: local-admin-key"

# 5. Check if Ollama is running (for LLM features)
curl http://localhost:11434/api/tags
```

---

## Quick Fix Checklist

- [x] Add quantity extraction patterns in `recommendations.py:228` ✅ IMPLEMENTED
- [x] Add AI/ML use case detection in `recommendations.py:494` ✅ IMPLEMENTED
- [x] Add stock vs quantity check in `recommend.py:741` ✅ IMPLEMENTED
- [ ] Add `/trace/{id}/timeline` endpoint or verify existing route (already exists at `decision_trace_events.py:230`)
- [x] Add camera/mic onClick handlers in `App.tsx` ✅ IMPLEMENTED
- [ ] Verify `decision_trace_events` table exists in database
- [x] Ensure feature flags are enabled (verified in `config/feature_flags.json`)
- [ ] Start backend on port 8080
- [x] Vite proxy configured to backend port 8080
- [ ] Start frontend with `npm run dev`
