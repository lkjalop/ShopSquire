const rawBase = (import.meta as any).env?.VITE_API_BASE_URL as string | undefined;
const API_BASE = rawBase ? rawBase.replace(/\/+$/, '') : '';

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
  labels?: string[];
  extracted_text?: string | null;
  provider?: string;
  model?: string;
  images?: Array<{ name: string; size: number; type: string; width?: number; height?: number; sha256?: string; phash?: string }>;
  description?: string;
  issue_type?: string;
}) {
  const r = await fetch(apiUrl('/api/v1/cv/analyze'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key',
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

export async function getCart(uid: string) {
  const u = new URL(apiUrl('/api/v1/cart'), window.location.href);
  u.searchParams.set('uid', uid || 'demo-user');
  const r = await fetch(u.toString(), {
    headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_get_failed (${r.status})`);
  return j;
}

export async function addCartItem(uid: string, sku: string, quantity = 1) {
  const r = await fetch(apiUrl('/api/v1/cart/items'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key',
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
    headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
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
    headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
  });
  const j = await safeJson(r);
  if (!r.ok || !j) throw new Error((j && j.detail) ? j.detail : `cart_clear_failed (${r.status})`);
  return j;
}
