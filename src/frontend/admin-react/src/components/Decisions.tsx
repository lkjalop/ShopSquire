import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchDecisions,
  fetchDecisionsFiltered,
  type DecisionRow,
  approveDecision,
  rejectDecision,
  reopenDecision,
  fetchFlags,
  fetchDecisionTraceQuery,
  fetchDecisionCausal,
  fetchInterleavingSummary,
  type DecisionTraceEvent,
  type DecisionTraceQuery,
  type DecisionCausalGraph,
} from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };
type TraceTab = 'summary' | 'agents' | 'timeline' | 'causal' | 'raw';
type EventCategory =
  | 'Security'
  | 'Policy'
  | 'Recommendation'
  | 'Fraud'
  | 'Inventory'
  | 'Execution'
  | 'Feedback'
  | 'Other';

const CATEGORY_ORDER: EventCategory[] = ['Security', 'Policy', 'Recommendation', 'Fraud', 'Inventory', 'Execution', 'Feedback', 'Other'];
const TAXONOMY_HINT = 'security_scan -> intent_classify -> constraint_parse -> candidate_retrieve -> candidate_rerank -> cv_analysis -> fraud_score -> inventory_check -> tier_decision -> policy_verdict -> ab_assignment -> proposal_build -> execution_result -> feedback_loop';

const CANONICAL_CATEGORY_MAP: Record<string, EventCategory> = {
  security_scan: 'Security',
  intent_classify: 'Recommendation',
  constraint_parse: 'Policy',
  candidate_retrieve: 'Recommendation',
  candidate_rerank: 'Recommendation',
  cv_analysis: 'Execution',
  fraud_score: 'Fraud',
  inventory_check: 'Inventory',
  tier_decision: 'Policy',
  policy_verdict: 'Policy',
  ab_assignment: 'Recommendation',
  proposal_build: 'Recommendation',
  execution_result: 'Execution',
  feedback_loop: 'Feedback',
  synthesis_reasoning: 'Policy',
};

type StructuredSections = {
  signals: Record<string, any>;
  policyChecks: Record<string, any>;
  actions: Record<string, any>;
  outcome: Record<string, any>;
  evidence: Record<string, any>;
  traceMeta: Record<string, any>;
};

type Neo4jRingSignal = {
  eventId: string;
  eventType: string;
  source: string;
  createdAt: string;
  clusterSize: number | null;
  ringRisk: number | null;
  ringHit: boolean;
};

function parseMaybeJson(value: unknown): any {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function normalizedEventType(ev: DecisionTraceEvent): string {
  const p = ev.payload;
  if (p && typeof p === 'object' && typeof p._event_type === 'string') return p._event_type;
  return (ev.event_type || '').toLowerCase();
}

function toEventCategory(eventType?: string): EventCategory {
  const t = (eventType || '').toLowerCase().trim();
  if (CANONICAL_CATEGORY_MAP[t]) return CANONICAL_CATEGORY_MAP[t];
  if (t.includes('security') || t.includes('owasp') || t.includes('threat')) return 'Security';
  if (t.includes('policy') || t.includes('constraint') || t.includes('tier_decision')) return 'Policy';
  if (t.includes('candidate') || t.includes('intent') || t.includes('proposal') || t.includes('recommend')) return 'Recommendation';
  if (t.includes('fraud') || t.includes('abuse') || t.includes('ato')) return 'Fraud';
  if (t.includes('inventory') || t.includes('stock') || t.includes('restock')) return 'Inventory';
  if (t.includes('execution') || t.includes('tool') || t.includes('model') || t.includes('action')) return 'Execution';
  if (t.includes('feedback') || t.includes('posthoc') || t.includes('label')) return 'Feedback';
  return 'Other';
}

function formatEventTime(input?: string): string {
  if (!input) return '-';
  const d = new Date(input);
  if (Number.isNaN(d.getTime())) return String(input);
  return d.toLocaleString();
}

function extractLatencyMs(payload: any): number | null {
  if (!payload || typeof payload !== 'object') return null;
  const raw = payload.latency_ms;
  if (typeof raw === 'number' && Number.isFinite(raw)) return Math.round(raw);
  if (typeof raw === 'string') {
    const n = Number(raw);
    if (Number.isFinite(n)) return Math.round(n);
  }
  return null;
}

function extractVerdict(payload: any): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const candidate = payload.verdict ?? payload.decision ?? payload.status ?? payload.action ?? payload.outcome;
  return candidate ? String(candidate) : null;
}

