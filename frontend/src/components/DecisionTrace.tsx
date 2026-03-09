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
    shopper_intent: '#7C3AED',
    cart_abandonment_detected: '#FF6B35',
    commerce_outcome: '#059669',
    copywriting: '#0EA5E9',
    copy_policy_gate: '#F97316',
  };
  const color = colorMap[type] || '#6b7280';
  return <span className={styles.verdict} style={{ background: color }}>{type.replace(/_/g, ' ')}</span>;
}

// Format timestamp to Time only
function formatTime(ts: string | undefined): string {
  if (!ts) return '--:--:--';
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return '--:--:--';
    return d.toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return ts.slice(11, 19) || '--:--:--';
  }
}

// Generate summary from event
function getSummary(evt: TraceEvent): string {
  if (evt.event_type === 'turn_envelope_diff') {
    const p = evt.payload || {};
    const changed = Array.isArray(p.changed_fields) ? p.changed_fields.length : 0;
    return `Envelope diff (${changed} changed)`;
  }
  if (evt.event_type === 'upsell_promotion_selected') {
    const promoted = Array.isArray(evt.payload?.promoted) ? evt.payload.promoted.length : 0;
    return `Upsell promotions selected (${promoted})`;
  }
  if (evt.event_type === 'copywriting') {
    const applied = evt.payload?.applied;
    const tone = evt.payload?.tone || 'balanced';
    const profile = evt.payload?.profile_id || '';
    if (applied === false) return `Copywriting skipped (${evt.payload?.reason || 'disabled'})`;
    return `Copywriting applied — tone: ${tone}${profile ? ` / ${profile}` : ''}`;
  }
  if (evt.payload?.summary) return evt.payload.summary;
  if (evt.payload?.action) return evt.payload.action;
  if (evt.payload?.model) return `Model: ${evt.payload.model}`;
  if (evt.payload?.rule_id) return `Rule: ${evt.payload.rule_id}`;
  if (evt.payload?.tool) return `Tool: ${evt.payload.tool}`;
  if (evt.payload?.query) return `Query: ${evt.payload.query.slice(0, 50)}...`;
  if (evt.source_id) return evt.source_id;
  const original = evt?.payload?._original_event_type || evt?.payload?.original_event_type || evt.event_type;
  return String(original || 'event').replace(/_/g, ' ');
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

function eventAliases(evt: TraceEvent): string[] {
  const out = new Set<string>();
  const direct = String(evt?.event_type || '').toLowerCase().trim();
  if (direct) out.add(direct);
  const payload = evt?.payload || {};
  const original = String(payload?._original_event_type || payload?.original_event_type || '').toLowerCase().trim();
  if (original) out.add(original);
  const schema = String(payload?._event_type || '').toLowerCase().trim();
  if (schema) out.add(schema);
  return Array.from(out);
}

function eventMatches(evt: TraceEvent, expected: string | string[]): boolean {
  const wants = Array.isArray(expected) ? expected : [expected];
  const want = new Set(wants.map((x) => String(x || '').toLowerCase().trim()).filter(Boolean));
  if (want.size === 0) return false;
  const aliases = eventAliases(evt);
  return aliases.some((x) => want.has(x));
}

export default function DecisionTrace({ traceId, onClose }: { traceId: string | null; onClose: () => void }) {
  const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
  const LOCAL_KEY = (() => {
    try {
      const k =
        localStorage.getItem('x-api-key') ||
        localStorage.getItem('shopsquire_api_key') ||
        localStorage.getItem('api_key') ||
        '';
      return String(k || '').trim();
    } catch {
      return '';
    }
  })();
  const effectiveApiKey = API_KEY || LOCAL_KEY || 'local-merchant-key';
  const authHeaders = effectiveApiKey ? { 'x-api-key': effectiveApiKey } : undefined;
  const [trace, setTrace] = useState<Trace | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [explain, setExplain] = useState<any | null>(null);
  const [replay, setReplay] = useState<any | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<'events' | 'summary' | 'intent' | 'multimodal' | 'complexity' | 'memory' | 'security' | 'audit' | 'raw'>('events');
  const [auditTrail, setAuditTrail] = useState<any | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [streamMode, setStreamMode] = useState<'ws' | 'sse' | 'poll'>('poll');
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [posthocType, setPosthocType] = useState<string>('fraud_confirmed');
  const [posthocValue, setPosthocValue] = useState<string>('true');
  const [posthocNote, setPosthocNote] = useState<string>('');
  const [posthocStatus, setPosthocStatus] = useState<string | null>(null);
  const [eventFilter, setEventFilter] = useState<'all' | 'turn_envelope_diff'>('all');
  const apiBase = getApiBase();
  const displayEventType = (evt: TraceEvent): string =>
    String(evt?.payload?._original_event_type || evt?.payload?.original_event_type || evt.event_type || 'event');

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
    const apiKey = ${JSON.stringify(API_KEY)};
    async function loadTrace() {
      try {
        const url = (apiBase ? apiBase : '') + '/api/v1/decisions/${traceId}';
        const headers = apiKey ? { 'x-api-key': apiKey } : undefined;
        const r = await fetch(url, {
          credentials: 'include',
          headers,
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
          credentials: 'include',
          headers: authHeaders,
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
            credentials: 'include',
            headers: authHeaders,
          }).then(safeJson),
          fetch(apiUrl(`/api/v1/decisions/${traceId}/replay`), {
            credentials: 'include',
            headers: authHeaders,
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
          credentials: 'include',
          headers: authHeaders,
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

  // Generate synthetic events from trace if timeline API not available.
  // If we only have a trace id (fetch still pending), render a lookup event so
  // the table is never empty immediately after chat submit.
  const pendingLookupEvents: TraceEvent[] = (!trace && traceId) ? [{
    event_type: 'trace_lookup',
    source_id: 'ui',
    payload: {
      trace_id: traceId,
      status: updating ? 'loading' : 'pending',
      summary: updating ? 'Loading trace data...' : 'Trace id captured; waiting for timeline events.',
    },
    timestamp: new Date().toISOString(),
  }] : [];

  const allDisplayEvents: TraceEvent[] = events.length > 0 ? events : (trace ? [
    { event_type: 'query_received', source_id: 'input', payload: { query: trace.input_query }, timestamp: trace.timestamp },
    ...(trace.intent_analysis ? [{ event_type: 'intent_analysis', source_id: 'nlp', payload: trace.intent_analysis, timestamp: trace.timestamp }] : []),
    ...(trace.agent_chain || []).map((a: any, i: number) => ({ event_type: 'agent_step', source_id: a.agent || `agent-${i}`, payload: a, timestamp: trace.timestamp })),
    ...(trace.model_selection ? [{ event_type: 'model_invoke', source_id: trace.model_selection.selected || 'llm', payload: trace.model_selection, latency_ms: trace.model_selection.latency_ms ?? undefined, timestamp: trace.timestamp }] : []),
    ...(trace.policy_gates ? [{ event_type: 'policy_gate', source_id: 'policy', payload: trace.policy_gates, timestamp: trace.timestamp }] : []),
    ...(trace.recommendation ? [{ event_type: 'success', source_id: 'output', payload: trace.recommendation, timestamp: trace.timestamp }] : []),
  ] : pendingLookupEvents);
  const displayEvents: TraceEvent[] =
    eventFilter === 'all'
      ? allDisplayEvents
      : allDisplayEvents.filter((e) => String(e.event_type || '').toLowerCase() === eventFilter);

  const ms = trace?.model_selection || {};

  const normalizeSecurityPayload = (value: any) => {
    if (!value || typeof value !== 'object') return null;
    const raw: any = value;
    const candidate = [
      raw.security,
      raw.security_analysis,
      raw.details?.security,
      raw.details?.security_analysis,
      raw.details,
      raw,
    ].find((v) => v && typeof v === 'object');
    if (!candidate || typeof candidate !== 'object') return null;
    const merged: any = { ...(candidate as any) };
    if (raw.severity != null && merged.severity == null) merged.severity = raw.severity;
    if (raw.risk_adj != null && merged.risk_adj == null) merged.risk_adj = raw.risk_adj;
    if (raw.risk_raw != null && merged.risk_raw == null) merged.risk_raw = raw.risk_raw;
    if (raw.dread_avg != null && merged.dread_avg == null) merged.dread_avg = raw.dread_avg;
    if (raw.cvss_score != null && merged.cvss_score == null) merged.cvss_score = raw.cvss_score;
    if (Array.isArray(raw.evidence_tags) && !Array.isArray(merged.evidence_tags)) merged.evidence_tags = raw.evidence_tags;
    return Object.keys(merged).length > 0 ? merged : null;
  };

  const extractSecurity = () => {
    const tr: any = trace || {};
    const traceCandidates = [
      tr.security,
      tr.security_analysis,
      tr.risk_quantification?.security,
      tr.evidence?.security,
      tr.evidence?.security_analysis,
      tr.evidence?.cv_analysis?.security,
      tr.evidence?.cv_analysis?.security_analysis,
      tr.evidence?.cv_analysis?.details?.security,
      tr.evidence?.cv_analysis?.details?.security_analysis,
      tr.evidence?.analysis?.security,
    ];
    for (const c of traceCandidates) {
      const normalized = normalizeSecurityPayload(c);
      if (normalized) return normalized;
    }

    const allEvents = events.length > 0 ? events : displayEvents;
    const secEvent = [...allEvents].reverse().find((e) => String(e.event_type || '').toLowerCase() === 'security_scan');
    const secNorm = normalizeSecurityPayload(secEvent?.payload);
    if (secNorm) return secNorm;

    const securityLikeEvent = [...allEvents].reverse().find((e) => {
      const et = String(e.event_type || '').toLowerCase();
      if (et.includes('security') || et.includes('risk')) return true;
      const p: any = e.payload || {};
      return Boolean(
        p.security
        || p.security_analysis
        || p.details?.security
        || p.details?.security_analysis
      );
    });
    return normalizeSecurityPayload(securityLikeEvent?.payload);
  };

  const security = extractSecurity();
  const playbookEvent = events.find((e) => eventMatches(e, ['cv_playbook', 'proposal_build']));
  const playbookPayload = playbookEvent?.payload || null;
  const playbookPreview = playbookPayload?.playbook || null;
  const playbookData = playbookPreview?.playbook || playbookPreview || null;
  const playbookTags = playbookPayload?.evidence_tags || playbookPreview?.triggered_by || [];
  // Contract NLP events
  const contractEvt = events.find((e) => eventMatches(e, ['contract_nlp_analysis', 'constraint_parse']));
  const contractPayload = contractEvt?.payload || null;
  const qualityEvt = events.find((e) => eventMatches(e, ['nlp_quality_gate', 'policy_verdict']));
  const qualityPayload = qualityEvt?.payload || null;
  const tier2Event = events.find((e) => eventMatches(e, ['cv_pipeline', 'execution_result']) && e.payload?.tier === 2);
  const tier2Summary = tier2Event?.payload?.tier2_summary || null;
  const envelopeDiffEvent =
    [...(events || [])].reverse().find((e) => String(e.event_type || '').toLowerCase() === 'turn_envelope_diff')
    || null;
  const envelopeDiff = envelopeDiffEvent?.payload || null;
  const upsellEvent =
    [...(events || [])].reverse().find((e) => String(e.event_type || '').toLowerCase() === 'upsell_promotion_selected')
    || null;
  const upsellPromoted = Array.isArray(upsellEvent?.payload?.promoted) ? upsellEvent?.payload?.promoted : [];
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
              <button className={activeTab === 'intent' ? styles.activeTab : ''} onClick={() => setActiveTab('intent')}>Intent</button>
              <button className={activeTab === 'multimodal' ? styles.activeTab : ''} onClick={() => setActiveTab('multimodal')}>Multimodal</button>
              <button className={activeTab === 'complexity' ? styles.activeTab : ''} onClick={() => setActiveTab('complexity')}>Complexity</button>
              <button className={activeTab === 'memory' ? styles.activeTab : ''} onClick={() => setActiveTab('memory')}>Memory</button>
              <button className={activeTab === 'security' ? styles.activeTab : ''} onClick={() => setActiveTab('security')}>Security Matrix</button>
              <button className={activeTab === 'audit' ? styles.activeTab : ''} onClick={() => {
                setActiveTab('audit');
                if (!auditTrail && traceId && !auditLoading) {
                  setAuditLoading(true);
                  fetch(apiUrl(`/api/v1/decisions/${traceId}/audit-trail`), { headers: authHeaders })
                    .then(r => r.json()).then(d => setAuditTrail(d)).catch(() => {}).finally(() => setAuditLoading(false));
                }
              }}>Audit Trail</button>
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
                <>
                  <div className={styles.eventFilterRow}>
                    <button
                      className={eventFilter === 'all' ? styles.eventFilterChipActive : styles.eventFilterChip}
                      onClick={() => setEventFilter('all')}
                    >
                      All Events
                    </button>
                    <button
                      className={eventFilter === 'turn_envelope_diff' ? styles.eventFilterChipActive : styles.eventFilterChip}
                      onClick={() => setEventFilter('turn_envelope_diff')}
                    >
                      Envelope Diff
                    </button>
                  </div>
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
                          <tr key={rowId} className={`${styles.row} ${String(evt.event_type || '').toLowerCase() === 'turn_envelope_diff' ? styles.rowEnvelopeDiff : ''}`} onClick={() => toggleRow(rowId)}>
                            <td><ChevronIcon expanded={isExpanded} /></td>
                            <td className={styles.time}>{formatTime(evt.timestamp || evt.created_at)}</td>
                            <td className={styles.summary}>
                              {getSummary(evt)}
                              {evt.latency_ms != null && <span className={styles.latency}>{evt.latency_ms}ms</span>}
                              {String(evt.event_type || '').toLowerCase() === 'turn_envelope_diff' && (
                                <span className={styles.envelopeBadge}>Envelope Diff</span>
                              )}
                            </td>
                            <td><VerdictBadge type={displayEventType(evt)} /></td>
                          </tr>
                          {isExpanded && (
                            <tr key={`${rowId}-detail`} className={styles.detailRow}>
                              <td colSpan={4}>
                                <div className={styles.detailBox}>
                                  <div className={styles.detailHeader}>Event Details</div>
                                  <div className={styles.detailGrid}>
                                    <div className={styles.detailLabel}>Type</div>
                                    <div className={styles.detailValue}>{humanizeKey(displayEventType(evt))}</div>
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
                                        {Object.entries(evt.payload)
                                          .filter(([key]) => !String(key || '').startsWith('_'))
                                          .map(([key, val]) => (
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
                      <tr><td colSpan={4} className={styles.empty}>Trace events are not available yet. Verify backend connectivity and trace identifier.</td></tr>
                    )}
                  </tbody>
                </table>
                </>
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
                  <div className={styles.sectionTitle}>Turn Envelope Diff</div>
                  {!envelopeDiff ? (
                    <div className={styles.muted}>No envelope diff recorded for this turn.</div>
                  ) : (
                    <>
                      <div className={styles.kvRow}><span>Reason</span><span>{envelopeDiff.reason || '—'}</span></div>
                      <div className={styles.kvRow}><span>Expanded</span><span>{String(Boolean(envelopeDiff.expanded))}</span></div>
                      <div className={styles.kvRow}><span>Narrowed</span><span>{String(Boolean(envelopeDiff.narrowed))}</span></div>
                      <div className={styles.kvRow}><span>Changed Fields</span><span>{Array.isArray(envelopeDiff.changed_fields) && envelopeDiff.changed_fields.length ? envelopeDiff.changed_fields.join(', ') : 'none'}</span></div>
                    </>
                  )}

                  <div className={styles.sectionTitle}>Upsell Promotion Reasons</div>
                  {upsellPromoted.length === 0 ? (
                    <div className={styles.muted}>No upsell promotions recorded in this trace.</div>
                  ) : (
                    <table className={styles.smallTable}>
                      <thead>
                        <tr>
                          <th>SKU</th>
                          <th>Confidence</th>
                          <th>Model</th>
                          <th>Reason Codes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {upsellPromoted.map((p: any, idx: number) => (
                          <tr key={`${p?.sku || 'sku'}-${idx}`}>
                            <td>{p?.sku || '—'}</td>
                            <td>
                              {typeof p?.reason_confidence === 'number'
                                ? `${Math.round((p.reason_confidence || 0) * 100)}%`
                                : '—'}
                            </td>
                            <td>{p?.model_source || 'rules'}</td>
                            <td>
                              {Array.isArray(p?.reason_codes) && p.reason_codes.length
                                ? p.reason_codes.slice(0, 3).map((r: any) => `${r.code}(${Math.round((r.confidence || 0) * 100)}%)`).join(', ')
                                : (Array.isArray(p?.reasons) ? p.reasons.join(', ') : '—')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
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

              {activeTab === 'intent' && (
                <div className={styles.summaryPane}>
                  {(() => {
                    const intentEvt = events.find(e => e.event_type === 'shopper_intent');
                    const abandonEvts = events.filter(e => e.event_type === 'cart_abandonment_detected');
                    const outcomeEvts = events.filter(e => e.event_type === 'commerce_outcome');
                    const si = intentEvt?.payload?.shopper_intent || intentEvt?.payload || null;
                    // Also look for shopper_intent inside constraints payloads
                    const constraintsSi = !si
                      ? (events.find(e => e.payload?.constraints?.shopper_intent)?.payload?.constraints?.shopper_intent || null)
                      : null;
                    const intent = si || constraintsSi;
                    const hasAny = intent || abandonEvts.length > 0 || outcomeEvts.length > 0;
                    if (!hasAny) return (
                      <div className={styles.empty}>
                        No shopper intent signals recorded for this trace. Intent data is captured after a user query contains urgency, persona, or budget cues.
                      </div>
                    );
                    const urgencyColor = (u: string) => {
                      const level = String(u || '').toLowerCase();
                      if (level === 'high' || level === 'urgent') return '#dc2626';
                      if (level === 'medium' || level === 'normal') return '#d97706';
                      return '#059669'; // low
                    };
                    const personaColor = '#7C3AED';
                    return (
                      <>
                        {intent && (
                          <>
                            <div className={styles.sectionTitle}>Shopper Intent Profile</div>
                            <div className={styles.intentBadgeRow}>
                              {intent.persona && (
                                <span className={styles.intentBadge} style={{ background: personaColor }}>
                                  Persona: {intent.persona}
                                </span>
                              )}
                              {intent.urgency && (
                                <span className={styles.intentBadge} style={{ background: urgencyColor(intent.urgency) }}>
                                  Urgency: {intent.urgency}
                                </span>
                              )}
                              {intent.bundle_receptivity !== undefined && (
                                <span className={styles.intentBadge} style={{ background: intent.bundle_receptivity ? '#0891b2' : '#6b7280' }}>
                                  Bundle: {intent.bundle_receptivity ? 'Receptive' : 'Not receptive'}
                                </span>
                              )}
                              {intent.budget_tier && (
                                <span className={styles.intentBadge} style={{ background: '#0369a1' }}>
                                  Budget: {intent.budget_tier}
                                </span>
                              )}
                              {intent.price_sensitivity && (
                                <span className={styles.intentBadge} style={{ background: '#92400e' }}>
                                  Price sensitivity: {intent.price_sensitivity}
                                </span>
                              )}
                            </div>
                            {Array.isArray(intent.priority_factors) && intent.priority_factors.length > 0 && (
                              <>
                                <div className={styles.sectionTitle}>Priority Factors</div>
                                <div className={styles.pillRow}>
                                  {intent.priority_factors.map((f: string, i: number) => (
                                    <span key={i} className={styles.pill}>{f}</span>
                                  ))}
                                </div>
                              </>
                            )}
                            {Array.isArray(intent.accessory_affinities) && intent.accessory_affinities.length > 0 && (
                              <>
                                <div className={styles.sectionTitle}>Accessory Affinities</div>
                                <div className={styles.pillRow}>
                                  {intent.accessory_affinities.map((a: string, i: number) => (
                                    <span key={i} className={styles.pill} style={{ background: '#e0f2fe', color: '#0369a1' }}>{a}</span>
                                  ))}
                                </div>
                              </>
                            )}
                            {intentEvt && (
                              <>
                                <div className={styles.sectionTitle}>Bitemporal Metadata</div>
                                <div className={styles.kvRow}><span>Valid From</span><span className={styles.mono}>{intentEvt.payload?.valid_from || intentEvt.timestamp || '—'}</span></div>
                                <div className={styles.kvRow}><span>System From</span><span className={styles.mono}>{intentEvt.payload?.system_from || intentEvt.created_at || '—'}</span></div>
                                <div className={styles.kvRow}><span>Recorded At</span><span className={styles.mono}>{formatTime(intentEvt.timestamp || intentEvt.created_at)}</span></div>
                              </>
                            )}
                          </>
                        )}

                        {abandonEvts.length > 0 && (
                          <>
                            <div className={styles.sectionTitle}>Cart Abandonment Signals</div>
                            <table className={styles.smallTable}>
                              <thead>
                                <tr><th>Session</th><th>Idle (s)</th><th>Cart Value</th><th>Persona</th><th>Action</th><th>Confidence</th></tr>
                              </thead>
                              <tbody>
                                {abandonEvts.map((e, i) => {
                                  const p = e.payload || {};
                                  return (
                                    <tr key={e.id || `ab-${i}`}>
                                      <td className={styles.mono}>{p.session_id || '—'}</td>
                                      <td>{p.idle_seconds ?? '—'}</td>
                                      <td>{p.cart_value_cents != null ? `$${(p.cart_value_cents / 100).toFixed(2)}` : '—'}</td>
                                      <td>
                                        {p.inferred_persona ? (
                                          <span className={styles.intentBadge} style={{ background: personaColor, fontSize: 11 }}>{p.inferred_persona}</span>
                                        ) : '—'}
                                      </td>
                                      <td>{p.suggested_action || '—'}</td>
                                      <td>{p.confidence != null ? `${Math.round(p.confidence * 100)}%` : '—'}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </>
                        )}

                        {outcomeEvts.length > 0 && (
                          <>
                            <div className={styles.sectionTitle}>Commerce Outcomes</div>
                            <table className={styles.smallTable}>
                              <thead>
                                <tr><th>Type</th><th>Upsell Clicked</th><th>Bundle Purchased</th><th>AOV Delta</th><th>Time</th></tr>
                              </thead>
                              <tbody>
                                {outcomeEvts.map((e, i) => {
                                  const p = e.payload || {};
                                  return (
                                    <tr key={e.id || `oc-${i}`}>
                                      <td><VerdictBadge type="commerce_outcome" /></td>
                                      <td>{p.upsell_clicked != null ? (p.upsell_clicked ? '✓' : '—') : '—'}</td>
                                      <td>{p.bundle_purchased != null ? (p.bundle_purchased ? '✓' : '—') : '—'}</td>
                                      <td>{p.aov_delta != null ? (p.aov_delta >= 0 ? `+$${p.aov_delta.toFixed(2)}` : `-$${Math.abs(p.aov_delta).toFixed(2)}`) : '—'}</td>
                                      <td className={styles.time}>{formatTime(e.timestamp || e.created_at)}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </>
                        )}
                      </>
                    );
                  })()}
                </div>
              )}

              {activeTab === 'multimodal' && (
                <div className={styles.summaryPane}>
                  {(() => {
                    const imgEvt = events.find(e => eventMatches(e, ['image_intent_routing', 'cv_analysis', 'intent_classify']));
                    const fusionEvt = events.find(e => eventMatches(e, ['multimodal_fusion', 'synthesis_reasoning', 'proposal_build']));
                    const secEvt = events.find(e => eventMatches(e, ['image_security_scan', 'security_scan']));
                    const hasData = imgEvt || fusionEvt || secEvt;
                    if (!hasData) return <div className={styles.empty}>No multimodal events recorded for this trace. Attach an image to your chat message to see image routing, fusion, and security scan details.</div>;
                    return (
                      <>
                        <div className={styles.sectionTitle}>Image Intent Routing</div>
                        {imgEvt ? (
                          <>
                            <div className={styles.kvRow}><span>Intent</span><span>{imgEvt.payload?.intent || '--'}</span></div>
                            <div className={styles.kvRow}><span>Confidence</span><span>{imgEvt.payload?.confidence != null ? `${Math.round(imgEvt.payload.confidence * 100)}%` : '--'}</span></div>
                            <div className={styles.kvRow}><span>Reason</span><span>{imgEvt.payload?.reason || '--'}</span></div>
                            <div className={styles.kvRow}><span>Signals</span><span>{JSON.stringify(imgEvt.payload?.signals || {})}</span></div>
                          </>
                        ) : <div className={styles.muted}>No image intent routing event.</div>}
                        <div className={styles.sectionTitle}>Multimodal Fusion</div>
                        {fusionEvt ? (
                          <>
                            <div className={styles.kvRow}><span>Images Count</span><span>{fusionEvt.payload?.image_count ?? '--'}</span></div>
                            <div className={styles.kvRow}><span>Voice Used</span><span>{fusionEvt.payload?.voice_used ? 'Yes' : 'No'}</span></div>
                            <div className={styles.kvRow}><span>Labels</span><span>{Array.isArray(fusionEvt.payload?.labels) ? fusionEvt.payload.labels.join(', ') : '--'}</span></div>
                            <div className={styles.kvRow}><span>OCR Text</span><span>{fusionEvt.payload?.ocr_text || '--'}</span></div>
                          </>
                        ) : <div className={styles.muted}>No multimodal fusion event.</div>}
                        <div className={styles.sectionTitle}>Image Security Scan</div>
                        {secEvt ? (
                          <>
                            <div className={styles.kvRow}><span>QR Detected</span><span>{secEvt.payload?.qr_detected ? 'Yes' : 'No'}</span></div>
                            <div className={styles.kvRow}><span>Adversarial Score</span><span>{secEvt.payload?.adversarial_score ?? '--'}</span></div>
                            <div className={styles.kvRow}><span>Reupload Needed</span><span>{secEvt.payload?.reupload_needed ? 'Yes' : 'No'}</span></div>
                          </>
                        ) : <div className={styles.muted}>No image security scan event.</div>}
                      </>
                    );
                  })()}
                </div>
              )}

              {activeTab === 'complexity' && (
                <div className={styles.summaryPane}>
                  {(() => {
                    const cxEvt = events.find(e => eventMatches(e, ['tier_complexity_score', 'tier_decision', 'model_selection']));
                    const escEvt = events.find(e => eventMatches(e, ['tier_escalation', 'tier_decision']));
                    const msTr = trace?.model_selection || {};
                    const score = cxEvt?.payload?.score ?? cxEvt?.payload?.complexity_score ?? (msTr as any).tier;
                    const hasModelFallback = Boolean(
                      (msTr as any)?.selected ||
                      (msTr as any)?.model ||
                      (msTr as any)?.intent_summary ||
                      (Array.isArray((msTr as any)?.path) && (msTr as any).path.length > 0) ||
                      (msTr as any)?.decision
                    );
                    if (score == null && !cxEvt && !escEvt && !hasModelFallback) return <div className={styles.empty}>No complexity scoring data in this trace.</div>;
                    const tierName = cxEvt?.payload?.tier || cxEvt?.payload?.model_tier || msTr?.selected || '--';
                    const signals = cxEvt?.payload?.signals || cxEvt?.payload?.complexity_signals || {};
                    const explanations = cxEvt?.payload?.explanations || [];
                    return (
                      <>
                        <div className={styles.sectionTitle}>Complexity Score</div>
                        <div className={styles.kvRow}><span>Score</span><span className={styles.mono}>{score ?? '--'} / 10</span></div>
                        <div className={styles.kvRow}><span>Tier</span><span>{tierName}</span></div>
                        <div className={styles.kvRow}><span>Model Selected</span><span>{cxEvt?.payload?.model || cxEvt?.payload?.llm_model || msTr?.selected || '--'}</span></div>
                        {/* Score bar */}
                        <div className={styles.scoreBar}>
                          <div className={styles.scoreBarFill} style={{ width: `${Math.min(100, (Number(score) || 0) * 10)}%` }} />
                        </div>
                        <div className={styles.sectionTitle}>Signals</div>
                        {Object.keys(signals).length > 0 ? (
                          <table className={styles.smallTable}>
                            <thead><tr><th>Signal</th><th>Value</th></tr></thead>
                            <tbody>
                              {Object.entries(signals).map(([k, v]) => (
                                <tr key={k}><td>{humanizeKey(k)}</td><td>{renderValue(v)}</td></tr>
                              ))}
                            </tbody>
                          </table>
                        ) : <div className={styles.muted}>No signal breakdown available.</div>}
                        {explanations.length > 0 && (
                          <>
                            <div className={styles.sectionTitle}>Explanations</div>
                            <ul className={styles.explainList}>{explanations.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
                          </>
                        )}
                        {escEvt && (
                          <>
                            <div className={styles.sectionTitle}>Tier Escalation</div>
                            <div className={styles.kvRow}><span>From</span><span>{escEvt.payload?.from_tier || '--'}</span></div>
                            <div className={styles.kvRow}><span>To</span><span>{escEvt.payload?.to_tier || '--'}</span></div>
                            <div className={styles.kvRow}><span>Reason</span><span>{escEvt.payload?.reason || '--'}</span></div>
                          </>
                        )}
                      </>
                    );
                  })()}
                </div>
              )}

              {activeTab === 'memory' && (
                <div className={styles.summaryPane}>
                  {(() => {
                    const cacheEvt = events.find(e => eventMatches(e, ['cache_hit', 'shortlist_memory_lock']));
                    const nqeEvt = events.find(e => eventMatches(e, ['nqe_refinement', 'nqe_plan_built', 'nqe_question_shown', 'nqe_assumption_applied']));
                    const memEvents = events.filter(e => {
                      const aliases = eventAliases(e).join(' ');
                      return /memory|context|cache|session|shortlist|nqe/.test(aliases);
                    });
                    if (!cacheEvt && !nqeEvt && memEvents.length === 0) return <div className={styles.empty}>No memory/cache events in this trace.</div>;
                    return (
                      <>
                        <div className={styles.sectionTitle}>CacheRAG</div>
                        {cacheEvt ? (
                          <>
                            <div className={styles.kvRow}><span>Cache Hit</span><span>{cacheEvt.payload?.hit ? 'Yes' : 'Miss'}</span></div>
                            <div className={styles.kvRow}><span>Key</span><span>{cacheEvt.payload?.key || '--'}</span></div>
                            <div className={styles.kvRow}><span>TTL</span><span>{cacheEvt.payload?.ttl ?? '--'}</span></div>
                          </>
                        ) : <div className={styles.muted}>No cache hit/miss event.</div>}
                        <div className={styles.sectionTitle}>NQE Refinement</div>
                        {nqeEvt ? (
                          <>
                            <div className={styles.kvRow}><span>Original Query</span><span>{nqeEvt.payload?.original || '--'}</span></div>
                            <div className={styles.kvRow}><span>Refined Query</span><span>{nqeEvt.payload?.refined || '--'}</span></div>
                            <div className={styles.kvRow}><span>Questions Generated</span><span>{nqeEvt.payload?.question_count ?? '--'}</span></div>
                          </>
                        ) : <div className={styles.muted}>No NQE refinement event.</div>}
                        {memEvents.length > 0 && (
                          <>
                            <div className={styles.sectionTitle}>Session Memory Events</div>
                            <table className={styles.smallTable}>
                              <thead><tr><th>Type</th><th>Summary</th><th>Time</th></tr></thead>
                              <tbody>
                                {memEvents.map((e, i) => (
                                  <tr key={e.id || `mem-${i}`}>
                                    <td>{humanizeKey(e.event_type)}</td>
                                    <td>{getSummary(e)}</td>
                                    <td className={styles.time}>{formatTime(e.timestamp || e.created_at)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </>
                        )}
                      </>
                    );
                  })()}
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

              {activeTab === 'audit' && (
                <div className={styles.summaryPane}>
                  {auditLoading && <div className={styles.empty}>Loading audit trail...</div>}
                  {!auditLoading && !auditTrail && <div className={styles.empty}>No audit trail data. Click the tab to fetch.</div>}
                  {auditTrail && (
                    <>
                      <div className={styles.sectionTitle}>Bitemporal Decision Audit</div>
                      <div className={styles.kvRow}><span>Decisions</span><span>{auditTrail.decision_count}</span></div>
                      <div className={styles.kvRow}><span>Events</span><span>{auditTrail.event_count}</span></div>
                      <div className={styles.kvRow}><span>Hash Chain Length</span><span>{auditTrail.immutability?.chain_length}</span></div>
                      <div className={styles.kvRow}><span>Tip Hash</span><span className={styles.mono}>{auditTrail.immutability?.tip_hash}</span></div>
                      <div className={styles.kvRow}><span>Chain Verified</span><span>{auditTrail.immutability?.verified ? '\u2705 Yes' : '\u274c No'}</span></div>

                      <div className={styles.sectionTitle}>Storage & Immutability</div>
                      <div className={styles.kvRow}><span>Backend</span><span>{auditTrail.storage?.backend}</span></div>
                      <div className={styles.kvRow}><span>Encryption at Rest</span><span>{auditTrail.storage?.encryption_at_rest ? 'Yes' : 'No'}</span></div>
                      <div className={styles.kvRow}><span>Backup</span><span>{auditTrail.storage?.backup_enabled ? 'Enabled' : 'Not configured'}</span></div>

                      {(auditTrail.decisions || []).length > 0 && (
                        <>
                          <div className={styles.sectionTitle}>Agent Decisions (Bitemporal)</div>
                          <table className={styles.smallTable}>
                            <thead><tr><th>Agent</th><th>Valid From</th><th>Valid To</th><th>System From</th><th>Status</th><th>Approval</th></tr></thead>
                            <tbody>
                              {(auditTrail.decisions || []).map((d: any, i: number) => (
                                <tr key={i}>
                                  <td>{d.agent_name}</td>
                                  <td className={styles.mono}>{d.valid_from?.slice(0, 19)}</td>
                                  <td className={styles.mono}>{d.valid_to === 'infinity' ? '\u221e' : d.valid_to?.slice(0, 19)}</td>
                                  <td className={styles.mono}>{d.system_from?.slice(0, 19)}</td>
                                  <td>{d.execution_status}</td>
                                  <td>{d.approval_required ? '\u26a0\ufe0f Required' : '\u2705 Auto'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </>
                      )}

                      <div className={styles.sectionTitle}>Hash Chain (Tamper Evidence)</div>
                      <div style={{maxHeight: '200px', overflow: 'auto'}}>
                        <table className={styles.smallTable}>
                          <thead><tr><th>#</th><th>Type</th><th>Timestamp</th><th>Hash</th><th>Prev</th></tr></thead>
                          <tbody>
                            {(auditTrail.hash_chain || []).slice(0, 50).map((h: any, i: number) => (
                              <tr key={i}>
                                <td>{i + 1}</td>
                                <td>{h.type}</td>
                                <td className={styles.mono}>{h.timestamp?.slice(0, 19) || '--'}</td>
                                <td className={styles.mono}>{h.hash}</td>
                                <td className={styles.mono}>{h.prev_hash === 'genesis' ? 'genesis' : h.prev_hash}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      <div className={styles.sectionTitle}>Compliance Retention Policy</div>
                      <div className={styles.sectionTitle} style={{fontSize: '11px', marginTop: '4px'}}>Must Retain</div>
                      {(auditTrail.retention_policy?.retain_mandatory || []).map((r: any, i: number) => (
                        <div key={i} className={styles.kvRow}>
                          <span style={{fontFamily: 'monospace', fontSize: '11px'}}>{r.field}</span>
                          <span title={r.reason}>{r.min_retention_days}d \u2014 {r.reason?.slice(0, 60)}</span>
                        </div>
                      ))}
                      <div className={styles.sectionTitle} style={{fontSize: '11px', marginTop: '8px'}}>Purge Eligible</div>
                      {(auditTrail.retention_policy?.purge_eligible || []).map((r: any, i: number) => (
                        <div key={i} className={styles.kvRow}>
                          <span style={{fontFamily: 'monospace', fontSize: '11px'}}>{r.field}</span>
                          <span>After {r.after_days}d \u2014 {r.reason?.slice(0, 60)}</span>
                        </div>
                      ))}
                      {(auditTrail.retention_policy?.pii_fields_detected || []).length > 0 && (
                        <>
                          <div className={styles.sectionTitle} style={{fontSize: '11px', marginTop: '8px', color: '#dc2626'}}>PII Fields Detected</div>
                          <div className={styles.tagRow}>
                            {auditTrail.retention_policy.pii_fields_detected.map((f: string) => (
                              <span key={f} className={styles.tag} style={{background: '#dc2626'}}>{f}</span>
                            ))}
                          </div>
                        </>
                      )}
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
