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
export interface SourcingIntentLine { item_ref: string; quantity: number; shortfall?: number; }
export interface UnresolvedPhrase { phrase?: string | null; quantity?: number; }
export interface SourcingIntent {
  mode?: string; pr_id?: string | null;  // STABLE Procurement Request id — the order identity across amendments
  lines: SourcingIntentLine[]; planned_case_count?: number;
  unresolved_phrases?: UnresolvedPhrase[];  // phrases we couldn't match to a SKU — surfaced, never dropped
  requirements?: Record<string, any>;  // buyer deadline/use_case/ship_to → carried to the case at confirm
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
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_add_failed (${r.status})`);
  return j;
}

// SET a line's absolute quantity (the cart stepper / "change your mind" control). qty<=0 removes it.
export async function setCartItemQty(uid: string, sku: string, quantity: number) {
  const r = await fetch(apiUrl(`/api/v1/cart/items/${encodeURIComponent(sku)}`), {
    method: 'PUT',
    credentials: 'include',
    headers: authHeaders({}, true),
    body: JSON.stringify({ uid: uid || 'demo-user', sku, quantity: Math.max(0, Math.floor(quantity)) }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_set_qty_failed (${r.status})`);
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