function extractConfidence(payload: any): number | null {
  if (!payload || typeof payload !== 'object') return null;
  const raw = payload.confidence ?? payload.confidence_calibrated ?? payload.score ?? payload.risk_score;
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string') {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function extractStructuredSections(payload: any): StructuredSections {
  const p = payload && typeof payload === 'object' ? payload : {};
  const signals: Record<string, any> = {};
  const policyChecks: Record<string, any> = {};
  const actions: Record<string, any> = {};
  const outcome: Record<string, any> = {};
  const evidence: Record<string, any> = {};
  const traceMeta: Record<string, any> = {};
  const assignSubset = (target: Record<string, any>, keys: string[]) => {
    for (const k of keys) {
      if (p[k] !== undefined) target[k] = p[k];
    }
  };
  assignSubset(signals, [
    'risk_score',
    'risk_band',
    'tags',
    'mitre',
    'severity',
    'latency_ms',
    'signals',
    'shipping_address_clustered',
    'shipping_address_cluster_size',
    'neo4j_cluster_size',
    'ring_risk',
    'neo4j_ring_risk',
    'ring_hit',
  ]);
  assignSubset(policyChecks, ['policy', 'policy_gate', 'tier', 'constraints', 'compliance', 'approval_required']);
  assignSubset(actions, ['action', 'actions', 'tool', 'tool_name', 'ticket_id', 'proposal', 'playbook_id']);
  assignSubset(outcome, ['verdict', 'decision', 'status', 'result', 'executed', 'error', 'reason']);
  assignSubset(evidence, ['evidence', 'evidence_items', 'evidence_tags', 'reasons', 'trace_refs']);
  assignSubset(traceMeta, ['trace_tags', 'strategy_tags', 'decision_tags', 'drilldown_hidden_tags', 'hidden_drilldown', 'trace_hidden']);
  return { signals, policyChecks, actions, outcome, evidence, traceMeta };
}

function readNum(v: any): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string') {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function extractNeo4jSignal(ev: DecisionTraceEvent & { normalizedType?: string }): Neo4jRingSignal | null {
  const p = (ev.payload && typeof ev.payload === 'object') ? ev.payload : {};
  const nestedSignals = (p.signals && typeof p.signals === 'object') ? p.signals : {};
  const clusterSize = readNum(
    p.neo4j_cluster_size ??
    p.shipping_address_cluster_size ??
    p.cluster_size ??
    nestedSignals.neo4j_cluster_size ??
    nestedSignals.shipping_address_cluster_size ??
    nestedSignals.cluster_size
  );
  const ringRisk = readNum(
    p.neo4j_ring_risk ??
    p.ring_risk ??
    nestedSignals.neo4j_ring_risk ??
    nestedSignals.ring_risk
  );
  const explicitRingHit = (p.ring_hit ?? p.shipping_address_clustered ?? nestedSignals.ring_hit ?? nestedSignals.shipping_address_clustered);
  const ringHit = typeof explicitRingHit === 'boolean'
    ? explicitRingHit
    : Boolean((clusterSize ?? 0) >= 4 || (ringRisk ?? 0) >= 0.65);
  if (clusterSize === null && ringRisk === null && !ringHit) return null;
  return {
    eventId: String(ev.id || ''),
    eventType: String(ev.normalizedType || ev.event_type || 'event'),
    source: String(ev.source_id || ev.source_type || 'unknown'),
    createdAt: String(ev.created_at || ''),
    clusterSize,
    ringRisk,
    ringHit,
  };
}

