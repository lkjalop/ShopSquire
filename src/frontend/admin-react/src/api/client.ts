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
export const DEFAULT_HTTP_TIMEOUT_MS = 30_000;

export interface HttpOptions extends RequestInit {
  /** Caller-visible deadline. Set a larger explicit value only for a known bounded batch operation. */
  timeoutMs?: number;
}

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
  return VOLATILE_API_KEY || API_KEY_ENV || '';
}

export function setClientApiKey(key: string) {
  VOLATILE_API_KEY = String(key || '').trim();
  try { sessionStorage.setItem('shopsquire_admin_api_key', VOLATILE_API_KEY); } catch { /* storage unavailable */ }
}

export function clearClientApiKey() {
  VOLATILE_API_KEY = '';
  try { sessionStorage.removeItem('shopsquire_admin_api_key'); } catch { /* storage unavailable */ }
}

function buildHeaders(opts?: HttpOptions, withContentType = true): Record<string, string> {
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

async function fetchWithDeadline<T>(
  path: string,
  opts: HttpOptions | undefined,
  withContentType: boolean,
  consume: (response: Response) => Promise<T>,
): Promise<T> {
  const { timeoutMs: requestedTimeout, signal: callerSignal, ...requestOpts } = opts || {};
  const timeoutMs = Math.max(1, Math.min(Number(requestedTimeout ?? DEFAULT_HTTP_TIMEOUT_MS), 300_000));
  const controller = new AbortController();
  const forwardAbort = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) forwardAbort();
  else callerSignal?.addEventListener('abort', forwardAbort, { once: true });
  const timer = window.setTimeout(() => controller.abort(
    new DOMException(`Request exceeded ${timeoutMs}ms deadline`, 'TimeoutError'),
  ), timeoutMs);
  try {
    const response = await fetch(`${apiBase()}${path}`, {
      ...requestOpts,
      headers: buildHeaders(opts, withContentType),
      credentials: 'include',
      signal: controller.signal,
    });
    await raiseForStatus(response);
    return await consume(response);
  } catch (error) {
    // Body readers may report a generic AbortError. Keep the actual caller or
    // deadline reason so the UI can distinguish cancellation from a timeout.
    if (controller.signal.aborted) throw controller.signal.reason ?? error;
    throw error;
  } finally {
    window.clearTimeout(timer);
    callerSignal?.removeEventListener('abort', forwardAbort);
  }
}

export async function http<T>(path: string, opts?: HttpOptions): Promise<T> {
  return fetchWithDeadline(path, opts, true, response => response.json());
}

export async function httpResponse(path: string, opts?: HttpOptions): Promise<Response> {
  return fetchWithDeadline(path, opts, false, async response => {
    if (!response.body) return response;
    // The export caller consumes a complete blob. Finish that read while the
    // deadline still owns the request, then return readable response content.
    const body = await response.arrayBuffer();
    return new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  });
}
