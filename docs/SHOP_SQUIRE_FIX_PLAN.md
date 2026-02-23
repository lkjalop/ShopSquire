# ShopSquire Fix Plan (Comprehensive Handoff)

Purpose: single document for GitHub Copilot to implement fixes and wiring. This includes frontend, backend, and analytics/ops. It lists each change with file targets and suggested replacement blocks or pseudocode where exact blocks are large.

---

## 0) Quick context

- Frontend entry point: `src/frontend/storefront-react/src/App.jsx`
- Frontend styles: `src/frontend/storefront-react/src/styles.css`
- API base env: `VITE_API_BASE` (default `http://localhost:8080/api/v1`)
- Recommend endpoint: `GET /api/v1/recommend/suggest?uid=&query=`
- Decision trace endpoint: `GET /api/v1/decisions/{trace_id}`
- CV complaints: `POST /api/v1/support/complaints/submit` and `GET /api/v1/support/complaints/{case_id}/status`

---

## 1) Frontend – Decision Trace Panel (make it dynamic + drill-down + rolling log)

### Goals
- No static demo trace unless explicitly requested.
- Rolling log view (list of trace events) with timestamps.
- Drill-down sections hidden by default: Playbook, MITRE/CVSS/DREAD/PASTA, Evidence.
- Include agent + human actors in the log if backend returns `actor_type` or `human_review`.

### File
- `src/frontend/storefront-react/src/App.jsx`

### Add state
Add the following state near other `useState` declarations:
```jsx
const [traceLog, setTraceLog] = useState([]); // array of trace entries
const [traceExpandedId, setTraceExpandedId] = useState(null);
```

### On each user interaction, append to trace log
In `handleSendMessage()` after `setLastTrace(...)`, add:
```jsx
const now = new Date();
const entry = {
  id: (data.trace_id || data.decision_id || `local-${now.getTime()}`),
  time: now.toISOString(),
  query: userMessage.content,
  status: data.status || 'ok',
  decision_id: data.decision_id,
  trace_id: data.trace_id,
  policy_version: data.policy_version,
  risk_score: data.risk_score,
  security: data.security,
  agent_chain: data.agent_chain,
  model_tier: data.model_tier,
  llm_model: data.llm_model,
  complexity_signals: data.complexity_signals,
  playbook: data.playbook,
  human_review: data.human_review, // if backend supplies
};
setTraceLog((prev) => [entry, ...prev].slice(0, 25));
```

### CV decisions should also append to trace log
After CV upload success and after each polling response, add entries:
```jsx
setTraceLog((prev) => [{
  id: `cv-${case_id}-${Date.now()}`,
  time: new Date().toISOString(),
  query: 'CV complaint analysis',
  status: decision || 'processing',
  decision_id: case_id,
  trace_id: case_id,
  security: data.fraud_signals || {},
  agent_chain: data.agent_chain,
  human_review: data.human_review,
  playbook: data.playbook,
}, ...prev].slice(0, 25));
```

### Update `DevTracePanel` to accept and render `traceLog`
Change signature:
```jsx
const DevTracePanel = ({ open, onClose, trace, traceLog, expandedId, onToggle }) => { ... }
```

Add a rolling log list at top:
```jsx
<div style={{ marginBottom: '12px' }}>
  <div style={{ fontWeight: 600, marginBottom: '6px' }}>Trace Log</div>
  {traceLog.length === 0 ? (
    <small style={{ color: '#6b7280' }}>No trace events yet.</small>
  ) : (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {traceLog.map((item) => (
        <div key={item.id} style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <div style={{ fontWeight: 600 }}>{item.query || 'Event'}</div>
            <small>{new Date(item.time).toLocaleTimeString()}</small>
          </div>
          <div style={{ fontSize: '12px', color: '#6b7280' }}>
            {item.status} • {item.decision_id || item.trace_id}
          </div>
          <button className="secondary sm" onClick={() => onToggle(item.id)}>
            {expandedId === item.id ? 'Hide details' : 'Show details'}
          </button>
          {expandedId === item.id && (
            <div style={{ marginTop: '8px' }}>
              <pre style={{ fontSize: '11px', whiteSpace: 'pre-wrap' }}>{JSON.stringify(item, null, 2)}</pre>
            </div>
          )}
        </div>
      ))}
    </div>
  )}
</div>
```

