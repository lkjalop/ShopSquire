const rawBase = (import.meta as any).env?.VITE_API_BASE_URL as string | undefined;

function resolveImplicitApiBase(): string {
  if (typeof window === 'undefined') return '';
  const { protocol, hostname, host, port } = window.location;
  const localHost = hostname.toLowerCase();
  const isLocal = localHost === '127.0.0.1' || localHost === 'localhost';
  if (!isLocal) return '';
  if (port === '8099') return `${protocol}//${host}`;
  if (port === '8080') return `${protocol}//${host}`;
  if (port === '5173' || port === '4173' || port === '3000') {
    return `${protocol}//${hostname}:8099`;
  }
  return '';
}

const API_BASE = rawBase ? rawBase.replace(/\/+$/, '') : resolveImplicitApiBase();
const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';

function csrfHeaders(): Record<string, string> {
  if (typeof document === 'undefined') return {};
  const entry = document.cookie
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith('ss_csrf='));
  const token = entry ? entry.slice('ss_csrf='.length) : '';
  return token ? { 'X-CSRF-Token': token } : {};
}

function authHeaders(extra: Record<string, string> = {}, includeJsonContentType = false): Record<string, string> {
  return {
    ...(includeJsonContentType ? { 'Content-Type': 'application/json' } : {}),
    ...csrfHeaders(),
    ...(API_KEY ? { 'x-api-key': API_KEY } : {}),
    ...extra,
  };
}

export function getApiBase(): string {
  return API_BASE;
}

export function apiUrl(path: string): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  return API_BASE ? `${API_BASE}${clean}` : clean;
}

export function wsUrl(path: string): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  if (API_BASE) {
    try {
      const u = new URL(API_BASE, window.location.href);
      const proto = u.protocol === 'https:' ? 'wss:' : 'ws:';
      const prefix = u.pathname.replace(/\/$/, '');
      return `${proto}//${u.host}${prefix}${clean}`;
    } catch {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${proto}//${window.location.host}${clean}`;
    }
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${clean}`;
}

export async function safeJson(response: Response): Promise<any | null> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function cvAnalyze(payload: {
  case_id?: string;
  order_id?: string;
  labels?: string[];
  extracted_text?: string | null;
  provider?: string;
  model?: string;
  images?: Array<{ name: string; size: number; type: string; width?: number; height?: number; sha256?: string; phash?: string }>;
  images_b64?: string[];
  description?: string;
  issue_type?: string;
}) {
  const r = await fetch(apiUrl('/api/v1/cv/analyze'), {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders({}, true),
    body: JSON.stringify({
      provider: 'basic',
      model: 'cv_triage_basic',
      labels: [],
      extracted_text: null,
      ...payload,
    }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cv_analyze_failed (${r.status})`);
  return j;
}

