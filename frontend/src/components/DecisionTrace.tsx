import { Fragment, useEffect, useState, useRef, useCallback } from 'react';
import styles from './DecisionTrace.module.css';
import { apiUrl, wsUrl, getApiBase, safeJson, getSplitOffer, type SplitOfferResult } from '../lib/api';
import { getOwnerApiKey } from '../lib/browserSession';
import FulfilmentTraceLink from './FulfilmentTraceLink';

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
    decision?: { action?: string; from?: string; to?: string } | null;
  };
  products?: any[];
  right_panel?: { anchor_sections?: any[] } | null;
  timing_breakdown?: Record<string, any> | null;
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

// Turn an internal rank token ("+ram_gb_min:8", "+use_case_match:office_general", "-oos") into a plain-English
// "Why recommended" pill. The RAW token stays in the pill's title (hover) so an operator can still audit it —
// this reads-out the reason instead of leaking rank internals to a buyer.
const _UC_LABELS: Record<string, string> = {
  office_general: 'office / work', business_professional: 'business use', office_finance: 'finance work',
  office_executive: 'exec use', gaming: 'gaming', gaming_competitive: 'competitive gaming',
  gaming_casual: 'casual gaming', university_general: 'study', note_taking_student: 'note-taking',
  content_creator: 'creative work', content_creation: 'creative work', ai_ml_workstation: 'AI / ML',
  data_science_student: 'data science', engineering_student: 'engineering', computer_science_student: 'coding',
};
const _SPEC_LABELS: Record<string, string> = {
  ram_gb: 'RAM', storage_gb: 'storage', refresh_hz: 'refresh', display_inches: 'display',
  gpu_vram_gb: 'GPU VRAM', battery_wh: 'battery', weight_kg: 'weight', price: 'price',
};
const _SPEC_UNITS: Record<string, string> = { ram_gb: 'GB', storage_gb: 'GB', refresh_hz: 'Hz', gpu_vram_gb: 'GB', display_inches: '"' };
const _REASON_FLAGS: Record<string, string> = {
  in_stock: 'In stock', within_budget: 'Within budget', over_budget: 'Over budget', oos: 'Out of stock',
  out_of_stock: 'Out of stock', embedding_similarity: 'Close match to your query', semantic_match: 'Close match to your query',
  supplier_available: 'Supplier available', preferred_brand: 'Preferred brand', price_value: 'Strong value',
  discrete_gpu: 'Dedicated GPU', nvidia: 'NVIDIA GPU', portable: 'Portable',
};
function humanizeReason(token: string): string {
  const raw = String(token || '').trim();
  if (!raw) return '';
  const neg = raw.startsWith('-');
  const body = raw.replace(/^[+-]/, '');
  // already a readable phrase (has spaces, not a key:value) → keep it
  if (body.includes(' ') && !body.includes(':')) return body;
  const [key, val] = body.split(':');
  if (key === 'use_case_match') return `Fits ${_UC_LABELS[val] || String(val || '').replace(/_/g, ' ')}`;
  if (key === 'use_case_tag' || key === 'use_case_tags') return `For ${String(val || '').replace(/_/g, ' ')}`;
  const mMin = key.match(/^(.*)_min$/);
  if (mMin && val) { const b = mMin[1]; return `${val}${_SPEC_UNITS[b] || ''}+ ${_SPEC_LABELS[b] || b.replace(/_/g, ' ')}`; }
  const mMax = key.match(/^(.*)_max$/);
  if (mMax && val) { const b = mMax[1]; return `≤${val}${_SPEC_UNITS[b] || ''} ${_SPEC_LABELS[b] || b.replace(/_/g, ' ')}`; }
  const flagKey = key.replace(/_use_case_match$/, '');
  if (key.endsWith('_use_case_match')) return `Fits ${_UC_LABELS[flagKey] || flagKey.replace(/_/g, ' ')}`;
  if (_REASON_FLAGS[key]) return (neg && key === 'in_stock') ? 'Out of stock' : _REASON_FLAGS[key];
  const pretty = key.replace(/_/g, ' ').replace(/\bgb\b/gi, 'GB').replace(/\bhz\b/gi, 'Hz');
  return (neg ? 'Not ' : '') + pretty.charAt(0).toUpperCase() + pretty.slice(1) + (val ? ` ${val}` : '');
}

function inlineText(value: any): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]';
    const primitive = value.every((item) => item === null || typeof item !== 'object');
    if (primitive) return value.map((item) => String(item)).join(', ');
    try {
      return JSON.stringify(value);
    } catch {
      return '[array]';
    }
  }
  if (typeof value === 'object') {
    const eventType = String(value._original_event_type || value.original_event_type || value.event_type || '').trim();
    if (eventType) return humanizeKey(eventType);
    const keys = Object.keys(value);
    if (keys.length === 0) return '{}';
    try {
      return JSON.stringify(value);
    } catch {
      return `{${keys.join(', ')}}`;
    }
  }
  return String(value);
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
    return `Copywriting applied ? tone: ${tone}${profile ? ` / ${profile}` : ''}`;
  }
  const summary = inlineText(evt.payload?.summary);
  if (summary) return summary;
  const action = inlineText(evt.payload?.action);
  if (action) return action;
  const model = inlineText(evt.payload?.model);
  if (model) return `Model: ${model}`;
  const ruleId = inlineText(evt.payload?.rule_id);
  if (ruleId) return `Rule: ${ruleId}`;
  const tool = inlineText(evt.payload?.tool);
  if (tool) return `Tool: ${tool}`;
  const query = inlineText(evt.payload?.query);
  if (query) return `Query: ${query.slice(0, 50)}...`;
  if (evt.source_id) return String(evt.source_id);
  const original = evt?.payload?._original_event_type || evt?.payload?.original_event_type || evt.event_type;
  return String(original || 'event').replace(/_/g, ' ');
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function renderValue(value: any) {
  const unknownText = new Set(['', '?', '--', '-', 'unknown', 'n/a', 'null', 'undefined']);
  if (value === null || value === undefined) return <span className={styles.muted}>Not available</span>;
  if (typeof value === 'boolean') {
    return <span className={value ? styles.booleanYes : styles.booleanNo}>{value ? 'Yes' : 'No'}</span>;
  }
  if (typeof value === 'number') return <span className={styles.mono}>{value}</span>;
  if (typeof value === 'string') {
    const normalized = value.trim();
    if (unknownText.has(normalized.toLowerCase())) return <span className={styles.muted}>Not available</span>;
    const cleaned = normalized.replace(/\u2013|\u2014/g, '-');
    const trimmed = cleaned.length > 220 ? `${cleaned.slice(0, 220)}...` : cleaned;
    return <span className={styles.valueText} title={cleaned}>{trimmed}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className={styles.muted}>Not observed</span>;
    const isPrimitive = value.every((v) => (v === null) || (typeof v !== 'object'));
    if (isPrimitive) return <span className={styles.valueText}>{value.join(', ')}</span>;
    return <pre className={styles.detailJson}>{JSON.stringify(value, null, 2)}</pre>;
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value || {});
    if (keys.length === 0) return <span className={styles.muted}>Not observed</span>;
    return <pre className={styles.detailJson}>{JSON.stringify(value, null, 2)}</pre>;
  }
  return <span className={styles.valueText}>{String(value)}</span>;
}

function isMissingValue(value: any): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    return ['', '?', '--', '-', 'unknown', 'n/a', 'null', 'undefined'].includes(normalized);
  }
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') return Object.keys(value).length === 0;
  return false;
}

