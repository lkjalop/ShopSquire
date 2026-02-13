# ShopSquire Dashboard Wireframes & Integration Guide
## Professional Backend Dashboards with Agent Integration

---

## Dashboard Status: COMPLETED

All 8 professional Grafana dashboards have been created with:
- Proper `gridPos` layouts
- Color-coded thresholds (green/yellow/red)
- Data links for drill-down navigation
- Configurable light/dark themes
- Panel descriptions and tooltips

| Dashboard | File | Panels | Key Features |
|-----------|------|--------|--------------|
| Executive Overview | `shopsquire-executive-overview.json` | 14 | KPIs, agent activity, security events |
| Agent Confidence | `shopsquire-agent-confidence.json` | 12 | Histogram, calibration, low-conf samples |
| CV Latency | `shopsquire-cv-latency.json` | 11 | Tier breakdown, slow requests, distribution |
| Escalation Rates | `shopsquire-escalation-rates.json` | 10 | By agent/reason, pending queue with actions |
| RAGAS Scores | `shopsquire-ragas-over-time.json` | 11 | 4 metrics, CI guard, low-score decisions |
| Model Selection | `shopsquire-model-selection.json` | 11 | Tier distribution, cost savings, T2 reasons |
| Query Cluster Drift | `shopsquire-query-cluster-drift.json` | 11 | Volume, drift score, new clusters |
| Human Review Queue | `shopsquire-human-review-queue.json` | 10 | Pending table, outcomes, avg review time |

---

## Integration Architecture

```
+------------------+     WebSocket      +------------------+
|                  |<-------------------|                  |
|   FRONTEND       |  /events/ws        |   BACKEND        |
|   (React/Vue)    |  /events/stream    |   (FastAPI)      |
|                  |------------------->|                  |
+--------+---------+     REST API       +--------+---------+
         |                                       |
         |  GET /decisions/{trace_id}            |
         |  GET /decisions/summary               |
         |                                       |
         v                                       v
+------------------+                    +------------------+
|   Grafana        |<-------------------|   Prometheus     |
|   Dashboards     |    PromQL          |   Metrics        |
+------------------+                    +------------------+
         |                                       ^
         |  Embed iframe or API                  |
         v                                       |
+------------------+     log_trace_event +-------+---------+
|   Evidence Panel |<--------------------|   Agents        |
|   (drill-down)   |     trace_broker    |   (11+ types)   |
+------------------+                     +-----------------+
```

---

## Part 1: Frontend Integration

### 1.1 WebSocket Connection for Real-Time Traces

Connect to the decision trace WebSocket to receive live events:

```typescript
// src/hooks/useDecisionTrace.ts
import { useEffect, useState, useCallback } from 'react';

interface TraceEvent {
  id: string;
  trace_id: string;
  event_type: string;
  source_type: string;
  source_id: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, any>;
  created_at: string;
}

export function useDecisionTrace(traceId: string) {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastEventTime, setLastEventTime] = useState<Date | null>(null);

  useEffect(() => {
    if (!traceId) return;

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/decisions/${traceId}/events/ws`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      try {
        const newEvents: TraceEvent[] = JSON.parse(event.data);
        setEvents(prev => [...prev, ...newEvents]);
        setLastEventTime(new Date());
      } catch (e) {
        console.error('Failed to parse trace event:', e);
      }
    };

    return () => ws.close();
  }, [traceId]);

  return { events, connected, lastEventTime };
}
```

### 1.2 SSE Stream Alternative

For environments where WebSocket is problematic:

```typescript
// src/hooks/useDecisionTraceSSE.ts
export function useDecisionTraceSSE(traceId: string) {
  const [events, setEvents] = useState<TraceEvent[]>([]);

  useEffect(() => {
    if (!traceId) return;

    const eventSource = new EventSource(
      `/api/v1/decisions/${traceId}/events/stream`
    );

    eventSource.onmessage = (event) => {
      const newEvents = JSON.parse(event.data);
      setEvents(prev => [...prev, ...newEvents]);
    };

    return () => eventSource.close();
  }, [traceId]);

  return events;
}
```

### 1.3 Evidence Drill-Down Component

```tsx
// src/components/EvidencePanel.tsx
import React, { useState } from 'react';

