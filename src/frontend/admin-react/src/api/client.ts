// Shared API client for the operator (admin-react). One place owns the base URL, the API-key + CSRF
// headers, and the http<T>/httpResponse helpers. Domain modules (decisions/fulfillment/marketIntel/…)
// import from here so each domain can be tested + mocked independently.

const API_BASE = (import.meta.env.VITE_API_BASE as string) || window.location.origin;
const API_KEY_ENV = (import.meta.env.VITE_API_KEY as string) || '';
// Hydrate from sessionStorage so a hard navigation (e.g. ?tab=procurement) keeps the key without
// re-prompting. sessionStorage (not localStorage) = cleared on tab close; production should prefer an
// HttpOnly cookie/session over any browser-stored key.
let VOLATILE_API_KEY = (() => { try { return sessionStorage.getItem('shopsquire_admin_api_key') || ''; } catch { return ''; } })();
const STATE_CHANGING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function apiBase(): string {
  // Every domain path hardcodes its own `/api/v1` prefix, so the base must NOT also end in one —
  // otherwise the join doubles to `/api/v1/api/v1/...` (a real 404 when VITE_API_BASE is set to
  // `http://host:8080/api/v1`). Strip a trailing `/api/v1` and any trailing slash so BOTH
  // `http://host:8080` and `http://host:8080/api/v1` resolve correctly.
  return API_BASE.replace(/\/$/, '').replace(/\/api\/v1$/, '');
}

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
  try { sessionStorage.setItem('shopsquire_admin_api_key', VOLATILE_API_KEY); } catch { /* storage unavailable */ }
}

export function clearClientApiKey() {
  VOLATILE_API_KEY = '';
  try { sessionStorage.removeItem('shopsquire_admin_api_key'); } catch { /* storage unavailable */ }
}

function buildHeaders(opts?: RequestInit, withContentType = true): Record<string, string> {
  const headers: Record<string, string> = withContentType ? { 'Content-Type': 'application/json' } : {};
  if (opts?.headers) {
    if (opts.headers instanceof Headers) {
      opts.headers.forEach((value, key) => { headers[key] = value; });
    } else if (Array.isArray(opts.headers)) {
      opts.headers.forEach(([key, value]) => { headers[key] = value; });
    } else {
      Object.assign(headers, opts.headers as Record<string, string>);
    }
  }
  const key = getApiKey();
  if (key) headers['x-api-key'] = key;
  const method = String(opts?.method || 'GET').toUpperCase();
  if (STATE_CHANGING.has(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  return headers;
}

async function raiseForStatus(r: Response): Promise<void> {
  if (r.ok) return;
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

export async function http<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(`${apiBase()}${path}`, { ...opts, headers: buildHeaders(opts), credentials: 'include' });
  await raiseForStatus(r);
  return r.json();
}

export async function httpResponse(path: string, opts?: RequestInit): Promise<Response> {
  const r = await fetch(`${apiBase()}${path}`, { ...opts, headers: buildHeaders(opts, false), credentials: 'include' });
  await raiseForStatus(r);
  return r;
}