Wire it:
```jsx
<DevTracePanel
  open={devTraceOpen}
  onClose={() => setDevTraceOpen(false)}
  trace={lastTrace}
  traceLog={traceLog}
  expandedId={traceExpandedId}
  onToggle={(id) => setTraceExpandedId((prev) => (prev === id ? null : id))}
/>
```

### Hide Playbook + Security details under drill-down
Inside `DevTracePanel`, for Playbook and Security sections, wrap with toggle buttons:
```jsx
const [showPlaybook, setShowPlaybook] = useState(false);
const [showSecurity, setShowSecurity] = useState(false);
```

Then:
```jsx
<button className="secondary sm" onClick={() => setShowPlaybook(!showPlaybook)}>
  {showPlaybook ? 'Hide Playbook' : 'Show Playbook'}
</button>
{showPlaybook && (...existing playbook render...)}
```

Same for MITRE/CVSS/DREAD/PASTA.

---

## 2) Frontend – Make chat response reflect real constraints

### Issue
Currently, if backend fails, chat responds with demo text. If backend works, it still doesn’t summarize filtered specs.

### Fix
- When backend response includes `constraints_used` or `proposal.nlp`, build a summary in assistant response.

### File
- `src/frontend/storefront-react/src/App.jsx`

### Suggested assistant reply builder
Replace assistant message text in `handleSendMessage` with:
```jsx
const constraints = data.constraints_used || {};
const specSummary = Array.isArray(constraints.specs) ? constraints.specs.join(', ') : '';
const budgetMin = constraints.budget_min;
const budgetMax = constraints.budget_max;
const budgetText = budgetMin && budgetMax
  ? `between $${budgetMin} and $${budgetMax}`
  : budgetMax ? `under $${budgetMax}`
  : budgetMin ? `over $${budgetMin}` : '';
const intro = results.length
  ? `I found ${results.length} options${budgetText ? ` ${budgetText}` : ''}.`
  : `I couldn't find matches${budgetText ? ` ${budgetText}` : ''}.`;
const specText = specSummary ? `Specs matched: ${specSummary}.` : '';
const assistantText = `${intro} ${specText}`.trim();
```

---

## 3) Backend – Filter by budget AND specs

### Issue
Price filtering works. Spec filtering (1TB, RAM) is not enforced in results.

### File
- `src/app/routers/recommend.py`

### Add spec filtering pass
After candidates are retrieved and optionally filtered by price, add:
```python
specs = constraints.get("specs") or []
if specs:
    def _match_spec(c):
        c_specs = c.get("specs") or {}
        c_text = json.dumps(c_specs).lower()
        for s in specs:
            if s.startswith("ram:") and s.split(":",1)[1] not in c_text:
                return False
            if s.startswith("ssd:") and s.split(":",1)[1] not in c_text:
                return False
            if s.startswith("gpu:") and "gpu" not in c_text:
                return False
        return True
    candidates = [c for c in candidates if _match_spec(c)]