export async function cvIssueNonce(): Promise<{ nonce: string; expires_in: number } | null> {
  const r = await fetch(apiUrl('/api/v1/cv/nonce'), {
    credentials: 'include',
    headers: authHeaders(),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) return null;
  return j;
}

export async function cvUpload(params: {
  file: File;
  nonce: string;
  order_id?: string;
  customer_id?: string;
  guest_email?: string;
  sku?: string;
  expected_label?: string;
  issue_type?: string;
  description?: string;
}) {
  const fd = new FormData();
  fd.append('image', params.file);
  const u = new URL(apiUrl('/api/v1/cv/upload'), window.location.href);
  u.searchParams.set('nonce', params.nonce);
  if (params.order_id) u.searchParams.set('order_id', params.order_id);
  if (params.customer_id) u.searchParams.set('customer_id', params.customer_id);
  if (params.guest_email) u.searchParams.set('guest_email', params.guest_email);
  if (params.sku) u.searchParams.set('sku', params.sku);
  if (params.expected_label) u.searchParams.set('expected_label', params.expected_label);
  if (params.issue_type) u.searchParams.set('issue_type', params.issue_type);
  if (params.description) u.searchParams.set('description', params.description);
  const r = await fetch(u.toString(), {
    method: 'POST',
    credentials: 'include',
    body: fd,
    headers: authHeaders(),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cv_upload_failed (${r.status})`);
  return j;
}

export async function getCart(uid: string) {
  const u = new URL(apiUrl('/api/v1/cart'), window.location.href);
  u.searchParams.set('uid', uid || 'demo-user');
  const r = await fetch(u.toString(), {
    credentials: 'include',
    headers: authHeaders(),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_get_failed (${r.status})`);
  return j;
}

// ── Fulfilment / procurement (buyer-facing; operator actions live in admin-react) ──
export interface FulfillmentOption {
  option_id: string;
  option_type: string;
  title: string;
  estimated_delivery_at?: string | null;
  total_units: number;
  constraints_satisfied: { complete: boolean; deadline_met: boolean; within_budget: boolean };
  tradeoffs: string[];
}

export async function getFulfillmentCase(caseId: string, view: 'buyer' | 'operator' = 'buyer') {
  const u = new URL(apiUrl(`/api/v1/fulfillment/cases/${encodeURIComponent(caseId)}`), window.location.href);
  u.searchParams.set('view', view);
  const r = await fetch(u.toString(), { credentials: 'include', headers: authHeaders() });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `case_get_failed (${r.status})`);
  return j;
}

export async function getFulfillmentJourney(caseId: string) {
  const r = await fetch(apiUrl(`/api/v1/fulfillment/cases/${encodeURIComponent(caseId)}/journey`),
    { credentials: 'include', headers: authHeaders() });
  return (await safeJson(r)) || { journey: [] };
}

// Resolve the procurement case opened from a decision trace_id (the DecisionTrace ↔ journey link).
// Returns { case_id, ... } or null when no case was opened for this turn (404).
export async function getFulfillmentCaseByTrace(traceId: string): Promise<{ case_id: string } | null> {
  const r = await fetch(apiUrl(`/api/v1/fulfillment/cases/by-trace/${encodeURIComponent(traceId)}`),
    { credentials: 'include', headers: authHeaders() });
  if (r.status === 404) return null;
  const j = await safeJson(r);
  return (r.ok && j && j.case_id) ? j : null;
}

// ── Fluid procurement: the deferred sourcing PREVIEW + the cart-confirmation that materializes it ──
export interface SourcingIntentLine { item_ref: string; name?: string | null; quantity: number; shortfall?: number; }
export interface UnresolvedPhrase { phrase?: string | null; quantity?: number; }
export interface SourcingIntent {
  mode?: string; pr_id?: string | null;  // STABLE Procurement Request id — the order identity across amendments
  lines: SourcingIntentLine[]; planned_case_count?: number;
  unresolved_phrases?: UnresolvedPhrase[];  // phrases we couldn't match to a SKU — surfaced, never dropped
  requirements?: Record<string, any>;  // buyer deadline/use_case/ship_to → carried to the case at confirm
}
// P0 multi-intent plan (from chat.py's `multi_intent`, present only on a genuine mixed turn). The planner
// AMENDS a prior/chosen line's qty and SCOPES new-category lines to a budget; the card renders it for the
// buyer to CONFIRM (never auto-applies money/qty). One line: scope 'prior' (ref+requested_qty) or 'new'
// (category+budget+results).
export interface MultiIntentPickResult { sku?: string; name?: string; price?: number; price_cents?: number; }
export interface MultiIntentLine {
  scope: 'prior' | 'new';
  ref?: string; name?: string;                 // prior line: the chosen sku + its display name
  amended?: boolean;                            // prior line: THIS turn actually changed its qty (vs carried forward)
  category?: string;                            // new line: the category token
  requested_qty?: number | null;
  budget_min?: number | null; budget_max?: number | null;
  results?: MultiIntentPickResult[];            // new line: candidate picks within the scoped budget
}
export interface MultiIntentPlan {
  plan: MultiIntentLine[];
  verdict?: { ok: boolean; violations: string[]; checked_lines?: number };
  needs_confirmation?: boolean;
  objection_angle?: string | null;
  warnings?: string[];
}

export interface ConfirmCartResult {
  order_group_id: string | null;
  case_count?: number;
  cases?: Array<{ case_id: string; supplier_name?: string; total_quantity?: number }>;
  committed_count?: number;
  idempotent?: boolean;
  amend_required?: boolean;
  reason?: string;
  // supersede (amend after confirm) result shape:
  status?: 'superseded' | 'operator_required' | 'noop';
  superseded?: string[];
  operator_required?: Array<{ case_id: string; state: string }>;
  created?: { case_count: number; cases?: Array<{ case_id: string }> } | null;
}

// GATE 1 at the buyer's cart-confirmation: materialize the previewed shortfall lines into durable
// procurement cases, IDEMPOTENTLY keyed on order_id (re-clicking returns the same cases). No supplier
// is contacted. supersede=true → the buyer is amending a confirmed order: retire the old pre-send cases +
// re-source. Maps the preview's {item_ref, quantity} lines to the endpoint's {item_ref, requested_qty}.
export async function confirmCartSourcing(
  uid: string, orderId: string, lines: SourcingIntentLine[], traceId?: string, supersede = false,
  requirements?: Record<string, any>,
): Promise<ConfirmCartResult> {
  // bound the request so the cart/checkout bridge can never hang on a slow/stuck backend (8s).
  const _timeout = (typeof AbortSignal !== 'undefined' && (AbortSignal as any).timeout)
    ? (AbortSignal as any).timeout(8000) : undefined;
  const r = await fetch(apiUrl('/api/v1/fulfillment/cases/confirm-cart'), {
    method: 'POST', credentials: 'include', headers: authHeaders({}, true),
    signal: _timeout,
    body: JSON.stringify({
      uid: uid || 'demo-user',
      order_id: orderId,
      trace_id: traceId,
      supersede,
      requirements: requirements || undefined,
      lines: (lines || []).map((l) => ({
        item_ref: l.item_ref,
        requested_qty: l.quantity,
        source_qty: l.shortfall && l.shortfall > 0 ? l.shortfall : undefined,
      })),
    }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `confirm_cart_failed (${r.status})`);
  return j;
}

export async function commitFulfillmentCase(caseId: string, uid: string) {
  const r = await fetch(apiUrl(`/api/v1/fulfillment/cases/${encodeURIComponent(caseId)}/commit`), {
    method: 'POST', credentials: 'include', headers: authHeaders({}, true),
    body: JSON.stringify({ uid: uid || 'demo-user' }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `commit_failed (${r.status})`);
  return j;
}

export async function selectFulfillmentOption(caseId: string, uid: string, optionId: string) {
  const r = await fetch(apiUrl(`/api/v1/fulfillment/cases/${encodeURIComponent(caseId)}/select-option`), {
    method: 'POST', credentials: 'include', headers: authHeaders({}, true),
    body: JSON.stringify({ uid: uid || 'demo-user', option_id: optionId }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `select_failed (${r.status})`);
  return j;
}

export async function addCartItem(uid: string, sku: string, quantity = 1) {
  const r = await fetch(apiUrl('/api/v1/cart/items'), {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders({}, true),
    body: JSON.stringify({ uid: uid || 'demo-user', sku, quantity }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) {
    // detail may be a string OR the stock-gate object {error, available, ...} — surface a useful message
    // (not "[object Object]") so the UI can tell the buyer WHY the add was blocked (409 stock gate).
    const d = j && (j as any).detail;
    const msg = typeof d === 'string' ? d : (d && (d.error || JSON.stringify(d))) || `cart_add_failed (${r.status})`;
    throw new Error(msg);
  }
  return j;
}

// ── Market-intel storefront surfaces (M5): read-only copy-angle signals the storefront renders ──
export async function getStorefrontEmphasis(inventoryPosition = 'balanced'):
  Promise<{ messaging_emphasis?: string; demand_trend?: string; rationale?: string[] } | null> {
  const u = new URL(apiUrl('/api/v1/fulfillment/market/storefront-emphasis'), window.location.href);
  u.searchParams.set('inventory_position', inventoryPosition);
  const r = await fetch(u.toString(), { credentials: 'include', headers: authHeaders() });
  return (r.ok ? await safeJson(r) : null);
}

// ── Consumer-signal emitter (Track 2b): real buyer interactions → /consumer/ingest, so the marketing-BI
// channel / verified-human / conversion panels populate from ACTUAL browsing, not just the synthetic seed.
// Best-effort + fire-and-forget (never blocks or surfaces errors) and privacy-first — the endpoint hashes
// ids, sanitizes properties, derives coarse ASN/country, and drops the raw IP. Send coarse props only
// (no query text / PII); the visit's channel is stamped first-touch from the UTM params. ──
function _consumerSessionId(): string {
  try {
    let s = sessionStorage.getItem('ss_sid');
    if (!s) { s = 'sid-' + Math.random().toString(36).slice(2, 12); sessionStorage.setItem('ss_sid', s); }
    return s;
  } catch { return 'sid-ephemeral'; }
}
export function emitConsumerSignal(uid: string, action: string, properties: Record<string, any> = {}): void {
  try {
    const body = [{
      uid: uid || 'demo-user',
      session_id: _consumerSessionId(),
      action,
      path: (typeof window !== 'undefined' && window.location ? window.location.pathname : '/') || '/',
      properties,
    }];
    fetch(apiUrl('/api/v1/consumer/ingest'), {
      method: 'POST', credentials: 'include', headers: authHeaders({}, true),
      body: JSON.stringify(body), keepalive: true,
    }).catch(() => { /* best-effort telemetry */ });
  } catch { /* best-effort */ }
}
let _pageViewEmitted = false;
export function emitPageView(uid: string): void {
  if (_pageViewEmitted) return;   // first-touch visit — one per session/page load
  _pageViewEmitted = true;
  const props: Record<string, any> = {};
  try {
    const p = new URLSearchParams(window.location.search);
    for (const k of ['utm_source', 'utm_medium', 'utm_campaign']) { const v = p.get(k); if (v) props[k] = v; }
    if (document.referrer) props.referrer = document.referrer;
  } catch { /* ignore */ }
  emitConsumerSignal(uid, 'page_view', props);
}

export async function getSupportResponse(objection?: string):
  Promise<{ objection_theme?: string; response_angle?: string; guidance?: string } | null> {
  const u = new URL(apiUrl('/api/v1/fulfillment/market/support-response'), window.location.href);
  if (objection) u.searchParams.set('objection', objection);
  const r = await fetch(u.toString(), { credentials: 'include', headers: authHeaders() });
  return (r.ok ? await safeJson(r) : null);
}

// SET a line's absolute quantity (the cart stepper / "change your mind" control). qty<=0 removes it.
export async function setCartItemQty(uid: string, sku: string, quantity: number, allowSourcing = false) {
  const r = await fetch(apiUrl(`/api/v1/cart/items/${encodeURIComponent(sku)}`), {
    method: 'PUT',
    credentials: 'include',
    headers: authHeaders({}, true),
    // allow_sourcing lets a procurement amendment ("15 instead") exceed on-hand stock — the shortfall is
    // sourced at confirm-cart — instead of a 409. Off by default so the normal stepper keeps the stock gate.
    body: JSON.stringify({ uid: uid || 'demo-user', sku, quantity: Math.max(0, Math.floor(quantity)), allow_sourcing: allowSourcing }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) {
    const d = j && (j as any).detail;
    const msg = typeof d === 'string' ? d : (d && (d.error || JSON.stringify(d))) || `cart_set_qty_failed (${r.status})`;
    throw new Error(msg);
  }
  return j;
}

export async function removeCartItem(uid: string, sku: string) {
  const u = new URL(apiUrl(`/api/v1/cart/items/${encodeURIComponent(sku)}`), window.location.href);
  u.searchParams.set('uid', uid || 'demo-user');
  const r = await fetch(u.toString(), {
    method: 'DELETE',
    credentials: 'include',
    headers: authHeaders(),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_remove_failed (${r.status})`);
  return j;
}

export async function clearCart(uid: string) {
  const u = new URL(apiUrl('/api/v1/cart/clear'), window.location.href);
  u.searchParams.set('uid', uid || 'demo-user');
  const r = await fetch(u.toString(), {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders(),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_clear_failed (${r.status})`);
  return j;
}
