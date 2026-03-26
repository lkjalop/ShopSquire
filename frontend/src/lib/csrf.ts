/**
 * CRIT-08 — CSRF token helper (double-submit cookie pattern).
 *
 * The backend (CSRFMiddleware) issues a non-httpOnly ``ss_csrf`` cookie on
 * login.  Every state-changing request (POST/PUT/PATCH/DELETE) must include
 * the cookie value in the ``X-CSRF-Token`` header.  This file provides:
 *
 *   - ``getCsrfToken()``   — reads the cookie value
 *   - ``csrfHeaders()``    — returns the header object to spread into fetch()
 *   - ``apiFetch()``       — opinionated fetch wrapper that adds CSRF + API key
 *
 * Usage:
 *   import { apiFetch } from '@/lib/csrf';
 *   const data = await apiFetch('/api/v1/payments/checkout', { method: 'POST', body: JSON.stringify(payload) });
 */

import { apiUrl } from './api';

const CSRF_COOKIE = 'ss_csrf';
const CSRF_HEADER = 'X-CSRF-Token';

/** Read the CSRF token from the browser cookie jar. */
export function getCsrfToken(): string {
  if (typeof document === 'undefined') return '';
  const entry = document.cookie
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${CSRF_COOKIE}=`));
  return entry ? entry.slice(CSRF_COOKIE.length + 1) : '';
}

/** Returns an object suitable for spreading into fetch() headers. */
export function csrfHeaders(): Record<string, string> {
  const token = getCsrfToken();
  return token ? { [CSRF_HEADER]: token } : {};
}

/**
 * Thin fetch wrapper that automatically:
 *   - Attaches ``X-CSRF-Token`` on state-changing methods
 *   - Sends ``credentials: 'include'`` so session cookies travel with the request
 *   - Attaches ``x-api-key`` if VITE_API_KEY is set
 *   - Converts non-ok responses into thrown Error objects with the response body
 *
 * @param path    API path (e.g. '/api/v1/payments/checkout')
 * @param init    Standard RequestInit — method defaults to 'GET'
 * @returns       Parsed JSON response (or null if no body)
 */
const STATE_CHANGING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const API_KEY = (import.meta as any).env?.VITE_API_KEY as string | undefined;

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();
  const extraHeaders: Record<string, string> = {};

  if (STATE_CHANGING.has(method)) {
    const token = getCsrfToken();
    if (token) extraHeaders[CSRF_HEADER] = token;
  }
  if (API_KEY) extraHeaders['x-api-key'] = API_KEY;

  const response = await fetch(apiUrl(path), {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...extraHeaders,
      ...(init.headers as Record<string, string> | undefined ?? {}),
    },
  });

  if (!response.ok) {
    let detail: string;
    try {
      const body = await response.json();
      detail = body?.detail ?? body?.message ?? response.statusText;
    } catch {
      detail = response.statusText;
    }
    const err = new Error(`${method} ${path} → ${response.status}: ${detail}`) as Error & { status: number };
    err.status = response.status;
    throw err;
  }

  // Return null for 204 No Content
  if (response.status === 204) return null as T;

  try {
    return (await response.json()) as T;
  } catch {
    return null as T;
  }
}
