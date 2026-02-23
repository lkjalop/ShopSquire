const rawBase = (import.meta as any).env?.VITE_API_BASE_URL as string | undefined;
const API_BASE = rawBase ? rawBase.replace(/\/+$/, '') : '';
const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';

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
    headers: {
      'Content-Type': 'application/json',
      ...(API_KEY ? { 'x-api-key': API_KEY } : {}),
    },
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
    headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
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
    headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
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
    headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_get_failed (${r.status})`);
  return j;
}

export async function addCartItem(uid: string, sku: string, quantity = 1) {
  const r = await fetch(apiUrl('/api/v1/cart/items'), {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(API_KEY ? { 'x-api-key': API_KEY } : {}),
    },
    body: JSON.stringify({ uid: uid || 'demo-user', sku, quantity }),
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_add_failed (${r.status})`);
  return j;
}

export async function removeCartItem(uid: string, sku: string) {
  const u = new URL(apiUrl(`/api/v1/cart/items/${encodeURIComponent(sku)}`), window.location.href);
  u.searchParams.set('uid', uid || 'demo-user');
  const r = await fetch(u.toString(), {
    method: 'DELETE',
    credentials: 'include',
    headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
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
    headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_clear_failed (${r.status})`);
  return j;
}