function formatDisplayText(value: any, fallback = 'Not available'): string {
  if (isMissingValue(value)) return fallback;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ');
  return String(value)
    .replaceAll('_', ' ')
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

function getLinkedArtifactUrl(sigs: Record<string, any>): string | null {
  const payloads: any[] = Array.isArray(sigs?.qr_payloads) ? sigs.qr_payloads : [];
  for (const p of payloads) {
    const data = String((p && (p.data || p.url || p.href)) || '').trim();
    if (/^https?:\/\//i.test(data)) return data;
  }
  const candidate = String(sigs?.qr_external_url || sigs?.qr_final_url || '').trim();
  return /^https?:\/\//i.test(candidate) ? candidate : null;
}

export default function DecisionTrace({ traceId, onClose, imageTriage, initialTab }: { traceId: string | null; onClose: () => void; imageTriage?: any[]; initialTab?: string }) {
  const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
  // No hardcoded key fallback — a bundled 'local-merchant-key' would ship a credential in the frontend.
  // The key comes ONLY from the build env (VITE_API_KEY / .env.local) or the saved owner key.
  const effectiveApiKey = API_KEY || getOwnerApiKey() || '';
  const authHeaders = effectiveApiKey ? { 'x-api-key': effectiveApiKey } : undefined;
  const [trace, setTrace] = useState<Trace | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [explain, setExplain] = useState<any | null>(null);
  const [replay, setReplay] = useState<any | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const _TABS = ['events', 'summary', 'why', 'intent', 'multimodal', 'complexity', 'memory', 'security', 'procurement', 'audit', 'raw'] as const;
  const [activeTab, setActiveTab] = useState<'events' | 'summary' | 'why' | 'intent' | 'multimodal' | 'complexity' | 'memory' | 'security' | 'procurement' | 'audit' | 'raw'>(
    (initialTab && (_TABS as readonly string[]).includes(initialTab)) ? (initialTab as typeof _TABS[number]) : 'events');
  // When this decision opened a procurement journey, badge the Procurement tab so the operator sees it
  // exists instead of having to click through blind. FulfilmentTraceLink resolves the case; it reports up.
  const [procurementCaseId, setProcurementCaseId] = useState<string | null>(null);
  const [auditTrail, setAuditTrail] = useState<any | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  // Procurement tab drill-downs — the DRAFTED supplier RFQ + the case's bitemporal journey (its own audit),
  // fetched by trace so the whole procurement story lives on ONE tab (no jumping to the ops console). The
  // drafted RFQ carries a supplier contact, so it's shown ONLY when an owner/operator key is configured
  // (a normal shopper never sees it — blind-ship stays intact).
  const [procCase, setProcCase] = useState<any | null>(null);
  const [procCases, setProcCases] = useState<any[]>([]);  // ALL cases for the trace (multi-supplier → N RFQs)
  const [procJourney, setProcJourney] = useState<any[] | null>(null);
  // PENDING sourcing plan (pre-GATE-1): when no case is bound to this trace yet but the buyer's cart
  // splits, show WHAT WOULD happen — the per-supplier backorder groups + each supplier's reorder channel —
  // instead of a bare empty tab. The RFQ drafts materialize at "Confirm delivery plan" (GATE 1).
  const [pendingSplit, setPendingSplit] = useState<SplitOfferResult | null>(null);
  useEffect(() => {
    if (activeTab !== 'procurement' || procCase) { return; }
    let alive = true;
    const uid = (() => { try { return sessionStorage.getItem('uid') || 'demo-user'; } catch { return 'demo-user'; } })();
    getSplitOffer(uid)
      .then((r) => { if (alive) setPendingSplit(r?.split && !r.split.fully_in_stock ? r : null); })
      .catch(() => { if (alive) setPendingSplit(null); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, procCase]);
  const [procLoading, setProcLoading] = useState(false);
  const canSeeOperatorDraft = !!getOwnerApiKey();
  const [updating, setUpdating] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [streamMode, setStreamMode] = useState<'ws' | 'sse' | 'poll'>('poll');
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [fallbackTraceId, setFallbackTraceId] = useState<string | null>(null);
  const noTraceTelemetrySentRef = useRef(false);
  const effectiveTraceId = (typeof traceId === 'string' && traceId.trim()) ? traceId.trim() : (fallbackTraceId || null);
  const traceIdText = effectiveTraceId || '';
  const [payloadActionStatus, setPayloadActionStatus] = useState<Record<string, string>>({});
  const [linkedArtifactResults, setLinkedArtifactResults] = useState<Record<string, any>>({});
  const [runtimeSecurityResults, setRuntimeSecurityResults] = useState<Record<string, any>>({});
  const [posthocType, setPosthocType] = useState<string>('fraud_confirmed');
  const [posthocValue, setPosthocValue] = useState<string>('true');
  const [posthocNote, setPosthocNote] = useState<string>('');
  const [posthocStatus, setPosthocStatus] = useState<string | null>(null);
  const [eventFilter, setEventFilter] = useState<'all' | 'turn_envelope_diff'>('all');
  const [explainReplayLoading, setExplainReplayLoading] = useState(false);
  const apiBase = getApiBase();
  const explainReplayAbortRef = useRef<AbortController | null>(null);
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Detach to new window
  const handleDetach = () => {
    if (!traceIdText) return;
    const width = 750;
    const height = 600;
    const left = window.screenX + (window.innerWidth - width) / 2;
    const top = window.screenY + (window.innerHeight - height) / 2;

    const traceWindow = window.open('', `DecisionTrace_${traceIdText}`, `width=${width},height=${height},left=${left},top=${top}`);
    if (traceWindow) {
      traceWindow.document.write(`
<!DOCTYPE html>
<html>
<head>
  <title>Decision Trace - ${traceIdText}</title>
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
  <div class="header">Decision Trace: ${traceIdText}</div>
  <div class="content">
    <div class="loading" id="loading">Loading trace data...</div>
    <div id="trace-content" style="display:none"></div>
  </div>
  <script>
    const apiBase = ${JSON.stringify(apiBase)};
    const apiKey = ${JSON.stringify(effectiveApiKey)};
    async function loadTrace() {
      try {
        const url = (apiBase ? apiBase : '') + '/api/v1/decisions/${traceIdText}';
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

  const bumpNoTraceTelemetry = useCallback(() => {
    try {
      const key = 'shopsquire.trace.no_trace_modal_opens';
      const raw = Number(window.localStorage.getItem(key) || '0');
      const next = Number.isFinite(raw) ? raw + 1 : 1;
      window.localStorage.setItem(key, String(next));
      const w = window as any;
      if (!w.__shopsquireTelemetry || typeof w.__shopsquireTelemetry !== 'object') {
        w.__shopsquireTelemetry = {};
      }
      w.__shopsquireTelemetry.no_trace_modal_opens = next;
    } catch {}
  }, []);

  const fetchExplainReplayLazy = useCallback(async () => {
    if (!effectiveTraceId) return;
    const tabsAllowFetch = activeTab === 'summary' || activeTab === 'audit' || activeTab === 'raw';
    if (!tabsAllowFetch) return;

    try {
      if (explainReplayAbortRef.current) explainReplayAbortRef.current.abort();
    } catch {}
    const ctl = new AbortController();
    explainReplayAbortRef.current = ctl;
    const timeoutId = window.setTimeout(() => ctl.abort(), 3000);
    setExplainReplayLoading(true);
    try {
      const headers = effectiveApiKey ? { 'x-api-key': effectiveApiKey } : undefined;
      const [reExplain, reReplay] = await Promise.all([
        fetch(apiUrl(`/api/v1/decisions/${effectiveTraceId}/explain`), {
          signal: ctl.signal,
          credentials: 'include',
          headers,
        }).then(safeJson),
        fetch(apiUrl(`/api/v1/decisions/${effectiveTraceId}/replay`), {
          signal: ctl.signal,
          credentials: 'include',
          headers,
        }).then(safeJson),
      ]);
      setExplain(reExplain);
      setReplay(reReplay);
    } catch {
      if (!ctl.signal.aborted) {
        setExplain(null);
        setReplay(null);
      }
    } finally {
      window.clearTimeout(timeoutId);
      if (explainReplayAbortRef.current === ctl) explainReplayAbortRef.current = null;
      setExplainReplayLoading(false);
    }
  }, [effectiveTraceId, activeTab, effectiveApiKey]);

  // Procurement drill-down: fetch the case (operator view → the drafted supplier RFQ) + its bitemporal
  // journey (the case's own audit trail) when the Procurement tab is open. Keeps the whole procurement
  // story — agent events, the human-gated draft, and the audit — on one tab. Re-runs when a case resolves.
  const loadProcurementDetail = useCallback(async () => {
    if (!effectiveTraceId) return;
    setProcLoading(true);
    try {
      const headers = effectiveApiKey ? { 'x-api-key': effectiveApiKey } : undefined;
      // Read-only: resolve EVERY case opened from this trace — a multi-supplier bulk order opens one case
      // per supplier group (each with its own drafted RFQ), so the Procurement tab shows all N, not just the
      // newest. Falls back gracefully to an empty list; the primary case (cases[0]) drives the audit journey.
      const allView: any = await fetch(
        apiUrl(`/api/v1/fulfillment/cases/by-trace/${encodeURIComponent(effectiveTraceId)}/all?view=operator`),
        { credentials: 'include', headers },
      ).then(safeJson).catch(() => null);
      const cases: any[] = Array.isArray(allView?.cases) ? allView.cases : [];
      setProcCases(cases);
      const primary = cases[0] || null;
      setProcCase(primary && (primary.case_id || primary.state) ? primary : null);
      const cid = (primary && primary.case_id) || procurementCaseId;
      if (cid) {
        const jr: any = await fetch(
          apiUrl(`/api/v1/fulfillment/cases/${encodeURIComponent(cid)}/journey`),
          { credentials: 'include', headers },
        ).then(safeJson).catch(() => null);
        setProcJourney(Array.isArray(jr?.journey) ? jr.journey : null);
      }
    } finally {
      setProcLoading(false);
    }
  }, [effectiveTraceId, effectiveApiKey, procurementCaseId]);

  useEffect(() => {
    if (activeTab !== 'procurement' || !effectiveTraceId) return;
    loadProcurementDetail();
  }, [activeTab, effectiveTraceId, procurementCaseId, loadProcurementDetail]);

  useEffect(() => {
    if (traceId && traceId.trim()) {
      setFallbackTraceId(null);
      noTraceTelemetrySentRef.current = false;
    }
  }, [traceId]);

  useEffect(() => {
    if (effectiveTraceId) return;
    if (!traceId && !noTraceTelemetrySentRef.current) {
      noTraceTelemetrySentRef.current = true;
      bumpNoTraceTelemetry();
    }
  }, [effectiveTraceId, traceId, bumpNoTraceTelemetry]);

  useEffect(() => {
    const currentTraceId = effectiveTraceId;
    if (!currentTraceId) {
      setTrace(null);
      setEvents([]);
      setExplain(null);
      setReplay(null);
      setAuditTrail(null);
      setUpdating(false);
      setStreamMode('poll');
      try {
        if (explainReplayAbortRef.current) explainReplayAbortRef.current.abort();
      } catch {}
      return;
    }
    let mounted = true;
    const ctl = new AbortController();
    let es: EventSource | null = null;
    let ws: WebSocket | null = null;
    let pollIv: ReturnType<typeof setInterval> | null = null;

    const mergeEvents = (incoming: any[]) => {
      if (!mounted || !Array.isArray(incoming)) return;
      setEvents(prev => {
        const byId = new Map<string, any>();
        (prev || []).forEach(e => { if (e.id) byId.set(e.id, e); });
        incoming.forEach(e => { if (e.id) byId.set(e.id, e); });
        return Array.from(byId.values()).sort((a, b) => (a.seq || 0) - (b.seq || 0));
      });
    };

    const fetchCanonicalTrace = async () => {
      setUpdating(true);
      try {
        const r = await fetch(apiUrl(`/api/v1/decisions/${currentTraceId}`), {
          signal: ctl.signal,
          credentials: 'include',
          headers: authHeaders,
        });
        if (r.ok) {
          const d = await safeJson(r);
          if (mounted) setTrace(d);
          return;
        }
        // fallback to query endpoint
        const qr = await fetch(apiUrl(`/api/v1/decisions/${currentTraceId}/query?include_events=true`), {
          signal: ctl.signal,
          credentials: 'include',
          headers: authHeaders,
        });
        if (!qr.ok) throw new Error(`trace_query_${qr.status}`);
        const qd = await safeJson(qr);
        if (!mounted || !qd) return;
        setTrace(qd as any);
        if (Array.isArray((qd as any).events)) setEvents((qd as any).events);
      } catch {
        if (mounted) setTrace(null);
      } finally {
        if (mounted) setUpdating(false);
      }
    };

    // Streaming ladder: WS → SSE → poll. The fallback MUST engage on ASYNC failure (5 s timeout /
    // onerror / a WS that 404s or closes after construction), not only when `new WebSocket()` throws
    // synchronously — the old code set up SSE/poll while `ws` was still truthy, so an async WS failure
    // left the trace with no live updates AND no fallback (the stale-trace / "WS noise" GPT-5.5 flagged).
    let fallbackStarted = false;
    const startPoll = () => {
      if (!mounted || pollIv !== null) return;
      setStreamMode('poll');
      pollIv = setInterval(fetchCanonicalTrace, 5000);
    };
    const startFallback = () => {
      if (!mounted || fallbackStarted || es) return;
      fallbackStarted = true;
      try {
        if ((window as any).EventSource) {
          const source = new EventSource(apiUrl(`/api/v1/decisions/${currentTraceId}/events/stream`));
          source.onmessage = (ev: MessageEvent) => {
            try {
              const data = JSON.parse(ev.data);
              const incoming = Array.isArray(data) ? data : (Array.isArray(data.events) ? data.events : [data]);
              mergeEvents(incoming);
            } catch {}
          };
          source.onerror = () => { try { source.close(); } catch {} if (es === source) es = null; startPoll(); };
          es = source;
          if (mounted) setStreamMode('sse');
          return;
        }
      } catch { es = null; }
      startPoll();
    };

    // Try WS first; give it 5 s to connect before degrading.
    let wsConnectTimer: ReturnType<typeof setTimeout> | null = null;
    try {
      const url = wsUrl(`/api/v1/decisions/${currentTraceId}/events/ws`);
      ws = new WebSocket(url);
      wsConnectTimer = setTimeout(() => {
        if (ws && ws.readyState !== WebSocket.OPEN) {
          try { ws.close(); } catch {}
          ws = null;
          startFallback();   // WS never opened → degrade
        }
      }, 5000);
      ws.onopen = () => {
        if (wsConnectTimer !== null) { clearTimeout(wsConnectTimer); wsConnectTimer = null; }
        if (mounted) setStreamMode('ws');
      };
      ws.onmessage = (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data);
          const incoming = Array.isArray(data) ? data : (Array.isArray(data.events) ? data.events : [data]);
          mergeEvents(incoming);
        } catch {}
      };
      ws.onerror = () => {
        if (wsConnectTimer !== null) { clearTimeout(wsConnectTimer); wsConnectTimer = null; }
        try { ws?.close(); } catch {} ws = null;
        startFallback();   // WS errored (incl. 404/close) → degrade cleanly
      };
      ws.onclose = () => {
        // A CLEAN server close (code 1000) fires onclose but NOT onerror, so without this the trace would
        // silently stop with no fallback. startFallback is idempotent + guarded on `mounted`, so this is a
        // no-op on intentional teardown (cleanup sets mounted=false first) and after an onerror already ran.
        if (wsConnectTimer !== null) { clearTimeout(wsConnectTimer); wsConnectTimer = null; }
        ws = null;
        startFallback();
      };
    } catch {
      ws = null;
      startFallback();     // WS construction threw → degrade
    }

    // Always load the initial snapshot immediately, independent of the streaming transport.
    fetchCanonicalTrace();

    return () => {
      mounted = false;
      ctl.abort();
      if (pollIv !== null) clearInterval(pollIv);
      if (wsConnectTimer !== null) clearTimeout(wsConnectTimer);
      try { ws?.close(); } catch {}
      try { es?.close(); } catch {}
      try {
        if (explainReplayAbortRef.current) explainReplayAbortRef.current.abort();
      } catch {}
    };
  }, [effectiveTraceId]);

  useEffect(() => {
    if (!effectiveTraceId) return;
    if (!(activeTab === 'summary' || activeTab === 'audit' || activeTab === 'raw')) return;
    if (explain || replay || explainReplayLoading) return;
    fetchExplainReplayLazy();
  }, [effectiveTraceId, activeTab, explain, replay, explainReplayLoading, fetchExplainReplayLazy]);

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
      status: updating ? 'checking' : 'pending',
      summary: updating ? 'Checking trace snapshot...' : 'Trace id captured; waiting for timeline events.',
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

  // Badge the Procurement tab when a case resolved OR the trace already carries procurement/split/supplier
  // activity — so the operator sees there's a story to open even before FulfilmentTraceLink resolves a case.
  const hasProcurementSignal = !!procurementCaseId || (events.length > 0 ? events : displayEvents).some((e) => {
    const s = String((e as any).source_id || '').toLowerCase();
    const t = String(e.event_type || '').toLowerCase();
    return s.includes('procurement') || s.includes('split') || s.includes('supplier') || s.includes('sourcing')
      || t.includes('procurement') || t.includes('split') || t.includes('sourc') || t.includes('availability') || t.includes('channel');
  });

  // Prefer recommendation records emitted through normalized envelopes
  // (e.g. feedback_loop with _original_event_type=recommendation_result).
  const recommendationEventPayload = (() => {
    const candidates = (allDisplayEvents || [])
      .map((evt) => {
        const payload = evt?.payload || {};
        const original = String(payload?._original_event_type || payload?.original_event_type || '').toLowerCase().trim();
        const isRec = original === 'recommendation_result' || eventMatches(evt, 'recommendation_result');
        if (!isRec) return null;
        const rightPanel = (payload?.right_panel_contract && typeof payload.right_panel_contract === 'object')
          ? payload.right_panel_contract
          : ((payload?.right_panel && typeof payload.right_panel === 'object') ? payload.right_panel : {});
        const anchors = Array.isArray((rightPanel as any)?.anchor_sections) ? (rightPanel as any).anchor_sections : [];
        const products = Array.isArray(payload?.products_summary) ? payload.products_summary : [];
        const score = (original === 'recommendation_result' ? 100 : 0) + (anchors.length > 0 ? 10 : 0) + (products.length > 0 ? 5 : 0);
        return { payload, score };
      })
      .filter(Boolean) as Array<{ payload: any; score: number }>;
    if (!candidates.length) return null;
    candidates.sort((a, b) => b.score - a.score);
    return candidates[0].payload || null;
  })();
  const whyAnchorSections: any[] = Array.isArray(trace?.right_panel?.anchor_sections) && trace!.right_panel!.anchor_sections!.length > 0
    ? (trace!.right_panel!.anchor_sections || [])
    : (Array.isArray((recommendationEventPayload as any)?.right_panel_contract?.anchor_sections)
      ? ((recommendationEventPayload as any)?.right_panel_contract?.anchor_sections || [])
      : []);
  const whyProducts: any[] = Array.isArray(trace?.products) && trace!.products!.length > 0
    ? (trace!.products || [])
    : (Array.isArray((recommendationEventPayload as any)?.products_summary)
      ? ((recommendationEventPayload as any)?.products_summary || [])
      : []);

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
    if (raw.policy_route != null && merged.policy_route == null) merged.policy_route = raw.policy_route;
    if (raw.route != null && merged.route == null) merged.route = raw.route;
    if (raw.signals && typeof raw.signals === 'object' && (!merged.signals || typeof merged.signals !== 'object')) merged.signals = raw.signals;
    if (raw.qr && typeof raw.qr === 'object' && (!merged.qr || typeof merged.qr !== 'object')) merged.qr = raw.qr;
    if (raw.image_trust_channels && typeof raw.image_trust_channels === 'object' && (!merged.image_trust_channels || typeof merged.image_trust_channels !== 'object')) merged.image_trust_channels = raw.image_trust_channels;
    if (raw.frameworks && typeof raw.frameworks === 'object' && (!merged.frameworks || typeof merged.frameworks !== 'object')) merged.frameworks = raw.frameworks;
    if (Array.isArray(raw.mitre_atlas) && !Array.isArray(merged.mitre_atlas)) merged.mitre_atlas = raw.mitre_atlas;
    if (Array.isArray(raw.mitre_attack) && !Array.isArray(merged.mitre_attack)) merged.mitre_attack = raw.mitre_attack;
    if (Array.isArray(raw.owasp_llm_top10) && !Array.isArray(merged.owasp_llm_top10)) merged.owasp_llm_top10 = raw.owasp_llm_top10;
    if (Array.isArray(raw.stride_categories) && !Array.isArray(merged.stride_categories)) merged.stride_categories = raw.stride_categories;
    if (Array.isArray(raw.maestro) && !Array.isArray(merged.maestro)) merged.maestro = raw.maestro;
    if (raw.pasta && typeof raw.pasta === 'object' && (!merged.pasta || typeof merged.pasta !== 'object')) merged.pasta = raw.pasta;
    if (raw.pasta_stage != null && merged.pasta_stage == null) merged.pasta_stage = raw.pasta_stage;
    if (raw.dread && typeof raw.dread === 'object' && (!merged.dread || typeof merged.dread !== 'object')) merged.dread = raw.dread;
    if (raw.cvss && typeof raw.cvss === 'object' && (!merged.cvss || typeof merged.cvss !== 'object')) merged.cvss = raw.cvss;
    if (raw.compliance && typeof raw.compliance === 'object' && (!merged.compliance || typeof merged.compliance !== 'object')) merged.compliance = raw.compliance;
    if (Array.isArray(raw.owasp_llm_top10) && !Array.isArray(merged.owasp_llm)) merged.owasp_llm = raw.owasp_llm_top10;
    if (Array.isArray(raw.stride_categories) && !Array.isArray(merged.stride)) merged.stride = raw.stride_categories;
    if (Array.isArray(raw.mitre_atlas) && !Array.isArray(merged.mitre)) merged.mitre = raw.mitre_atlas;
    if (Array.isArray(raw.owasp_agentic_top10) && !Array.isArray(merged.owasp_agentic)) merged.owasp_agentic = raw.owasp_agentic_top10;
    // MAESTRO agentic boundary normalization
    if (Array.isArray(raw.maestro_tags) && !Array.isArray(merged.maestro_tags)) merged.maestro_tags = raw.maestro_tags;
    if (raw.maestro_checked != null && merged.maestro_checked == null) merged.maestro_checked = raw.maestro_checked;
    if (raw.maestro_boundary != null && merged.maestro_boundary == null) merged.maestro_boundary = raw.maestro_boundary;
    if (Array.isArray(raw.maestro_violations) && !Array.isArray(merged.maestro_violations)) merged.maestro_violations = raw.maestro_violations;
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

  const fallbackSecurity = (() => {
    const tr: any = trace || {};
    const recPayload: any = recommendationEventPayload || {};
    const triage = (Array.isArray(imageTriage) && imageTriage.length > 0) ? (imageTriage[0] || {}) : {};
    const triageSec = (triage?.security && typeof triage.security === 'object') ? triage.security : triage;
    const triageSignals = (triageSec?.signals && typeof triageSec.signals === 'object') ? triageSec.signals : {};
    const imageSecurity =
      (tr?.image_security && typeof tr.image_security === 'object')
      ? tr.image_security
      : ((recPayload?.image_security && typeof recPayload.image_security === 'object') ? recPayload.image_security : {});
    const matrix =
      (tr?.right_panel?.security_matrix && typeof tr.right_panel.security_matrix === 'object')
      ? tr.right_panel.security_matrix
      : ((recPayload?.right_panel_contract?.security_matrix && typeof recPayload.right_panel_contract.security_matrix === 'object')
        ? recPayload.right_panel_contract.security_matrix
        : {});

    if (
      Object.keys(triageSignals || {}).length === 0
      && Object.keys(imageSecurity || {}).length === 0
      && Object.keys(matrix || {}).length === 0
    ) {
      return null;
    }

    const unsafeFlags = Array.isArray(imageSecurity?.unsafe_flags) ? imageSecurity.unsafe_flags : [];
    const mergedSignals: Record<string, any> = {
      ...triageSignals,
      raw_payload_quarantined: imageSecurity?.raw_payload_quarantined ?? true,
      recommendation_allowed: true,
      deep_security_pending: true,
    };
    for (const flag of unsafeFlags) {
      mergedSignals[String(flag)] = true;
    }
    return {
      severity: imageSecurity?.trust_state === 'under_review' ? 'review' : 'info',
      policy_route: matrix?.policy_action || 'allow_recommendation_quarantine_payload',
      route: matrix?.policy_action || 'allow_recommendation_quarantine_payload',
      owasp_llm_top10: Array.isArray(matrix?.owasp) ? matrix.owasp : [],
      mitre_atlas: Array.isArray(matrix?.mitre) ? matrix.mitre : [],
      maestro: Array.isArray(matrix?.maestro) ? matrix.maestro : [],
      signals: mergedSignals,
      raw_payload_quarantined: imageSecurity?.raw_payload_quarantined ?? true,
      recommendation_allowed: true,
      deep_security_pending: true,
      image_triage: Array.isArray(imageTriage) ? imageTriage : [],
      image_security: imageSecurity,
    };
  })();

  const security = extractSecurity() || fallbackSecurity;

  // Did this turn actually carry an IMAGE? The Security Matrix's QR / steganography / OCR / adversarial
  // checks only run on uploads — on a text-only turn `security` is still truthy (a security_matrix contract
  // + default quarantine flags), which reads as if an image were scanned. Detect the real thing so the tab
  // can label image-security as upload-only COVERAGE instead of implying this text query was scanned.
  const hadImage = (() => {
    if (Array.isArray(imageTriage) && imageTriage.length > 0) return true;
    const s: any = security || {};
    if (s.image_security && Object.keys(s.image_security).length > 0) return true;
    if (Array.isArray(s.image_triage) && s.image_triage.length > 0) return true;
    const sig: any = s.signals || {};
    return !!(sig.qr_code_detected || sig.steg_suspicious || sig.steg_detected || sig.ocr_text
      || sig.adversarial_detected || sig.image_relevance || sig.gan_detected);
  })();

  // Collect MAESTRO agent_guardrail events from the trace event stream.
  // These are emitted by the orchestrator and recommend ingress with
  // maestro_checked, maestro_boundary, and maestro_violations.
  const maestroGuardrailEvents: Array<{ agent: string; boundary: string; violations: any[]; tags: string[]; control?: string; verdict?: string; action?: string }> = (() => {
    const allEvts = events.length > 0 ? events : displayEvents;
    const guardrailRows = allEvts
      .filter((e) => String(e.event_type || '').toLowerCase() === 'agent_guardrail' && e.payload?.maestro_checked)
      .map((e) => ({
        agent: String(e.source_id || e.payload?.maestro_boundary || ''),
        boundary: String(e.payload?.maestro_boundary || ''),
        violations: Array.isArray(e.payload?.maestro_violations) ? e.payload.maestro_violations : [],
        tags: Array.isArray(e.payload?.tags) ? e.payload.tags : [],
      }));
    const matrixRows = Array.isArray((security as any)?.maestro)
      ? ((security as any).maestro || []).map((row: any) => ({
        agent: String(row?.agent || row?.boundary || row?.control || 'MAESTRO'),
        boundary: String(row?.boundary || ''),
        violations: [],
        tags: ['maestro', String(row?.control || '').trim()].filter(Boolean),
        control: String(row?.control || ''),
        verdict: String(row?.verdict || ''),
        action: String(row?.action || ''),
      }))
      : [];
    return [...guardrailRows, ...matrixRows];
  })();
  const maestroViolationCount = maestroGuardrailEvents.reduce((acc, ev) => acc + ev.violations.length, 0);

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
  const upsellBundle = (upsellEvent?.payload?.bundle_savings && typeof upsellEvent.payload.bundle_savings === 'object')
    ? upsellEvent.payload.bundle_savings
    : null;
  const owaspLlmTags = (security?.owasp_llm && Array.isArray(security.owasp_llm))
    ? security.owasp_llm
    : (Array.isArray(security?.owasp_llm_top10) ? security.owasp_llm_top10 : (security?.owasp || []));
  const owaspAgenticTags = (security?.owasp_agentic && Array.isArray(security.owasp_agentic))
    ? security.owasp_agentic
    : (Array.isArray((security as any)?.owasp_agentic_top10) ? (security as any).owasp_agentic_top10 : []);
  const strideTags = (security?.stride && Array.isArray(security.stride))
    ? security.stride
    : (Array.isArray(security?.stride_categories) ? security.stride_categories : []);
  const mitreIds = (security?.mitre && Array.isArray(security.mitre))
    ? security.mitre
    : (Array.isArray((security as any)?.mitre_atlas) ? (security as any).mitre_atlas : []);
  const mitreDetails = (security?.mitre_details && security.mitre_details.length > 0)
    ? security.mitre_details
    : (mitreIds || []).map((id: string) => ({
        id,
        name: null,
        weight: null,
        dread_avg: security?.dread?.avg ?? security?.dread_avg,
        evidence_tags: security?.evidence?.matched_patterns || [],
        signals: Object.keys(security?.signals || {}).filter((k) => security?.signals?.[k]),
      }));
  const pasta = security?.pasta || {};
  const stages = Array.isArray(pasta?.stages) ? pasta.stages : [];
  const qrInfo = (security?.qr && typeof security.qr === 'object')
    ? security.qr
    : ((security?.details?.qr && typeof security.details.qr === 'object') ? security.details.qr : {});
  const trustChannels = (security?.image_trust_channels && typeof security.image_trust_channels === 'object')
    ? security.image_trust_channels
    : ((security?.details?.image_trust_channels && typeof security.details.image_trust_channels === 'object')
      ? security.details.image_trust_channels
      : {});
  const dreadWeighted = Number(security?.dread?.weighted_avg ?? security?.dread_weighted_avg ?? NaN);
  const riskAdjusted = Number(security?.risk_adj ?? NaN);
  const compositeRisk = Number.isFinite(riskAdjusted)
    ? Math.max(0, Math.min(100, riskAdjusted <= 10 ? riskAdjusted * 10 : riskAdjusted))
    : (Number.isFinite(dreadWeighted) ? Math.max(0, Math.min(100, dreadWeighted * 10)) : null);
  const triageItems: any[] = (() => {
    if (Array.isArray(imageTriage) && imageTriage.length > 0) return imageTriage;
    const sec: any = security || {};
    if (Array.isArray(sec.image_triage) && sec.image_triage.length > 0) return sec.image_triage;
    if (Array.isArray(sec.images) && sec.images.length > 0) return sec.images;
    if ((sec.extracted_text || sec.ocr_text || (sec.signals && Object.keys(sec.signals || {}).length > 0)) && sec) return [sec];
    return [];
  })();

  /** One-line "why this fired" for the analyst ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â driven by hypothesis first, signals as fallback. */
  function buildWhyFiredLine(sigs: Record<string, any>, payloadAnalysis: any): string | null {
    const hyp = payloadAnalysis?.attack_hypothesis;
    const DETECTION_MAP: Record<string, string> = {
      c2_beacon:              'Detected because decoded payload referenced beacon/check-in terms.',
      lolbin_command_sequence:'Detected because hidden payload contains LOLBin execution patterns.',
      prompt_injection:       'Detected because payload contains AI system-prompt override instructions.',
      data_exfiltration:      'Detected because payload references exfiltration commands or data upload patterns.',
      ransomware:             'Detected because payload contains file-lock/ransomware indicators.',
      payment_fraud:          'Detected because QR payload is an external payment/social-engineering link.',
      macros:                 'Detected because payload references VBA macro or Office script execution patterns.',
      steg_unknown_payload:   'Detected because steganography anomaly flagged but payload is not decodable.',
    };
    if (hyp && hyp !== 'unknown' && DETECTION_MAP[hyp]) return DETECTION_MAP[hyp];
    if (hyp && hyp !== 'unknown') return `Detected because passive triage classified this as ${String(hyp).replace(/_/g, ' ')}.`;
    if (sigs.qr_prompt_injection) return 'Detected because QR payload is an injection attempt.';
    if (sigs.steg_suspicious) return 'Detected because steganographic anomaly found in pixel data.';
    if (sigs.adversarial_detected) return 'Detected because adversarial perturbations found in image.';
    if (sigs.manipulation_detected) return 'Detected because pixel-level image manipulation detected.';
    return null;
  }

  /** Build a plain-English heuristic narrative from a single triage result. */
  function buildTriageNarrative(t: any): string {
    const sigs = t?.security?.signals || t?.signals || {};
    const filename = t?._filename || 'image';
    const payloadAnalysis = t?.security?.payload_analysis || t?.payload_analysis || {};
    const parts: string[] = [];

    if (sigs.qr_code_detected) {
      const payloads: any[] = sigs.qr_payloads || [];
      if (payloads.length > 0) {
        parts.push(`QR code detected in ${filename}. Decoded payload: "${payloads.map((p: any) => p.data).join('" / "')}".`);
      } else {
        parts.push(`QR code detected in ${filename} but payload could not be fully decoded.`);
      }
    }
    if (sigs.qr_prompt_injection) parts.push('Prompt-injection pattern found in QR data ? request blocked.');
    if (sigs.qr_external_url) parts.push('QR code contains an external URL; flagged for review.');
    if (sigs.adversarial_detected) parts.push('Adversarial perturbation signature found; image may be crafted to mislead the classifier.');
    if (sigs.ai_generated_suspected) parts.push('High diffusion-model score ? image may be AI-generated.');
    if (payloadAnalysis.attack_hypothesis === 'ransomware' || sigs.ransomware_indicator) {
      parts.push('\u26a0\ufe0f RANSOMWARE INDICATOR ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â sandbox detonation required before any further processing. Do NOT execute on a live host.');
    } else if (payloadAnalysis.attack_hypothesis && payloadAnalysis.attack_hypothesis !== 'unknown') {
      parts.push(`Passive triage suggests ${String(payloadAnalysis.attack_hypothesis).replace(/_/g, ' ')} behavior.`);
    } else if (sigs.steg_suspicious) {
      parts.push(`Steganography anomaly detected (score: ${sigs.steg_score ?? '?'}); metadata may be hiding a payload.`);
    }
    if (payloadAnalysis.pasta_stage) {
      parts.push(`PASTA ${payloadAnalysis.pasta_stage}.`);
    }
    const _dp = payloadAnalysis.decode_path;
    if (_dp && _dp !== 'safe_passive_decode_only') {
      parts.push(`Decode advisory: ${_dp.replace(/_/g, ' ')}.`);
    }

    const ocrText = (t?.security?.extracted_text || t?.security?.ocr_text || t?.extracted_text || t?.ocr_text || '').trim();
    if (ocrText) parts.push(`OCR/extracted text: "${ocrText.slice(0, 200)}${ocrText.length > 200 ? '?' : ''}"`);

    if (parts.length === 0) parts.push(`No threats detected in ${filename}. Image appears benign.`);
    return parts.join(' ');
  }

  function summarizeSecurityFindingType(findingType: string): string {
    const mapping: Record<string, string> = {
      ssn_leakage_linked_qr: 'Linked QR path suggests SSN or PII exposure.',
      prompt_injection_hidden: 'Hidden prompt-injection content was detected.',
      c2_beacon_pattern: 'Hidden beacon or callback behavior was detected.',
      lolbin_command_sequence: 'Hidden LOLBin execution instructions were detected.',
      data_exfiltration_instruction: 'Hidden data-exfiltration instructions were detected.',
    };
    return mapping[findingType] || `${formatDisplayText(findingType, 'Security finding detected')}.`;
  }

  function getOwnerScopeMeta(scope: any): { label: string; className: string } | null {
    const normalized = String(scope || '').trim().toLowerCase();
    if (!normalized) return null;
    if (normalized === 'likely_internal_platform') return { label: 'Owner: internal', className: styles.tagGreen };
    if (normalized === 'external_or_third_party') return { label: 'Owner: external', className: styles.tagRed };
    if (normalized === 'external_redirect_service') return { label: 'Owner: redirect / unknown', className: styles.tagWarn };
    return { label: 'Owner: unknown', className: styles.tagWarn };
  }

  function buildSecurityAgentBriefs() {
    const payloadFindings: any[] = triageItems.flatMap((item: any) => item?.security?.payload_findings || item?.payload_findings || []);
    const threatHunterLeads: any[] = triageItems.flatMap((item: any) => item?.security?.threat_hunter_leads || item?.threat_hunter_leads || []);
    const payloadAnalysis = triageItems[0]?.security?.payload_analysis || triageItems[0]?.payload_analysis || {};
    const sigs = triageItems[0]?.security?.signals || triageItems[0]?.signals || security?.signals || {};
    const primaryFinding = payloadFindings[0] || {};
    const qrDestinationKnown = !isMissingValue(qrInfo?.destination_url) || !isMissingValue(qrInfo?.final_url);
    const correlationSeen = !isMissingValue(qrInfo?.intel_risk) || !isMissingValue(qrInfo?.reputation_verdict) || qrDestinationKnown;
    const agentRows = [
      {
        label: 'Payload Agent',
        direct: sigs.qr_code_detected ? 'Decoded QR content or hidden payload content was inspected.' : 'No direct QR or hidden payload content was observed.',
        inferred: payloadFindings.length ? summarizeSecurityFindingType(String(primaryFinding.finding_type || '')) : 'No stronger payload hypothesis was needed.',
        contextual: 'Did not widen the verdict using narrative or contextual text alone.',
        detail: payloadFindings.length > 1 ? payloadFindings.slice(1).map((finding: any) => summarizeSecurityFindingType(String(finding?.finding_type || ''))) : [],
      },
      {
        label: 'Correlation Agent',
        direct: correlationSeen ? 'Checked QR destination reputation and linked-artifact context against supporting telemetry.' : 'No stronger infrastructure overlap was observed.',
        inferred: correlationSeen ? 'Only widened the incident story when destination or reputation overlap was present.' : 'No extra correlation lead was justified.',
        contextual: 'Did not escalate based on missing or placeholder enrichment values.',
        detail: [],
      },
      {
        label: 'Threat Hunter Agent',
        direct: threatHunterLeads.length ? formatDisplayText(threatHunterLeads[0]?.what_we_observed?.[0], 'Evidence-backed hunt lead available.') : 'No direct artifact or infrastructure lead was strong enough to widen the hunt.',
        inferred: threatHunterLeads.length ? formatDisplayText(threatHunterLeads[0]?.why_it_matters, 'Used only evidence-backed overlap to suggest likely next checks.') : 'No hunt lead was emitted without direct evidence or real overlap.',
        contextual: 'Did not widen the hunt using contextual guides, specs, or generator files alone.',
        detail: [],
      },
      {
        label: 'Playbook Agent',
        direct: playbookPreview ? `Recommended ${formatDisplayText(playbookData?.title || playbookData?.id || 'response playbook')}.` : 'No response playbook was attached.',
        inferred: 'Mapped the evidence to next steps only after policy and severity were known.',
        contextual: 'Did not add response actions from low-authority context alone.',
        detail: [],
      },
    ];
    return agentRows;
  }

  function getSecurityIncidentBrief() {
    const payloadFindings: any[] = triageItems.flatMap((item: any) => item?.security?.payload_findings || item?.payload_findings || []);
    const threatHunterLeads: any[] = triageItems.flatMap((item: any) => item?.security?.threat_hunter_leads || item?.threat_hunter_leads || []);
    const primaryFinding = payloadFindings[0] || {};
    const payloadAnalysis = triageItems[0]?.security?.payload_analysis || triageItems[0]?.payload_analysis || {};
    const sigs = triageItems[0]?.security?.signals || triageItems[0]?.signals || security?.signals || {};
    const linkedArtifact = triageItems.map((item: any) => item?.security?.linked_artifact_analysis || item?.payload_analysis?.linked_artifact_analysis || null).find(Boolean)
      || triageItems.map((item: any) => {
        const findings = item?.security?.payload_findings || item?.payload_findings || [];
        return Array.isArray(findings) ? findings.map((f: any) => f?.linked_artifact).find(Boolean) : null;
      }).find(Boolean)
      || {};
    const ownerScopeMeta = getOwnerScopeMeta(linkedArtifact?.linked_owner_scope);
    const severity = formatDisplayText(security?.severity || 'review', 'review').toLowerCase();
    const route = formatDisplayText(security?.policy_route || security?.route || 'review', 'review');
    const decision =
      primaryFinding.headline ||
      (payloadAnalysis.attack_hypothesis && payloadAnalysis.attack_hypothesis !== 'unknown'
        ? `${formatDisplayText(payloadAnalysis.attack_hypothesis)} detected`
        : severity === 'high'
          ? 'Security review required'
          : 'Review recommended');
    const triggers = [
      buildWhyFiredLine(sigs, payloadAnalysis),
      sigs.qr_external_url ? 'A QR code points to an external destination.' : null,
      qrInfo?.reputation_verdict && qrInfo.reputation_verdict !== 'benign' ? `QR reputation is ${formatDisplayText(qrInfo.reputation_verdict)}.` : null,
      primaryFinding.business_risk ? summarizeSecurityFindingType(primaryFinding.finding_type || '') : null,
    ].filter(Boolean) as string[];
    const agentBriefs = buildSecurityAgentBriefs();
    const businessImpact = primaryFinding.business_risk
      || (payloadAnalysis.attack_hypothesis === 'pii_data_exfil_via_qr'
        ? 'Sensitive identity data could be exposed or redirected outside approved channels.'
        : 'The image may trigger unsafe follow-on actions unless it is reviewed.');
    const actions = [
      payloadAnalysis.attack_hypothesis === 'pii_data_exfil_via_qr' ? 'Do not share or act on the linked QR content.' : 'Do not trust the linked content yet.',
      'Escalate to security or privacy review.',
      payloadAnalysis.suggested_next_step === 'review' ? 'Review linked artifact or payload evidence before any business action.' : null,
      threatHunterLeads.length ? formatDisplayText(threatHunterLeads[0]?.what_to_hunt_next?.[0], 'Use the threat-hunter lead only on hosts or users tied to this artifact.') : null,
      qrInfo?.destination_url || qrInfo?.final_url ? 'Push this to SIEM/XDR if the incident needs broader correlation.' : null,
    ].filter(Boolean) as string[];
    const pushRecommendation = severity === 'high' || route.toLowerCase().includes('escal')
      ? 'Push to SIEM/XDR now'
      : 'Hold push until human review';
    return {
      decision: `${decision} - ${severity} confidence`,
      triggers: Array.from(new Set(triggers)).slice(0, 3),
      agentBriefs,
      businessImpact,
      actions,
      pushRecommendation,
      threatHunterLeads,
      ownerScopeMeta,
      ownerReason: formatDisplayText(linkedArtifact?.linked_owner_reason, ''),
      exposureScope: formatDisplayText(linkedArtifact?.linked_exposure_scope, ''),
      humanVerificationRequired: Boolean(linkedArtifact?.linked_human_verification_required),
    };
  }

  const triggerPayloadAction = useCallback(async (
    itemKey: string,
    t: any,
    action: 'analyze_payload_further' | 'queue_sandbox_detonation' | 'analyze_linked_artifact',
  ) => {
    if (!traceId) {
      setPayloadActionStatus((prev) => ({ ...prev, [itemKey]: 'No trace id available.' }));
      return;
    }
    const payloadAnalysis = t?.security?.payload_analysis || t?.payload_analysis || {};
    const filename = t?._filename || 'image';
    const sigs = t?.security?.signals || t?.signals || {};
    try {
      const linkedArtifactUrl = getLinkedArtifactUrl(sigs);
      const isLinked = action === 'analyze_linked_artifact';
      setPayloadActionStatus((prev) => ({ ...prev, [itemKey]:
        action === 'queue_sandbox_detonation'
          ? 'Queueing sandbox detonation...'
          : isLinked
            ? 'Fetching linked document in safe passive mode...'
            : 'Creating analyst follow-up...'
      }));
      const resp = await fetch(apiUrl(isLinked ? '/api/v1/incidents/analyze-linked-artifact' : '/api/v1/incidents/escalate'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...(authHeaders || {}) },
        body: JSON.stringify(isLinked ? {
          trace_id: traceId,
          reason: action,
          filename,
          artifact_url: linkedArtifactUrl,
          context: {
            filename,
            security_payload: payloadAnalysis,
            signals: sigs,
            extracted_text: t?.security?.extracted_text || t?.extracted_text || '',
          },
        } : {
          trace_id: traceId,
          reason: action,
          context: {
            filename,
            security_payload: payloadAnalysis,
            signals: sigs,
            extracted_text: t?.security?.extracted_text || t?.extracted_text || '',
          },
        }),
      });
      const data = await safeJson(resp);
      if (resp.ok && data?.ok && data?.incident_id) {
        if (isLinked) {
          const analysis = data?.analysis || data?.context?.linked_artifact_analysis || {};
          setLinkedArtifactResults((prev) => ({ ...prev, [itemKey]: analysis }));
          const artifactType = String(analysis?.linked_artifact_type || 'unknown').replace(/_/g, ' ');
          const hypothesis = String(analysis?.linked_attack_hypothesis || 'unknown').replace(/_/g, ' ');
          const nextStep = String(analysis?.linked_suggested_next_step || 'review').replace(/_/g, ' ');
          const reasonSummary = String(analysis?.linked_reason_summary || '').trim();
          const policyAction = String(analysis?.linked_policy_action || 'review').replace(/_/g, ' ');
          const pii = analysis?.pii_detected ? ` | PII: ${(analysis?.pii_type || []).join(', ') || 'detected'}` : '';
          const ssn = Array.isArray(analysis?.ssn_hits) && analysis.ssn_hits.length > 0 ? ` | SSNs: ${analysis.ssn_hits.length}` : '';
          setPayloadActionStatus((prev) => ({
            ...prev,
            [itemKey]: `Linked artifact analyzed (${data.incident_id}). Type: ${artifactType} | Hypothesis: ${hypothesis} | Policy: ${policyAction} | Next: ${nextStep}${reasonSummary ? ` | Why: ${reasonSummary}` : ''}${pii}${ssn}.`,
          }));
          return;
        }
        const _profiles: any[] = data?.context?.lolbin_behavioral_profiles || data?.lolbin_behavioral_profiles || [];
        const _ransomware = data?.ransomware_indicator || payloadAnalysis?.attack_hypothesis === 'ransomware';
        const _profileSummary = _profiles.length > 0
          ? ` ${_profiles.map((p: any) => `${p.full_name || p.binary} (${p.mitre_sub_technique || 'MITRE'})`).join(' | ')}.`
          : '';
        const _ransomwareWarning = _ransomware ? ' ÃƒÂ¢Ã…Â¡Ã‚Â \ufe0f Ransomware indicator ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â do NOT execute outside sandbox.' : '';
        const _hypothesis = String(payloadAnalysis?.attack_hypothesis || 'unknown').replace(/_/g, ' ');
        const _payloadType = String(payloadAnalysis?.payload_type || 'unknown').replace(/_/g, ' ');
        const _nextStep = String(payloadAnalysis?.suggested_next_step || 'allow').replace(/_/g, ' ');
        const _triage = `Hypothesis: ${_hypothesis} | Payload: ${_payloadType} | Next: ${_nextStep}.`;
        const _runtimeResult = data?.runtime_security_result || data?.context?.runtime_security_result || null;
        if (_runtimeResult && typeof _runtimeResult === 'object') {
          setRuntimeSecurityResults((prev) => ({ ...prev, [itemKey]: _runtimeResult }));
        }
        setPayloadActionStatus((prev) => ({
          ...prev,
          [itemKey]: action === 'queue_sandbox_detonation'
            ? `Sandbox detonation queued (${data.incident_id}). ${_triage}${_profileSummary}${_ransomwareWarning}${_runtimeResult?.summary ? ` ${String(_runtimeResult.summary)}` : ''}`
            : `Analyst follow-up queued (${data.incident_id}). ${_triage}${_profileSummary}${_ransomwareWarning}`,
        }));
        return;
      }
      const detail = (data && (data.detail || data.error)) ? String(data.detail || data.error) : `http_${resp.status}`;
      setPayloadActionStatus((prev) => ({ ...prev, [itemKey]: `Action failed: ${detail}.` }));
    } catch (e: any) {
      setPayloadActionStatus((prev) => ({ ...prev, [itemKey]: `Action failed: ${e?.message || 'network_error'}.` }));
    }
  }, [authHeaders, traceId]);

  const buildSecurityReport = () => ({
    decision_id: trace?.decision_id,
    timestamp: trace?.timestamp,
    query: trace?.input_query,
    model_selection: trace?.model_selection,
    security,
    image_triage: triageItems,
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
        role="dialog"
        aria-modal="true"
        aria-label="Decision Trace"
        data-testid="decision-trace-modal"
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
            <button className={styles.iconBtn} onClick={handleDetach} disabled={!traceIdText} title={traceIdText ? 'Pop-out to new window' : 'Pop-out available after a trace id is created'}>
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
              <button className={activeTab === 'why' ? styles.activeTab : ''} onClick={() => setActiveTab('why')}>Why Recommended</button>
              <button className={activeTab === 'intent' ? styles.activeTab : ''} onClick={() => setActiveTab('intent')}>Intent</button>
              <button className={activeTab === 'multimodal' ? styles.activeTab : ''} onClick={() => setActiveTab('multimodal')}>Multimodal</button>
              <button className={activeTab === 'complexity' ? styles.activeTab : ''} onClick={() => setActiveTab('complexity')}>Complexity</button>
              <button className={activeTab === 'memory' ? styles.activeTab : ''} onClick={() => setActiveTab('memory')}>Memory</button>
              <button className={activeTab === 'security' ? styles.activeTab : ''} onClick={() => setActiveTab('security')}>Security Matrix</button>
              <button className={activeTab === 'procurement' ? styles.activeTab : ''} onClick={() => setActiveTab('procurement')}>
                Procurement{hasProcurementSignal ? <span title="Procurement activity is present in this decision (open to see the drafted RFQ + audit)" style={{ marginLeft: 5, color: '#059669', fontWeight: 700 }}>●</span> : null}
              </button>
              <button className={activeTab === 'audit' ? styles.activeTab : ''} onClick={() => {
                setActiveTab('audit');
                if (!auditTrail && traceIdText && !auditLoading) {
                  setAuditLoading(true);
                  fetch(apiUrl(`/api/v1/decisions/${traceIdText}/audit-trail`), { headers: authHeaders })
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
              {/* Links this decision to the procurement journey it opened (renders only when one exists) */}
              <FulfilmentTraceLink traceId={effectiveTraceId || undefined} onResolved={setProcurementCaseId} />
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
                        <Fragment key={rowId}>
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
                                    <div className={styles.detailValue}>{evt.source_id || '?'}</div>
                                    <div className={styles.detailLabel}>Timestamp</div>
                                    <div className={styles.detailValue}>{evt.timestamp || evt.created_at || '?'}</div>
                                    <div className={styles.detailLabel}>Latency</div>
                                    <div className={styles.detailValue}>{evt.latency_ms != null ? `${evt.latency_ms}ms` : 'not recorded'}</div>
                                    <div className={styles.detailLabel}>Bitemporal</div>
                                    <div className={styles.detailValue}>
                                      {evt.payload?.bitemporal
                                        ? `valid_from=${evt.payload.bitemporal.valid_from || '?'} | system_from=${evt.payload.bitemporal.system_from || '?'}`
                                        : 'not recorded'}
                                    </div>
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
                        </Fragment>
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
                  {explainReplayLoading && <div className={styles.muted}>Loading explanation...</div>}
                  {!explain && <div className={styles.muted}>No explanation available.</div>}
                  {explain && typeof explain.summary === 'string' && (
                    <div className={styles.kvRow}><span>Summary</span><span>{explain.summary}</span></div>
                  )}
                  {explain && typeof explain.summary === 'object' && (
                    <div className={styles.explainBullets}>
                      <div className={styles.kvRow}><span>Reasoning</span><span>{explain.summary.reasoning || '?'}</span></div>
                      <div className={styles.kvRow}><span>Risks</span><span>{explain.summary.risks ? JSON.stringify(explain.summary.risks) : '?'}</span></div>
                      <div className={styles.kvRow}><span>Next Steps</span><span>{explain.summary.next_steps ? JSON.stringify(explain.summary.next_steps) : '?'}</span></div>
                    </div>
                  )}

                  {/* Contract NLP Analysis */}
                  <div className={styles.sectionTitle}>Contract NLP</div>
                  {!contractPayload ? (
                    <div className={styles.muted}>No contract NLP analysis recorded.</div>
                  ) : (
                    <>
                      <div className={styles.kvRow}><span>Mode</span><span>{contractPayload.mode || '?'}</span></div>
                      <div className={styles.kvRow}><span>Score</span><span>{contractPayload.score ?? '?'}</span></div>
                      <div className={styles.kvRow}><span>Risks</span><span>{Array.isArray(contractPayload.risks) && contractPayload.risks.length ? contractPayload.risks.join(', ') : '?'}</span></div>
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
                      <div className={styles.kvRow}><span>Decision</span><span>{qualityPayload.decision || '?'}</span></div>
                      <div className={styles.kvRow}><span>Reasons</span><span>{Array.isArray(qualityPayload.reasons) && qualityPayload.reasons.length ? qualityPayload.reasons.join(', ') : '?'}</span></div>
                      <div className={styles.kvRow}><span>Risk?Adjusted Score</span><span>{qualityPayload.metrics?.risk_adjusted_score ?? '?'}</span></div>
                      <div className={styles.kvRow}><span>Precision Target</span><span>{qualityPayload.metrics?.precision_target ?? '?'}</span></div>
                      <div className={styles.kvRow}><span>Recall Target</span><span>{qualityPayload.metrics?.recall_target ?? '?'}</span></div>
                      <div className={styles.kvRow}><span>Thresholds</span><span>{qualityPayload.thresholds ? JSON.stringify(qualityPayload.thresholds) : '?'}</span></div>
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
                            <td>{t.tool || '?'}</td>
                            <td>{t.source || '?'}</td>
                            <td>{t.destination || '?'}</td>
                            <td>{t.time || '?'}</td>
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
                      <div className={styles.kvRow}><span>Product</span><span>{trace.recommendation.product_id || '?'}</span></div>
                      <div className={styles.kvRow}><span>Score</span><span>{trace.recommendation.score ?? '?'}</span></div>
                      <div className={styles.kvRow}><span>Reasoning</span><span>{trace.recommendation.reasoning || '?'}</span></div>
                    </>
                  )}
                  <div className={styles.sectionTitle}>Turn Envelope Diff</div>
                  {!envelopeDiff ? (
                    <div className={styles.muted}>No envelope diff recorded for this turn.</div>
                  ) : (
                    <>
                      <div className={styles.kvRow}><span>Reason</span><span>{envelopeDiff.reason || '?'}</span></div>
                      <div className={styles.kvRow}><span>Expanded</span><span>{String(Boolean(envelopeDiff.expanded))}</span></div>
                      <div className={styles.kvRow}><span>Narrowed</span><span>{String(Boolean(envelopeDiff.narrowed))}</span></div>
                      <div className={styles.kvRow}><span>Changed Fields</span><span>{Array.isArray(envelopeDiff.changed_fields) && envelopeDiff.changed_fields.length ? envelopeDiff.changed_fields.join(', ') : 'none'}</span></div>
                    </>
                  )}

                  <div className={styles.sectionTitle}>Upsell Promotion Reasons</div>
                  {upsellPromoted.length === 0 ? (
                    <div className={styles.muted}>No upsell promotions recorded in this trace.</div>
                  ) : (
                    <>
                      {upsellBundle && (
                        <div className={styles.kvBlock}>
                          <div className={styles.kvRow}><span>Bundle status</span><span>{upsellBundle.status || '?'}</span></div>
                          <div className={styles.kvRow}><span>Message</span><span>{upsellBundle.message || '?'}</span></div>
                          <div className={styles.kvRow}><span>Discount requested</span><span>{Math.round(Number(upsellBundle.requested_discount_percent || 0) * 100)}%</span></div>
                          <div className={styles.kvRow}><span>Approval required</span><span>{String(Boolean(upsellBundle.approval_required))}</span></div>
                        </div>
                      )}
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
                              <td>{p?.sku || '?'}</td>
                              <td>
                                {typeof p?.reason_confidence === 'number'
                                  ? `${Math.round((p.reason_confidence || 0) * 100)}%`
                                  : '?'}
                              </td>
                              <td>{p?.model_source || 'rules'}</td>
                              <td>
                                {Array.isArray(p?.reason_codes) && p.reason_codes.length
                                  ? p.reason_codes.slice(0, 3).map((r: any) => `${r.code}(${Math.round((r.confidence || 0) * 100)}%)`).join(', ')
                                  : (Array.isArray(p?.reasons) ? p.reasons.join(', ') : '?')}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  )}
                  <div className={styles.sectionTitle}>Post?hoc Outcome</div>
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

              {activeTab === 'why' && (
                <div className={styles.summaryPane}>
                  {Array.isArray(whyAnchorSections) && whyAnchorSections.length > 0 ? (
                    (whyAnchorSections || []).map((sec: any, idx: number) => (
                      <div key={`anchor-${idx}`} className={styles.anchorBlock}>
                        <div className={styles.sectionTitle}>{sec?.title || `Image ${idx + 1}`}</div>
                        <div className={styles.kvRow}>
                          <span>Match basis</span>
                          <span>{Array.isArray(sec?.match_basis) ? sec.match_basis.join(' ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· ') : '?'}</span>
                        </div>
                        {sec?.summary && <div className={styles.whyNarrative}>{sec.summary}</div>}
                        {Array.isArray(sec?.top_products) && sec.top_products.slice(0, 3).map((p: any, pIdx: number) => (
                          <div key={`p-${idx}-${p?.sku || pIdx}`} className={styles.productReasonRow}>
                            <div className={styles.rowLeft}>
                              <strong>{p?.name || p?.sku || 'Product'}</strong>
                            </div>
                            <div className={styles.rowRight}>
                              <span className={styles.scoreChip}>score {p?.score_norm ?? '?'}</span>
                            </div>
                            {Array.isArray(p?.reasons) && p.reasons.length > 0 && (
                              <div className={styles.pillRow}>
                                {p.reasons.slice(0, 3).map((r: string, i: number) => (
                                  <span key={`${p?.sku || pIdx}-r-${i}`} className={styles.pill} title={r}>{humanizeReason(r)}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ))
                  ) : (
                    <div className={styles.muted}>No anchor-section reasoning recorded for this trace.</div>
                  )}

                  <div className={styles.sectionTitle}>All Ranked Products</div>
                  {Array.isArray(whyProducts) && whyProducts.length > 0 ? (
                    whyProducts.slice(0, 8).map((p: any, i: number) => (
                      <div key={`rp-${p?.sku || i}`} className={styles.productReasonRow}>
                        <div className={styles.rowLeft}>
                          <strong>{p?.name || p?.sku || 'Product'}</strong>
                          <span className={styles.sku}>{p?.sku || ''}</span>
                        </div>
                        <div className={styles.rowRight}>
                          <span className={styles.scoreChip}>{p?.score_norm ?? '?'}</span>
                        </div>
                        {Array.isArray(p?.reason_codes) && p.reason_codes.length > 0 ? (
                          <div className={styles.pillRow}>
                            {p.reason_codes.slice(0, 3).map((rc: any, rcIdx: number) => (
                              <span key={`${p?.sku || i}-rc-${rcIdx}`} className={styles.pill} title={String(rc?.code || '')}>
                                {humanizeReason(String(rc?.code || 'reason'))} ({Math.round((Number(rc?.confidence) || 0) * 100)}%)
                              </span>
                            ))}
                          </div>
                        ) : (
                          Array.isArray(p?.reasons) && p.reasons.length > 0 && (
                            <div className={styles.pillRow}>
                              {p.reasons.slice(0, 3).map((r: string, rIdx: number) => (
                                <span key={`${p?.sku || i}-r2-${rIdx}`} className={styles.pill} title={r}>{humanizeReason(r)}</span>
                              ))}
                            </div>
                          )
                        )}
                      </div>
                    ))
                  ) : (
                    <div className={styles.muted}>No ranked product reasons recorded for this trace.</div>
                  )}
                </div>
              )}

              {activeTab === 'intent' && (
                <div className={styles.summaryPane}>
                  {(() => {
                    const intentEvt = events.find(e =>
                      eventMatches(e, ['shopper_intent', 'intent_analysis', 'nlp_intent', 'image_intent_routing'])
                    );
                    const abandonEvts = events.filter(e => e.event_type === 'cart_abandonment_detected');
                    const outcomeEvts = events.filter(e => e.event_type === 'commerce_outcome');
                    const si = intentEvt?.payload?.shopper_intent
                      || intentEvt?.payload?.intent_profile
                      || intentEvt?.payload?.intent
                      || intentEvt?.payload
                      || null;
                    // Also look for shopper_intent inside constraints payloads
                    const constraintsSi = !si
                      ? (events.find(e => e.payload?.constraints?.shopper_intent)?.payload?.constraints?.shopper_intent || null)
                      : null;
                    const recPayload: any = recommendationEventPayload || {};
                    const recConstraints: any = recPayload?.constraints_used || recPayload?.constraints || {};
                    const recUseCase: any = recPayload?.use_case_analysis || {};
                    const recPersona =
                      recPayload?.buyer_persona
                      || recPayload?.buyer_persona_candidate
                      || recConstraints?.buyer_persona
                      || null;
                    const recUseCaseKey =
                      recUseCase?.use_case_key
                      || recConstraints?.use_case
                      || null;
                    const recBudgetMin = Number(
                      recConstraints?.budget_min
                      ?? recPayload?.budget_min
                      ?? NaN
                    );
                    const recBudgetMax = Number(
                      recConstraints?.budget_max
                      ?? recPayload?.budget_max
                      ?? NaN
                    );
                    const budgetTier = (() => {
                      if (Number.isFinite(recBudgetMax)) {
                        if (recBudgetMax <= 900) return 'tight';
                        if (recBudgetMax <= 1500) return 'mid';
                        return 'high';
                      }
                      return null;
                    })();
                    const synthesizedIntent = (!si && !constraintsSi && (recPersona || recUseCaseKey || Number.isFinite(recBudgetMax)))
                      ? {
                          persona: recPersona || null,
                          budget_tier: budgetTier,
                          priority_factors: Array.isArray(recUseCase?.priority_factors) ? recUseCase.priority_factors : [],
                          accessory_affinities: Array.isArray(recUseCase?.accessory_affinities) ? recUseCase.accessory_affinities : [],
                          use_case_key: recUseCaseKey || null,
                          budget_min: Number.isFinite(recBudgetMin) ? recBudgetMin : null,
                          budget_max: Number.isFinite(recBudgetMax) ? recBudgetMax : null,
                          source: 'recommendation_result_fallback',
                        }
                      : null;
                    const intent = si || constraintsSi || synthesizedIntent;
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
                              {intent.use_case_key && (
                                <span className={styles.intentBadge} style={{ background: '#0f766e' }}>
                                  Use-case: {String(intent.use_case_key).replace(/_/g, ' ')}
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
                              {(Number(intent.budget_min) > 0 || Number(intent.budget_max) > 0) && (
                                <span className={styles.intentBadge} style={{ background: '#1d4ed8' }}>
                                  Budget band: {Number(intent.budget_min) > 0 ? `$${Number(intent.budget_min).toLocaleString()}` : '—'}-{Number(intent.budget_max) > 0 ? `$${Number(intent.budget_max).toLocaleString()}` : '—'}
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
                                <div className={styles.kvRow}><span>Valid From</span><span className={styles.mono}>{intentEvt.payload?.valid_from || intentEvt.timestamp || '?'}</span></div>
                                <div className={styles.kvRow}><span>System From</span><span className={styles.mono}>{intentEvt.payload?.system_from || intentEvt.created_at || '?'}</span></div>
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
                                      <td className={styles.mono}>{p.session_id || '?'}</td>
                                      <td>{p.idle_seconds ?? '?'}</td>
                                      <td>{p.cart_value_cents != null ? `$${(p.cart_value_cents / 100).toFixed(2)}` : '?'}</td>
                                      <td>
                                        {p.inferred_persona ? (
                                          <span className={styles.intentBadge} style={{ background: personaColor, fontSize: 11 }}>{p.inferred_persona}</span>
                                        ) : '?'}
                                      </td>
                                      <td>{p.suggested_action || '?'}</td>
                                      <td>{p.confidence != null ? `${Math.round(p.confidence * 100)}%` : '?'}</td>
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
                                      <td>{p.upsell_clicked != null ? (p.upsell_clicked ? 'Yes' : 'No') : '?'}</td>
                                      <td>{p.bundle_purchased != null ? (p.bundle_purchased ? 'Yes' : 'No') : '?'}</td>
                                      <td>{p.aov_delta != null ? (p.aov_delta >= 0 ? `+$${p.aov_delta.toFixed(2)}` : `-$${Math.abs(p.aov_delta).toFixed(2)}`) : '?'}</td>
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
                    const imgEvt = events.find(e => eventMatches(e, ['image_intent_routing', 'cv_analysis', 'intent_classify', 'image_context_received']));
                    const fusionEvt = events.find(e => eventMatches(e, ['multimodal_fusion', 'synthesis_reasoning', 'proposal_build', 'right_panel_anchor_sections', 'recommendation_result']));
                    const secEvt = events.find(e => eventMatches(e, ['image_security_scan', 'security_scan', 'image_security_posture']));
                    const hasTracePanel = Boolean(trace?.right_panel && (Array.isArray((trace as any)?.right_panel?.anchor_sections) || (trace as any)?.right_panel?.mode));
                    const hasData = imgEvt || fusionEvt || secEvt || hasTracePanel;
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
                        ) : hasTracePanel ? (
                          <div className={styles.muted}>
                            Multimodal reasoning is present in right-panel contract mode: {(trace as any)?.right_panel?.mode || '--'}.
                          </div>
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
                    const timingEvt = events.find(e => eventMatches(e, 'timing_breakdown'));
                    const msTr = trace?.model_selection || {};
                    const timing = (timingEvt?.payload || (trace as any)?.timing_breakdown || {}) as Record<string, any>;
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
                        <div className={styles.sectionTitle}>Timing Breakdown</div>
                        {Object.keys(timing || {}).length > 0 ? (
                          <>
                            {(() => {
                              const rows = [
                                ['route_total_ms', 'Total Route'],
                                ['guard_ms', 'Input Guard'],
                                ['catalog_profile_ms', 'Catalog Profile'],
                                ['nlp_ms', 'NLP'],
                                ['ollama_summary_ms', 'Ollama Summary'],
                                ['retrieve_ms', 'Retrieval'],
                                ['rerank_ms', 'Rerank'],
                                ['image_fill_ms', 'Image Fill'],
                                ['copywriting_ms', 'Copywriting'],
                              ].filter(([key]) => typeof timing?.[key] === 'number');
                              const maxMs = Math.max(1, ...rows.map(([key]) => Number(timing[key]) || 0));
                              return (
                                <div className={styles.timingBars}>
                                  {rows.map(([key, label]) => (
                                    <div key={key} className={styles.timingRow}>
                                      <div className={styles.timingLabel}>{label}</div>
                                      <div className={styles.timingTrack}>
                                        <div
                                          className={styles.timingFill}
                                          style={{ width: `${Math.max(4, ((Number(timing[key]) || 0) / maxMs) * 100)}%` }}
                                        />
                                      </div>
                                      <div className={styles.timingValue}>{`${Math.round(Number(timing[key]) || 0)}ms`}</div>
                                    </div>
                                  ))}
                                </div>
                              );
                            })()}
                            <table className={styles.smallTable}>
                              <thead><tr><th>Stage</th><th>Latency</th></tr></thead>
                              <tbody>
                                {[
                                  ['route_total_ms', 'Total Route'],
                                  ['guard_ms', 'Input Guard'],
                                  ['catalog_profile_ms', 'Catalog Profile'],
                                  ['catalog_profile_cache_hit', 'Catalog Cache Hit'],
                                  ['nlp_ms', 'NLP'],
                                  ['ollama_summary_ms', 'Ollama Summary'],
                                  ['retrieve_ms', 'Retrieval'],
                                  ['rerank_ms', 'Rerank'],
                                  ['image_fill_ms', 'Image Fill'],
                                  ['copywriting_ms', 'Copywriting'],
                                ].filter(([key]) => Object.prototype.hasOwnProperty.call(timing || {}, key)).map(([key, label]) => (
                                  <tr key={key}>
                                    <td>{label}</td>
                                    <td>{key === 'catalog_profile_cache_hit' ? (timing[key] ? 'Yes' : 'No') : timing[key] == null ? 'Skipped' : `${Math.round(Number(timing[key]) || 0)}ms`}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </>
                        ) : (
                          <div className={styles.muted}>No stage timing data recorded for this trace.</div>
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
                  {security && !hadImage && (
                    <div style={{ margin: '0 0 10px', padding: '8px 10px', borderRadius: 8, border: '1px solid #bfdbfe', background: '#eff6ff', fontSize: 13, color: '#1e3a8a' }}>
                      <strong>Text-only turn — no image uploaded.</strong> The image checks below (QR decode,
                      steganography, OCR, adversarial/GAN) describe the coverage that runs on <em>uploaded images</em>;
                      they did not scan this text query. This turn's controls are input inspection, rate limiting, and
                      the framework mappings shown — not image forensics.
                    </div>
                  )}
                  {security && (
                    <>
                      {(() => {
                        const incident = getSecurityIncidentBrief();
                        return (
                          <div className={styles.incidentBrief}>
                            <div className={styles.briefCard}>
                              <div className={styles.briefTitle}>Decision</div>
                              <div className={styles.briefBody}>{incident.decision}</div>
                              {(incident.ownerScopeMeta || incident.humanVerificationRequired) && (
                                <div className={styles.tagRow} style={{ marginTop: 8 }}>
                                  {incident.ownerScopeMeta && (
                                    <span className={incident.ownerScopeMeta.className}>{incident.ownerScopeMeta.label}</span>
                                  )}
                                  {incident.humanVerificationRequired && (
                                    <span className={styles.tagWarn}>Human verification required</span>
                                  )}
                                </div>
                              )}
                            </div>
                            <div className={styles.briefCard}>
                              <div className={styles.briefTitle}>Business Impact</div>
                              <div className={styles.briefBody}>{incident.businessImpact}</div>
                              {(incident.ownerReason || incident.exposureScope) && (
                                <div className={styles.muted} style={{ marginTop: 8 }}>
                                  {[incident.ownerReason, incident.exposureScope ? `Exposure scope: ${incident.exposureScope.replace(/_/g, ' ')}` : ''].filter(Boolean).join(' ')}
                                </div>
                              )}
                            </div>
                            <div className={styles.briefCard}>
                              <div className={styles.briefTitle}>What Triggered It</div>
                              <ul className={styles.actionList}>
                                {incident.triggers.map((item, idx) => <li key={`trigger-${idx}`}>{item}</li>)}
                              </ul>
                            </div>
                            <div className={styles.briefCard}>
                              <div className={styles.briefTitle}>What Agents Found</div>
                              <div className={styles.agentBriefStack}>
                                {(incident.agentBriefs || []).map((agent: any, idx: number) => (
                                  <details key={`agent-${idx}`} className={styles.detailSection}>
                                    <summary className={styles.detailToggle}>{formatDisplayText(agent?.label, 'Agent')}</summary>
                                    <div className={styles.detailBody}>
                                      <div className={styles.kvRow}><span>Direct</span><span>{formatDisplayText(agent?.direct, 'Not observed')}</span></div>
                                      <div className={styles.kvRow}><span>Inferred</span><span>{formatDisplayText(agent?.inferred, 'Not available')}</span></div>
                                      <div className={styles.kvRow}><span>Context only</span><span>{formatDisplayText(agent?.contextual, 'Not available')}</span></div>
                                      {Array.isArray(agent?.detail) && agent.detail.length ? (
                                        <>
                                          <div className={styles.sectionTitle}>Drill Down</div>
                                          <ul className={styles.playbookList}>{agent.detail.map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                                        </>
                                      ) : null}
                                    </div>
                                  </details>
                                ))}
                              </div>
                            </div>
                            <div className={styles.briefCard}>
                              <div className={styles.briefTitle}>What To Do Now</div>
                              <ul className={styles.actionList}>
                                {incident.actions.map((item, idx) => <li key={`action-${idx}`}>{item}</li>)}
                              </ul>
                            </div>
                            <div className={styles.briefCard}>
                              <div className={styles.briefTitle}>Push Recommendation</div>
                              <div className={styles.briefBody}>
                                <span className={incident.pushRecommendation.includes('Hold') ? styles.tagWarn : styles.tagRed}>
                                  {incident.pushRecommendation}
                                </span>
                              </div>
                            </div>
                            {incident.threatHunterLeads?.length ? (
                              <div className={styles.briefCard}>
                                <div className={styles.briefTitle}>Threat Hunter Leads</div>
                                <ul className={styles.actionList}>
                                  {incident.threatHunterLeads.slice(0, 2).map((lead: any, idx: number) => (
                                    <li key={`hunter-${idx}`}>{formatDisplayText(lead?.title, 'Evidence-backed hunting lead available')}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                          </div>
                        );
                      })()}
                      {(() => {
                        const severityLabel = formatDisplayText(security.severity, 'review').toLowerCase();
                        const killChainPhase = formatDisplayText(
                          security.pasta?.current_stage || security.pasta?.stage || security.pasta_stage,
                          'Review',
                        );
                        const lead = Array.isArray(security?.threat_hunter_leads) && security.threat_hunter_leads.length > 0
                          ? security.threat_hunter_leads[0]
                          : null;
                        const approvalAware = ['high', 'critical'].includes(severityLabel) || String(security.policy_route || security.route || '').toLowerCase().includes('escal');
                        const plainEnglish = lead?.why_it_matters
                          || buildWhyFiredLine(security?.signals || {}, security?.payload_analysis || {})
                          || 'This artifact needs review because the evidence suggests a security-relevant workflow, not just a cosmetic image issue.';
                        const hunterAction = lead?.what_to_hunt_next?.[0] || 'Correlate this artifact with endpoint, identity, and network telemetry before broader containment.';
                        const humanAction = approvalAware
                          ? 'Hold blocking or containment actions until a human reviewer approves the next step.'
                          : 'Low-risk logging and observation can continue automatically, but escalation should stay human-led.';
                        return (
                          <div className={styles.playbookPanel}>
                            <div className={styles.sectionTitle}>What This Means</div>
                            <div className={styles.muted}>{plainEnglish}</div>
                            <div className={styles.kvRow}><span>Kill chain phase</span><span>{killChainPhase}</span></div>
                            <div className={styles.kvRow}><span>Severity gate</span><span>{severityLabel}</span></div>
                            <div className={styles.kvRow}><span>Human approval</span><span>{humanAction}</span></div>
                            <details className={styles.detailSection}>
                              <summary className={styles.detailToggle}>Role-based next actions</summary>
                              <div className={styles.detailBody}>
                                <div className={styles.sectionTitle}>Threat Hunter</div>
                                <ul className={styles.playbookList}>
                                  <li>{hunterAction}</li>
                                </ul>
                                <div className={styles.sectionTitle}>SOC / Security Ops</div>
                                <ul className={styles.playbookList}>
                                  <li>{approvalAware ? 'Prepare containment options, but keep them pending explicit approval.' : 'Queue low-risk monitoring and evidence collection.'}</li>
                                </ul>
                                <div className={styles.sectionTitle}>Human Reviewer</div>
                                <ul className={styles.playbookList}>
                                  <li>{lead?.business_guidance || 'Use the plain-English summary to decide whether to escalate, block, or request more evidence.'}</li>
                                </ul>
                              </div>
                            </details>
                          </div>
                        );
                      })()}
                      <details className={styles.detailSection}>
                        <summary className={styles.detailToggle}>Open security matrix detail</summary>
                        <div className={styles.detailBody}>
                      <div className={styles.sectionHeaderRow}>
                        <div className={styles.sectionTitle}>Security Overview</div>
                        <div className={styles.sectionActions}>
                          <button className={styles.copyBtn} onClick={copySecurityReport}>Copy Security Report</button>
                          {copyStatus && <span className={styles.copyStatus}>{copyStatus}</span>}
                        </div>
                      </div>
                      <div className={styles.kvRow}><span>Severity</span><span>{formatDisplayText(security.severity, 'Review')}</span></div>
                      <div className={styles.kvRow}><span>Risk (Adjusted)</span><span>{formatDisplayText(security.risk_adj, 'Pending enrichment')}</span></div>
                      <div className={styles.kvRow}>
                        <span>Composite Risk</span>
                        <span><span className={styles.scoreChip}>{compositeRisk == null ? 'Pending enrichment' : `${Math.round(compositeRisk)}/100`}</span></span>
                      </div>
                      <div className={styles.kvRow}><span>DREAD Avg</span><span>{formatDisplayText(security.dread?.avg ?? security.dread_avg, 'Not available')}</span></div>
                      <div className={styles.kvRow}><span>DREAD Weighted Avg</span><span>{formatDisplayText(security.dread?.weighted_avg ?? security.dread_weighted_avg, 'Not available')}</span></div>
                      <div className={styles.kvRow}><span>CVSS</span><span>{formatDisplayText(security.cvss?.score ?? security.cvss_score, 'Not available')}</span></div>
                      <div className={styles.kvRow}><span>PASTA Stage</span><span>{formatDisplayText(security.pasta?.current_stage || security.pasta?.stage || security.pasta_stage, 'Not available')}</span></div>
                      <div className={styles.kvRow}><span>Policy Route</span><span>{formatDisplayText(security.policy_route || security.route, 'Review')}</span></div>
                      <div className={styles.kvRow}><span>QR Destination</span><span>{formatDisplayText(qrInfo?.destination_url, 'No linked artifact')}</span></div>
                      <div className={styles.kvRow}><span>QR Final URL</span><span>{formatDisplayText(qrInfo?.final_url, 'Not available')}</span></div>
                      <div className={styles.kvRow}><span>QR Redirect Hops</span><span>{formatDisplayText(qrInfo?.redirect_hops ?? 0, '0')}</span></div>
                      <div className={styles.kvRow}><span>QR Reputation</span><span>{formatDisplayText(qrInfo?.reputation_verdict, 'Pending enrichment')}</span></div>
                      <div className={styles.kvRow}><span>QR Confidence</span><span>{formatDisplayText(qrInfo?.confidence, 'Not available')}</span></div>
                      <div className={styles.kvRow}><span>QR Intel Risk</span><span>{formatDisplayText(qrInfo?.intel_risk, 'Pending enrichment')}</span></div>
                      <div className={styles.kvRow}><span>QR Intel Pending</span><span>{qrInfo?.intel_pending ? 'Yes' : 'No'}</span></div>
                      <div className={styles.kvRow}>
                        <span>QR Intel Sources</span>
                        <span>{Array.isArray(qrInfo?.intel_sources) && qrInfo.intel_sources.length > 0 ? qrInfo.intel_sources.join(', ') : 'Pending enrichment'}</span>
                      </div>
                      <div className={styles.kvRow}>
                        <span>Image Trust Channels</span>
                        <span>
                          <span className={trustChannels?.visual_embedding_trusted ? styles.booleanYes : styles.booleanNo}>
                            visual:{trustChannels?.visual_embedding_trusted ? 'trusted' : 'untrusted'}
                          </span>
                          {' ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· '}
                          <span className={trustChannels?.ocr_trusted ? styles.booleanYes : styles.booleanNo}>
                            ocr:{trustChannels?.ocr_trusted ? 'trusted' : 'untrusted'}
                          </span>
                          {' ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· '}
                          <span className={trustChannels?.qr_trusted ? styles.booleanYes : styles.booleanNo}>
                            qr:{trustChannels?.qr_trusted ? 'trusted' : 'untrusted'}
                          </span>
                        </span>
                      </div>

                      <div className={styles.sectionTitle}>CV Playbook</div>
                      {playbookPreview ? (
                        <div className={styles.playbookPanel}>
                          <div className={styles.kvRow}><span>Playbook</span><span>{formatDisplayText(playbookData?.title || playbookData?.id, 'Not available')}</span></div>
                          <div className={styles.kvRow}><span>ID</span><span>{formatDisplayText(playbookData?.id, 'Not available')}</span></div>
                          <div className={styles.kvRow}><span>Override</span><span>{playbookPreview.override ? 'Yes' : 'No'}</span></div>
                          <div className={styles.kvRow}><span>Risk Band</span><span>{formatDisplayText(playbookPreview.risk_band || playbookPayload?.risk_band, 'Not available')}</span></div>
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
                      <div className={styles.sectionTitle}>Threat Hunter Leads</div>
                      {Array.isArray(security?.threat_hunter_leads) && security.threat_hunter_leads.length > 0 ? (
                        <div className={styles.playbookPanel}>
                          {security.threat_hunter_leads.slice(0, 3).map((lead: any, idx: number) => (
                            <details key={lead?.lead_id || `hunter-lead-${idx}`} className={styles.detailSection}>
                              <summary className={styles.detailToggle}>{formatDisplayText(lead?.title, 'Threat hunting lead')}</summary>
                              <div className={styles.detailBody}>
                                <div className={styles.kvRow}><span>Confidence</span><span>{formatDisplayText(lead?.confidence_band, 'medium')}</span></div>
                                <div className={styles.kvRow}><span>Likely Next Stage</span><span>{formatDisplayText(lead?.likely_kill_chain_stage, 'Not available')}</span></div>
                                <div className={styles.sectionTitle}>What We Observed</div>
                                <ul className={styles.playbookList}>{(lead?.what_we_observed || []).map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                                <div className={styles.sectionTitle}>What To Hunt Next</div>
                                <ul className={styles.playbookList}>{(lead?.what_to_hunt_next || []).map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                                <div className={styles.sectionTitle}>Where To Check</div>
                                <ul className={styles.playbookList}>{(lead?.where_to_check || []).map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                                {lead?.target_checklists && Object.keys(lead.target_checklists).length > 0 ? (
                                  <>
                                    <div className={styles.sectionTitle}>Target-specific hunt checklist</div>
                                    {Object.entries(lead.target_checklists).map(([target, checks]: any, i: number) => (
                                      <div key={`target-${i}`}>
                                        <div className={styles.kvRow}><span>{formatDisplayText(target, 'Target')}</span><span></span></div>
                                        <ul className={styles.playbookList}>{(Array.isArray(checks) ? checks : []).map((item: string, j: number) => <li key={j}>{item}</li>)}</ul>
                                      </div>
                                    ))}
                                  </>
                                ) : null}
                                <div className={styles.sectionTitle}>What Would Confirm It</div>
                                <ul className={styles.playbookList}>{(lead?.confirmation_signals || []).map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                                <div className={styles.sectionTitle}>What Would Weaken It</div>
                                <ul className={styles.playbookList}>{(lead?.disproving_signals || []).map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
                                {lead?.analyst_guidance ? <div className={styles.kvRow}><span>Analyst Guidance</span><span>{formatDisplayText(lead?.analyst_guidance, 'Not available')}</span></div> : null}
                              </div>
                            </details>
                          ))}
                        </div>
                      ) : (
                        <div className={styles.muted}>No evidence-backed threat-hunting leads were generated for this trace.</div>
                      )}
                        </div>
                      </details>

                      <div className={styles.sectionTitle}>OWASP LLM Top 10</div>
                      <div className={styles.tagRow}>
                        {owaspLlmTags.map((t: string) => (
                          <span key={t} className={styles.tag}>{t}</span>
                        ))}
                        {owaspLlmTags.length === 0 && <span className={styles.muted}>None</span>}
                      </div>

                      <div className={styles.sectionTitle}>OWASP Agentic Top 10</div>
                      <div className={styles.tagRow}>
                        {owaspAgenticTags.map((t: string) => (
                          <span key={t} className={styles.tag}>{t}</span>
                        ))}
                        {owaspAgenticTags.length === 0 && <span className={styles.muted}>None</span>}
                      </div>

                      <div className={styles.sectionTitle}>MAESTRO Agentic Boundaries (CSA 2025)</div>
                      {maestroGuardrailEvents.length === 0 && (
                        <div className={styles.muted}>No agent boundary checks recorded for this trace.</div>
                      )}
                      {maestroGuardrailEvents.length > 0 && (
                        <div className={styles.playbookPanel}>
                          <div className={styles.kvRow}>
                            <span>Boundaries checked</span>
                            <span>{maestroGuardrailEvents.length}</span>
                          </div>
                          <div className={styles.kvRow}>
                            <span>Violations</span>
                            <span>
                              {maestroViolationCount === 0
                                ? <span className={styles.booleanYes}>None - all agents within scope</span>
                                : <span className={styles.tagRed}>{maestroViolationCount} violation{maestroViolationCount > 1 ? 's' : ''}</span>
                              }
                            </span>
                          </div>
                          <table className={styles.smallTable}>
                            <thead>
                              <tr>
                                <th>Agent</th>
                                <th>Boundary</th>
                                <th>Status</th>
                                <th>Violations</th>
                              </tr>
                            </thead>
                            <tbody>
                              {maestroGuardrailEvents.map((ev, idx) => (
                                <tr key={`maestro-${idx}`}>
                                  <td>{ev.agent || '-'}</td>
                                  <td>
                                    {ev.boundary || '-'}
                                    {ev.control && <div className={styles.muted}>{ev.control}</div>}
                                  </td>
                                  <td>
                                    {ev.violations.length === 0
                                      ? <span className={styles.booleanYes}>{ev.verdict || 'within boundary'}</span>
                                      : <span className={styles.tagWarn}>{ev.violations.length} violation{ev.violations.length > 1 ? 's' : ''}</span>
                                    }
                                    {ev.action && <div className={styles.muted}>{ev.action}</div>}
                                  </td>
                                  <td>
                                    {ev.violations.length === 0
                                      ? <span className={styles.muted}>-</span>
                                      : (
                                        <ul className={styles.playbookList}>
                                          {ev.violations.map((v: any, vi: number) => (
                                            <li key={vi} title={v.detail}>
                                              <span className={v.severity === 'critical' || v.severity === 'high' ? styles.tagRed : styles.tagWarn}>
                                                {v.severity}
                                              </span>
                                              {' '}{String(v.violation_type || '').replace(/_/g, ' ')}
                                            </li>
                                          ))}
                                        </ul>
                                      )
                                    }
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}


                      <div className={styles.sectionTitle}>STRIDE</div>
                      <div className={styles.tagRow}>
                        {strideTags.map((t: string) => (
                          <span key={t} className={styles.tag}>{t}</span>
                        ))}
                        {strideTags.length === 0 && <span className={styles.muted}>None</span>}
                      </div>

                      <div className={styles.sectionTitle}>MITRE ATLAS (Evidence-based)</div>
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
                              <td>{formatDisplayText(m.name, 'Not available')}</td>
                              <td>{formatDisplayText(m.weight, 'Not available')}</td>
                              <td>{formatDisplayText(m.dread_avg, 'Not available')}</td>
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
                            <tr><td colSpan={5} className={styles.muted}>
                              {(security?.signals && Object.keys(security.signals).length > 0)
                                ? 'Evaluated - no MITRE mapping for active signals.'
                                : 'Evaluated - no issues detected.'}
                            </td></tr>
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
                      {/* Per-signal PASTA stage chips derived from active signals */}
                      {(() => {
                        const _sigs = security?.signals || {};
                        const _SIGNAL_PASTA: Record<string, string> = {
                          ransomware_indicator: 'Stage6',
                          c2_beacon: 'Stage5',
                          lolbin_command_sequence: 'Stage4',
                          cross_modal_mismatch: 'Stage5',
                          pci_card_exposed: 'Stage5',
                          multimodal_attack_surface_high: 'Stage5',
                          steg_suspicious: 'Stage4',
                          steg_score_elevated: 'Stage4',
                          macros_embedded: 'Stage4',
                          adversarial_detected: 'Stage3',
                          qr_prompt_injection: 'Stage3',
                        };
                        const _STAGE_CLASS: Record<string, string> = {
                          Stage6: styles.tagRed,
                          Stage5: styles.tagRed,
                          Stage4: styles.tagWarn,
                          Stage3: styles.tagWarn,
                        };
                        const chips = Object.entries(_SIGNAL_PASTA)
                          .filter(([sig]) => _sigs[sig])
                          .map(([sig, stage]) => ({ sig, stage }));
                        if (chips.length === 0) return null;
                        return (
                          <div className={styles.tagRow} style={{ marginTop: '4px' }}>
                            {chips.map(({ sig, stage }) => (
                              <span key={sig} className={_STAGE_CLASS[stage] || styles.tag} title={sig}>
                                {stage} \u2014 {sig.replace(/_/g, ' ')}
                              </span>
                            ))}
                          </div>
                        );
                      })()}
                    </>
                  )}

                  {/* Image Triage Signals */}
                  {triageItems && triageItems.length > 0 && (
                    <>
                      <div className={styles.sectionTitle}>Image Triage Signals</div>
                      {triageItems.map((t: any, idx: number) => {
                        const runtimeResult = runtimeSecurityResults[`${traceId || 'trace'}:${idx}:${t?._filename || `Image ${idx + 1}`}`] || {};
                        const runtimeOverride = (runtimeResult?.payload_analysis_override && typeof runtimeResult.payload_analysis_override === 'object')
                          ? runtimeResult.payload_analysis_override
                          : {};
                        const sigs = t?.security?.signals || t?.signals || {};
                        const ocrText = (t?.security?.extracted_text || t?.security?.ocr_text || t?.extracted_text || t?.ocr_text || t?.ocr?.best_text || '').trim();
                        const payloads: any[] = sigs.qr_payloads || t?.qr_payloads || [];
                        const payloadAnalysis = { ...(t?.security?.payload_analysis || t?.payload_analysis || {}), ...runtimeOverride };
                        const evidence = (t?.security?.evidence && typeof t.security.evidence === 'object') ? t.security.evidence : {};
                        const mitreAttack: string[] = Array.isArray(runtimeResult?.mitre_attack)
                          ? runtimeResult.mitre_attack
                          : Array.isArray(t?.security?.mitre_attack)
                            ? t.security.mitre_attack
                            : Array.isArray(payloadAnalysis?.mitre_attack)
                              ? payloadAnalysis.mitre_attack
                              : [];
                        const mitreAtlas: string[] = Array.isArray(runtimeResult?.mitre_atlas)
                          ? runtimeResult.mitre_atlas
                          : Array.isArray(t?.security?.mitre_atlas)
                            ? t.security.mitre_atlas
                            : Array.isArray(payloadAnalysis?.mitre_atlas)
                              ? payloadAnalysis.mitre_atlas
                              : [];
                        const possibleMitre: string[] = Array.from(new Set([
                          ...(Array.isArray(t?.security?.possible_mitre_attack) ? t.security.possible_mitre_attack : []),
                          ...(Array.isArray(payloadAnalysis?.possible_mitre_attack) ? payloadAnalysis.possible_mitre_attack : []),
                          ...(Array.isArray(t?.security?.possible_mitre_atlas) ? t.security.possible_mitre_atlas : []),
                          ...(Array.isArray(payloadAnalysis?.possible_mitre_atlas) ? payloadAnalysis.possible_mitre_atlas : []),
                        ]));
                        const claimStatus = String(runtimeResult?.claim_status || t?.security?.claim_status || payloadAnalysis?.claim_status || evidence?.claim_status || 'unknown');
                        const findingGroup = String(runtimeResult?.finding_group || t?.security?.finding_group || payloadAnalysis?.finding_group || evidence?.finding_group || 'unknown');
                        const evidenceLane = String(runtimeResult?.evidence_lane || t?.security?.evidence_lane || payloadAnalysis?.evidence_lane || evidence?.evidence_lane || 'unknown');
                        const runtimeEvidenceRequired: string[] = Array.isArray(runtimeResult?.runtime_evidence_missing)
                          ? runtimeResult.runtime_evidence_missing
                          : Array.isArray(t?.security?.runtime_evidence_required)
                          ? t.security.runtime_evidence_required
                          : Array.isArray(payloadAnalysis?.runtime_evidence_required)
                            ? payloadAnalysis.runtime_evidence_required
                            : Array.isArray(evidence?.runtime_evidence_required)
                              ? evidence.runtime_evidence_required
                              : [];
                        const runtimeEvidencePresent: string[] = Array.isArray(runtimeResult?.runtime_evidence_present)
                          ? runtimeResult.runtime_evidence_present
                          : Array.isArray(t?.security?.runtime_evidence_present)
                          ? t.security.runtime_evidence_present
                          : Array.isArray(payloadAnalysis?.runtime_evidence_present)
                            ? payloadAnalysis.runtime_evidence_present
                            : Array.isArray(evidence?.runtime_evidence_present)
                              ? evidence.runtime_evidence_present
                              : [];
                        const findingGroups = (t?.security?.finding_groups && typeof t.security.finding_groups === 'object') ? t.security.finding_groups : {};
                        const payloadFindings: any[] = Array.isArray(t?.security?.payload_findings) ? t.security.payload_findings : [];
                        const runtimePromotedFinding = runtimeResult?.supported ? [{
                          headline: runtimeResult?.summary || `${formatDisplayText(payloadAnalysis?.attack_hypothesis || 'runtime finding')} confirmed by runtime lab`,
                          finding_group: 'active_findings',
                        }] : [];
                        const activeFindings: any[] = Array.isArray(findingGroups?.active_findings)
                          ? findingGroups.active_findings
                          : payloadFindings.filter((f: any) => String(f?.finding_group || '') === 'active_findings');
                        const effectiveActiveFindings = runtimePromotedFinding.length > 0 ? runtimePromotedFinding : activeFindings;
                        const detectionArtifactPatterns: any[] = Array.isArray(findingGroups?.detection_artifact_patterns)
                          ? findingGroups.detection_artifact_patterns
                          : payloadFindings.filter((f: any) => String(f?.finding_group || '') === 'detection_artifact_patterns');
                        const unconfirmedHypotheses: any[] = Array.isArray(findingGroups?.unconfirmed_higher_order_hypotheses)
                          ? findingGroups.unconfirmed_higher_order_hypotheses
                          : payloadFindings.filter((f: any) => String(f?.finding_group || '') === 'unconfirmed_higher_order_hypotheses');
                        const suppressedFindings: any[] = payloadFindings.filter((f: any) => String(f?.claim_status || '').toLowerCase() === 'suppressed');
                        const runtimeRequiredFindings: any[] = payloadFindings.filter((f: any) =>
                          Boolean(f?.runtime_confirmation_required) ||
                          (Array.isArray(f?.runtime_evidence_required) && f.runtime_evidence_required.length > 0)
                        );
                        const artifactProvenance: any[] = Array.isArray(runtimeResult?.artifact_provenance)
                          ? runtimeResult.artifact_provenance
                          : Array.isArray(evidence?.artifact_provenance)
                            ? evidence.artifact_provenance
                            : [];
                        const filename = t?._filename || `Image ${idx + 1}`;
                        const itemKey = `${traceId || 'trace'}:${idx}:${filename}`;
                        const linkedArtifact = linkedArtifactResults[itemKey] || t?.security?.linked_artifact_analysis || payloadAnalysis?.linked_artifact_analysis || {};
                        const cleanFlag = t?.security?.clean;
                        const clean = cleanFlag !== false && !sigs.qr_code_detected && !sigs.adversarial_detected && !sigs.steg_suspicious;
                        return (
                          <div key={idx} className={styles.triageBlock}>
                            <div className={styles.kvRow}>
                              <span>{filename}</span>
                              <span className={clean ? styles.tagGreen : styles.tagRed}>{clean ? 'Clean' : 'Flagged'}</span>
                            </div>
                            {/* Why this fired ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â one-liner analyst detection reason */}
                            {!clean && (() => {
                              const _why = buildWhyFiredLine(sigs, payloadAnalysis);
                              return _why ? (
                                <div className={styles.kvRow}>
                                  <span className={styles.tagWarn}>Why flagged</span>
                                  <span className={styles.muted}>{_why}</span>
                                </div>
                              ) : null;
                            })()}
                            {/* Narrative summary */}
                            <div className={styles.triageNarrative}>{buildTriageNarrative(t)}</div>
                            {/* OCR / extracted text */}
                            {ocrText && (
                              <>
                                <div className={styles.sectionSubTitle}>OCR / Extracted Text</div>
                                <pre className={styles.rawBlock}>{ocrText.slice(0, 400)}{ocrText.length > 400 ? '\n?' : ''}</pre>
                              </>
                            )}
                            {!ocrText && (
                              <>
                                <div className={styles.sectionSubTitle}>OCR / Extracted Text</div>
                                <div className={styles.muted}>Evaluated - no OCR text extracted.</div>
                              </>
                            )}
                            <div className={styles.sectionSubTitle}>Payload Assessment</div>
                            <div className={styles.payloadGrid}>
                              <div className={styles.kvRow}><span>Decoded artifact available</span><span>{renderValue(Boolean(payloadAnalysis.decoded_artifact_available))}</span></div>
                              <div className={styles.kvRow}><span>Payload type</span><span>{renderValue(payloadAnalysis.payload_type || 'unknown')}</span></div>
                              <div className={styles.kvRow}><span>Attack hypothesis</span><span>{renderValue(payloadAnalysis.attack_hypothesis || 'unknown')}</span></div>
                              <div className={styles.kvRow}><span>Claim status</span><span>{renderValue(claimStatus)}</span></div>
                              <div className={styles.kvRow}><span>Finding group</span><span>{renderValue(findingGroup)}</span></div>
                              <div className={styles.kvRow}><span>Evidence lane</span><span>{renderValue(evidenceLane)}</span></div>
                              <div className={styles.kvRow}><span>Runtime confirmation required</span><span>{renderValue(Boolean(runtimeRequiredFindings.length > 0 || payloadAnalysis.runtime_confirmation_required))}</span></div>
                              {payloadAnalysis.pasta_stage && (
                                <div className={styles.kvRow}><span>PASTA stage</span><span className={styles.tagWarn}>{payloadAnalysis.pasta_stage}</span></div>
                              )}
                              <div className={styles.kvRow}><span>Decode path</span><span className={(
                                payloadAnalysis.decode_path === 'sandbox_required_do_not_execute'
                                  ? styles.tagRed
                                  : payloadAnalysis.decode_path === 'lolbin_command_decode'
                                    ? styles.tagWarn
                                    : undefined
                              )}>{renderValue(payloadAnalysis.decode_path || 'safe_passive_decode_only')}</span></div>
                              <div className={styles.kvRow}><span>Suggested next step</span><span>{renderValue(payloadAnalysis.suggested_next_step || 'allow')}</span></div>
                            </div>
                            <div className={styles.sectionSubTitle}>Claim Lanes</div>
                            <div className={styles.payloadGrid}>
                              <div className={styles.kvRow}><span>Observed</span><span>{effectiveActiveFindings.length}</span></div>
                              <div className={styles.kvRow}><span>Possible</span><span>{unconfirmedHypotheses.length}</span></div>
                              <div className={styles.kvRow}><span>Suppressed</span><span>{suppressedFindings.length}</span></div>
                              <div className={styles.kvRow}><span>Runtime required</span><span>{runtimeRequiredFindings.length}</span></div>
                            </div>
                            {(activeFindings.length > 0 || detectionArtifactPatterns.length > 0 || unconfirmedHypotheses.length > 0 || runtimeRequiredFindings.length > 0 || suppressedFindings.length > 0) && (
                              <>
                                <div className={styles.sectionSubTitle}>Evidence-backed Findings</div>
                                {effectiveActiveFindings.length > 0 && (
                                  <>
                                    <div className={styles.kvRow}><span>Observed findings</span><span>{effectiveActiveFindings.length}</span></div>
                                    <ul className={styles.playbookList}>{effectiveActiveFindings.slice(0, 4).map((finding: any, fi: number) => <li key={`af-${fi}`}>{formatDisplayText(finding?.headline || finding?.summary || finding?.finding_type, 'Observed finding')}</li>)}</ul>
                                  </>
                                )}
                                {detectionArtifactPatterns.length > 0 && (
                                  <>
                                    <div className={styles.kvRow}><span>Detection artifact patterns</span><span>{detectionArtifactPatterns.length}</span></div>
                                    <ul className={styles.playbookList}>{detectionArtifactPatterns.slice(0, 3).map((finding: any, fi: number) => <li key={`df-${fi}`}>{formatDisplayText(finding?.headline || finding?.summary || finding?.finding_type, 'Artifact pattern')}</li>)}</ul>
                                  </>
                                )}
                                {unconfirmedHypotheses.length > 0 && (
                                  <>
                                    <div className={styles.kvRow}><span>Hypotheses pending runtime telemetry</span><span>{unconfirmedHypotheses.length}</span></div>
                                    <ul className={styles.playbookList}>{unconfirmedHypotheses.slice(0, 4).map((finding: any, fi: number) => <li key={`uh-${fi}`}>{formatDisplayText(finding?.headline || finding?.summary || finding?.finding_type, 'Unconfirmed hypothesis')}</li>)}</ul>
                                  </>
                                )}
                                {runtimeRequiredFindings.length > 0 && (
                                  <>
                                    <div className={styles.kvRow}><span>Runtime required</span><span>{runtimeRequiredFindings.length}</span></div>
                                    <ul className={styles.playbookList}>{runtimeRequiredFindings.slice(0, 4).map((finding: any, fi: number) => <li key={`rr-${fi}`}>{formatDisplayText(finding?.headline || finding?.summary || finding?.finding_type, 'Runtime confirmation required')}</li>)}</ul>
                                    <div className={styles.muted}>Passive evidence only. Runtime confirmation is still required, and no process-tree or network telemetry has been observed yet for these claims.</div>
                                  </>
                                )}
                                {suppressedFindings.length > 0 && (
                                  <>
                                    <div className={styles.kvRow}><span>Suppressed claims</span><span>{suppressedFindings.length}</span></div>
                                    <ul className={styles.playbookList}>{suppressedFindings.slice(0, 3).map((finding: any, fi: number) => <li key={`sf-${fi}`}>{formatDisplayText(finding?.headline || finding?.summary || finding?.finding_type, 'Suppressed claim')}</li>)}</ul>
                                  </>
                                )}
                              </>
                            )}
                            {linkedArtifact?.linked_artifact_available && (
                              <>
                                <div className={styles.sectionSubTitle}>Linked Artifact Analysis</div>
                                <div className={styles.payloadGrid}>
                                  <div className={styles.kvRow}><span>Linked artifact available</span><span>{renderValue(Boolean(linkedArtifact.linked_artifact_available))}</span></div>
                                  <div className={styles.kvRow}><span>Linked artifact type</span><span>{renderValue(linkedArtifact.linked_artifact_type || 'unknown')}</span></div>
                                  <div className={styles.kvRow}><span>Verdict</span><span>{renderValue(linkedArtifact.linked_verdict_label || 'Needs Review')}</span></div>
                                  <div className={styles.kvRow}><span>Confidence</span><span>{renderValue(linkedArtifact.linked_confidence_band || 'medium')}</span></div>
                                  <div className={styles.kvRow}><span>Linked owner scope</span><span>{(() => { const meta = getOwnerScopeMeta(linkedArtifact.linked_owner_scope); return meta ? <span className={meta.className}>{meta.label}</span> : renderValue('unknown'); })()}</span></div>
                                  <div className={styles.kvRow}><span>Exposure scope</span><span>{renderValue(linkedArtifact.linked_exposure_scope || 'unknown')}</span></div>
                                  <div className={styles.kvRow}><span>Policy action</span><span>{renderValue(linkedArtifact.linked_policy_action || 'review')}</span></div>
                                  <div className={styles.kvRow}><span>Human verification required</span><span>{renderValue(Boolean(linkedArtifact.linked_human_verification_required))}</span></div>
                                  <div className={styles.kvRow}><span>PII detected</span><span>{renderValue(Boolean(linkedArtifact.pii_detected))}</span></div>
                                  <div className={styles.kvRow}><span>PII type</span><span>{renderValue(linkedArtifact.pii_type || [])}</span></div>
                                  <div className={styles.kvRow}><span>SSN hits</span><span>{renderValue(linkedArtifact.ssn_hits || [])}</span></div>
                                  <div className={styles.kvRow}><span>Linked hypothesis</span><span>{renderValue(linkedArtifact.linked_attack_hypothesis || 'unknown')}</span></div>
                                  <div className={styles.kvRow}><span>Linked decode path</span><span>{renderValue(linkedArtifact.linked_decode_path || 'safe_passive_link_fetch_only')}</span></div>
                                  <div className={styles.kvRow}><span>Linked next step</span><span>{renderValue(linkedArtifact.linked_suggested_next_step || 'review')}</span></div>
                                </div>
                                {!isMissingValue(linkedArtifact.linked_reason_summary) && (
                                  <>
                                    <div className={styles.sectionSubTitle}>Why It Was Flagged</div>
                                    <div className={styles.muted}>{formatDisplayText(linkedArtifact.linked_reason_summary, 'Not available')}</div>
                                  </>
                                )}
                                {linkedArtifact.linked_user_summary && typeof linkedArtifact.linked_user_summary === 'object' && (
                                  <>
                                    <div className={styles.sectionSubTitle}>Operator Summary</div>
                                    <div className={styles.kvRow}><span>What we saw</span><span>{renderValue(linkedArtifact.linked_user_summary.what_we_saw || 'Not available')}</span></div>
                                    <div className={styles.kvRow}><span>Why it matters</span><span>{renderValue(linkedArtifact.linked_user_summary.why_it_matters || 'Not available')}</span></div>
                                    <div className={styles.kvRow}><span>What happens next</span><span>{renderValue(linkedArtifact.linked_user_summary.what_happens_next || 'Not available')}</span></div>
                                  </>
                                )}
                                {!isMissingValue(linkedArtifact.linked_owner_reason) && (
                                  <>
                                    <div className={styles.sectionSubTitle}>Owner Assessment</div>
                                    <div className={styles.muted}>{formatDisplayText(linkedArtifact.linked_owner_reason, 'Not available')}</div>
                                  </>
                                )}
                                {Array.isArray(linkedArtifact.linked_artifact_provenance) && linkedArtifact.linked_artifact_provenance.length > 0 && (
                                  <>
                                    <div className={styles.sectionSubTitle}>Linked Artifact Provenance</div>
                                    <ul className={styles.playbookList}>
                                      {linkedArtifact.linked_artifact_provenance.map((row: any, pi: number) => (
                                        <li key={`lap-${pi}`}>{`${row?.source_file || 'artifact'} Ã¢â‚¬Â¢ ${row?.extraction_method || 'extract'} Ã¢â‚¬Â¢ ${row?.match_ref || 'match'} Ã¢â‚¬Â¢ ${row?.confidence || 'unknown'}${row?.reason ? ` Ã¢â‚¬Â¢ ${row.reason}` : ''}`}</li>
                                      ))}
                                    </ul>
                                  </>
                                )}
                                {linkedArtifact.linked_text_excerpt && (
                                  <>
                                    <div className={styles.sectionSubTitle}>Linked Artifact Text Excerpt</div>
                                    <pre className={styles.rawBlock}>{String(linkedArtifact.linked_text_excerpt)}</pre>
                                  </>
                                )}
                              </>
                            )}
                            {Array.isArray(payloadAnalysis?.lolbin_behavioral_profiles) && payloadAnalysis.lolbin_behavioral_profiles.length > 0 && (
                              <>
                                <div className={styles.sectionSubTitle}>LOLBin Behavioral Analysis</div>
                                {payloadAnalysis.lolbin_behavioral_profiles.map((profile: any, pi: number) => (
                                  <div key={pi} className={styles.behaviorCard}>
                                    <div className={styles.kvRow}>
                                      <span><strong>{profile.full_name || profile.detected_as || 'LOLBin'}</strong></span>
                                      <span className={styles.tagWarn}>{profile.mitre_sub_technique || 'MITRE'}</span>
                                    </div>
                                    <div className={styles.triageNarrative}>{profile.description || 'Behavioral context unavailable.'}</div>
                                    <div className={styles.kvRow}><span>Kill-chain stage</span><span>{profile.kill_chain_stage || '?'}</span></div>
                                    <div className={styles.kvRow}><span>Detection note</span><span className={styles.muted}>{profile.detection_note || '?'}</span></div>
                                    {Array.isArray(profile.abuse_patterns) && profile.abuse_patterns.length > 0 && (
                                      <pre className={styles.rawBlock}>{profile.abuse_patterns.join('\n')}</pre>
                                    )}
                                  </div>
                                ))}
                              </>
                            )}
                            <div className={styles.sectionSubTitle}>MITRE Attack</div>
                            <div className={styles.tagRow}>
                              {[...mitreAtlas, ...mitreAttack].map((tag: string) => (
                                <span key={tag} className={styles.tagWarn}>{tag}</span>
                              ))}
                              {[...mitreAtlas, ...mitreAttack].length === 0 && <span className={styles.muted}>No active ATT&amp;CK / ATLAS mappings.</span>}
                            </div>
                            {possibleMitre.length > 0 && (
                              <>
                                <div className={styles.sectionSubTitle}>Possible Runtime-only Mappings</div>
                                <div className={styles.tagRow}>
                                  {possibleMitre.map((tag: string) => (
                                    <span key={tag} className={styles.tag}>{tag}</span>
                                  ))}
                                </div>
                                <div className={styles.muted}>Passive evidence only. Execution, C2, and similar mappings stay in this lane until runtime confirmation is available. No process-tree or network telemetry has been observed yet for these claims.</div>
                              </>
                            )}
                            {(runtimeEvidenceRequired.length > 0 || runtimeEvidencePresent.length > 0) && (
                              <>
                                <div className={styles.sectionSubTitle}>Runtime Evidence</div>
                                {runtimeResult?.runtime_label && (
                                  <div className={styles.muted}>{formatDisplayText(runtimeResult.runtime_label, 'Not available')}</div>
                                )}
                                {runtimeEvidenceRequired.length > 0 && (
                                  <>
                                    <div className={styles.kvRow}><span>Still required</span><span>{runtimeEvidenceRequired.length}</span></div>
                                    <ul className={styles.playbookList}>{runtimeEvidenceRequired.map((item: string, ri: number) => <li key={`rr-${ri}`}>{item}</li>)}</ul>
                                  </>
                                )}
                                {runtimeEvidencePresent.length > 0 && (
                                  <>
                                    <div className={styles.kvRow}><span>Already present</span><span>{runtimeEvidencePresent.length}</span></div>
                                    <ul className={styles.playbookList}>{runtimeEvidencePresent.map((item: string, ri: number) => <li key={`rp-${ri}`}>{item}</li>)}</ul>
                                  </>
                                )}
                                {Array.isArray(runtimeResult?.parallel_swarm) && runtimeResult.parallel_swarm.length > 0 && (
                                  <>
                                    <div className={styles.sectionSubTitle}>Parallel Runtime Swarm</div>
                                    {runtimeResult.parallel_swarm.map((agent: any, ai: number) => (
                                      <div key={`rsa-${ai}`} className={styles.behaviorCard}>
                                        <div className={styles.kvRow}>
                                          <span><strong>{formatDisplayText(agent?.agent || `Agent ${ai + 1}`)}</strong></span>
                                          <span className={styles.tagWarn}>{formatDisplayText(agent?.verdict_impact || 'supporting')}</span>
                                        </div>
                                        <div className={styles.triageNarrative}>{formatDisplayText(agent?.inspected || 'Not available')}</div>
                                        {Array.isArray(agent?.findings) && agent.findings.length > 0 && (
                                          <ul className={styles.playbookList}>
                                            {agent.findings.map((finding: string, fi: number) => <li key={`rsf-${ai}-${fi}`}>{finding}</li>)}
                                          </ul>
                                        )}
                                        {Array.isArray(agent?.evidence_refs) && agent.evidence_refs.length > 0 && (
                                          <div className={styles.muted}>Evidence refs: {agent.evidence_refs.join(', ')}</div>
                                        )}
                                      </div>
                                    ))}
                                  </>
                                )}
                              </>
                            )}
                            {artifactProvenance.length > 0 && (
                              <>
                                <div className={styles.sectionSubTitle}>Artifact Provenance</div>
                                <ul className={styles.playbookList}>
                                  {artifactProvenance.map((row: any, pi: number) => (
                                    <li key={`ap-${pi}`}>{`${row?.source_file || 'artifact'} Ã¢â‚¬Â¢ ${row?.extraction_method || 'extract'} Ã¢â‚¬Â¢ ${row?.match_ref || 'match'} Ã¢â‚¬Â¢ ${row?.confidence || 'unknown'}${row?.reason ? ` Ã¢â‚¬Â¢ ${row.reason}` : ''}`}</li>
                                  ))}
                                </ul>
                              </>
                            )}
                            {/* Decoded QR payloads */}
                            {payloads.length > 0 && (
                              <>
                                <div className={styles.sectionSubTitle}>Decoded QR Payload{payloads.length > 1 ? 's' : ''}</div>
                                {payloads.map((p: any, pi: number) => (
                                  <div key={pi} className={styles.kvRow}>
                                    <span>{p.type || 'QR'}</span>
                                    <span className={styles.qrPayload} title={p.data}>{p.data}</span>
                                  </div>
                                ))}
                              </>
                            )}
                            {/* Active signal flags */}
                            <div className={styles.tagRow}>
                              {Object.entries(sigs)
                                .filter(([k, v]) => typeof v === 'boolean' && v && k !== 'qr_payloads')
                                .map(([k]) => {
                                  const SIGNAL_LABELS: Record<string, string> = payloadAnalysis?.signal_labels || {
                                    ransomware_indicator: 'Ransomware Indicator',
                                    steg_suspicious: 'Steg Anomaly',
                                    steg_score_elevated: 'Steg Score Elevated',
                                    c2_beacon: 'C2 Beacon',
                                    lolbin_command_sequence: 'LOLBin Command Sequence',
                                    macros_embedded: 'Embedded Macros',
                                    cross_modal_mismatch: 'Cross-Modal Mismatch',
                                    pci_card_exposed: 'PCI Card Exposed',
                                    multimodal_attack_surface_high: 'High Attack Surface',
                                    adversarial_detected: 'Adversarial Image',
                                    ai_generated_suspected: 'AI-Generated Suspected',
                                    qr_code_detected: 'QR Code',
                                    qr_prompt_injection: 'QR Prompt Injection',
                                    qr_external_url: 'QR External URL',
                                  };
                                  const label = SIGNAL_LABELS[k] || k.replace(/_/g, ' ');
                                  const isCritical = k === 'ransomware_indicator' || k === 'c2_beacon' || k === 'lolbin_command_sequence';
                                  return <span key={k} className={isCritical ? styles.tagRed : styles.tagWarn}>{label}</span>;
                                })}
                              {sigs.steg_score != null && (
                                <span className={styles.tagWarn}>steg score: {sigs.steg_score}</span>
                              )}
                              {sigs.steganography?.decoded_content && (
                                <div className={styles.stegDecodedBlock} style={{marginTop: '6px', padding: '6px 8px', background: '#1a0000', border: '1px solid #c0392b', borderRadius: '4px', fontFamily: 'monospace', fontSize: '11px', color: '#e74c3c', wordBreak: 'break-all'}}>
                                  <strong style={{color: '#ff6b6b'}}>⚠ LSB Payload Extracted:</strong>{' '}
                                  {sigs.steganography.decoded_content.slice(0, 300)}
                                  {sigs.steganography.decoded_content.length > 300 ? '…' : ''}
                                </div>
                              )}
                            </div>
                            {!clean && (
                              <>
                                <div className={styles.actionRow}>
                                  {getLinkedArtifactUrl(sigs) && (
                                    <button
                                      type="button"
                                      className={styles.secondaryAction}
                                      onClick={() => triggerPayloadAction(itemKey, t, 'analyze_linked_artifact')}
                                    >
                                      Analyze linked document
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    className={styles.secondaryAction}
                                    onClick={() => triggerPayloadAction(itemKey, t, 'analyze_payload_further')}
                                  >
                                    Analyze payload further
                                  </button>
                                  <button
                                    type="button"
                                    className={styles.primaryAction}
                                    onClick={() => triggerPayloadAction(itemKey, t, 'queue_sandbox_detonation')}
                                  >
                                    Queue sandbox detonation
                                  </button>
                                </div>
                                {payloadActionStatus[itemKey] && (
                                  <div className={styles.actionStatus}>{payloadActionStatus[itemKey]}</div>
                                )}
                              </>
                            )}
                          </div>
                        );
                      })}
                    </>
                  )}
                </div>
              )}

              {activeTab === 'procurement' && (
                <div className={styles.summaryPane}>
                  {(() => {
                    const src = events.length > 0 ? events : displayEvents;
                    const procEvents = (src || []).filter((e) => {
                      const sid = String((e as any).source_id || '');
                      const sidl = sid.toLowerCase();
                      const et = String(e.event_type || '').toLowerCase();
                      return ['Market_Intelligence_Agent', 'Procurement_Agent', 'Alternatives_Agent', 'Supplier_Selection_Agent'].includes(sid)
                        // agents whose id carries the procurement/split/supplier/sourcing role (catches
                        // Procurement_Split_Agent + Supplier_Channel_Agent the old allow-list missed)
                        || sidl.includes('procurement') || sidl.includes('split') || sidl.includes('supplier') || sidl.includes('sourcing')
                        || et.startsWith('bulk_') || et.startsWith('procurement_') || et.startsWith('alternatives_')
                        || et.includes('availability') || et.includes('buyer_qualif') || et.includes('supplier')
                        || et.includes('split') || et.includes('sourc') || et.includes('channel')
                        || et.includes('integrity') || sidl.includes('integrity');  // outbound integrity guard
                    });
                    // Outbound integrity blocks — the platform quarantining its OWN drafted supplier mail
                    // before send (poisoned payload / data leak). Surfaced prominently: bounded autonomy
                    // contained ShopSquire's own potential blast radius.
                    const integrityBlocks = (src || []).filter((e) =>
                      String(e.event_type || '').toLowerCase().includes('outbound_integrity'));
                    // The GENUINE market-intelligence step (real findings + a bounded, deterministic
                    // recommendation) — surfaced as a card so the intelligence is seen, not just logged.
                    const miEvent: any = [...(src || [])].reverse().find((e: any) =>
                      String(e?.payload?._original_event_type || e.event_type) === 'market_intelligence_assessed'
                      && e?.payload?.recommendation);
                    const mi: any = miEvent?.payload || null;
                    const draft: any = (procCase?.state_json?.draft) || null;
                    const money = (c: any) => (typeof c === 'number' ? `$${(c / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : null);
                    return (
                      <>
                        {integrityBlocks.length > 0 && (
                          <div data-testid="proc-integrity-guard" style={{ border: '1px solid #16a34a', background: '#f0fdf4', borderRadius: 10, padding: '10px 12px', fontSize: 13, marginBottom: 12 }}>
                            <div style={{ fontWeight: 700, marginBottom: 4, color: '#166534' }}>
                              🛡 Outbound integrity guard — {integrityBlocks.length} supplier message{integrityBlocks.length > 1 ? 's' : ''} quarantined before send
                            </div>
                            <div style={{ color: '#166534', marginBottom: 6 }}>
                              ShopSquire scanned its OWN drafted supplier email and did NOT relay it — bounded autonomy contained the blast radius so the platform can't become a threat vector into a supplier's inbox.
                            </div>
                            {integrityBlocks.map((e, i) => {
                              const p: any = (e as any).payload || {};
                              const findings: string[] = Array.isArray(p.findings) ? p.findings : [];
                              const action = String(p.action || 'block');
                              return (
                                <div key={i} style={{ paddingLeft: 6, borderLeft: `3px solid ${action === 'block' ? '#dc2626' : '#f59e0b'}`, marginBottom: 4 }}>
                                  <span style={{ fontWeight: 600, color: action === 'block' ? '#b91c1c' : '#92400e' }}>{action === 'block' ? 'BLOCKED' : 'HELD FOR REVIEW'}</span>
                                  {p.recipient_domain ? <span style={{ color: '#6b7280' }}> → {p.recipient_domain}</span> : null}
                                  {findings.length ? <span style={{ color: '#374151' }}> · {findings.join(', ')}</span> : null}
                                </div>
                              );
                            })}
                          </div>
                        )}
                        {mi && (
                          <div data-testid="proc-market-intel" style={{ border: '1px solid #6366f1', background: '#eef2ff', borderRadius: 10, padding: '10px 12px', fontSize: 13, marginBottom: 12 }}>
                            <div style={{ fontWeight: 700, color: '#3730a3', marginBottom: 4 }}>
                              📊 Market Intelligence — {String(mi.mode) === 'live' ? `${mi.signal_count} active signal${mi.signal_count === 1 ? '' : 's'}` : 'internal-only (no external signal)'}
                            </div>
                            <div style={{ marginBottom: 6 }}>
                              <span style={{ fontWeight: 700 }}>Recommended action:</span> {String(mi.recommendation || '—')}
                              <div style={{ color: '#4b5563', marginTop: 2 }}>{String(mi.rationale || '')}</div>
                            </div>
                            {Array.isArray(mi.signals) && mi.signals.length > 0 && (
                              <div>
                                {mi.signals.map((s: any, i: number) => (
                                  <div key={i} style={{ paddingLeft: 6, borderLeft: `3px solid ${String(s.severity) === 'critical' ? '#dc2626' : '#f59e0b'}`, marginBottom: 3, color: '#374151' }}>
                                    <span className={styles.mono} style={{ fontSize: 11 }}>{String(s.type || '')}</span>
                                    {s.summary ? <span> — {String(s.summary)}</span> : null}
                                  </div>
                                ))}
                              </div>
                            )}
                            <div style={{ marginTop: 6, fontSize: 11, color: '#6b7280' }}>
                              Deterministic finding→action synthesis (no LLM) over the market-analysis engine's persisted findings — advisory only; the human decides at the send gate.
                            </div>
                          </div>
                        )}
                        {procEvents.length === 0 && !procCase && pendingSplit?.split ? (
                          <div data-testid="proc-pending-plan" style={{ border: '1px solid #fcd34d', background: '#fffbeb', borderRadius: 10, padding: '10px 12px', fontSize: 13 }}>
                            <div style={{ fontWeight: 700, marginBottom: 4 }}>⏳ Pending sourcing plan — nothing confirmed, no supplier contacted</div>
                            <div style={{ color: '#92400e', marginBottom: 8 }}>
                              {pendingSplit.split.now.reduce((s, l) => s + l.qty, 0)} ship from stock · {pendingSplit.split.later.reduce((s, l) => s + l.qty, 0)} require supplier reorder
                            </div>
                            {Object.entries(
                              pendingSplit.split.later.reduce((acc: Record<string, typeof pendingSplit.split.later>, l) => {
                                const k = l.supplier_ref || 'unassigned'; (acc[k] = acc[k] || []).push(l); return acc;
                              }, {})
                            ).map(([ref, lines]) => {
                              const sup: any = (pendingSplit as any).suppliers?.[ref] || {};
                              const ch = String(sup.channel || 'email').toLowerCase();
                              const chLabel = ch === 'email' ? '✉ EMAIL — agent drafts, human sends'
                                : (ch === 'phone' || ch === 'portal') ? `${ch === 'phone' ? '📞 PHONE' : '🌐 PORTAL'} — HUMAN-ONLY`
                                : `⚙ ${ch.toUpperCase()} — system integration`;
                              const eta = Math.max(...lines.map((l) => l.eta_days ?? 0));
                              return (
                                <div key={ref} style={{ marginBottom: 8, paddingLeft: 6, borderLeft: '3px solid #f59e0b' }}>
                                  <div style={{ fontWeight: 600 }}>
                                    {sup.name || ref} <span style={{ fontWeight: 400, color: '#6b7280' }}>· {lines.reduce((s, l) => s + l.qty, 0)} unit(s){eta ? ` · ~${eta}d` : ''} · {chLabel}</span>
                                  </div>
                                  {lines.map((l) => (<div key={l.sku} style={{ color: '#374151' }}>{l.qty} × {l.sku}</div>))}
                                </div>
                              );
                            })}
                            <div style={{ color: '#6b7280' }}>RFQ drafts are created when the buyer confirms the delivery plan in the cart (GATE 1) — then this tab shows each drafted email + the audit trail.</div>
                          </div>
                        ) : procEvents.length === 0 ? (
                          <div className={styles.empty}>No procurement / supplier-selection / market-intelligence activity in this trace (not a bulk or sourcing turn).</div>
                        ) : (
                          <table className={styles.table}>
                            <thead><tr><th>Agent</th><th>Event</th><th>Detail</th></tr></thead>
                            <tbody>
                              {procEvents.map((e, i) => {
                                const p: any = (e as any).payload || {};
                                const tp = Array.isArray(p.transfer_plan) ? p.transfer_plan : [];
                                const detail = [
                                  p.sku && `SKU ${p.sku}`,
                                  p.order_qty != null && `qty ${p.order_qty}`,
                                  p.in_stock != null && `in-stock ${p.in_stock}`,
                                  p.shortfall != null && `shortfall ${p.shortfall}`,
                                  p.now_qty != null && `ship-now ${p.now_qty}`,
                                  p.later_qty != null && `follow ${p.later_qty}`,
                                  p.eta_days != null && `ETA ~${p.eta_days}d`,
                                  tp.length > 0 && `transfer ${tp.map((t: any) => `${t.qty}@${t.from_location}`).join(', ')}`,
                                  p.status && `status ${p.status}`,
                                  Array.isArray(p.types) && p.types.length > 0 && `options: ${p.types.join(', ')}`,
                                  p.count != null && `${p.count} alternatives`,
                                  p.channel && `channel: ${p.channel}`,
                                  p.requires_human === true && '👤 HUMAN-only outreach',
                                  p.integration_kind && `→ ${String(p.integration_kind).toUpperCase()} integration`,
                                  p.channel && p.agent_may_draft === true && 'agent drafts · human sends',
                                  p.case_id && `case ${String(p.case_id).slice(0, 8)}`,
                                ].filter(Boolean).join(' · ');
                                return (
                                  <tr key={i}>
                                    <td>{(e as any).source_id || '—'}</td>
                                    <td>{displayEventType(e)}</td>
                                    <td>{detail || getSummary(e)}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        )}

                        {procLoading && <div className={styles.empty} style={{ marginTop: 8 }}>Loading the procurement case…</div>}

                        {/* MULTI-SUPPLIER: a bulk order that splits across suppliers opens one case per supplier,
                            each with its OWN drafted RFQ. Show them all (read-only proof) so "3 suppliers → where
                            are the emails?" is answered in-place. Single-supplier orders fall through to the rich
                            single card below. */}
                        {procCases.length > 1 && (
                          <div data-testid="proc-multi-rfq" style={{ marginTop: 10 }}>
                            <div style={{ fontWeight: 700, marginBottom: 6 }}>
                              📧 {procCases.length} supplier RFQs drafted — one per supplier · human-gated · nothing sent
                            </div>
                            {procCases.map((c: any, idx: number) => {
                              const d: any = c?.state_json?.draft || {};
                              const cp: any = d.channel_plan || {};
                              const tm: any = d.supplier_terms || {};
                              const chLabel = cp.requires_human
                                ? `${String(cp.channel || '').toUpperCase()} · human-only`
                                : cp.integration_kind
                                  ? `${String(cp.integration_kind).toUpperCase()} integration handoff`
                                  : `${String(cp.channel || 'email')} · agent drafts · human sends (GATE 2)`;
                              const terms = [
                                tm.moq != null ? `MOQ ${tm.moq}` : null,
                                tm.lead_time_days != null ? `${tm.lead_time_days}d lead` : null,
                                tm.contract_status ? String(tm.contract_status) : null,
                                (tm.price_breaks || []).length ? `breaks ${(tm.price_breaks || []).map((b: any) => `${b.min_qty}→${b.discount_pct}%`).join(',')}` : null,
                              ].filter(Boolean).join(' · ');
                              return (
                                <details key={c.case_id || idx} data-testid={`proc-rfq-${idx}`} style={{ border: '1px solid #d1d5db', borderRadius: 8, padding: '8px 10px', marginBottom: 6 }} open={idx === 0}>
                                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
                                    Supplier {idx + 1} of {procCases.length} — {d.recipient_ref || '—'}
                                    <span style={{ marginLeft: 8, fontSize: 12, color: '#6b7280' }}>{chLabel}</span>
                                  </summary>
                                  <div style={{ marginTop: 8, fontSize: 13 }}>
                                    {d.recipient_domain && <div className={styles.kvRow}><span>Domain</span><span className={styles.mono}>{d.recipient_domain}</span></div>}
                                    {terms && <div className={styles.kvRow}><span>Ordering terms</span><span>{terms}</span></div>}
                                    {cp.rationale && <div className={styles.kvRow}><span>Why this channel</span><span style={{ color: '#6b7280' }}>{cp.rationale}</span></div>}
                                    <div className={styles.kvRow}><span>Subject</span><span>{d.subject || '—'}</span></div>
                                    {canSeeOperatorDraft ? (
                                      <>
                                        <div style={{ marginTop: 6, fontWeight: 600, color: '#6b7280' }}>Body (quote request — no price is ever stated to the supplier)</div>
                                        <pre style={{ whiteSpace: 'pre-wrap', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, padding: 8, marginTop: 4, maxHeight: 220, overflow: 'auto' }}>{d.body || '(not drafted yet)'}</pre>
                                      </>
                                    ) : (
                                      <div className={styles.empty} style={{ marginTop: 6 }}>Human-gated — sign in with an operator key to view the drafted email.</div>
                                    )}
                                  </div>
                                </details>
                              );
                            })}
                          </div>
                        )}

                        {/* Drafted supplier RFQ — the "how it's made" artefact, inline + collapsed so the demo
                            never leaves this tab. Human-gated: shown only with an owner/operator key; a normal
                            shopper never sees a supplier contact (blind-ship stays intact). It is NOT sent. */}
                        {procCases.length <= 1 && procCase && draft && canSeeOperatorDraft && (
                          <details data-testid="proc-drafted-rfq" style={{ marginTop: 10, border: '1px solid #d1d5db', borderRadius: 8, padding: '8px 10px' }} open>
                            <summary style={{ cursor: 'pointer', fontWeight: 700 }}>
                              📧 Drafted supplier RFQ — {String(procCase.state || '').replace(/_/g, ' ').toLowerCase()}
                              <span style={{ marginLeft: 8, fontWeight: 600, color: '#b45309', fontSize: 12 }}>human-gated · not sent</span>
                            </summary>
                            <div style={{ marginTop: 8, fontSize: 13 }}>
                              <div className={styles.kvRow}><span>To (supplier)</span><span data-testid="proc-rfq-recipient">{draft.recipient_ref || '—'}{draft.recipient_domain ? ` · ${draft.recipient_domain}` : ''}</span></div>
                              {draft.recipient_email && <div className={styles.kvRow}><span>Contact</span><span className={styles.mono}>{draft.recipient_email}</span></div>}
                              {draft.channel_plan && (
                                <div className={styles.kvRow} data-testid="proc-supplier-channel"><span>Preferred channel</span><span>
                                  <strong>{String(draft.channel_plan.channel || 'email')}</strong>
                                  {draft.channel_plan.requires_human
                                    ? ' · human-only (no automated outreach)'
                                    : draft.channel_plan.integration_kind
                                      ? ` · ${String(draft.channel_plan.integration_kind).toUpperCase()} integration handoff`
                                      : draft.channel_plan.agent_may_draft
                                        ? ' · agent drafts · human sends (GATE 2)'
                                        : ''}
                                </span></div>
                              )}
                              {draft.channel_plan?.rationale && (
                                <div className={styles.kvRow}><span>Why this channel</span><span style={{ color: '#6b7280' }}>{draft.channel_plan.rationale}</span></div>
                              )}
                              {draft.supplier_terms && (draft.supplier_terms.moq != null || draft.supplier_terms.lead_time_days != null || (draft.supplier_terms.price_breaks || []).length > 0 || draft.supplier_terms.contract_status) && (
                                <div className={styles.kvRow} data-testid="proc-supplier-terms"><span>Ordering terms</span><span>
                                  {[
                                    draft.supplier_terms.moq != null ? `MOQ ${draft.supplier_terms.moq}` : null,
                                    draft.supplier_terms.lead_time_days != null ? `${draft.supplier_terms.lead_time_days}d lead` : null,
                                    draft.supplier_terms.min_order_value_cents ? `min $${Math.round(draft.supplier_terms.min_order_value_cents / 100)}` : null,
                                    draft.supplier_terms.contract_status ? String(draft.supplier_terms.contract_status) : null,
                                    (draft.supplier_terms.price_breaks || []).length
                                      ? `breaks: ${(draft.supplier_terms.price_breaks || []).map((b: any) => `${b.min_qty}→${b.discount_pct}%`).join(', ')}`
                                      : null,
                                  ].filter(Boolean).join(' · ')}
                                </span></div>
                              )}
                              <div className={styles.kvRow}><span>Subject</span><span data-testid="proc-rfq-subject">{draft.subject || '—'}</span></div>
                              {draft.content_hash && <div className={styles.kvRow}><span>Content hash</span><span className={styles.mono}>{draft.content_hash}</span></div>}
                              {(draft.send_gate || draft.gate) && <div className={styles.kvRow}><span>Send gate</span><span>{String(draft.send_gate?.status || draft.send_gate || draft.gate)}</span></div>}
                              <div style={{ marginTop: 6, fontWeight: 600, color: '#6b7280' }}>Body (a quote request — no price is ever stated to the supplier)</div>
                              <pre data-testid="proc-rfq-body" style={{ whiteSpace: 'pre-wrap', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, padding: 8, marginTop: 4, maxHeight: 260, overflow: 'auto' }}>{draft.body || '(not drafted yet)'}</pre>
                            </div>
                          </details>
                        )}
                        {procCases.length <= 1 && procCase && draft && !canSeeOperatorDraft && (
                          <div className={styles.empty} style={{ marginTop: 8 }}>A supplier RFQ was drafted for this order (human-gated). Sign in with an operator key to view it.</div>
                        )}
                        {/* Read-only proof surface: any change to the supplier or the drafted email happens in the
                            operator console (admin), where edits re-lock the send gate — never from this trace. */}
                        {(procCases.length > 0 || (procCase && draft)) && (
                          <div data-testid="proc-readonly-note" style={{ marginTop: 8, fontSize: 12, color: '#6b7280', borderTop: '1px dashed #e5e7eb', paddingTop: 6 }}>
                            🔒 Read-only trace — this is the audit view. To change the supplier or edit the RFQ, an
                            authorised operator does that in the admin console; any edit voids the prior approval and
                            re-locks the send gate (GATE 2). Nothing is ever sent from here.
                          </div>
                        )}

                        {/* Audit trail — the case's own bitemporal journey (state · actor · reason · time),
                            inline so the operator proves provenance without switching tabs/windows. */}
                        {procCase && Array.isArray(procJourney) && procJourney.length > 0 && (
                          <details data-testid="proc-audit-trail" style={{ marginTop: 10, border: '1px solid #d1d5db', borderRadius: 8, padding: '8px 10px' }} open>
                            <summary style={{ cursor: 'pointer', fontWeight: 700 }}>
                              🧾 Procurement audit trail <span style={{ fontWeight: 500, color: '#6b7280' }}>({procJourney.length} state transitions · bitemporal)</span>
                            </summary>
                            <table className={styles.table} style={{ marginTop: 8 }}>
                              <thead><tr><th>State</th><th>Event</th><th>Actor</th><th>When</th></tr></thead>
                              <tbody>
                                {procJourney.map((s: any, i: number) => (
                                  <tr key={i}>
                                    <td>{String(s.state || '').replace(/_/g, ' ')}</td>
                                    <td>{s.event}{s.reason_code ? ` · ${s.reason_code}` : ''}</td>
                                    <td>{s.actor_type === 'human_operator' ? '👤 ' : ''}{s.actor_id || s.actor_type || '—'}</td>
                                    <td className={styles.mono} style={{ fontSize: 11 }}>{String(s.valid_from || '').replace('T', ' ').slice(0, 19)}{s.valid_to == null ? ' · current' : ''}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {money(procCase?.state_json?.split?.subtotal_cents) && (
                              <div className={styles.kvRow} style={{ marginTop: 6 }}><span>Order subtotal</span><span>{money(procCase.state_json.split.subtotal_cents)}</span></div>
                            )}
                          </details>
                        )}
                      </>
                    );
                  })()}
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
                      <div className={styles.kvRow}><span>Chain Verified</span><span>{auditTrail.immutability?.verified ? '\u2705 Yes' : '\u26a0\ufe0f Not in this environment'}</span></div>
                      {auditTrail.immutability?.reason && (
                        <div className={styles.kvRow}><span>Why</span><span style={{ fontSize: 12, color: '#6b7280' }}>{auditTrail.immutability.reason}</span></div>
                      )}
                      {auditTrail.immutability?.persisted_chain && (
                        <div className={styles.kvRow}><span>Persisted WORM chain</span><span style={{ fontSize: 12 }}>
                          {auditTrail.immutability.persisted_chain.entries_checked} entries \u00b7 anchor {auditTrail.immutability.persisted_chain.anchor_present ? 'present' : 'pending'}
                        </span></div>
                      )}

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
                <>
                  {explainReplayLoading && <div className={styles.muted}>Loading replay payload...</div>}
                  {replay && (
                    <>
                      <div className={styles.sectionTitle}>Replay</div>
                      <pre className={styles.rawJson}>{JSON.stringify(replay, null, 2)}</pre>
                    </>
                  )}
                  <div className={styles.sectionTitle}>Trace Payload</div>
                  <pre className={styles.rawJson}>{JSON.stringify(trace, null, 2)}</pre>
                </>
              )}

              {!trace && (
                <div className={styles.empty}>
                  {traceIdText
                    ? `Trace snapshot is not available yet for ${traceIdText}.`
                    : 'No backend trace id is available yet. Showing local image triage only.'}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}




