export type DecisionRow = {
  id: string;
  agent_name: string;
  valid_from?: string;
  valid_to?: string | null;
  system_from?: string;
  system_to?: string | null;
  input_data?: any;
  proposed_action?: any;
  policy_version?: string;
  approval_required?: boolean;
  execution_status?: string;
};

export type ApprovalItem = {
  id: string;
  capability: string;
  payload: any;
  reason?: string | null;
  status: 'pending' | 'approved' | 'rejected';
  created_at?: string;
};

const API_BASE = (import.meta.env.VITE_API_BASE as string) || window.location.origin;
const API_KEY_ENV = (import.meta.env.VITE_API_KEY as string) || '';
let VOLATILE_API_KEY = '';
const STATE_CHANGING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function getCsrfToken(): string {
  if (typeof document === 'undefined') return '';
  const entry = document.cookie
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith('ss_csrf='));
  return entry ? entry.slice('ss_csrf='.length) : '';
}

function getApiKey(): string {
  return API_KEY_ENV || VOLATILE_API_KEY || '';
}

export function setClientApiKey(key: string) {
  VOLATILE_API_KEY = String(key || '').trim();
}

export function clearClientApiKey() {
  VOLATILE_API_KEY = '';
}

async function http<T>(path: string, opts?: RequestInit): Promise<T> {
  const url = `${API_BASE.replace(/\/$/, '')}${path}`;
  const method = String(opts?.method || 'GET').toUpperCase();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (opts?.headers) {
    if (opts.headers instanceof Headers) {
      opts.headers.forEach((value, key) => {
        headers[key] = value;
      });
    } else if (Array.isArray(opts.headers)) {
      opts.headers.forEach(([key, value]) => {
        headers[key] = value;
      });
    } else {
      Object.assign(headers, opts.headers as Record<string, string>);
    }
  }
  const key = getApiKey();
  if (key) headers['x-api-key'] = key;
  if (STATE_CHANGING.has(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  const r = await fetch(url, { ...opts, headers, credentials: 'include' });
  if (!r.ok) {
    let detail = '';
    try {
      const body = await r.json();
      detail = body?.detail ? String(body.detail) : (body?.error ? String(body.error) : '');
    } catch {
      detail = '';
    }
    const err: any = new Error(`${r.status} ${r.statusText}${detail ? `: ${detail}` : ''}`);
    err.status = r.status;
    err.detail = detail;
    throw err;
  }
  return r.json();
}

async function httpResponse(path: string, opts?: RequestInit): Promise<Response> {
  const url = `${API_BASE.replace(/\/$/, '')}${path}`;
  const method = String(opts?.method || 'GET').toUpperCase();
  const headers: Record<string, string> = {};
  if (opts?.headers) {
    if (opts.headers instanceof Headers) {
      opts.headers.forEach((value, key) => {
        headers[key] = value;
      });
    } else if (Array.isArray(opts.headers)) {
      opts.headers.forEach(([key, value]) => {
        headers[key] = value;
      });
    } else {
      Object.assign(headers, opts.headers as Record<string, string>);
    }
  }
  const key = getApiKey();
  if (key) headers['x-api-key'] = key;
  if (STATE_CHANGING.has(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  const r = await fetch(url, { ...opts, headers, credentials: 'include' });
  if (!r.ok) {
    let detail = '';
    try {
      const body = await r.json();
      detail = body?.detail ? String(body.detail) : (body?.error ? String(body.error) : '');
    } catch {
      detail = '';
    }
    const err: any = new Error(`${r.status} ${r.statusText}${detail ? `: ${detail}` : ''}`);
    err.status = r.status;
    err.detail = detail;
    throw err;
  }
  return r;
}

export async function setApiKeyCookie(apiKey: string): Promise<{ ok: boolean }> {
  return http(`/api/v1/auth/api-key-cookie`, {
    method: 'POST',
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export async function clearApiKeyCookie(): Promise<{ ok: boolean }> {
  return http(`/api/v1/auth/api-key-cookie`, { method: 'DELETE' });
}

export async function fetchPreferences(uid: string): Promise<{ preferences?: any }> {
  return http(`/api/v1/preferences?uid=${encodeURIComponent(uid)}`);
}

export async function fetchCitationMemoryStats(): Promise<any> {
  return http(`/api/v1/merchant/intelligence/citation_memory/stats`);
}

export async function fetchTrustedClaims(params?: { minTrust?: number; limit?: number }): Promise<any[]> {
  const q = new URLSearchParams();
  q.set('min_trust', String(params?.minTrust ?? 0.6));
  q.set('limit', String(params?.limit ?? 20));
  return http(`/api/v1/merchant/intelligence/citation_memory/trusted_claims?${q.toString()}`);
}

export async function fetchUserProfile(userId: string): Promise<any> {
  return http(`/api/v1/merchant/intelligence/user_profiles/${encodeURIComponent(userId)}`);
}

export async function fetchUserBehavioralModel(userId: string): Promise<any> {
  return http(`/api/v1/merchant/intelligence/user_profiles/${encodeURIComponent(userId)}/behavioral_model`);
}

export async function fetchObservationSummary(sessionId: string): Promise<{ summary: any }> {
  return http(`/api/v1/merchant/intelligence/observation_summary/${encodeURIComponent(sessionId)}`);
}

export async function fetchAgentTrust(agentName: string): Promise<{ agent_name: string; trust_score: number }> {
  return http(`/api/v1/merchant/intelligence/citation_memory/agent_trust/${encodeURIComponent(agentName)}`);
}

export async function downloadAuthenticated(path: string): Promise<Blob> {
  const r = await httpResponse(path);
  return r.blob();
}

export async function fetchMe(): Promise<{ role: 'merchant' | 'owner' | 'developer'; allowed_roles: string[] }> {
  return http(`/api/v1/admin/me`);
}

export async function fetchOverview(): Promise<{
  revenue_today: number;
  orders_today: number;
  autonomy_percent: number;
  security_status: string;
  critical_events_24h: number;
  approval_pending: number;
  decision_series: { day: string; count: number }[];
  approval_latency_p95_sec: number;
  policy_reject_rate: number;
  uptime_seconds: number;
}> {
  return http(`/api/v1/admin/overview`);
}

export async function fetchLiveFeed(): Promise<{ items: { type: string; id: string; time: string; summary: string }[] }> {
  return http(`/api/v1/admin/live-feed?limit=6`);
}

export async function fetchAnalytics(days: number): Promise<{ days: number; series: any }> {
  return http(`/api/v1/admin/analytics?days=${days}`);
}

export type TransactionTimeseriesPoint = {
  bucket: string | null;
  orders: number;
  revenue: number;
  paid: number;
  refunded: number;
  chargeback: number;
  pending_payment: number;
};

export async function fetchTransactionTimeseries(params: { granularity: 'day' | 'month'; start: string; end: string }): Promise<{
  granularity: 'day' | 'month';
  start: string;
  end: string;
  series: TransactionTimeseriesPoint[];
  totals: { orders: number; revenue: number; aov: number; paid: number; refunded: number; chargeback: number; pending_payment: number };
}> {
  const q = new URLSearchParams();
  q.set('granularity', params.granularity);
  q.set('start', params.start);
  q.set('end', params.end);
  return http(`/api/v1/admin/bi/transactions/timeseries?${q.toString()}`);
}

export type ExecutivePulse = {
  window: { start: string; end: string };
  kpis: {
    revenue: number;
    gross_margin_pct: number;
    refund_pct: number;
    chargeback_pct: number;
    approval_rate: number;
    autonomy_pct: number;
    mttd_minutes: number;
    mttr_minutes: number;
  };
  trend_overlays: {
    revenue: Array<{
      bucket: string;
      actual: number;
      baseline: number;
      anomaly_low: number;
      anomaly_high: number;
      is_anomaly: boolean;
    }>;
    causal_factors: Array<{ id: string; count: number }>;
  };
  agentic_ops: {
    auto_vs_human: Array<{ bucket: string; auto: number; human: number }>;
    false_positive_drift: Array<{ week: string; fp_rate: number; total: number }>;
    per_agent: Array<{ agent: string; error_rate: number; avg_latency_ms: number; count: number }>;
  };
  security_incursions_matrix: Array<{ week: string; type: string; severity: string; count: number }>;
  decision_replay: Array<{ policy_version: string; decisions: number; approval_rate: number }>;
};

export async function fetchExecutivePulse(start: string, end: string): Promise<ExecutivePulse> {
  const q = new URLSearchParams();
  q.set('start', start);
  q.set('end', end);
  return http(`/api/v1/admin/bi/executive-pulse?${q.toString()}`);
}

export async function fetchTrendPackAlarms(weeks = 8): Promise<{ status: string; weeks: number; alarm_count: number; alarms: Array<{ type: string; severity: string; message: string }> }> {
  return http(`/api/v1/admin/bi/trend-pack/alarms?weeks=${weeks}`);
}

export async function runBiQueryAgent(payload: { query: string; start?: string; end?: string; limit?: number }): Promise<any> {
  return http(`/api/v1/admin/bi/query-agent`, { method: 'POST', body: JSON.stringify(payload || {}) });
}

export async function fetchAgenticRagSummary(days = 7): Promise<{
  status: string;
  days: number;
  event_counts: Record<string, number>;
  contexts_injected: number;
  verify_failures: number;
  avg_budget_utilization: number;
}> {
  return http(`/api/v1/admin/bi/agentic-rag/summary?days=${days}`);
}

export async function fetchDbStackStatus(): Promise<{
  postgres_source_of_truth: boolean;
  timescaledb_extension: boolean;
  timescale_cagg_orders_hourly: boolean;
  redis_configured: boolean;
  neo4j_pilot_enabled: boolean;
  security_event_storage_targets?: string[];
  security_event_storage_paths?: Record<string, string>;
}> {
  return http(`/api/v1/admin/bi/db-stack/status`);
}

export async function fetchMlGovernanceSummary(days = 30): Promise<any> {
  return http(`/api/v1/admin/bi/ml-governance/summary?days=${days}`);
}

export async function fetchHitlReviewerConsistency(days = 30): Promise<any> {
  return http(`/api/v1/admin/bi/hitl/reviewer-consistency?days=${days}`);
}

export type MemoryHealthSummary = {
  window: { start: string; end: string };
  days: number;
  totals: {
    events: number;
    memory_miss: number;
    shortlist_lock_failed: number;
    disambiguation_prompts: number;
    summary_checkpoints: number;
  };
  averages: {
    memory_confidence: number;
    summary_age_sec: number;
  };
  stale_slots_top: Array<{ slot: string; count: number }>;
};

export async function fetchMemoryHealth(days = 7): Promise<MemoryHealthSummary> {
  return http(`/api/v1/admin/bi/memory-health?days=${days}`);
}

export type PersonaSuccessSummary = {
  window: { start: string; end: string };
  days: number;
  totals: { traces: number; reformulated: number; reupload_required: number };
  personas: Array<{
    persona: string;
    traces: number;
    resolution_turns_avg: number;
    reformulation_rate: number;
    reupload_rate: number;
  }>;
};

export async function fetchPersonaSuccess(days = 7): Promise<PersonaSuccessSummary> {
  return http(`/api/v1/admin/bi/persona-success?days=${days}`);
}

export async function fetchComplianceOverview(days = 7): Promise<any> {
  return http(`/api/v1/admin/compliance/overview?days=${days}`);
}

export async function fetchComplianceEvidence(days = 7): Promise<any> {
  return http(`/api/v1/admin/compliance/evidence?days=${days}`);
}

export async function fetchComplianceLiveFeed(limit = 20): Promise<{ items: any[] }> {
  return http(`/api/v1/admin/compliance/live-feed?limit=${limit}`);
}

export async function fetchGrcRiskRegister(days = 30): Promise<any> {
  return http(`/api/v1/admin/grc/risk-register?days=${days}`);
}

export async function fetchGrcReport(days = 30): Promise<any> {
  return http(`/api/v1/admin/grc/report?days=${days}`);
}

export async function fetchGrcTrends(days = 30): Promise<any> {
  return http(`/api/v1/admin/grc/trends?days=${days}`);
}

export async function runGrcFingerprintIngest(): Promise<any> {
  return http(`/api/v1/admin/grc/fingerprint-ingest/run`, { method: 'POST' });
}

export async function fetchGrcFingerprintAlerts(params?: { status?: string; severity?: string; limit?: number; offset?: number }): Promise<{ items: any[] }> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.severity) q.set('severity', params.severity);
  q.set('limit', String(params?.limit || 100));
  q.set('offset', String(params?.offset || 0));
  return http(`/api/v1/admin/grc/fingerprint-alerts?${q.toString()}`);
}

export async function updateGrcFingerprintAlertStatus(alertId: string, status: 'open' | 'in_progress' | 'resolved' | 'ignored', note?: string): Promise<any> {
  const q = new URLSearchParams();
  q.set('status', status);
  if (note) q.set('note', note);
  return http(`/api/v1/admin/grc/fingerprint-alerts/${encodeURIComponent(alertId)}/status?${q.toString()}`, { method: 'POST' });
}

export async function listApiKeys(): Promise<{ keys: Record<string, string[]> }> {
  return http(`/api/v1/admin/api-keys`);
}

export async function addApiKey(targetRole: string, key: string): Promise<{ updated: boolean }> {
  return http(`/api/v1/admin/api-keys?target_role=${encodeURIComponent(targetRole)}&key=${encodeURIComponent(key)}`, { method: 'POST' });
}

export async function deleteApiKey(targetRole: string, key: string): Promise<{ deleted: boolean }> {
  return http(`/api/v1/admin/api-keys?target_role=${encodeURIComponent(targetRole)}&key=${encodeURIComponent(key)}`, { method: 'DELETE' });
}

export async function rotateApiKey(targetRole: string): Promise<{ created: boolean; key: string }> {
  return http(`/api/v1/admin/api-keys/rotate?target_role=${encodeURIComponent(targetRole)}`, { method: 'POST' });
}

export async function listApiKeyAudit(params?: { action?: string; role?: string; since?: number; until?: number }): Promise<{ events: any[] }> {
  const q = new URLSearchParams();
  q.set('limit', '50');
  if (params?.action) q.set('action', params.action);
  if (params?.role) q.set('target_role', params.role);
  if (params?.since) q.set('since', String(params.since));
  if (params?.until) q.set('until', String(params.until));
  return http(`/api/v1/admin/api-keys/audit?${q.toString()}`);
}

export async function revokeApiKey(targetRole: string, key: string): Promise<{ deleted: boolean }> {
  return http(`/api/v1/admin/api-keys/revoke?target_role=${encodeURIComponent(targetRole)}&key=${encodeURIComponent(key)}`, { method: 'POST' });
}

export async function fetchOrders(limit = 50, offset = 0): Promise<{ orders: any[] }> {
  return http(`/api/v1/orders/list?limit=${limit}&offset=${offset}`);
}

export async function cancelOrder(orderId: string): Promise<{ cancelled: boolean }> {
  return http(`/api/v1/orders/${encodeURIComponent(orderId)}/cancel`, { method: 'POST' });
}

export async function returnOrder(orderId: string): Promise<{ return_requested: boolean }> {
  return http(`/api/v1/orders/${encodeURIComponent(orderId)}/return`, { method: 'POST' });
}

export async function updateOrderStatus(orderId: string, status: string): Promise<{ updated: boolean; status: string }> {
  return http(`/api/v1/orders/${encodeURIComponent(orderId)}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
}

export async function fetchDecisions(): Promise<DecisionRow[]> {
  const data = await http<{ results: DecisionRow[] }>(`/api/v1/decisions/query`);
  return data.results || [];
}


export async function fetchDecisionsFiltered(params: { agent?: string }): Promise<DecisionRow[]> {
  const q = new URLSearchParams();
  if (params.agent) q.set('agent_name', params.agent);
  const data = await http<{ results: DecisionRow[] }>(`/api/v1/decisions/query?${q.toString()}`);
  return data.results || [];
}

export type DecisionTraceEvent = {
  id: string;
  seq?: number | null;
  trace_id?: string;
  event_type?: string;
  source_type?: string | null;
  source_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  payload?: any;
  created_at?: string;
};

export type DecisionTraceQuery = {
  decision_id: string;
  timestamp?: string;
  input_query?: string | null;
  intent_analysis?: any;
  agent_chain?: any[];
  rag_context?: any;
  evidence?: any;
  recommendation?: any;
  policy_gates?: any;
  bitemporal?: any;
  model_selection?: any;
  events?: DecisionTraceEvent[];
};

export type DecisionCausalGraph = {
  trace_id: string;
  nodes: Array<{
    id: string;
    event_type?: string;
    source_type?: string;
    source_id?: string;
    target_type?: string;
    target_id?: string;
    created_at?: string;
  }>;
  edges: Array<{ from: string; to: string; type?: string }>;
};

export async function fetchDecisionTraceQuery(traceId: string): Promise<DecisionTraceQuery> {
  return http(`/api/v1/decisions/${encodeURIComponent(traceId)}/query?include_events=true`);
}

export async function fetchDecisionSession(sessionId: string): Promise<{ session_id: string; count: number; decisions: any[] }> {
  return http(`/api/v1/decisions/session/${encodeURIComponent(sessionId)}`);
}

export async function fetchDecisionCausal(traceId: string): Promise<DecisionCausalGraph> {
  return http(`/api/v1/decisions/trace/${encodeURIComponent(traceId)}/causal`);
}

export async function fetchInterleavingSummary(traceId: string): Promise<{ summary: any }> {
  return http(`/api/v1/admin/interleaving/${encodeURIComponent(traceId)}/summary`);
}

export async function approveDecision(decisionId: string, approvedBy: string): Promise<void> {
  await http(`/api/v1/decisions/${encodeURIComponent(decisionId)}/approve?approved_by=${encodeURIComponent(approvedBy)}`, { method: 'POST' });
}

export async function rejectDecision(decisionId: string, rejectedBy: string, reason?: string): Promise<void> {
  const q = new URLSearchParams();
  q.set('rejected_by', rejectedBy);
  if (reason) q.set('reason', reason);
  await http(`/api/v1/decisions/${encodeURIComponent(decisionId)}/reject?${q.toString()}`, { method: 'POST' });
}

export async function reopenDecision(decisionId: string, actor: string, comment?: string): Promise<void> {
  const q = new URLSearchParams();
  q.set('actor', actor);
  if (comment) q.set('comment', comment);
  await http(`/api/v1/decisions/${encodeURIComponent(decisionId)}/reopen?${q.toString()}`, { method: 'POST' });
}

export async function fetchFlags(): Promise<Record<string, any>> {
  return http(`/api/v1/admin/flags`);
}

export async function fetchApprovals(): Promise<ApprovalItem[]> {
  const data = await http<{ pending: ApprovalItem[] }>(`/api/v1/approvals/pending`);
  return data.pending || [];
}

export async function approveApproval(id: string): Promise<void> {
  await http(`/api/v1/approvals/${encodeURIComponent(id)}/approve`, { method: 'POST' });
}

export async function rejectApproval(id: string): Promise<void> {
  await http(`/api/v1/approvals/${encodeURIComponent(id)}/reject`, { method: 'POST' });
}

export type SecurityEvent = { id: string; time: string; severity: string; technique: string; action: string; user: string; risk: number; raw: string; normalized: string; detection: string };
export async function fetchSecurityEvents(limit = 50, offset = 0): Promise<SecurityEvent[]> {
  const data = await http<{ events: any[] }>(`/api/v1/admin/security/events?limit=${limit}&offset=${offset}`);
  const rows = data.events || [];
  return rows.map(r => ({
    id: r.id,
    time: r.event_time,
    severity: r.severity,
    technique: (r.details?.analysis?.mitre_atlas || []).join(', '),
    action: 'n/a',
    user: r.details?.payload?.user || 'unknown',
    risk: r.verdict_score,
    raw: r.details?.payload || null,
    normalized: r.details?.analysis?.sanitized || null,
    detection: JSON.stringify(r.details?.analysis || {}),
  }));
}


export async function fetchSecurityEventsFiltered(params: { limit?: number; offset?: number; severity?: string; since?: string; until?: string }): Promise<SecurityEvent[]> {
  const q = new URLSearchParams();
  q.set('limit', String(params.limit || 50));
  q.set('offset', String(params.offset || 0));
  if (params.severity) q.set('severity', params.severity);
  if (params.since) q.set('since', params.since);
  if (params.until) q.set('until', params.until);
  const data = await http<{ events: any[] }>(`/api/v1/admin/security/events?${q.toString()}`);
  const rows = data.events || [];
  return rows.map(r => ({
    id: r.id,
    time: r.event_time,
    severity: r.severity,
    technique: (r.details?.analysis?.mitre_atlas || []).join(', '),
    action: 'n/a',
    user: r.details?.payload?.user || 'unknown',
    risk: r.verdict_score,
    raw: r.details?.payload || null,
    normalized: r.details?.analysis?.sanitized || null,
    detection: JSON.stringify(r.details?.analysis || {}),
  }));
}

export type InventoryConnectorHealth = { id: string; name: string; health: any };
export type InventorySyncRun = { id: string; tenant_id?: string | null; source: string; status: string; started_at?: string | null; finished_at?: string | null; records_seen?: number; records_applied?: number; error?: string | null };

export async function fetchInventoryConnectors(): Promise<{ items: InventoryConnectorHealth[] }> {
  return http(`/api/v1/admin/inventory/connectors`);
}

export async function runInventorySync(body: { connector?: string; tenant_id?: string | null; dry_run?: boolean; upsert_products?: boolean; csv_path?: string | null }): Promise<any> {
  return http(`/api/v1/admin/inventory/sync`, { method: 'POST', body: JSON.stringify(body || {}) });
}

export async function fetchInventorySyncRuns(limit = 50): Promise<{ items: InventorySyncRun[] }> {
  return http(`/api/v1/admin/inventory/sync/runs?limit=${limit}`);
}

export async function fetchInventoryExternalStock(limit = 200): Promise<{ items: any[] }> {
  return http(`/api/v1/admin/inventory/external_stock/recent?limit=${limit}`);
}

export async function fetchInventoryConnectorSummary(limitSamples = 5): Promise<{ items: any[] }> {
  return http(`/api/v1/admin/inventory/connectors/summary?limit_samples=${limitSamples}`);
}

export async function fetchSupplierRiskSummary(hours = 24 * 7): Promise<{
  window_hours: number;
  quarantined_updates: number;
  avg_risk_score: number;
  source_risk: Array<{ source: string; quarantined: number; risk_avg: number; trust_score: number }>;
  recent_quarantines: Array<{ id: string; source: string; sku: string; warehouse: string; stock: number; risk_score: number; reasons: string[]; created_at: string }>;
}> {
  return http(`/api/v1/admin/inventory/supplier-risk?hours=${hours}`);
}

export async function fetchInventoryDriftCheck(): Promise<{
  missing_inventory_products: number;
  orphan_inventory_rows: number;
  unknown_order_line_skus: number;
  negative_stock_rows: number;
  status: string;
}> {
  return http(`/api/v1/admin/inventory/drift/check`);
}

export async function fetchDemoReadiness(hours = 24): Promise<{
  window_hours: number;
  security_posture: { blocked_attacks: number; escalations: number; supplier_quarantines: number; api_abuse_blocked: number };
  model_quality: { ctr: number; add_to_cart_rate: number; low_confidence_fallback_rate: number; low_confidence_count: number; total_decisions: number };
}> {
  return http(`/api/v1/admin/demo/readiness?hours=${hours}`);
}

export async function fetchCVIncidentsRecent(limit = 50): Promise<{ items: any[] }> {
  return http(`/api/v1/admin/cv/incidents/recent?limit=${limit}`);
}

export async function fetchCVIncidentsBySku(limit = 500): Promise<{ items: any[] }> {
  return http(`/api/v1/admin/cv/incidents/by_sku?limit=${limit}`);
}

export async function fetchCVReadiness(): Promise<any> {
  return http(`/api/v1/admin/cv/readiness`);
}

export async function fetchTenantConfig(configKey: string, tenantId?: string | null): Promise<{ tenant_id: string; config_key: string; value: any }> {
  const q = new URLSearchParams();
  if (tenantId) q.set('tenant_id', tenantId);
  return http(`/api/v1/config/${encodeURIComponent(configKey)}?${q.toString()}`);
}

export async function putTenantConfig(configKey: string, value: any, tenantId?: string | null): Promise<{ ok: boolean }> {
  const q = new URLSearchParams();
  if (tenantId) q.set('tenant_id', tenantId);
  return http(`/api/v1/config/${encodeURIComponent(configKey)}?${q.toString()}`, { method: 'PUT', body: JSON.stringify(value || {}) });
}

export async function escalateEvent(id: string): Promise<void> {
  await http(`/api/v1/admin/security/events/${encodeURIComponent(id)}/escalate`, { method: 'POST' });
}

export async function blockEvent(id: string): Promise<void> {
  await http(`/api/v1/admin/security/events/${encodeURIComponent(id)}/block`, { method: 'POST' });
}

export async function fetchSecurityEventById(id: string): Promise<any> {
  return http(`/api/v1/admin/security/events/${encodeURIComponent(id)}`);
}

export async function fetchSecurityMetrics(hours = 24): Promise<any> {
  return http(`/api/v1/admin/security/metrics?hours=${hours}`);
}

export type UpsellPerformance = {
  window_hours: number;
  impressions: number;
  clicks: number;
  add_to_cart: number;
  ctr: number;
  add_to_cart_rate: number;
  blocked_poisoned_candidates: number;
  poison_reason_counts: Record<string, number>;
  top_skus: Array<{ sku: string; views: number; clicks: number; add_to_cart: number; ctr: number }>;
  sample_trace_ids: string[];
};

export async function fetchUpsellPerformance(hours = 24, topK = 5): Promise<UpsellPerformance> {
  return http(`/api/v1/admin/upsell/performance?hours=${hours}&top_k=${topK}`);
}

export type SecurityEscalationSummary = {
  window_hours: number;
  total_events: number;
  escalated: number;
  blocked: number;
  escalation_rate: number;
  block_rate: number;
  by_severity: Record<string, number>;
  dread: { avg: number; p95: number; high_count: number; critical_count: number; escalated_avg: number };
  evidence: { events_with_evidence: number; escalated_with_evidence: number; avg_evidence_items: number };
  top_paths: Array<{ path: string; count: number }>;
  recent_alerts: Array<{
    id: string;
    event_time: string;
    severity: string;
    path: string;
    escalated: boolean;
    blocked: boolean;
    dread_avg?: number | null;
    evidence_count: number;
    evidence_tags: string[];
    trace_id?: string | null;
  }>;
  sample_trace_ids: string[];
};

export async function fetchSecurityEscalationSummary(hours = 24, limit = 2000): Promise<SecurityEscalationSummary> {
  return http(`/api/v1/admin/security/escalations/summary?hours=${hours}&limit=${limit}`);
}

export async function fetchNetworkProbeSummary(hours = 24): Promise<{
  window_hours: number;
  total_events: number;
  high_risk_events: number;
  by_stage: Record<string, number>;
  by_probe_type: Record<string, number>;
  recent: any[];
}> {
  return http(`/api/v1/admin/security/network-probes/summary?hours=${hours}`);
}

export async function fetchKillchainProgression(hours = 24): Promise<{
  window_hours: number;
  stage_counts: Record<string, number>;
  trace_progressions: Array<{ trace_id: string; stages: string[]; escalated: boolean }>;
  escalation_recommended: boolean;
}> {
  return http(`/api/v1/admin/security/killchain/progression?hours=${hours}`);
}

export async function fetchSupplyChainStatus(): Promise<any> {
  return http(`/api/v1/admin/security/supply-chain`);
}

export type SecurityAttackBucket = {
  hour: string;
  security_type: string;
  threat: string;
  vector: string;
  count: number;
};

export async function fetchSecurityAttackTimeseries(hours = 24, limit = 5000): Promise<{ hours: number; buckets: SecurityAttackBucket[]; totals_by_type: { security_type: string; count: number }[]; source?: string }> {
  return http(`/api/v1/admin/security/attacks/timeseries?hours=${hours}&limit=${limit}`);
}

export type SecurityGeoAsnTrend = {
  asn: string;
  country: string;
  count: number;
  network_confidence: number;
  network_confidence_avg: number;
  asn_risk_avg: number;
  vpn_or_hosting_hits: number;
  velocity_anomaly_hits: number;
  sender_tool_behavior_avg: number;
  ip_churn_velocity: number;
  geo_trust_level: 'low' | 'medium' | 'high';
  last_seen?: string | null;
  business_contexts?: Record<string, number>;
  security_contexts?: Record<string, number>;
};

export async function fetchSecurityGeoAsnTrends(hours = 24, limit = 5000): Promise<{ hours: number; trends: SecurityGeoAsnTrend[]; source?: string; notes?: any }> {
  return http(`/api/v1/admin/security/geoip-asn/trends?hours=${hours}&limit=${limit}`);
}

export type IncidentAlertSummary = {
  hours: number;
  totals: {
    sla_breach_alerts: number;
    runbook_failure_alerts: number;
    incidents_with_alerts: number;
  };
  recent: Array<{
    type: 'sla_breach' | 'runbook_failure';
    incident_id: string;
    severity: string;
    title: string;
    status: string;
    alerted_at?: string | null;
    created_at?: string | null;
    sla_due_at?: string | null;
    runbook_id?: string | null;
    runbook_run_id?: string | null;
  }>;
};

export async function fetchIncidentAlertSummary(hours = 24, limit = 30): Promise<IncidentAlertSummary> {
  return http(`/api/v1/admin/incidents/ops/alerts/summary?hours=${hours}&limit=${limit}`);
}

export async function sendAlertmanagerTest(): Promise<{ sent: boolean; alertmanager_url?: string }> {
  return http(`/api/v1/admin/alertmanager/test`, { method: 'POST' });
}

export async function fetchToolInvocations(limit = 20): Promise<any> {
  return http(`/api/v1/admin/tool-invocations?limit=${limit}`);
}

export async function fetchIamEvents(limit = 20, actor?: string): Promise<any> {
  const q = new URLSearchParams();
  q.set('limit', String(limit));
  if (actor) q.set('actor', actor);
  return http(`/api/v1/admin/iam/events?${q.toString()}`);
}

export type AbacDenyGroup = {
  tenant_id: string;
  resource_sensitivity: string;
  abac_reason: string;
  count: number;
  latest_created_at?: string | null;
  sample_trace_id?: string | null;
};

export async function fetchAbacDenySummary(hours = 24, limit = 2000): Promise<{ hours: number; total_denies: number; groups: AbacDenyGroup[] }> {
  return http(`/api/v1/admin/security/abac/denies?hours=${hours}&limit=${limit}`);
}

export async function fetchEmailIocFeedbackQuality(): Promise<{ items: any[] }> {
  return http(`/api/v1/admin/email_security/feedback/ioc_quality`);
}

export type IncidentRow = {
  id: string;
  event_id?: string;
  created_at?: string;
  created_by?: string;
  severity?: string;
  title?: string;
  description?: string;
  status?: string;
  sla_status?: string;
  sla_due_at?: string;
  runbook_id?: string;
  runbook_run_id?: string;
  sla?: { sla_status?: string; sla_due_at?: string; remaining_seconds?: number | null };
};
export async function fetchIncidents(params?: { limit?: number; offset?: number; status?: string; severity?: string }) : Promise<IncidentRow[]> {
  const q = new URLSearchParams();
  q.set('limit', String(params?.limit || 50));
  q.set('offset', String(params?.offset || 0));
  if (params?.status) q.set('status', params.status);
  if (params?.severity) q.set('severity', params.severity);
  const data = await http<{ incidents: IncidentRow[] }>(`/api/v1/admin/incidents?${q.toString()}`);
  return data.incidents || [];
}

export async function updateIncidentStatus(id: string, status: string): Promise<void> {
  await http(`/api/v1/admin/incidents/${encodeURIComponent(id)}/status?status=${encodeURIComponent(status)}`, { method: 'POST' });
}

export async function issueIncidentStaffToken(id: string): Promise<{ ok: boolean; staff_token: string; ttl_seconds: number }> {
  return http(`/api/v1/admin/incidents/${encodeURIComponent(id)}/room/token`, { method: 'POST' });
}

export async function getIncident(id: string): Promise<IncidentRow> {
  return http(`/api/v1/admin/incidents/${encodeURIComponent(id)}`);
}

export async function fetchIncidentEvidence(id: string): Promise<{ incident_id: string; items: any[] }> {
  return http(`/api/v1/admin/incidents/${encodeURIComponent(id)}/evidence`);
}

// DB readiness and Timescale helpers
export async function fetchDbReadiness(): Promise<{ engine: string; dialect: string; connected: boolean; migrations_ok: boolean; timescale_ready: boolean; error?: string | null }> {
  return http(`/api/v1/admin/db/readiness`);
}

export async function ensureTimescale(): Promise<{ engine: string; dialect: string; connected: boolean; migrations_ok: boolean; timescale_ready: boolean; error?: string | null }> {
  return http(`/api/v1/admin/db/ensure-timescale`, { method: 'POST' });
}

// Email Security Incidents (admin drilldown)
export type EmailSecurityIncident = {
  id: string;
  created_at?: string;
  tenant_id?: string;
  provider?: string;
  supplier_key_hash?: string;
  severity: 'info' | 'warning' | 'error';
  risk_band?: 'low' | 'medium' | 'high';
  playbook?: { id?: string; title?: string } | null;
  tags?: string[];
  reasons?: string[];
  evidence_snapshot?: any;
  ticket?: { id?: string; created: boolean; rate_limited: boolean; deduped: boolean };
};

export async function fetchEmailSecurityIncidents(params?: { tenantId?: string; severity?: string; supplierKeyHash?: string; playbookId?: string; hasTicket?: boolean; limit?: number; offset?: number }): Promise<EmailSecurityIncident[]> {
  const q = new URLSearchParams();
  q.set('limit', String(params?.limit || 50));
  q.set('offset', String(params?.offset || 0));
  if (params?.tenantId) q.set('tenant_id', params.tenantId);
  if (params?.severity) q.set('severity', params.severity);
  if (params?.supplierKeyHash) q.set('supplier_key_hash', params.supplierKeyHash);
  if (params?.playbookId) q.set('playbook_id', params.playbookId);
  if (typeof params?.hasTicket === 'boolean') q.set('has_ticket', params!.hasTicket ? 'true' : 'false');
  const data = await http<{ incidents: EmailSecurityIncident[] }>(`/api/v1/admin/email_security/incidents?${q.toString()}`);
  return data.incidents || [];
}

export async function getEmailSecurityIncident(id: string): Promise<{ incident: EmailSecurityIncident }> {
  return http(`/api/v1/admin/email_security/incidents/${encodeURIComponent(id)}`);
}

export type EmailSecurityInvestigation = {
  incident: EmailSecurityIncident;
  trace_id?: string | null;
  timeline: Array<{ id: string; event_type: string; source_type?: string; source_id?: string; payload?: any; created_at?: string }>;
  timeline_summary?: { event_count?: number; event_type_counts?: Record<string, number>; first_event_at?: string | null; last_event_at?: string | null };
  score_breakdown?: any;
  trust_case?: any;
  access_policy?: any;
  sandbox_ioc_stage?: any;
  mailbox_compromise?: any;
  phishing_page_stage?: any;
  bec_kill_chain?: any;
  explain?: any;
  agent_runs?: Array<{
    agent_name: string;
    scope_enforced: boolean;
    tools_used: string[];
    scope_violations: Array<{ violation_type: string; detail: string; severity: string }>;
    confidence: number;
    why_ran: string;
    output_quality: string;
    verdict_after: string;
  }>;
  recommended_actions?: Array<{ id: string; label: string }>;
  actions?: Array<{ id: string; action: string; note?: string; actor?: string; created_at?: string }>;
  feedback?: any;
};

export async function fetchEmailSecurityInvestigation(incidentId: string): Promise<EmailSecurityInvestigation> {
  return http(`/api/v1/admin/email_security/investigations/${encodeURIComponent(incidentId)}`);
}

export async function submitEmailSecurityInvestigationAction(
  incidentId: string,
  payload: { action: string; note?: string },
): Promise<{ ok: boolean; incident_id: string; action_id: string; action: string; status?: string }> {
  return http(`/api/v1/admin/email_security/investigations/${encodeURIComponent(incidentId)}/action`, {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
}

export type MaestroBoundaryEntry = {
  risk_tier: string;
  allowed_tools: string[];
  allowed_data_scopes: string[];
  max_autonomous_value_usd: number;
  can_write_db: boolean;
  can_call_external_api: boolean;
  can_invoke_llm: boolean;
  allowed_peers: string[];
  recent_violations_24h?: number;
  recent_checks_24h?: number;
};

export async function fetchMaestroBoundaries(opts?: {
  agent?: string;
  risk_tier?: string;
  include_recent_violations?: boolean;
  hours?: number;
}): Promise<{
  enforcement_mode: string;
  agent_count: number;
  boundaries: Record<string, MaestroBoundaryEntry>;
  framework: string;
  control: string;
  violation_window_hours?: number | null;
  total_violations_in_window?: number | null;
}> {
  const params = new URLSearchParams();
  if (opts?.agent) params.set('agent', opts.agent);
  if (opts?.risk_tier) params.set('risk_tier', opts.risk_tier);
  if (opts?.include_recent_violations) params.set('include_recent_violations', '1');
  if (opts?.hours) params.set('hours', String(opts.hours));
  const qs = params.toString();
  return http(`/api/v1/admin/security/maestro/boundaries${qs ? `?${qs}` : ''}`);
}


export async function runEmailSecurityReplayLab(payload?: {
  tenant_id?: string;
  incident_ids?: string[];
  decision_ids?: string[];
}): Promise<{
  evaluated: number;
  changed_count: number;
  changed_rate: number;
  policy_verdict_counts: Record<string, number>;
  results: Array<{ decision_id: string; agent_name?: string; valid_from?: string; drift?: any }>;
}> {
  return http(`/api/v1/admin/email_security/replay_lab/run`, {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
}

export type EmailSecuritySupplierBucket = {
  supplier_key_hash: string;
  counts: { error: number; warning: number; info: number };
  last_seen?: string;
};

export async function fetchEmailSecuritySuppliers(params?: { tenantId?: string; limit?: number }): Promise<EmailSecuritySupplierBucket[]> {
  const q = new URLSearchParams();
  q.set('limit', String(params?.limit || 50));
  if (params?.tenantId) q.set('tenant_id', params.tenantId);
  const data = await http<{ suppliers: EmailSecuritySupplierBucket[] }>(`/api/v1/admin/email_security/suppliers?${q.toString()}`);
  return data.suppliers || [];
}

export type PlaybookDetails = {
  id: string;
  title?: string;
  risk_band_min?: string;
  severity?: string;
  checks?: string[];
  actions?: string[];
  owners?: string[];
  closure_criteria?: string[];
};

export async function fetchPlaybookById(id: string): Promise<{ playbook: PlaybookDetails }> {
  return http(`/api/v1/admin/email_security/playbooks/${encodeURIComponent(id)}`);
}

export async function fetchEmailSecurityRunbook(tenantId?: string): Promise<any> {
  const q = new URLSearchParams();
  if (tenantId) q.set('tenant_id', tenantId);
  return http(`/api/v1/admin/email_security/demo/runbook?${q.toString()}`);
}

export async function executeEmailSecurityRunbook(payload?: { tenant_id?: string; scenarios?: string[] }): Promise<any> {
  return http(`/api/v1/admin/email_security/demo/runbook/execute`, { method: 'POST', body: JSON.stringify(payload || {}) });
}

export async function fetchEmailSecurityConnectorReliability(hours = 24): Promise<any> {
  return http(`/api/v1/admin/email_security/connectors/reliability?hours=${hours}`);
}

export async function fetchEmailSecurityConnectorDlq(params?: { limit?: number; offset?: number; target?: string }): Promise<any> {
  const q = new URLSearchParams();
  q.set('limit', String(params?.limit || 100));
  q.set('offset', String(params?.offset || 0));
  if (params?.target) q.set('target', params.target);
  return http(`/api/v1/admin/email_security/connectors/dlq?${q.toString()}`);
}

export async function requeueEmailSecurityConnectorDlq(itemId: string): Promise<any> {
  return http(`/api/v1/admin/email_security/connectors/dlq/${encodeURIComponent(itemId)}/requeue`, { method: 'POST' });
}

export async function bulkLabelEmailSecurityIncidents(payload: {
  incident_ids: string[];
  outcome_type?: string;
  outcome_value?: string;
  actor_id?: string;
  actor_role?: string;
  note?: string;
}): Promise<any> {
  return http(`/api/v1/admin/email_security/feedback/bulk_label`, { method: 'POST', body: JSON.stringify(payload || {}) });
}

export async function fetchEmailSecurityFeedbackSummary(params?: { tenantId?: string; hours?: number }): Promise<any> {
  const q = new URLSearchParams();
  q.set('hours', String(params?.hours || (24 * 30)));
  if (params?.tenantId) q.set('tenant_id', params.tenantId);
  return http(`/api/v1/admin/email_security/feedback/summary?${q.toString()}`);
}

export type AdminPlaybook = {
  id: string;
  title?: string;
  domain?: string;
  priority?: number;
  enabled?: boolean;
  version?: string;
  trigger_logic?: 'any' | 'all' | string;
  risk_band_min?: string;
  severity?: string;
  checks?: string[];
  actions?: any[];
  owners?: string[];
  closure_criteria?: string[];
  entry_conditions?: Record<string, any>;
  rollback?: Record<string, any>;
  requires_approval_roles?: string[];
  sla_minutes?: number;
};

export async function fetchAdminPlaybooks(params?: { includeDisabled?: boolean; domain?: string }): Promise<{ playbooks: AdminPlaybook[] }> {
  const q = new URLSearchParams();
  if (typeof params?.includeDisabled === 'boolean') q.set('include_disabled', params.includeDisabled ? 'true' : 'false');
  if (params?.domain) q.set('domain', params.domain);
  return http(`/api/v1/admin/playbooks?${q.toString()}`);
}

export async function fetchAdminPlaybookItem(id: string): Promise<{ playbook: AdminPlaybook }> {
  return http(`/api/v1/admin/playbooks/item/${encodeURIComponent(id)}`);
}

export async function validateAdminPlaybooks(config?: any): Promise<{ valid: boolean; errors: string[] }> {
  return http(`/api/v1/admin/playbooks/validate`, { method: 'POST', body: JSON.stringify(config ? { config } : {}) });
}

export async function dryRunAdminPlaybooks(payload: { tags: string[]; risk_band?: string; context?: Record<string, any> }): Promise<any> {
  return http(`/api/v1/admin/playbooks/dry-run`, { method: 'POST', body: JSON.stringify(payload || {}) });
}

export async function publishAdminPlaybook(payload: { playbook_id: string; updates: Record<string, any>; actor?: string; approval_id?: string }): Promise<any> {
  return http(`/api/v1/admin/playbooks/publish`, { method: 'POST', body: JSON.stringify(payload || {}) });
}

export async function rollbackAdminPlaybook(payload: { playbook_id: string; target_version: string; actor?: string; approval_id?: string }): Promise<any> {
  return http(`/api/v1/admin/playbooks/rollback`, { method: 'POST', body: JSON.stringify(payload || {}) });
}

export async function fetchAdminPlaybookDiff(playbookId: string, fromVersion: string, toVersion: string): Promise<{ diff: string[] }> {
  const q = new URLSearchParams();
  q.set('from_version', fromVersion);
  q.set('to_version', toVersion);
  return http(`/api/v1/admin/playbooks/${encodeURIComponent(playbookId)}/diff?${q.toString()}`);
}

export async function fetchAdminPlaybookKpis(days = 30): Promise<any> {
  return http(`/api/v1/admin/playbooks/kpis/summary?days=${days}`);
}

export async function fetchAdminPlaybookReliability(days = 30): Promise<any> {
  return http(`/api/v1/admin/playbooks/ops/reliability?days=${days}`);
}

export async function fetchAdminPlaybookDriftAlerts(days = 30): Promise<any> {
  return http(`/api/v1/admin/playbooks/ops/drift-alerts?days=${days}`);
}

export async function fetchAdminPlaybookTrail(playbookId: string, limit = 50): Promise<any> {
  return http(`/api/v1/admin/playbooks/trail/${encodeURIComponent(playbookId)}?limit=${limit}`);
}

export async function fetchAdminPlaybookDlq(limit = 100): Promise<any> {
  return http(`/api/v1/admin/playbooks/ops/dlq?limit=${limit}`);
}

export async function reprocessAdminPlaybookDlq(limit = 50): Promise<any> {
  return http(`/api/v1/admin/playbooks/ops/dlq/reprocess`, { method: 'POST', body: JSON.stringify({ limit }) });
}

export async function fetchAdminStreamHealth(): Promise<any> {
  return http(`/api/v1/admin/playbooks/ops/streams/health`);
}

export async function recoverAdminStreams(count = 100): Promise<any> {
  return http(`/api/v1/admin/playbooks/ops/streams/recover`, { method: 'POST', body: JSON.stringify({ count }) });
}

export async function replayAdminStreams(count = 100): Promise<any> {
  return http(`/api/v1/admin/playbooks/ops/streams/replay`, { method: 'POST', body: JSON.stringify({ count }) });
}

export async function fetchAdminLlmRouting(windowMinutes = 60, tenantId?: string | null): Promise<any> {
  const q = new URLSearchParams();
  q.set('window_minutes', String(windowMinutes));
  if (tenantId) q.set('tenant_id', tenantId);
  return http(`/api/v1/admin/playbooks/ops/llm/routing?${q.toString()}`);
}

// Rules Admin (DB-backed rules via RuleStore)
export type RuleDefinition = {
  id: string;
  tenant_id?: string | null;
  domain?: string | null;
  title: string;
  pattern?: string | null;
  expression?: string | null;
  priority: number;
  active?: number;
  created_by?: string | null;
  version?: string | null;
  effective_from?: string | null;
  effective_to?: string | null;
  created_at?: string | null;
};

export async function listRules(params?: { tenantId?: string; domain?: string }): Promise<RuleDefinition[]> {
  const q = new URLSearchParams();
  if (params?.tenantId) q.set('tenant_id', params.tenantId);
  if (params?.domain) q.set('domain', params.domain);
  const data = await http<{ rules: RuleDefinition[] }>(`/api/v1/rules/?${q.toString()}`);
  return data.rules || [];
}

export async function createRule(payload: Partial<RuleDefinition>): Promise<{ ok: boolean; id: string }> {
  return http(`/api/v1/rules/`, { method: 'POST', body: JSON.stringify(payload) });
}

export async function updateRule(id: string, updates: Partial<RuleDefinition>): Promise<{ ok: boolean }> {
  return http(`/api/v1/rules/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(updates) });
}

export async function deleteRule(id: string): Promise<{ ok: boolean }> {
  return http(`/api/v1/rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function previewRule(payload: { text: string; tenant_id?: string; domain?: string }): Promise<any> {
  return http(`/api/v1/rules/preview`, { method: 'POST', body: JSON.stringify(payload) });
}

// --- Supply-chain attack simulation ---

export type SCScenario = {
  scenario_id: string;
  name: string;
  description: string;
  mitre_attack: string[];
  owasp_tags: string[];
  kill_chain: string[];
  expected_signals: string[];
  expected_severity: string;
  human_escalation_expected: boolean;
  payload: Record<string, any>;
};

export type SCThinkingStep = {
  step_id: number;
  agent: string;
  action: string;
  reasoning: string;
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  duration_ms: number;
  timestamp: string;
};

export type SCSimResult = {
  scenario_id: string;
  scenario_name: string;
  trace_id: string;
  decision_id: string;
  thinking_steps: SCThinkingStep[];
  agent_chain: { agent_id: string; role: string; order: number; status: string; findings: Record<string, any> }[];
  risk_analysis: Record<string, any>;
  signals_detected: string[];
  severity: string;
  human_escalation_triggered: boolean;
  escalation_reason: string;
  incident_id?: string | null;
  bitemporal: Record<string, string>;
  elapsed_ms: number;
  pass_fail: string;
};

export type SCSwarmJob = {
  job_id: string;
  status: string;
  created_at?: number;
  completed_at?: number;
  rounds?: { round: number; results: any[] }[];
  summary?: { total_runs: number; pass_rate: number; rounds_completed: number };
};

export async function fetchSCScenarios(): Promise<SCScenario[]> {
  const data = await http<{ scenarios: SCScenario[] }>(`/api/v1/admin/supply-chain-sim/scenarios`);
  return data.scenarios || [];
}

export async function fetchSCScenario(id: string): Promise<SCScenario> {
  return http<SCScenario>(`/api/v1/admin/supply-chain-sim/scenarios/${encodeURIComponent(id)}`);
}

export async function runSCScenario(id: string): Promise<SCSimResult> {
  return http<SCSimResult>(`/api/v1/admin/supply-chain-sim/run?scenario_id=${encodeURIComponent(id)}`, { method: 'POST' });
}

export async function runSCAll(): Promise<{ results: SCSimResult[]; summary: any; report_text: string }> {
  return http(`/api/v1/admin/supply-chain-sim/run-all`, { method: 'POST' });
}

export async function startSCSwarm(rounds = 1, scenarioIds?: string[]): Promise<{ job_id: string; status: string }> {
  const q = new URLSearchParams();
  q.set('rounds', String(rounds));
  if (scenarioIds?.length) q.set('scenario_ids', scenarioIds.join(','));
  return http(`/api/v1/admin/supply-chain-sim/swarm?${q.toString()}`, { method: 'POST' });
}

export async function fetchSCSwarm(jobId: string): Promise<SCSwarmJob> {
  return http<SCSwarmJob>(`/api/v1/admin/supply-chain-sim/swarm/${encodeURIComponent(jobId)}`);
}

export function streamSCScenario(id: string): EventSource {
  const url = `${API_BASE.replace(/\/$/, '')}/api/v1/admin/supply-chain-sim/run/${encodeURIComponent(id)}/stream`;
  return new EventSource(url, { withCredentials: true });
}

export function streamSCAll(): EventSource {
  const url = `${API_BASE.replace(/\/$/, '')}/api/v1/admin/supply-chain-sim/run-all/stream`;
  return new EventSource(url, { withCredentials: true });
}