export function Decisions({ role }: Props) {
  const [selected, setSelected] = useState<DecisionRow | null>(null);
  const [rows, setRows] = useState<DecisionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flags, setFlags] = useState<Record<string, any> | null>(null);
  const [agent, setAgent] = useState('');
  const [tab, setTab] = useState<TraceTab>('summary');
  const [trace, setTrace] = useState<DecisionTraceQuery | null>(null);
  const [causal, setCausal] = useState<DecisionCausalGraph | null>(null);
  const [interleavingSummary, setInterleavingSummary] = useState<any | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<'All' | EventCategory>('All');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [focusedEventId, setFocusedEventId] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFlags().then((f) => { if (!cancelled) setFlags(f); }).catch(() => { if (!cancelled) setFlags(null); });
    fetchDecisions()
      .then((r) => { if (!cancelled) setRows(r); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selected?.id) {
      setTrace(null);
      setCausal(null);
      setInterleavingSummary(null);
      return;
    }
    let cancelled = false;
    setTab('summary');
    setTraceLoading(true);
    setTraceError(null);
    setExpandedEventId(null);
    setFocusedEventId(null);
    Promise.allSettled([
      fetchDecisionTraceQuery(selected.id),
      fetchDecisionCausal(selected.id),
      fetchInterleavingSummary(selected.id),
    ])
      .then((results) => {
        if (cancelled) return;
        const [traceRes, causalRes, interRes] = results;
        if (traceRes.status === 'fulfilled') {
          setTrace(traceRes.value);
        } else {
          setTraceError(traceRes.reason?.message || 'Failed to load trace details');
          setTrace(null);
        }
        setCausal(causalRes.status === 'fulfilled' ? causalRes.value : null);
        setInterleavingSummary(interRes.status === 'fulfilled' ? (interRes.value?.summary || null) : null);
      })
      .finally(() => {
        if (!cancelled) setTraceLoading(false);
      });
    return () => { cancelled = true; };
  }, [selected?.id]);

  const traceEvents = useMemo(() => (trace?.events || []) as DecisionTraceEvent[], [trace?.events]);

  const categorizedEvents = useMemo(() => {
    return traceEvents.map((ev) => {
      const normalizedType = normalizedEventType(ev);
      return { ...ev, normalizedType, category: toEventCategory(normalizedType || ev.event_type) };
    });
  }, [traceEvents]);

  const filteredTimelineEvents = useMemo(() => {
    if (categoryFilter === 'All') return categorizedEvents;
    return categorizedEvents.filter((ev) => ev.category === categoryFilter);
  }, [categorizedEvents, categoryFilter]);

  const eventCategoryCounts = useMemo(() => {
    const out: Record<EventCategory, number> = {
      Security: 0,
      Policy: 0,
      Recommendation: 0,
      Fraud: 0,
      Inventory: 0,
      Execution: 0,
      Feedback: 0,
      Other: 0,
    };
    for (const ev of categorizedEvents) out[ev.category] += 1;
    return out;
  }, [categorizedEvents]);

  const complianceGovernance = useMemo(() => {
    const tags = new Set<string>();
    const governance = new Set<string>();
    let llmTierEvents = 0;
    let humanFallbacks = 0;
    for (const ev of categorizedEvents) {
      const p = (ev.payload && typeof ev.payload === 'object') ? ev.payload : {};
      const arrays = [p.compliance_tags, p.trace_tags, p.strategy_tags, p.decision_tags];
      for (const arr of arrays) {
        if (!Array.isArray(arr)) continue;
        for (const item of arr) {
          const s = String(item || '').trim();
          if (!s) continue;
          tags.add(s);
          if (s.startsWith('gdpr:') || s.startsWith('privacy:') || s.startsWith('slsa:') || s.startsWith('platform:')) {
            governance.add(s);
          }
        }
      }
      if (String(p.model_tier || '').trim()) llmTierEvents += 1;
      const decision = String(p.decision || p.verdict || p.status || '').toLowerCase();
      if (decision.includes('human') || decision.includes('review') || decision.includes('fallback')) {
        humanFallbacks += 1;
      }
    }
    return {
      tags: Array.from(tags).sort(),
      governance: Array.from(governance).sort(),
      llmTierEvents,
      humanFallbacks,
    };
  }, [categorizedEvents]);

  const agentSummaries = useMemo(() => {
    const grouped = new Map<string, {
      agent: string;
      events: number;
      lastEvent: string;
      categories: Set<EventCategory>;
      latencyTotal: number;
      latencyCount: number;
      verdicts: string[];
      confidence: number[];
      evidenceCount: number;
    }>();
    for (const ev of categorizedEvents) {
      const agentKey = (ev.source_id || ev.source_type || 'unknown_agent').toString();
      const current = grouped.get(agentKey) || {
        agent: agentKey,
        events: 0,
        lastEvent: '-',
        categories: new Set<EventCategory>(),
        latencyTotal: 0,
        latencyCount: 0,
        verdicts: [],
        confidence: [],
        evidenceCount: 0,
      };
      current.events += 1;
      current.lastEvent = ev.normalizedType || ev.event_type || current.lastEvent;
      current.categories.add(ev.category);
      const latency = extractLatencyMs(ev.payload);
      if (latency !== null) {
        current.latencyTotal += latency;
        current.latencyCount += 1;
      }
      const verdict = extractVerdict(ev.payload);
      if (verdict) current.verdicts.push(verdict);
      const conf = extractConfidence(ev.payload);
      if (conf !== null) current.confidence.push(conf);
      const sections = extractStructuredSections(ev.payload);
      if (Object.keys(sections.evidence).length > 0) current.evidenceCount += 1;
      grouped.set(agentKey, current);
    }
    return Array.from(grouped.values())
      .map((s) => ({
        agent: s.agent,
        events: s.events,
        lastEvent: s.lastEvent,
        categories: Array.from(s.categories).sort(),
        avgLatencyMs: s.latencyCount > 0 ? Math.round(s.latencyTotal / s.latencyCount) : null,
        latestVerdict: s.verdicts.length ? s.verdicts[s.verdicts.length - 1] : null,
        avgConfidence: s.confidence.length ? Math.round((s.confidence.reduce((a, b) => a + b, 0) / s.confidence.length) * 1000) / 1000 : null,
        evidenceEvents: s.evidenceCount,
      }))
      .sort((a, b) => b.events - a.events);
  }, [categorizedEvents]);

  const conflictSummary = useMemo(() => {
    const byEventType = new Map<string, Map<string, string>>();
    for (const ev of categorizedEvents) {
      const t = ev.normalizedType || ev.event_type || 'event';
      const agentKey = (ev.source_id || ev.source_type || 'unknown_agent').toString();
      const verdict = extractVerdict(ev.payload);
      if (!verdict) continue;
      const m = byEventType.get(t) || new Map<string, string>();
      m.set(agentKey, verdict);
      byEventType.set(t, m);
    }
    const rows: Array<{ eventType: string; verdicts: string[]; byAgent: Array<{ agent: string; verdict: string }> }> = [];
    byEventType.forEach((m, t) => {
      const values = Array.from(new Set(Array.from(m.values())));
      if (values.length > 1) {
        rows.push({
          eventType: t,
          verdicts: values,
          byAgent: Array.from(m.entries()).map(([agent, verdict]) => ({ agent, verdict })),
        });
      }
    });
    return rows;
  }, [categorizedEvents]);

  const killChainSummary = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const ev of categorizedEvents) {
      const p = (ev.payload && typeof ev.payload === 'object') ? ev.payload : {};
      const stage = String(p.kill_chain_stage || p.stage || '').trim();
      if (!stage) continue;
      counts[stage] = (counts[stage] || 0) + 1;
    }
    return counts;
  }, [categorizedEvents]);

  const neo4jSignals = useMemo(() => {
    return categorizedEvents
      .map((ev) => extractNeo4jSignal(ev))
      .filter((s): s is Neo4jRingSignal => !!s);
  }, [categorizedEvents]);

  const neo4jSummary = useMemo(() => {
    const maxRisk = neo4jSignals.reduce((m, s) => Math.max(m, s.ringRisk ?? 0), 0);
    const maxCluster = neo4jSignals.reduce((m, s) => Math.max(m, s.clusterSize ?? 0), 0);
    const ringHits = neo4jSignals.filter((s) => s.ringHit).length;
    return { maxRisk, maxCluster, ringHits };
  }, [neo4jSignals]);

  const causalLayout = useMemo(() => {
    const nodes = causal?.nodes || [];
    const edges = causal?.edges || [];
    const laneMap: Record<EventCategory, number> = {
      Security: 0,
      Policy: 1,
      Recommendation: 2,
      Fraud: 3,
      Inventory: 4,
      Execution: 5,
      Feedback: 6,
      Other: 7,
    };
    const nodePos = new Map<string, { x: number; y: number; category: EventCategory }>();
    nodes.forEach((n, i) => {
      const category = toEventCategory((n.event_type || '').toLowerCase());
      const x = 80 + i * 150;
      const y = 40 + laneMap[category] * 64;
      nodePos.set(n.id, { x, y, category });
    });
    const width = Math.max(720, 180 + nodes.length * 150);
    const height = 560;
    return { nodes, edges, nodePos, width, height };
  }, [causal]);

  const causalFocus = useMemo(() => {
    const edges = causal?.edges || [];
    const upstream = new Set<string>();
    const downstream = new Set<string>();
    if (!focusedEventId) return { upstream, downstream, highlighted: new Set<string>(), highlightedEdges: new Set<string>() };
    const parents = new Map<string, string[]>();
    const children = new Map<string, string[]>();
    for (const e of edges) {
      if (!parents.has(e.to)) parents.set(e.to, []);
      if (!children.has(e.from)) children.set(e.from, []);
      parents.get(e.to)!.push(e.from);
      children.get(e.from)!.push(e.to);
    }
    const walk = (start: string, nextMap: Map<string, string[]>, bucket: Set<string>) => {
      const q = [start];
      const seen = new Set<string>([start]);
      while (q.length > 0) {
        const cur = q.shift()!;
        for (const nxt of nextMap.get(cur) || []) {
          if (!seen.has(nxt)) {
            seen.add(nxt);
            bucket.add(nxt);
            q.push(nxt);
          }
        }
      }
    };
    walk(focusedEventId, parents, upstream);
    walk(focusedEventId, children, downstream);
    const highlighted = new Set<string>([focusedEventId, ...Array.from(upstream), ...Array.from(downstream)]);
    const highlightedEdges = new Set<string>();
    for (const e of edges) {
      if (highlighted.has(e.from) && highlighted.has(e.to)) highlightedEdges.add(`${e.from}->${e.to}`);
    }
    return { upstream, downstream, highlighted, highlightedEdges };
  }, [causal?.edges, focusedEventId]);

  useEffect(() => {
    if (tab !== 'timeline' || !expandedEventId) return;
    const el = rowRefs.current[expandedEventId];
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [tab, expandedEventId]);

  return (
    <div className="stagger">
      <div className="panel" style={{ marginBottom: 12 }}>
        <strong>Filters</strong>
        <div className="page-sub" style={{ marginTop: 8 }}>
          <input
            className="modal-input"
            placeholder="Agent name (optional)"
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            style={{ maxWidth: 240, marginRight: 8 }}
          />
          <button
            className="btn secondary"
            onClick={async () => {
              setLoading(true);
              setError(null);
              try {
                const filtered = agent ? await fetchDecisionsFiltered({ agent }) : await fetchDecisions();
                setRows(filtered);
              } catch (e: any) {
                setError(e.message || 'Failed to filter');
              } finally {
                setLoading(false);
              }
            }}
          >
            Apply
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Decision Logs</h3>
        {loading && <div className="page-sub">Loading...</div>}
        {error && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {error}</div>}
        <table className="table">
          <thead>
            <tr>
              <th>Trace</th>
              <th>Status</th>
              <th>Agent</th>
              <th>Action</th>
              <th>Time</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id}>
                <td style={{ fontFamily: 'monospace' }}>{d.id}</td>
                <td>{d.execution_status}</td>
                <td>{d.agent_name}</td>
                <td>{(() => { try { const a = typeof d.proposed_action === 'string' ? JSON.parse(d.proposed_action) : d.proposed_action; return a?.decision_mode || 'action'; } catch { return 'action'; } })()}</td>
                <td>{d.valid_from || ''}</td>
                <td><button className="btn secondary" onClick={() => setSelected(d)}>View</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>Decision Trace</h3>
          <div className="page-sub" style={{ marginBottom: 10 }}>
            Trace ID: <code>{selected.id}</code>
          </div>
          <div className="trace-tabs">
            <button className={`trace-tab ${tab === 'summary' ? 'active' : ''}`} onClick={() => setTab('summary')}>Summary</button>
            <button className={`trace-tab ${tab === 'agents' ? 'active' : ''}`} onClick={() => setTab('agents')}>Agents</button>
            <button className={`trace-tab ${tab === 'timeline' ? 'active' : ''}`} onClick={() => setTab('timeline')}>Timeline</button>
            <button className={`trace-tab ${tab === 'causal' ? 'active' : ''}`} onClick={() => setTab('causal')}>Causal</button>
            <button className={`trace-tab ${tab === 'raw' ? 'active' : ''}`} onClick={() => setTab('raw')}>Raw</button>
          </div>
          {traceLoading && <div className="page-sub" style={{ marginTop: 10 }}>Loading trace details...</div>}
          {traceError && <div className="page-sub" style={{ color: '#9f2d1b', marginTop: 10 }}>{traceError}</div>}

          {tab === 'summary' && (
            <>
              <div className="grid-4" style={{ marginTop: 12 }}>
                <div className="panel"><strong>{categorizedEvents.length}</strong><div className="page-sub">Total Events</div></div>
                <div className="panel"><strong>{agentSummaries.length}</strong><div className="page-sub">Agents Involved</div></div>
                <div className="panel"><strong>{interleavingSummary?.tier ?? '-'}</strong><div className="page-sub">Tier</div></div>
                <div className="panel"><strong>{interleavingSummary?.tool_budget_remaining ?? '-'}</strong><div className="page-sub">Tool Budget Left</div></div>
              </div>
              <div className="trace-chip-row" style={{ marginTop: 10 }}>
                {CATEGORY_ORDER.map((category) => (
                  <span key={category} className="trace-chip">
                    {category}: {eventCategoryCounts[category]}
                  </span>
                ))}
              </div>
              {conflictSummary.length > 0 && (
                <div className="panel" style={{ marginTop: 10 }}>
                  <strong>Conflict Resolution</strong>
                  <div className="page-sub">Agents disagreed on these stages. Use synthesis reasoning and policy verdict events to verify final resolution.</div>
                  <div className="list">
                    {conflictSummary.map((c) => (
                      <div key={c.eventType} className="list-item">
                        <div>
                          <strong>{c.eventType}</strong>
                          <div className="page-sub">{c.byAgent.map((r) => `${r.agent}:${r.verdict}`).join(' | ')}</div>
                        </div>
                        <span className="badge">{c.verdicts.join(' vs ')}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {Object.keys(killChainSummary).length > 0 && (
                <div className="panel" style={{ marginTop: 10 }}>
                  <strong>Kill Chain Progression</strong>
                  <div className="trace-chip-row" style={{ marginTop: 8 }}>
                    {Object.entries(killChainSummary).map(([k, v]) => (
                      <span key={k} className="trace-chip">{k}: {v}</span>
                    ))}
                  </div>
                </div>
              )}
              {neo4jSignals.length > 0 && (
                <div className="panel" style={{ marginTop: 10 }}>
                  <strong>Neo4j Ring Drilldown</strong>
                  <div className="page-sub">
                    Ring-hit events: {neo4jSummary.ringHits} | Max cluster: {neo4jSummary.maxCluster || '-'} | Max ring risk: {neo4jSummary.maxRisk ? neo4jSummary.maxRisk.toFixed(3) : '-'}
                  </div>
                  <div className="list">
                    {neo4jSignals.slice(0, 8).map((s) => (
                      <div key={`neo4j-${s.eventId}`} className="list-item">
                        <div>
                          <strong>{s.eventType}</strong>
                          <div className="page-sub">{formatEventTime(s.createdAt)} | {s.source}</div>
                        </div>
                        <span className="badge">
                          cluster={s.clusterSize ?? '-'} | risk={s.ringRisk !== null ? s.ringRisk.toFixed(3) : '-'} | hit={s.ringHit ? 'yes' : 'no'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="panel" style={{ marginTop: 10 }}>
                <strong>Compliance & Governance</strong>
                <div className="page-sub">
                  LLM-tier events: {complianceGovernance.llmTierEvents} | Human-review/fallback events: {complianceGovernance.humanFallbacks}
                </div>
                <div className="trace-chip-row" style={{ marginTop: 8 }}>
                  {(complianceGovernance.governance.length > 0 ? complianceGovernance.governance : complianceGovernance.tags.slice(0, 16)).map((t) => (
                    <span key={`gov-${t}`} className="trace-chip">{t}</span>
                  ))}
                </div>
              </div>
              <div style={{ marginTop: 12 }}>
                <strong>Decision Snapshot</strong>
                <div className="split">
                  <pre className="panel">{JSON.stringify(trace?.recommendation || parseMaybeJson(selected.proposed_action) || {}, null, 2)}</pre>
                  <pre className="panel">{JSON.stringify(trace?.policy_gates || {}, null, 2)}</pre>
                </div>
              </div>
              <div className="callout" style={{ marginTop: 10 }}>
                Taxonomy target: {TAXONOMY_HINT}
              </div>
            </>
          )}

          {tab === 'agents' && (
            <div className="trace-agent-grid" style={{ marginTop: 12 }}>
              {agentSummaries.length === 0 && <div className="page-sub">No agent events found in this trace.</div>}
              {agentSummaries.map((agentSummary) => (
                <div key={agentSummary.agent} className="trace-agent-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                    <strong style={{ fontFamily: 'monospace' }}>{agentSummary.agent}</strong>
                    <span className="badge">{agentSummary.events} events</span>
                  </div>
                  <div className="page-sub" style={{ marginTop: 8 }}>Last event: {agentSummary.lastEvent}</div>
                  <div className="page-sub">Avg latency: {agentSummary.avgLatencyMs !== null ? `${agentSummary.avgLatencyMs} ms` : '-'}</div>
                  <div className="page-sub">Verdict: {agentSummary.latestVerdict || '-'}</div>
                  <div className="page-sub">Confidence: {agentSummary.avgConfidence !== null ? agentSummary.avgConfidence : '-'}</div>
                  <div className="page-sub">Evidence events: {agentSummary.evidenceEvents}</div>
                  <div className="trace-chip-row" style={{ marginTop: 8 }}>
                    {agentSummary.categories.map((c) => <span className="trace-chip" key={`${agentSummary.agent}-${c}`}>{c}</span>)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'timeline' && (
            <div style={{ marginTop: 12 }}>
              <div className="trace-chip-row" style={{ marginBottom: 10 }}>
                <button className={`trace-chip-btn ${categoryFilter === 'All' ? 'active' : ''}`} onClick={() => setCategoryFilter('All')}>All ({categorizedEvents.length})</button>
                {CATEGORY_ORDER.map((category) => (
                  <button key={category} className={`trace-chip-btn ${categoryFilter === category ? 'active' : ''}`} onClick={() => setCategoryFilter(category)}>
                    {category} ({eventCategoryCounts[category]})
                  </button>
                ))}
              </div>
              <div className="trace-timeline">
                {filteredTimelineEvents.length === 0 && <div className="page-sub">No events for this category.</div>}
                {filteredTimelineEvents.map((ev) => {
                  const expanded = expandedEventId === ev.id;
                  const isFocused = focusedEventId === ev.id;
                  const isRelated = !!ev.id && causalFocus.highlighted.has(ev.id);
                  const sections = extractStructuredSections(ev.payload);
                  const payloadObj = (ev.payload && typeof ev.payload === 'object') ? ev.payload : {};
                  const traceTags = (() => {
                    const tags: string[] = [];
                    for (const k of ['trace_tags', 'strategy_tags', 'decision_tags']) {
                      const vals = payloadObj[k];
                      if (!Array.isArray(vals)) continue;
                      for (const v of vals) {
                        const s = String(v || '').trim();
                        if (s && !tags.includes(s)) tags.push(s);
                      }
                    }
                    return tags;
                  })();
                  const hiddenDrilldown = payloadObj.drilldown_hidden_tags || payloadObj.hidden_drilldown || payloadObj.trace_hidden || null;
                  return (
                    <div
                      key={ev.id}
                      ref={(el) => { if (ev.id) rowRefs.current[ev.id] = el; }}
                      className={`trace-event-row ${isFocused ? 'focused' : ''} ${isRelated ? 'related' : ''}`}
                    >
                      <div className="trace-event-head">
                        <div>
                          <span className="badge">{ev.category}</span>{' '}
                          <strong>{ev.normalizedType || ev.event_type || 'event'}</strong>{' '}
                          <span className="page-sub">{formatEventTime(ev.created_at)}</span>
                        </div>
                        <button className="btn secondary" onClick={() => { setExpandedEventId(expanded ? null : ev.id); setFocusedEventId(expanded ? null : (ev.id || null)); }}>
                          {expanded ? 'Hide details' : 'Show details'}
                        </button>
                      </div>
                      <div className="page-sub">
                        Source: <code>{ev.source_id || ev.source_type || 'unknown'}</code>
                        {extractLatencyMs(ev.payload) !== null ? ` | Latency: ${extractLatencyMs(ev.payload)} ms` : ''}
                        {extractVerdict(ev.payload) ? ` | Verdict: ${extractVerdict(ev.payload)}` : ''}
                        {(() => {
                          const n = extractNeo4jSignal(ev);
                          if (!n) return '';
                          return ` | Neo4j cluster: ${n.clusterSize ?? '-'} | ring risk: ${n.ringRisk !== null ? n.ringRisk.toFixed(3) : '-'} | ring hit: ${n.ringHit ? 'yes' : 'no'}`;
                        })()}
                      </div>
                      {traceTags.length > 0 && (
                        <div className="trace-chip-row" style={{ marginTop: 6 }}>
                          {traceTags.map((t) => <span key={`${ev.id}-${t}`} className="trace-chip">{t}</span>)}
                        </div>
                      )}
                      {expanded && (
                        <div className="split" style={{ marginTop: 8 }}>
                          <pre className="panel"><strong>Signals</strong>{'\n'}{JSON.stringify(sections.signals, null, 2)}</pre>
                          <pre className="panel"><strong>Policy checks</strong>{'\n'}{JSON.stringify(sections.policyChecks, null, 2)}</pre>
                          <pre className="panel"><strong>Actions</strong>{'\n'}{JSON.stringify(sections.actions, null, 2)}</pre>
                          <pre className="panel"><strong>Outcome</strong>{'\n'}{JSON.stringify(sections.outcome, null, 2)}</pre>
                          <pre className="panel"><strong>Evidence</strong>{'\n'}{JSON.stringify(sections.evidence, null, 2)}</pre>
                          <pre className="panel"><strong>Trace tags (hidden drilldown)</strong>{'\n'}{JSON.stringify(sections.traceMeta, null, 2)}</pre>
                          {hiddenDrilldown && (
                            <pre className="panel"><strong>Hidden drilldown domains</strong>{'\n'}{JSON.stringify(hiddenDrilldown, null, 2)}</pre>
                          )}
                          <pre className="panel"><strong>Raw</strong>{'\n'}{JSON.stringify(ev.payload || {}, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {tab === 'causal' && (
            <div style={{ marginTop: 12 }}>
              {!causal || !causal.nodes || causal.nodes.length === 0 ? (
                <div className="page-sub">No causal graph data found for this trace.</div>
              ) : (
                <div className="trace-causal-wrap">
                  <svg width={causalLayout.width} height={causalLayout.height}>
                    {causalLayout.edges.map((edge, i) => {
                      const from = causalLayout.nodePos.get(edge.from);
                      const to = causalLayout.nodePos.get(edge.to);
                      if (!from || !to) return null;
                      const edgeKey = `${edge.from}->${edge.to}`;
                      const highlighted = causalFocus.highlightedEdges.has(edgeKey);
                      return (
                        <line
                          key={`${edge.from}-${edge.to}-${i}`}
                          x1={from.x + 32}
                          y1={from.y}
                          x2={to.x - 32}
                          y2={to.y}
                          stroke={highlighted ? '#1f4f8f' : edge.type === 'causal_parent' ? '#cc5b2c' : '#2a6d6b'}
                          strokeWidth={highlighted ? 3 : 2}
                          opacity={highlighted ? 1 : 0.45}
                        />
                      );
                    })}
                    {causalLayout.nodes.map((node) => {
                      const pos = causalLayout.nodePos.get(node.id);
                      if (!pos) return null;
                      const focused = focusedEventId === node.id;
                      const related = causalFocus.highlighted.has(node.id);
                      return (
                        <g
                          key={node.id}
                          onClick={() => {
                            setFocusedEventId(node.id);
                            setExpandedEventId(node.id);
                            setCategoryFilter('All');
                            setTab('timeline');
                          }}
                          style={{ cursor: 'pointer' }}
                        >
                          <circle cx={pos.x} cy={pos.y} r={18} fill={focused ? '#ffe7db' : related ? '#e9f4f4' : '#fff'} stroke={focused ? '#1f4f8f' : '#cc5b2c'} strokeWidth={focused ? 3 : 2} />
                          <text x={pos.x + 26} y={pos.y + 4} fontSize="11" fill="#1a1b1f">
                            {(node.event_type || 'event').slice(0, 24)}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>
              )}
              {focusedEventId && (
                <div className="panel" style={{ marginTop: 10 }}>
                  <strong>Focused Node</strong>
                  <div className="page-sub">Event: <code>{focusedEventId}</code></div>
                  <div className="page-sub">Upstream: {causalFocus.upstream.size} | Downstream: {causalFocus.downstream.size}</div>
                  <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => { setTab('timeline'); setExpandedEventId(focusedEventId); }}>
                    Open in Timeline
                  </button>
                </div>
              )}
            </div>
          )}

          {tab === 'raw' && (
            <div style={{ marginTop: 12 }}>
              <strong>Trace Query</strong>
              <pre className="panel">{JSON.stringify(trace, null, 2)}</pre>
              <strong>Causal</strong>
              <pre className="panel">{JSON.stringify(causal, null, 2)}</pre>
              <strong>Interleaving</strong>
              <pre className="panel">{JSON.stringify(interleavingSummary, null, 2)}</pre>
            </div>
          )}

          <div className="list">
            <div className="list-item">
              <div>ID</div>
              <strong>{selected.id}</strong>
            </div>
            <div className="list-item">
              <div>Agent</div>
              <strong>{selected.agent_name}</strong>
            </div>
            <div className="list-item">
              <div>Status</div>
              <strong>{selected.execution_status}</strong>
            </div>
            <div className="list-item">
              <div>Policy</div>
              <strong>{selected.policy_version}</strong>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <strong>Input</strong>
            <pre className="panel">{typeof selected.input_data === 'string' ? selected.input_data : JSON.stringify(selected.input_data, null, 2)}</pre>
          </div>
          {flags?.DECISION_LOG_WRITES_ENABLED && (
            <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
              <button className="btn" onClick={async () => {
                const name = prompt('Approver name');
                if (!name) return;
                try { await approveDecision(selected.id, name); alert('Approved'); } catch (e: any) { alert(`Error: ${e.message || e}`); }
              }}>Approve</button>
              <button className="btn" onClick={async () => {
                const name = prompt('Actor name');
                if (!name) return;
                const reason = prompt('Reason for rejection') || '';
                try { await rejectDecision(selected.id, name, reason); alert('Rejected'); } catch (e: any) { alert(`Error: ${e.message || e}`); }
              }}>Reject</button>
              <button className="btn" onClick={async () => {
                const name = prompt('Actor name');
                if (!name) return;
                const comment = prompt('Reopen comment') || '';
                try { await reopenDecision(selected.id, name, comment); alert('Reopened'); } catch (e: any) { alert(`Error: ${e.message || e}`); }
              }}>Reopen</button>
            </div>
          )}
        </div>
      )}

      {role === 'developer' && (
        <div className="callout" style={{ marginTop: 12 }}>
          Developer note: export raw decision payloads from the API console to build automated QA tests.
        </div>
      )}
    </div>
  );
}