interface EvidencePanelProps {
  traceId: string;
  event: TraceEvent;
  onApprove: () => void;
  onReject: () => void;
}

export function EvidencePanel({ traceId, event, onApprove, onReject }: EvidencePanelProps) {
  const [expanded, setExpanded] = useState(false);

  const securityTags = event.payload?.security || {};
  const mitreTags = securityTags.mitre || [];
  const owaspTags = securityTags.owasp_llm || [];
  const strideTags = securityTags.stride || [];

  return (
    <div className={`evidence-panel ${expanded ? 'expanded' : ''}`}>
      <div className="evidence-header" onClick={() => setExpanded(!expanded)}>
        <span className="trace-id">{traceId}</span>
        <span className="event-type">{event.event_type}</span>
        <span className="source">{event.source_id} → {event.target_id}</span>
        <span className="time">{new Date(event.created_at).toLocaleTimeString()}</span>
      </div>

      {expanded && (
        <div className="evidence-body">
          {/* Security Tags */}
          <div className="security-tags">
            {mitreTags.map(tag => (
              <span key={tag} className="tag mitre">{tag}</span>
            ))}
            {owaspTags.map(tag => (
              <span key={tag} className="tag owasp">{tag}</span>
            ))}
            {strideTags.map(tag => (
              <span key={tag} className="tag stride">{tag}</span>
            ))}
          </div>

          {/* Payload JSON */}
          <div className="payload-section">
            <h4>Input</h4>
            <pre>{JSON.stringify(event.payload?.input, null, 2)}</pre>

            <h4>Context</h4>
            <pre>{JSON.stringify(event.payload?.context, null, 2)}</pre>

            <h4>Proposed Action</h4>
            <pre>{JSON.stringify(event.payload?.proposed_action, null, 2)}</pre>
          </div>

          {/* CV Evidence (if present) */}
          {event.payload?.cv_evidence && (
            <div className="cv-evidence">
              <h4>CV Forensics</h4>
              <div className="scores">
                <span>Manipulation: {event.payload.cv_evidence.manipulation_score}</span>
                <span>Splice: {event.payload.cv_evidence.splice_score}</span>
                <span>Blur: {event.payload.cv_evidence.blur_score}</span>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="actions">
            <button className="approve" onClick={onApprove}>Approve</button>
            <button className="reject" onClick={onReject}>Reject</button>
            <button className="request-info">Request More Info</button>
          </div>
        </div>
      )}
    </div>
  );
}
```

### 1.4 Grafana Panel Embedding

Embed Grafana panels in your custom frontend:

```tsx
// src/components/GrafanaDashboard.tsx
interface GrafanaPanelProps {
  dashboardUid: string;
  panelId: number;
  theme?: 'light' | 'dark';
  timeRange?: { from: string; to: string };
}

export function GrafanaPanel({ dashboardUid, panelId, theme = 'dark', timeRange }: GrafanaPanelProps) {
  const baseUrl = process.env.REACT_APP_GRAFANA_URL || 'http://localhost:3000';
  const from = timeRange?.from || 'now-24h';
  const to = timeRange?.to || 'now';

  const src = `${baseUrl}/d-solo/${dashboardUid}?panelId=${panelId}&from=${from}&to=${to}&theme=${theme}`;

  return (
    <iframe
      src={src}
      width="100%"
      height="300"
      frameBorder="0"
      title={`Grafana Panel ${panelId}`}
    />
  );
}

// Usage
<GrafanaPanel
  dashboardUid="shopsquire-exec-overview"
  panelId={7}
  theme="dark"
/>
```

---

## Part 2: Agent Integration

### 2.1 How Agents Emit Trace Events

All agents use `log_trace_event()` to emit events to the decision trace:

```python
# src/app/services/decision_log.py
from src.app.services.decision_log import log_trace_event

# Example: Agent emitting a trace event
log_trace_event(
    trace_id=trace_id,
    event_type="agent_decision",
    source_type="agent",
    source_id="InventoryAgent",
    target_type="system",
    target_id=None,
    payload={
        "decision": "approve_reorder",
        "confidence": 0.87,
        "reasoning": "Stock below threshold",
        "product_sku": "LAPTOP-001",
        "recommended_qty": 50,
    },
)
```

### 2.2 Agent Bus for Inter-Agent Communication

Agents communicate via Redis pub/sub:

```python
# src/app/services/agent_bus.py
from src.app.services.agent_bus import AgentBus, build_agent_message

# Publish message from one agent to another
bus = AgentBus(redis_client)
await bus.publish(
    build_agent_message(
        source_agent="InventoryAgent",
        target_agent="CVProvider",
        message_type="image_verification_request",
        payload={"image_url": "...", "context": {...}},
        trace_id=trace_id,
    )
)
```

### 2.3 Agent Handoff with Trace Logging

```python
# src/app/services/agent_handoff.py
from src.app.services.agent_handoff import AgentHandoff

handoff = AgentHandoff(bus)
await handoff.request_handoff(
    from_agent="InventoryAgent",
    to_agent="PricingAgent",
    reason="Need price optimization",
    context={"sku": "LAPTOP-001", "current_price": 999.00},
    trace_id=trace_id,
)
```

### 2.4 Registered Agents

| Agent | File | Trace Events Emitted |
|-------|------|---------------------|
| InventoryAgent | `src/app/services/inventory_agent.py` | `reorder_recommendation`, `ticket_created` |
| CVProvider | `src/app/services/cv_tiered.py` | `cv_tier_decision`, `forensics_result` |
| PricingAgent | `src/app/services/orchestrator.py` | `pricing_decision`, `competitor_match` |
| SecurityObserver | `src/app/security/observer.py` | `security_signal`, `velocity_anomaly` |
| TicketingAgent | `src/app/services/ticketing.py` | `ticket_created`, `ticket_escalated` |
| AuditEvidenceAgent | `src/app/services/audit_evidence_agent.py` | `evidence_collected` |
| ConversationalQuery | `src/app/services/conversational_query.py` | `nlp_intent`, `query_cluster` |
| InterleavingController | `src/app/services/interleaving_controller.py` | `think`, `tool_call`, `observe` |
| HumanReviewQueue | `src/agents/human_review.py` | `review_queued`, `review_completed` |
| PolicyGateAgent | `src/app/tools/runner.py` | `policy_gate` |
| GeoIPService | `src/app/services/geoip.py` | `geoip_lookup`, `geo_anomaly` |

---

## Part 3: Grafana Deployment

### 3.1 Provisioning Dashboards

Copy dashboard JSON files to Grafana provisioning:

```bash
# Copy dashboards to Grafana provisioning
cp config/observability/grafana/dashboards/*.json /etc/grafana/provisioning/dashboards/

# Create provisioning config
cat > /etc/grafana/provisioning/dashboards/shopsquire.yaml << EOF
apiVersion: 1
providers:
  - name: 'ShopSquire'
    orgId: 1
    folder: 'ShopSquire'
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards
EOF
```

### 3.2 Required Prometheus Metrics

Ensure these metrics are exposed by the backend:

```python
# Core metrics (src/app/observability/metrics.py)
shopsquire_agent_invocations_total{agent}
shopsquire_agent_escalations_total{agent, reason}
shopsquire_agent_confidence{agent}
shopsquire_decision_events_total{result}
shopsquire_security_events_total{event_type, severity}
shopsquire_human_review_pending
shopsquire_human_review_completed_total{outcome}

# CV metrics
shopsquire_cv_tier_selection_total{tier}
shopsquire_cv_processing_seconds_bucket{tier, le}

# RAGAS metrics
shopsquire_ragas_faithfulness_score
shopsquire_ragas_answer_relevance_score
shopsquire_ragas_context_precision_score
shopsquire_ragas_context_recall_score

# Model selection
shopsquire_model_selection_total{tier}
shopsquire_model_cost_savings_usd

# Query clustering
shopsquire_query_cluster_volume_total{cluster}
shopsquire_cluster_drift_score
```

### 3.3 Theme Configuration

Dashboards support a `theme` variable for light/dark switching:

1. Select dashboard
2. Click Settings (gear icon)
3. Go to Variables
4. Edit `theme` variable
5. Set default to `dark` or `light`

---

## Part 4: Evidence Drill-Down Flow

### 4.1 Click Path

```
Dashboard Panel (table row)
    ↓ Click row
Data Link: /api/v1/decisions/${trace_id}
    ↓ Opens
Decision Detail Page
    ↓ Contains
Evidence Panel with:
    - Input data
    - Retrieved context
    - Proposed action
    - Security tags (MITRE, OWASP, STRIDE)
    - CV evidence (if applicable)
    - Action buttons (Approve/Reject)
```

### 4.2 API Endpoints for Evidence

```
GET /api/v1/decisions/{trace_id}
    → Full decision log with input/context/action

GET /api/v1/decisions/{trace_id}/events
    → All trace events for this decision

GET /api/v1/decisions/{trace_id}/events/stream
    → SSE stream of new events

WS  /api/v1/decisions/{trace_id}/events/ws
    → WebSocket for real-time events
```

### 4.3 Security Tags Structure

```json
{
  "security": {
    "severity": "high",
    "mitre": ["AML.T0001", "AML.T0015"],
    "owasp_llm": ["LLM01", "LLM02"],
    "owasp_agentic": ["AG01"],
    "stride": ["Tampering", "Spoofing"],
    "cvss": {"score": 7.5},
    "dread": {"avg": 6.2},
    "evidence": {
      "matched_patterns": ["jailbreak_attempt", "excessive_tokens"]
    }
  }
}
```

---

## Part 5: Quick Start

### 5.1 Local Development

```bash
# Start backend
uvicorn src.app.main:app --reload --port 8000

# Start Prometheus (docker)
docker run -p 9090:9090 -v $(pwd)/config/observability/prometheus.yml:/etc/prometheus/prometheus.yml prom/prometheus

# Start Grafana (docker)
docker run -p 3000:3000 \
  -v $(pwd)/config/observability/grafana/dashboards:/etc/grafana/provisioning/dashboards \
  -e GF_AUTH_ANONYMOUS_ENABLED=true \
  grafana/grafana
```

### 5.2 Access Dashboards

- Grafana: http://localhost:3000
- Default credentials: admin/admin
- Navigate to Dashboards → ShopSquire folder

### 5.3 Test WebSocket

```javascript
// Browser console
const ws = new WebSocket('ws://localhost:8000/api/v1/decisions/test-trace-123/events/ws');
ws.onmessage = (e) => console.log('Event:', JSON.parse(e.data));
```

---

## Summary

| Component | Status | Location |
|-----------|--------|----------|
| 8 Grafana Dashboards | Done | `config/observability/grafana/dashboards/` |
| WebSocket Endpoint | Done | `src/app/routers/decisions.py:423` |
| SSE Stream | Done | `src/app/routers/decisions.py:452` |
| Trace Broker | Done | `src/app/services/trace_broker.py` |
| Agent Bus | Done | `src/app/services/agent_bus.py` |
| log_trace_event | Done | `src/app/services/decision_log.py:189` |
| Evidence API | Done | `src/app/routers/decisions.py` |
| Security Tags | Done | `_build_security_payload()` |