```

Add `Spec_Filter_Agent` into `agent_chain` when filtering occurs.

---

## 4) Decision Trace: Add human review + ticketing linkage

### Goal
Trace panel should show if a human/security/admin is in the loop.

### Backend additions (if not already):
- `human_review`: `{status: 'pending'|'approved'|'rejected', by: 'admin@shop.com', ticket_id: 'TKT-123'}`
- `agent_chain` includes human actor:
```json
{ "agent": "Human_Reviewer", "confidence": null, "duration_ms": 120000, "actor_type": "human" }
```

### Files
- `src/app/routers/decisions.py`
- `src/app/routers/support_complaints.py`
- `src/app/services/ticketing.py`

Add `human_review` in the decision trace response and in CV status response.

---

## 5) CV flow – refund rejection, policy breach, fraud

### Goal
If return policy lapsed or receipt mismatch, CV flow should show rejection + evidence + escalation.

### Backend
- `src/app/routers/support_complaints.py`
Add or extend:
```python
cv_analysis = {
  "confidence": 0.88,
  "severity": "high",
  "signals": {
      "receipt_mismatch": True,
      "return_window_expired": True,
      "duplicate_claim": False
  }
}
```

Return:
```json
"decision": "blocked",
"human_review": {"status": "pending", "ticket_id": "TKT-..."}
```

---

## 6) API / TimescaleDB / PolicyGraph / ContextGraph

### TimescaleDB (analytics)
- Convert `decision_logs` and `security_events` to hypertables.
- Add continuous aggregates (per-tier, per-agent).
- Endpoints in `/api/v1/query` should read from aggregates.

Files:
- `db/migrations/timescale_continuous_aggregates.sql`
- `src/app/services/conversational_query.py`

### PolicyGraph / PolicyRAG
- Store policy evaluations in `pg_evaluations` tied to decision_id.
- Include `policy_gates` in decision trace response.

Files:
- `src/app/services/policy_graph_evaluator.py`
- `src/app/routers/decisions.py`

### ContextGraph
- If using `contextgraph` or `policygraph`, store edges: `decision_id -> policy_id -> rule_id`.

---

## 7) Security Agent Improvements

### Add more standards
If you ingest ISO 27001, ISO 42001, EU AI Act:
- Add them to policy graph tables, or add `policy_version` referencing the standards set.
- Security agent should include a `compliance_flags` field in trace for visibility.

### PCI-DSS enforcement
- Never log PAN/CVV or Stripe tokens.
- Redaction already exists; confirm `redact_payload()` runs on payment endpoints.

---

## 8) Ollama model tiering & escalation

### Goal
Model tier displayed in trace. Complexity-based escalation/degradation.

Backend:
- Ensure `model_tier`, `llm_model`, `complexity_signals` are always set in `recommend/suggest`.
- Add escalation rule: if complexity high and GPU unavailable, respond degraded with reason.

Files:
- `src/app/routers/recommend.py`
- `src/app/services/llm_provider.py`

---

## 9) Frontend Buttons + Wiring Checklist

### Buttons that must work
- Header: Cart, Bell (optional), Gear (trace)
- Chat overlay: Camera, Send, Gear, Close
- Right panel: Grid/List/Compare, Demo Trace (optional), Close
- CV: Escalate to human
- Cart: Checkout

Ensure each maps to functions in `App.jsx` and triggers API calls:
- `handleSendMessage()` -> `/api/v1/recommend/suggest`
- `handleViewDetail()` -> `/api/v1/products/{sku}`
- `handleAddToCart()` -> `/api/v1/cart/items`
- `handleCheckout()` -> `/api/v1/orders/create`
- `handleComplaintSubmit()` -> `/api/v1/support/complaints/submit`
- CV polling -> `/api/v1/support/complaints/{case_id}/status`

---

## 10) Playwright tests (recommended)

Add new tests to `tests/browser` that target React UI:
- Price range filter: “between 1500 and 2200” returns only in range.
- Spec filter: “1TB” returns only spec-matching products.
- Decision trace panel updates after query.
- CV upload -> status -> trace entry -> escalation button shown.

---

## 11) Clarify Tailwind decision

If you want Tailwind:
- Install Tailwind + config under `src/frontend/storefront-react`.
- Replace `styles.css` with Tailwind base imports and rework classes.

If you do NOT want Tailwind:
- Keep `styles.css` and extend it for improved visuals.

---

## 12) What’s blocking current behavior

If the chat is generic:
- The frontend is failing to reach the backend.
- Confirm API is running and `VITE_API_BASE` is correct.

---

## 13) Prioritized order

1) Fix decision trace log + drill-downs + timestamps (frontend).
2) Add spec filtering in backend.
3) CV flow audit trail + human review fields.
4) Playwright tests for UI + CV + trace.
5) Timescale + PolicyGraph + ContextGraph integrations.

---

End of file.
