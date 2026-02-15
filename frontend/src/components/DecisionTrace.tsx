import { useEffect, useState, useRef, useCallback } from 'react';
import styles from './DecisionTrace.module.css';
import { apiUrl, getApiBase, safeJson, wsUrl } from '../lib/api';

type TraceEvent = {
  id?: string;
  seq?: number;
  event_type: string;
  source_id?: string;
  latency_ms?: number;
  payload?: any;
  tags?: string[];
  timestamp?: string;
  created_at?: string;
};

type Trace = {
  decision_id: string;
  timestamp: string;
  input_query?: string;
  intent_analysis?: any;
  agent_chain?: any[];
  rag_context?: any;
  recommendation?: { product_id?: string; reasoning?: string; score?: number };
  policy_gates?: any;
  bitemporal?: any;
  model_selection?: {
    selected?: string | null;
    tier?: number | null;
    complex?: boolean | null;
    reason?: any;
    path?: string[] | null;
    latency_ms?: number | null;
    intent_summary?: string | null;
  };
};

// Icons
const CloseIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18"><path d="M18 6L6 18M6 6l12 12"/></svg>;
const DetachIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>;
const MinimizeIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><line x1="5" y1="12" x2="19" y2="12"/></svg>;
const ChevronIcon = ({ expanded }: { expanded: boolean }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.2s' }}>
    <polyline points="9 18 15 12 9 6"/>
  </svg>
);

// Verdict badge component
function VerdictBadge({ type }: { type: string }) {
  const colorMap: Record<string, string> = {
    rule_match: '#4CAF50',
    tool_call: '#2196F3',
    model_invoke: '#FF9800',
    escalation: '#F44336',
    policy_gate: '#9C27B0',
    security_block: '#F44336',
    success: '#4CAF50',
    warning: '#FF9800',
    error: '#F44336',
    query_received: '#2196F3',
    intent_analysis: '#9C27B0',
    agent_step: '#FF9800',
  };
  const color = colorMap[type] || '#6b7280';
  return <span className={styles.verdict} style={{ background: color }}>{type.replace(/_/g, ' ')}</span>;
}

// Format timestamp to Time only
function formatTime(ts: string | undefined): string {
  if (!ts) return '--:--:--';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return ts.slice(11, 19) || '--:--:--';
  }
}

// Generate summary from event
function getSummary(evt: TraceEvent): string {
  if (evt.payload?.summary) return evt.payload.summary;
  if (evt.payload?.action) return evt.payload.action;
  if (evt.payload?.model) return `Model: ${evt.payload.model}`;
  if (evt.payload?.rule_id) return `Rule: ${evt.payload.rule_id}`;
  if (evt.payload?.tool) return `Tool: ${evt.payload.tool}`;
  if (evt.payload?.query) return `Query: ${evt.payload.query.slice(0, 50)}...`;
  if (evt.source_id) return evt.source_id;
  return evt.event_type.replace(/_/g, ' ');
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function renderValue(value: any) {
  if (value === null || value === undefined) return <span className={styles.muted}>--</span>;
  if (typeof value === 'boolean') {
    return <span className={value ? styles.booleanYes : styles.booleanNo}>{value ? 'Yes' : 'No'}</span>;
  }
  if (typeof value === 'number') return <span className={styles.mono}>{value}</span>;
  if (typeof value === 'string') {
    const trimmed = value.length > 220 ? `${value.slice(0, 220)}...` : value;
    return <span className={styles.valueText} title={value}>{trimmed}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className={styles.muted}>Empty</span>;
    const isPrimitive = value.every((v) => (v === null) || (typeof v !== 'object'));
    if (isPrimitive) return <span className={styles.valueText}>{value.join(', ')}</span>;
    return <pre className={styles.detailJson}>{JSON.stringify(value, null, 2)}</pre>;
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value || {});
    if (keys.length === 0) return <span className={styles.muted}>Empty</span>;
    return <pre className={styles.detailJson}>{JSON.stringify(value, null, 2)}</pre>;
  }
  return <span className={styles.valueText}>{String(value)}</span>;
}

export default function DecisionTrace({ traceId, onClose }: { traceId: string | null; onClose: () => void }) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [explain, setExplain] = useState<any | null>(null);
  const [replay, setReplay] = useState<any | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<'events' | 'summary' | 'security' | 'raw'>('events');
  const [updating, setUpdating] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [streamMode, setStreamMode] = useState<'ws' | 'sse' | 'poll'>('poll');
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [posthocType, setPosthocType] = useState<string>('fraud_confirmed');
  const [posthocValue, setPosthocValue] = useState<string>('true');
  const [posthocNote, setPosthocNote] = useState<string>('');
  const [posthocStatus, setPosthocStatus] = useState<string | null>(null);
  const apiBase = getApiBase();

  // Draggable state
  const [position, setPosition] = useState({ x: window.innerWidth / 2 - 350, y: 80 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartPos = useRef({ x: 0, y: 0 });
  const modalRef = useRef<HTMLDivElement>(null);

  // Handle drag start
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return; // Don't drag when clicking buttons
    setIsDragging(true);
    dragStartPos.current = { x: e.clientX - position.x, y: e.clientY - position.y };
    e.preventDefault();
  }, [position]);

  // Handle drag move
  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = modalRef.current?.getBoundingClientRect();
      const w = rect?.width ?? 400;
      const h = rect?.height ?? 100;
      const newX = Math.max(0, Math.min(window.innerWidth - w, e.clientX - dragStartPos.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - h, e.clientY - dragStartPos.current.y));
      setPosition({ x: newX, y: newY });
    };

    const handleMouseUp = () => setIsDragging(false);

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  // Detach to new window
  const handleDetach = () => {
    if (!traceId) return;
    const width = 750;
    const height = 600;
    const left = window.screenX + (window.innerWidth - width) / 2;
    const top = window.screenY + (window.innerHeight - height) / 2;

    const traceWindow = window.open('', `DecisionTrace_${traceId}`, `width=${width},height=${height},left=${left},top=${top}`);
    if (traceWindow) {
      traceWindow.document.write(`
<!DOCTYPE html>
<html>
<head>
  <title>Decision Trace - ${traceId}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f3f4f6; padding: 16px; }
    .header { background: #1e3a5f; color: white; padding: 12px 16px; border-radius: 8px 8px 0 0; font-weight: 600; }
    .content { background: white; padding: 16px; border-radius: 0 0 8px 8px; max-height: calc(100vh - 100px); overflow: auto; }
    pre { background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
    .loading { text-align: center; padding: 40px; color: #6b7280; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; padding: 8px; background: #f9fafb; border-bottom: 2px solid #e5e7eb; font-size: 11px; text-transform: uppercase; color: #6b7280; }
    td { padding: 8px; border-bottom: 1px solid #f3f4f6; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; color: white; text-transform: uppercase; }
    .time { font-family: monospace; color: #6b7280; }
  </style>
</head>
<body>
  <div class="header">Decision Trace: ${traceId}</div>
  <div class="content">
    <div class="loading" id="loading">Loading trace data...</div>
    <div id="trace-content" style="display:none"></div>
  </div>
  <script>
    const apiBase = ${JSON.stringify(apiBase)};
    async function loadTrace() {
      try {
        const url = (apiBase ? apiBase : '') + '/api/v1/decisions/${traceId}';
        const r = await fetch(url, {
          headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' }
        });
        const data = await r.json();
        document.getElementById('loading').style.display = 'none';
        const content = document.getElementById('trace-content');
        content.style.display = 'block';
        content.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
      } catch (e) {
        document.getElementById('loading').innerHTML = 'Failed to load trace: ' + e.message;
      }
    }
    loadTrace();
    setInterval(loadTrace, 5000);
  </script>
</body>
</html>
      `);
      traceWindow.document.close();
      onClose(); // Close the inline modal
    }
  };

  useEffect(() => {
    if (!traceId) {
      setTrace(null);
      setEvents([]);
      setExplain(null);
      setReplay(null);
      setUpdating(false);
      setStreamMode('poll');
      return;
    }
    let mounted = true;
    const ctl = new AbortController();
    let es: EventSource | null = null;
    let ws: WebSocket | null = null;

    const fetchTrace = async () => {
      setUpdating(true);
      try {
        const r = await fetch(apiUrl(`/api/v1/decisions/${traceId}`), {
          signal: ctl.signal,
          headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' }
        });
        const d = await safeJson(r);
        if (mounted) setTrace(d);
      } catch {
        if (mounted) setTrace(null);
      } finally {
        if (mounted) setUpdating(false);
      }
    };

    const fetchExplainReplay = async () => {
      try {
        const [reExplain, reReplay] = await Promise.all([
          fetch(apiUrl(`/api/v1/decisions/${traceId}/explain`), {
            headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' }
          }).then(safeJson),
          fetch(apiUrl(`/api/v1/decisions/${traceId}/replay`), {
            headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' }
          }).then(safeJson),
        ]);
        if (mounted) {
          setExplain(reExplain);
          setReplay(reReplay);
        }
      } catch {
        if (mounted) {
          setExplain(null);
          setReplay(null);
        }
      }
    };

    const fetchTimeline = async () => {
      try {
        const r = await fetch(apiUrl(`/api/v1/trace/${traceId}/timeline`), {
          headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' }
        });
        if (r.ok) {
          const j = await safeJson(r);
          if (mounted && Array.isArray(j.events)) setEvents(j.events);
        }
      } catch {
        // Fallback: generate events from trace
      }
    };

    // Prefer WebSocket streaming; if it fails, try SSE; else poll.
    try {
      const url = wsUrl(`/api/v1/decisions/${traceId}/events/ws`);
      ws = new WebSocket(url);
      ws.onmessage = (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data);
          const incoming = Array.isArray(data) ? data : (Array.isArray(data.events) ? data.events : [data]);
          if (mounted && Array.isArray(incoming)) {
            setEvents((prev) => {
              const byId = new Map<string, any>();
              (prev || []).forEach(e => { if (e.id) byId.set(e.id, e); });
              incoming.forEach((e: any) => { if (e.id) byId.set(e.id, e); });
              return Array.from(byId.values()).sort((a: any, b: any) => (a.seq || 0) - (b.seq || 0));
            });
          }
        } catch {}
      };
      ws.onopen = () => { if (mounted) setStreamMode('ws'); };
      ws.onerror = () => { try { ws && ws.close(); } catch {}; ws = null; };
    } catch {
      ws = null;
    }

    if (!ws) {
      try {
        if ((window as any).EventSource) {
          const wire = (source: EventSource | null) => {
            if (!source) return null;
            source.onmessage = (ev: MessageEvent) => {
              try {
                const data = JSON.parse(ev.data);
                const incoming = Array.isArray(data) ? data : (Array.isArray(data.events) ? data.events : [data]);
                if (mounted && Array.isArray(incoming)) {
                  setEvents((prev) => {
                    const byId = new Map<string, any>();
                    (prev || []).forEach(e => { if (e.id) byId.set(e.id, e); });
                    incoming.forEach((e: any) => { if (e.id) byId.set(e.id, e); });
                    return Array.from(byId.values()).sort((a: any, b: any) => (a.seq || 0) - (b.seq || 0));
                  });
                }
              } catch {}
            };
            source.onerror = () => {
              try { source.close(); } catch {}
              if (es === source) es = null;
            };
            return source;
          };
          try {
            es = wire(new EventSource(apiUrl(`/api/v1/decisions/${traceId}/events/stream`)));
          } catch {
            es = null;
          }
          if (!es) {
            try {
              es = wire(new EventSource(apiUrl(`/api/v1/trace/${traceId}/events/stream`)));
            } catch {
              es = null;
            }
          }
          if (es && mounted) setStreamMode('sse');
        }
      } catch {
        es = null;
      }
    }

    fetchTrace();
    fetchExplainReplay();
    // If SSE not connected, poll as fallback
    if (!es && !ws) {
      fetchTimeline();
      const iv = setInterval(() => { fetchTrace(); fetchExplainReplay(); }, 5000);
      const iv2 = setInterval(fetchTimeline, 4000);
      if (mounted) setStreamMode('poll');
      return () => {
        mounted = false;
        ctl.abort();
        clearInterval(iv);
        clearInterval(iv2);
        if (es) try { es.close(); } catch {}
        if (ws) try { ws.close(); } catch {}
      };
    }

    return () => {
      mounted = false;
      ctl.abort();
      if (es) try { es.close(); } catch {}
      if (ws) try { ws.close(); } catch {}
    };
  }, [traceId]);

  const toggleRow = (id: string) => {
    setExpandedRows(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Generate synthetic events from trace if timeline API not available
  const displayEvents: TraceEvent[] = events.length > 0 ? events : (trace ? [
    { event_type: 'query_received', source_id: 'input', payload: { query: trace.input_query }, timestamp: trace.timestamp },
    ...(trace.intent_analysis ? [{ event_type: 'intent_analysis', source_id: 'nlp', payload: trace.intent_analysis, timestamp: trace.timestamp }] : []),
    ...(trace.agent_chain || []).map((a: any, i: number) => ({ event_type: 'agent_step', source_id: a.agent || `agent-${i}`, payload: a, timestamp: trace.timestamp })),
    ...(trace.model_selection ? [{ event_type: 'model_invoke', source_id: trace.model_selection.selected || 'llm', payload: trace.model_selection, latency_ms: trace.model_selection.latency_ms ?? undefined, timestamp: trace.timestamp }] : []),
    ...(trace.policy_gates ? [{ event_type: 'policy_gate', source_id: 'policy', payload: trace.policy_gates, timestamp: trace.timestamp }] : []),
    ...(trace.recommendation ? [{ event_type: 'success', source_id: 'output', payload: trace.recommendation, timestamp: trace.timestamp }] : []),
  ] : []);

  const ms = trace?.model_selection || {};

  const extractSecurity = () => {
    if (trace && (trace as any).security) return (trace as any).security;
    const secEvent = events.find(e => e.event_type === 'security_scan');
    // Many producers emit { details: <analysis>, severity: <band> }. Merge them so the UI can
    // reliably render severity/risk fields without requiring all keys to live inside `details`.
    if (secEvent?.payload?.details && typeof secEvent.payload.details === 'object') {
      const det: any = secEvent.payload.details;
      const merged: any = { ...det };
      if (secEvent.payload.severity != null && merged.severity == null) merged.severity = secEvent.payload.severity;
      if (secEvent.payload.risk_adj != null && merged.risk_adj == null) merged.risk_adj = secEvent.payload.risk_adj;
      if (secEvent.payload.risk_raw != null && merged.risk_raw == null) merged.risk_raw = secEvent.payload.risk_raw;
      if (secEvent.payload.dread_avg != null && merged.dread_avg == null) merged.dread_avg = secEvent.payload.dread_avg;
      if (secEvent.payload.cvss_score != null && merged.cvss_score == null) merged.cvss_score = secEvent.payload.cvss_score;
      return merged;
    }
    if (secEvent?.payload?.security) return secEvent.payload.security;
    if (secEvent?.payload) return secEvent.payload;
    return null;
  };

  const security = extractSecurity();
  const playbookEvent = events.find((e) => e.event_type === 'cv_playbook');
  const playbookPayload = playbookEvent?.payload || null;
  const playbookPreview = playbookPayload?.playbook || null;
  const playbookData = playbookPreview?.playbook || playbookPreview || null;
  const playbookTags = playbookPayload?.evidence_tags || playbookPreview?.triggered_by || [];
  // Contract NLP events
  const contractEvt = events.find((e) => e.event_type === 'contract_nlp_analysis');
  const contractPayload = contractEvt?.payload || null;
  const qualityEvt = events.find((e) => e.event_type === 'nlp_quality_gate');
  const qualityPayload = qualityEvt?.payload || null;
  const tier2Event = events.find((e) => e.event_type === 'cv_pipeline' && e.payload?.tier === 2);
  const tier2Summary = tier2Event?.payload?.tier2_summary || null;
  const mitreDetails = (security?.mitre_details && security.mitre_details.length > 0)
    ? security.mitre_details
    : (security?.mitre || []).map((id: string) => ({
        id,
        name: null,
        weight: null,
        dread_avg: security?.dread?.avg ?? security?.dread_avg,
        evidence_tags: security?.evidence?.matched_patterns || [],
        signals: Object.keys(security?.signals || {}).filter((k) => security?.signals?.[k]),
      }));
  const pasta = security?.pasta || {};
  const stages = Array.isArray(pasta?.stages) ? pasta.stages : [];

  const buildSecurityReport = () => ({
    decision_id: trace?.decision_id,
    timestamp: trace?.timestamp,
    query: trace?.input_query,
    model_selection: trace?.model_selection,
    security,
  });

  const copySecurityReport = async () => {
    try {
      const payload = JSON.stringify(buildSecurityReport(), null, 2);
      await navigator.clipboard.writeText(payload);
      setCopyStatus('Copied');
      setTimeout(() => setCopyStatus(null), 1500);
    } catch {
      setCopyStatus('Copy failed');
      setTimeout(() => setCopyStatus(null), 2000);
    }
  };

  const submitPosthoc = async () => {
    if (!trace?.decision_id) {
      setPosthocStatus('No decision id available');
      return;
    }
    try {
      const resp = await fetch(apiUrl('/api/v1/posthoc/record'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision_id: trace.decision_id,
          outcome_type: posthocType,
          outcome_value: posthocValue,
          evidence: posthocNote ? { note: posthocNote } : {},
        }),
      });
      const data = await safeJson(resp);
      if (!resp.ok || !data) {
        throw new Error((data && data.detail) ? data.detail : 'posthoc_failed');
      }
      setPosthocStatus('Outcome recorded');
      setTimeout(() => setPosthocStatus(null), 2000);
    } catch {
      setPosthocStatus('Record failed');
      setTimeout(() => setPosthocStatus(null), 2000);
    }
  };

  return (
    <div className={styles.overlay}>
      <div
        ref={modalRef}
        className={`${styles.modal} ${minimized ? styles.minimized : ''}`}
        style={{ left: position.x, top: position.y }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header - Draggable */}
        <div
          className={styles.header}
          onMouseDown={handleDragStart}
          style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
        >
          <div className={styles.headerLeft}>
            <strong>Decision Trace</strong>
            {traceId ? (
              <span className={styles.traceId} title={traceId}>{traceId.slice(0, 12)}</span>
            ) : (
              <span className={styles.traceIdMuted} title="No trace id yet">no trace id</span>
            )}
            {ms.tier != null && <span className={styles.tier}>Tier {ms.tier}</span>}
            {/* Show NLP gate quick badge when available */}
            {qualityPayload && (
              <span className={`${styles.gateBadge} ${qualityPayload.decision === 'allow' ? styles.gateAllow : (qualityPayload.decision === 'review' ? styles.gateReview : styles.gateAbstain)}`} title={`NLP gate: ${qualityPayload.decision || '--'}`}>
                NLP: {qualityPayload.decision?.toUpperCase() || '--'}
              </span>
            )}
            {updating && <span className={styles.updating}>updating</span>}
            <span className={`${styles.streamBadge} ${streamMode === 'ws' ? styles.streamWS : (streamMode === 'sse' ? styles.streamSSE : styles.streamPoll)}`} title="Streaming mode">
              {streamMode}
            </span>
          </div>
          <div className={styles.headerRight}>
            <button className={styles.iconBtn} onClick={() => setMinimized(!minimized)} title={minimized ? 'Expand' : 'Minimize'}>
              <MinimizeIcon />
            </button>
            <button className={styles.iconBtn} onClick={handleDetach} disabled={!traceId} title={traceId ? 'Pop-out to new window' : 'Pop-out available after a trace id is created'}>
              <DetachIcon />
            </button>
            <button className={styles.iconBtn} onClick={onClose} title="Close">
              <CloseIcon />
            </button>
          </div>
        </div>

        {!minimized && (
          <>
            {/* Tabs */}
            <div className={styles.tabs}>
              <button className={activeTab === 'events' ? styles.activeTab : ''} onClick={() => setActiveTab('events')}>Events</button>
              <button className={activeTab === 'summary' ? styles.activeTab : ''} onClick={() => setActiveTab('summary')}>Summary</button>
              <button className={activeTab === 'security' ? styles.activeTab : ''} onClick={() => setActiveTab('security')}>Security Matrix</button>
              <button className={activeTab === 'raw' ? styles.activeTab : ''} onClick={() => setActiveTab('raw')}>Raw</button>
            </div>

            {/* Content */}
            <div className={styles.body}>
              {!traceId && (
                <div className={styles.empty} style={{ marginBottom: 10 }}>
                  No decision trace yet. Run a query (chat) or submit/analyze a CV case to generate a trace id.
                </div>
              )}
              {activeTab === 'events' && (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}></th>
                      <th style={{ width: 80 }}>Time</th>
                      <th>Summary</th>
                      <th style={{ width: 100 }}>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayEvents.map((evt, idx) => {
                      const rowId = evt.id || `evt-${idx}`;
                      const isExpanded = expandedRows.has(rowId);
                      return (
                        <>
                          <tr key={rowId} className={styles.row} onClick={() => toggleRow(rowId)}>
                            <td><ChevronIcon expanded={isExpanded} /></td>
                            <td className={styles.time}>{formatTime(evt.timestamp || evt.created_at)}</td>
                            <td className={styles.summary}>{getSummary(evt)}{evt.latency_ms != null && <span className={styles.latency}>{evt.latency_ms}ms</span>}</td>
                            <td><VerdictBadge type={evt.event_type} /></td>
                          </tr>
                          {isExpanded && (
                            <tr key={`${rowId}-detail`} className={styles.detailRow}>
                              <td colSpan={4}>
                                <div className={styles.detailBox}>
                                  <div className={styles.detailHeader}>Event Details</div>
                                  <div className={styles.detailGrid}>
                                    <div className={styles.detailLabel}>Type</div>
                                    <div className={styles.detailValue}>{humanizeKey(evt.event_type)}</div>
                                    <div className={styles.detailLabel}>Source</div>
                                    <div className={styles.detailValue}>{evt.source_id || '—'}</div>
                                    <div className={styles.detailLabel}>Timestamp</div>
                                    <div className={styles.detailValue}>{evt.timestamp || evt.created_at || '—'}</div>
                                    <div className={styles.detailLabel}>Latency</div>
                                    <div className={styles.detailValue}>{evt.latency_ms != null ? `${evt.latency_ms}ms` : '—'}</div>
                                  </div>
                                  <div className={styles.detailHeader}>Payload</div>
                                  {evt.payload && typeof evt.payload === 'object' ? (
                                    <table className={styles.detailTable}>
                                      <tbody>
                                        {Object.entries(evt.payload).map(([key, val]) => (
                                          <tr key={key}>
                                            <td className={styles.detailKey}>{humanizeKey(key)}</td>
                                            <td className={styles.detailVal}>{renderValue(val)}</td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  ) : (
                                    <div className={styles.detailEmpty}>
                                      {evt.payload ? renderValue(evt.payload) : 'No payload recorded.'}
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      );
                    })}
                    {displayEvents.length === 0 && (
                      <tr><td colSpan={4} className={styles.empty}>No events recorded yet. Check backend connectivity or trace ID.</td></tr>
                    )}
                  </tbody>
                </table>
              )}

              {activeTab === 'summary' && trace && (
                <div className={styles.summaryPane}>
                  <div className={styles.kvRow}><span>Decision ID</span><span>{trace.decision_id}</span></div>
                  <div className={styles.kvRow}><span>Timestamp</span><span>{trace.timestamp}</span></div>
                  <div className={styles.kvRow}><span>Query</span><span>{trace.input_query || '--'}</span></div>
                  <div className={styles.kvRow}><span>Model</span><span>{ms.selected || '--'}</span></div>
                  <div className={styles.kvRow}><span>Path</span><span>{Array.isArray(ms.path) ? ms.path.join(' -> ') : '--'}</span></div>
                  <div className={styles.kvRow}><span>Latency</span><span>{ms.latency_ms != null ? `${Math.round(ms.latency_ms)}ms` : '--'}</span></div>
                  <div className={styles.kvRow}><span>Intent</span><span>{ms.intent_summary || '--'}</span></div>
                  <div className={styles.kvRow}>
                    <span>Tier Decision</span>
                    <span>
                      {ms?.decision?.action ? (
                        <>
                          {ms.decision.action}
                          {(ms.decision.from || ms.decision.to) ? ` (${ms.decision.from || '-'} -> ${ms.decision.to || '-'})` : ''}
                        </>
                      ) : '-'}
                    </span>
                  </div>
                  {/* Explain summary from backend */}
                  <div className={styles.sectionTitle}>Explanation</div>
                  {!explain && <div className={styles.muted}>No explanation available.</div>}
                  {explain && typeof explain.summary === 'string' && (
                    <div className={styles.kvRow}><span>Summary</span><span>{explain.summary}</span></div>
                  )}
                  {explain && typeof explain.summary === 'object' && (
                    <div className={styles.explainBullets}>
                      <div className={styles.kvRow}><span>Reasoning</span><span>{explain.summary.reasoning || '—'}</span></div>
                      <div className={styles.kvRow}><span>Risks</span><span>{explain.summary.risks ? JSON.stringify(explain.summary.risks) : '—'}</span></div>
                      <div className={styles.kvRow}><span>Next Steps</span><span>{explain.summary.next_steps ? JSON.stringify(explain.summary.next_steps) : '—'}</span></div>
                    </div>
                  )}

                  {/* Contract NLP Analysis */}
                  <div className={styles.sectionTitle}>Contract NLP</div>
                  {!contractPayload ? (
                    <div className={styles.muted}>No contract NLP analysis recorded.</div>
                  ) : (
                    <>
                      <div className={styles.kvRow}><span>Mode</span><span>{contractPayload.mode || '—'}</span></div>
                      <div className={styles.kvRow}><span>Score</span><span>{contractPayload.score ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>Risks</span><span>{Array.isArray(contractPayload.risks) && contractPayload.risks.length ? contractPayload.risks.join(', ') : '—'}</span></div>
                      {contractPayload.summary && (
                        <div className={styles.kvRow}><span>Summary</span><span>{contractPayload.summary}</span></div>
                      )}
                    </>
                  )}

                  {/* NLP Quality Gate */}
                  <div className={styles.sectionTitle}>NLP Quality Gate</div>
                  {!qualityPayload ? (
                    <div className={styles.muted}>No quality gate evaluation recorded.</div>
                  ) : (
                    <>
                      <div className={styles.kvRow}><span>Decision</span><span>{qualityPayload.decision || '—'}</span></div>
                      <div className={styles.kvRow}><span>Reasons</span><span>{Array.isArray(qualityPayload.reasons) && qualityPayload.reasons.length ? qualityPayload.reasons.join(', ') : '—'}</span></div>
                      <div className={styles.kvRow}><span>Risk‑Adjusted Score</span><span>{qualityPayload.metrics?.risk_adjusted_score ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>Precision Target</span><span>{qualityPayload.metrics?.precision_target ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>Recall Target</span><span>{qualityPayload.metrics?.recall_target ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>Thresholds</span><span>{qualityPayload.thresholds ? JSON.stringify(qualityPayload.thresholds) : '—'}</span></div>
                    </>
                  )}

                  {/* Replay tools invoked */}
                  <div className={styles.sectionTitle}>Tools Invoked</div>
                  {!replay || !Array.isArray(replay.tools_invoked) || replay.tools_invoked.length === 0 ? (
                    <div className={styles.muted}>No tools recorded.</div>
                  ) : (
                    <table className={styles.smallTable}>
                      <thead>
                        <tr>
                          <th>Tool</th>
                          <th>Source</th>
                          <th>Destination</th>
                          <th>Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {replay.tools_invoked.map((t: any, i: number) => (
                          <tr key={`${t.tool || 'tool'}-${i}`}>
                            <td>{t.tool || '—'}</td>
                            <td>{t.source || '—'}</td>
                            <td>{t.destination || '—'}</td>
                            <td>{t.time || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {tier2Summary && (
                    <div className={styles.kvRow}>
                      <span>Tier 2 Quality</span>
                      <span>
                        {tier2Summary.model_pack || '-'}
                        {tier2Summary.detected?.length ? ` | ${tier2Summary.detected.join(', ')}` : ''}
                      </span>
                    </div>
                  )}
                  {trace.recommendation && (
                    <>
                      <div className={styles.sectionTitle}>Recommendation</div>
                      <div className={styles.kvRow}><span>Product</span><span>{trace.recommendation.product_id || '—'}</span></div>
                      <div className={styles.kvRow}><span>Score</span><span>{trace.recommendation.score ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>Reasoning</span><span>{trace.recommendation.reasoning || '—'}</span></div>
                    </>
                  )}
                  <div className={styles.sectionTitle}>Post‑hoc Outcome</div>
                  <div className={styles.posthocRow}>
                    <select value={posthocType} onChange={(e) => setPosthocType(e.target.value)}>
                      <option value="fraud_confirmed">Fraud Confirmed</option>
                      <option value="fraud_cleared">Fraud Cleared</option>
                      <option value="refund_reversed">Refund Reversed</option>
                      <option value="return_accepted">Return Accepted</option>
                      <option value="customer_satisfied">Customer Satisfied</option>
                    </select>
                    <select value={posthocValue} onChange={(e) => setPosthocValue(e.target.value)}>
                      <option value="true">True</option>
                      <option value="false">False</option>
                      <option value="unknown">Unknown</option>
                    </select>
                  </div>
                  <textarea
                    className={styles.posthocNote}
                    placeholder="Evidence note (optional)"
                    value={posthocNote}
                    onChange={(e) => setPosthocNote(e.target.value)}
                  />
                  <div className={styles.posthocActions}>
                    <button className={styles.copyBtn} onClick={submitPosthoc}>Record Outcome</button>
                    {posthocStatus && <span className={styles.copyStatus}>{posthocStatus}</span>}
                  </div>
                </div>
              )}

              {activeTab === 'security' && (
                <div className={styles.summaryPane}>
                  {!security && (
                    <div className={styles.empty}>No security analysis available for this trace.</div>
                  )}
                  {security && (
                    <>
                      <div className={styles.sectionHeaderRow}>
                        <div className={styles.sectionTitle}>Security Overview</div>
                        <div className={styles.sectionActions}>
                          <button className={styles.copyBtn} onClick={copySecurityReport}>Copy Security Report</button>
                          {copyStatus && <span className={styles.copyStatus}>{copyStatus}</span>}
                        </div>
                      </div>
                      <div className={styles.kvRow}><span>Severity</span><span>{security.severity || '—'}</span></div>
                      <div className={styles.kvRow}><span>Risk (Adjusted)</span><span>{security.risk_adj ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>DREAD Avg</span><span>{security.dread?.avg ?? security.dread_avg ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>CVSS</span><span>{security.cvss?.score ?? security.cvss_score ?? '—'}</span></div>
                      <div className={styles.kvRow}><span>PASTA Stage</span><span>{security.pasta?.current_stage || security.pasta?.stage || security.pasta_stage || '—'}</span></div>

                      <div className={styles.sectionTitle}>CV Playbook</div>
                      {playbookPreview ? (
                        <div className={styles.playbookPanel}>
                          <div className={styles.kvRow}><span>Playbook</span><span>{playbookData?.title || playbookData?.id || '—'}</span></div>
                          <div className={styles.kvRow}><span>ID</span><span>{playbookData?.id || '—'}</span></div>
                          <div className={styles.kvRow}><span>Override</span><span>{playbookPreview.override ? 'Yes' : 'No'}</span></div>
                          <div className={styles.kvRow}><span>Risk Band</span><span>{playbookPreview.risk_band || playbookPayload?.risk_band || '—'}</span></div>
                          <div className={styles.sectionTitle}>Evidence Tags</div>
                          <div className={styles.tagRow}>
                            {playbookTags.map((t: string) => (
                              <span key={t} className={styles.tag}>{t}</span>
                            ))}
                            {playbookTags.length === 0 && <span className={styles.muted}>None</span>}
                          </div>
                          {playbookData?.checks?.length ? (
                            <>
                              <div className={styles.sectionTitle}>Checks</div>
                              <ul className={styles.playbookList}>
                                {playbookData.checks.map((c: string, i: number) => <li key={i}>{c}</li>)}
                              </ul>
                            </>
                          ) : null}
                          {playbookData?.actions?.length ? (
                            <>
                              <div className={styles.sectionTitle}>Actions</div>
                              <ul className={styles.playbookList}>
                                {playbookData.actions.map((a: string, i: number) => <li key={i}>{a}</li>)}
                              </ul>
                            </>
                          ) : null}
                        </div>
                      ) : (
                        <div className={styles.muted}>No CV playbook recorded for this trace.</div>
                      )}

                      <div className={styles.sectionTitle}>OWASP LLM Top 10</div>
                      <div className={styles.tagRow}>
                        {(security.owasp_llm || security.owasp || []).map((t: string) => (
                          <span key={t} className={styles.tag}>{t}</span>
                        ))}
                        {(security.owasp_llm || security.owasp || []).length === 0 && <span className={styles.muted}>None</span>}
                      </div>

                      <div className={styles.sectionTitle}>OWASP Agentic Top 10</div>
                      <div className={styles.tagRow}>
                        {(security.owasp_agentic || []).map((t: string) => (
                          <span key={t} className={styles.tag}>{t}</span>
                        ))}
                        {(security.owasp_agentic || []).length === 0 && <span className={styles.muted}>None</span>}
                      </div>

                      <div className={styles.sectionTitle}>STRIDE</div>
                      <div className={styles.tagRow}>
                        {(security.stride || []).map((t: string) => (
                          <span key={t} className={styles.tag}>{t}</span>
                        ))}
                        {(security.stride || []).length === 0 && <span className={styles.muted}>None</span>}
                      </div>

                      <div className={styles.sectionTitle}>MITRE ATLAS (Evidence‑based)</div>
                      <table className={styles.smallTable}>
                        <thead>
                          <tr>
                            <th>ID</th>
                            <th>Name</th>
                            <th>Weight</th>
                            <th>DREAD</th>
                            <th>Evidence Tags</th>
                          </tr>
                        </thead>
                        <tbody>
                          {mitreDetails.map((m: any) => (
                            <tr key={m.id}>
                              <td>{m.id}</td>
                              <td>{m.name || '—'}</td>
                              <td>{m.weight ?? '—'}</td>
                              <td>{m.dread_avg ?? '—'}</td>
                              <td>
                                <div className={styles.tagRow}>
                                  {(m.evidence_tags || []).map((t: string) => (
                                    <span key={t} className={styles.tag}>{t}</span>
                                  ))}
                                  {(m.evidence_tags || []).length === 0 && <span className={styles.muted}>None</span>}
                                </div>
                              </td>
                            </tr>
                          ))}
                          {mitreDetails.length === 0 && (
                            <tr><td colSpan={5} className={styles.muted}>No MITRE techniques detected.</td></tr>
                          )}
                        </tbody>
                      </table>

                      <div className={styles.sectionTitle}>PASTA Workflow</div>
                      <div className={styles.stageRow}>
                        {stages.map((s: any) => (
                          <span key={s.id} className={`${styles.stage} ${styles[s.status || 'pending'] || ''}`}>
                            {s.id}: {s.name}
                          </span>
                        ))}
                        {stages.length === 0 && <span className={styles.muted}>No workflow data.</span>}
                      </div>
                    </>
                  )}
                </div>
              )}

              {activeTab === 'raw' && trace && (
                <pre className={styles.rawJson}>{JSON.stringify(trace, null, 2)}</pre>
              )}

              {!trace && (
                <div className={styles.empty}>Loading trace data for {traceId}...</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
