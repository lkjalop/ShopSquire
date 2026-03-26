# ShopSquire — Frontend Hardening Plan (Port 5173 + 8080 UI Routes)
**Date:** 2026-03-26
**Scope:** React/TypeScript frontend (Vite, port 5173), server-side HTML UI routes (port 8080), Admin Dashboard, Email Lab, Storefront
**Frameworks:** PCI DSS 4.0 Req 6, OWASP Top 10 2025, OWASP LLM Top 10 2025, ISO 27001 A.8.9, GDPR Art 25

---

## Overview

ShopSquire has two distinct frontend surfaces:
1. **Port 5173** — Vite-served React SPA (development) / CDN-served static bundle (production)
   - Components: `AdminDashboard`, `ChatOverlay`, `ProductGrid`, `DecisionTrace`, `EscalationRoom`, `ImageRecommendPanel`, `CartPanel`, `LoginModal`, `OOBVerification`
2. **Port 8080 (UI routes)** — FastAPI server-side HTML rendered via `ui.py` / `ui_storefront.py`
   - Email Security Lab (`/merchant/email-lab`)
   - Merchant Dashboard
   - Vision triage pages

Both surfaces call the same backend API at port 8080.

---

## CRITICAL — Frontend

---

### FE-CRIT-01 — No Content Security Policy
**File:** [frontend/vite.config.ts](frontend/vite.config.ts) + [src/app/main.py](src/app/main.py)

**Current state:** No CSP header on any response. XSS in any component → full app compromise, including ability to exfiltrate JWT tokens, cart state, and decision traces.

**PCI DSS 4.0 Req 6.4.3** mandates CSP for payment pages. Admin dashboard views payment data.

**Fix — `frontend/vite.config.ts`:**
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    headers: {
      'X-Frame-Options': 'DENY',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
      // Start with report-only in dev, enforce in prod build
      'Content-Security-Policy-Report-Only':
        "default-src 'self'; " +
        "script-src 'self' 'unsafe-eval'; " +        // unsafe-eval needed for Vite HMR only
        "style-src 'self' 'unsafe-inline'; " +
        "img-src 'self' data: blob: https:; " +
        "connect-src 'self' http://localhost:8080 ws://localhost:8080 ws://localhost:5173; " +
        "media-src 'self' blob:; " +
        "worker-src blob:; " +
        "frame-ancestors 'none'; " +
        "report-uri http://localhost:8080/api/v1/security/csp-report",
    }
  },
  build: {
    // Production: inject CSP meta tag or handle via nginx/CDN
    rollupOptions: {
      output: {
        // Content hashing for cache busting
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
      }
    }
  }
})
```

**Add CSP report endpoint to backend — `src/app/routers/security_integrations.py` or new route:**
```python
@router.post("/api/v1/security/csp-report")
async def csp_report(request: Request):
    body = await request.json()
    report = body.get("csp-report", body)
    logger.warning("CSP_VIOLATION document=%s violated=%s blocked=%s",
        report.get("document-uri"),
        report.get("violated-directive"),
        report.get("blocked-uri"),
    )
    # Emit to SIEM / security event bus
    await telemetry_emit("shopsquire:csp_violation", report)
    return {"status": "received"}
```

---

### FE-CRIT-02 — JWT/Session stored in localStorage (XSS-extractable)
**File:** [frontend/src/App.tsx](frontend/src/App.tsx) + [frontend/src/lib/api.ts](frontend/src/lib/api.ts)

**Current state:**
```typescript
localStorage.setItem('ss_owner_key', key)  // from email-check.png finding
```
`localStorage` is accessible to any JavaScript on the page. XSS → exfiltrate token → account takeover.

**Fix:** Move sensitive tokens to `httpOnly` cookies set by the backend. For keys that must be client-side (admin key for email lab), use `sessionStorage` (cleared on tab close) instead of `localStorage`, and pair with CSP + short expiry:

```typescript
// frontend/src/lib/auth.ts
export function setOwnerKey(key: string) {
  // sessionStorage only — cleared when tab/browser closes
  sessionStorage.setItem('ss_owner_key', key);
}
export function getOwnerKey(): string | null {
  return sessionStorage.getItem('ss_owner_key');
}
export function clearOwnerKey() {
  sessionStorage.removeItem('ss_owner_key');
}
```

For the JWT session token — exclusively use `httpOnly; Secure; SameSite=Strict` cookies. Remove any `localStorage.getItem('token')` patterns in `api.ts`.

---

### FE-CRIT-03 — No CSRF protection on state-changing requests
**File:** [frontend/src/lib/api.ts](frontend/src/lib/api.ts) + [src/app/routers/auth.py](src/app/routers/auth.py)

**Fix (double-submit cookie pattern):**

Backend — issue a non-httpOnly CSRF cookie alongside the session cookie:
```python
# auth.py — on login success
csrf_token = secrets.token_urlsafe(32)
response.set_cookie("ss_csrf", csrf_token, httponly=False, secure=not is_local, samesite="Strict")
response.set_cookie("ss_session", jwt_token, httponly=True, secure=not is_local, samesite="Strict")
```

Frontend — read CSRF cookie and send as header on all mutating requests:
```typescript
// frontend/src/lib/api.ts
function getCsrfToken(): string {
  return document.cookie
    .split(';')
    .find(c => c.trim().startsWith('ss_csrf='))
    ?.split('=')[1] ?? '';
}

export async function apiPost(path: string, body: unknown) {
  return fetch(apiUrl(path), {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCsrfToken(),
    },
    body: JSON.stringify(body),
  });
}
```

Backend CSRF validation middleware — `src/app/security/csrf_middleware.py`:
```python
from starlette.middleware.base import BaseHTTPMiddleware
import hmac

CSRF_EXEMPT = {"/api/v1/auth/login", "/api/v1/security/csp-report", "/health"}

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        if request.url.path in CSRF_EXEMPT:
            return await call_next(request)
        cookie_token = request.cookies.get("ss_csrf", "")
        header_token = request.headers.get("X-CSRF-Token", "")
        if not cookie_token or not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse({"detail": "csrf_validation_failed"}, status_code=403)
        return await call_next(request)
```

---

### FE-CRIT-04 — Admin Dashboard accessible without role verification on load
**File:** [frontend/src/components/AdminDashboard.tsx](frontend/src/components/AdminDashboard.tsx)

**Current state:**
The admin dashboard component is rendered client-side when a certain tab is selected. If the API key check is client-side only, a user can manipulate the DOM/state to access admin views.

**Fix — server-side role check before any admin data is loaded:**
```typescript
// AdminDashboard.tsx — add at top of component:
const { data: roleCheck, error } = useSWR('/api/v1/auth/me', apiFetch);
if (error || roleCheck?.role !== 'admin') {
  return <div className="error">Access denied. Requires admin role.</div>;
}
```

**Also add `require_role(ROLE_OWNER, ROLE_MERCHANT)` to every `/api/v1/admin/` endpoint** — verify these are not callable with a basic user JWT.

---

## HIGH — Frontend

---

### FE-HIGH-01 — File upload in ImageRecommendPanel lacks server-side validation
**File:** [frontend/src/components/ImageRecommendPanel.tsx](frontend/src/components/ImageRecommendPanel.tsx) + [src/app/routers/vision.py](src/app/routers/vision.py)

**Problem:** Images are uploaded from the frontend and processed by CV pipeline. If file type validation only happens client-side (`accept="image/*"`), an attacker can POST arbitrary files.

**Fix — backend `vision.py`:**
```python
from src.app.security.file_validator import validate_image_upload

@router.post("/api/v1/vision/analyze")
async def analyze_image(file: UploadFile, ...):
    content = await file.read()
    verdict = validate_image_upload(content, file.filename, max_bytes=10 * 1024 * 1024)
    if not verdict.ok:
        raise HTTPException(400, detail=f"File rejected: {verdict.reason}")
```

`file_validator.py` — check: magic bytes match declared MIME type, file size limit, no embedded scripts (polyglot attack), no EXIF GPS exfil.

---

### FE-HIGH-02 — OOBVerification component sends phone/email in plaintext query params
**File:** [frontend/src/components/OOBVerification.tsx](frontend/src/components/OOBVerification.tsx)

**Problem:** If OOB verification (out-of-band supplier/identity check) passes phone number or email via URL query params, those values appear in browser history, server logs, and referrer headers.

**Fix:** Use POST body for all OOB verification requests. Never include PII in URL query parameters:
```typescript
// Instead of: fetch(`/api/v1/oob/verify?phone=${phone}`)
// Use:
fetch('/api/v1/oob/verify', {
  method: 'POST',
  body: JSON.stringify({ contact: phone, method: 'sms' }),
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
});
```

---

### FE-HIGH-03 — DecisionTrace renders raw HTML from API response
**File:** [frontend/src/components/DecisionTrace.tsx](frontend/src/components/DecisionTrace.tsx)

**Problem:** If any part of the decision trace uses `dangerouslySetInnerHTML` to render agent step content, an agent prompt injection that writes HTML could execute in the admin's browser.

**Fix:** Audit `DecisionTrace.tsx` for any `dangerouslySetInnerHTML` usage. Replace with:
```typescript
import DOMPurify from 'dompurify';

// If HTML rendering is required:
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(content) }} />

// For plain text (preferred):
<pre className={styles.traceContent}>{content}</pre>
```

Add `dompurify` to `package.json` dependencies.

---

### FE-HIGH-04 — No rate limiting on authentication endpoints from frontend
**File:** [frontend/src/components/LoginModal.tsx](frontend/src/components/LoginModal.tsx) + [src/app/routers/auth.py](src/app/routers/auth.py)

**Problem:** The login modal does not implement exponential backoff or lockout on repeated failures at the UI level. While backend has brute-force detection (`check_bruteforce` in `auth.py`), the frontend keeps retrying without delay.

**Fix — `LoginModal.tsx`:**
```typescript
const [attempts, setAttempts] = useState(0);
const [locked, setLocked] = useState(false);

async function handleLogin() {
  if (locked) return;
  const resp = await apiFetch('/api/v1/auth/login', { method: 'POST', body: creds });
  if (!resp.ok) {
    const newAttempts = attempts + 1;
    setAttempts(newAttempts);
    if (newAttempts >= 5) {
      setLocked(true);
      setTimeout(() => { setLocked(false); setAttempts(0); }, 30_000); // 30s lockout
    }
  }
}
```

---

### FE-HIGH-05 — No subresource integrity (SRI) on external scripts
**File:** [frontend/index.html](frontend/index.html) + build pipeline

**Problem:** If any external scripts or fonts are loaded without SRI hashes, a CDN compromise injects malicious code without detection.

**Fix — audit `index.html` and Vite config:** For any `<script src="https://...">` or `<link href="https://...">`, add `integrity` and `crossorigin` attributes:
```html
<script
  src="https://cdn.example.com/lib.min.js"
  integrity="sha384-HASH_HERE"
  crossorigin="anonymous"
></script>
```

For Vite-bundled assets, all third-party code is inlined — no SRI needed. Prefer bundling over CDN links for all critical dependencies.

---

## MEDIUM — Frontend

---

### FE-MED-01 — ChatOverlay sends full conversation history on every turn (PII accumulation)
**File:** [frontend/src/components/ChatOverlay.tsx](frontend/src/components/ChatOverlay.tsx)

**Problem:** If the chat component sends the full `messages` array on each request, past messages containing PII (customer names, emails mentioned by user) accumulate in each request body — appearing in backend access logs and potentially being sent to the LLM.

**Fix:** Send only a session reference + the current message. Backend reconstructs context from Redis session memory:
```typescript
// Instead of sending full history:
const payload = { session_id: sessionId, message: currentMessage };
// Backend loads context from Redis session:{uid}:recent_retrieval
```

---

### FE-MED-02 — No error boundary for security-sensitive components
**File:** [frontend/src/components/AppErrorBoundary.tsx](frontend/src/components/AppErrorBoundary.tsx)

**Problem:** If `DecisionTrace`, `AdminDashboard`, or `EscalationRoom` throw an unhandled error, React may render raw error stack traces containing file paths, component names, and potentially sensitive state.

**Fix — verify `AppErrorBoundary.tsx` wraps all sensitive components:**
```typescript
// App.tsx — wrap admin and security components:
<AppErrorBoundary fallback={<div>Something went wrong. Please reload.</div>}>
  <AdminDashboard />
</AppErrorBoundary>
```

**In `AppErrorBoundary.tsx`:** In production (`import.meta.env.PROD`), never render `error.stack` — log it server-side instead via an error reporting endpoint.

---

### FE-MED-03 — Image data URLs stored in chat message state (memory leak + PII risk)
**File:** [frontend/src/App.tsx:~45](frontend/src/App.tsx#L45)

**Current state:**
```typescript
images?: string[];  // data-URL thumbnails shown inline
```
Full base64-encoded image data URLs stored in React state for every message. With long conversations, this accumulates megabytes of image data in-memory and in any state persistence.

**Fix:** Replace stored `data:image/...;base64,...` with blob URLs + object URL revocation:
```typescript
// When image is uploaded:
const blobUrl = URL.createObjectURL(file);
// When message is cleared or component unmounts:
URL.revokeObjectURL(blobUrl);
// Never store full base64 in message state — use a Map<messageId, File> instead
```

---

### FE-MED-04 — Admin dashboard polling interval not configurable (DoS risk)
**File:** [frontend/src/components/AdminDashboard.tsx](frontend/src/components/AdminDashboard.tsx)

**Problem:** If the admin dashboard polls decision traces, metrics, or alerts on a short fixed interval, a tab left open in the background continuously hammers the backend.

**Fix:** Use visibility API to pause polling when tab is hidden:
```typescript
useEffect(() => {
  const handleVisibility = () => {
    if (document.hidden) stopPolling();
    else startPolling();
  };
  document.addEventListener('visibilitychange', handleVisibility);
  return () => document.removeEventListener('visibilitychange', handleVisibility);
}, []);
```

---

### FE-MED-05 — No client-side audit log for admin actions
**File:** [frontend/src/components/AdminDashboard.tsx](frontend/src/components/AdminDashboard.tsx)

**Problem:** Admin actions (acknowledge incident, disable agent, run supply-chain scan) have no client-side confirmation or evidence trail visible to the operator. Under ISO 27001 A.8.15, admin actions should be logged.

**Fix:** After every destructive admin action, POST an audit event:
```typescript
async function auditAdminAction(action: string, target: string, outcome: string) {
  await apiFetch('/api/v1/audit/admin-action', {
    method: 'POST',
    body: JSON.stringify({ action, target, outcome, timestamp: new Date().toISOString() }),
  });
}
// Usage: await auditAdminAction('disable_agent', 'fraud_scorer', 'success');
```

---

## Server-Side HTML UI Routes (Port 8080) — `/merchant/email-lab`

---

### FE-8080-01 — Email Lab renders user-controlled content without escaping
**File:** [src/app/routers/ui.py](src/app/routers/ui.py) or [src/app/routers/ui_storefront.py](src/app/routers/ui_storefront.py)

**Problem:** If the email analysis result (parsed from potentially malicious email bodies) is rendered into the server-side HTML template without proper escaping, an attacker can send a crafted email that injects HTML into the email lab UI — XSS via the email content itself.

**Fix:** Ensure all template variables are HTML-escaped. If using Jinja2:
```python
# Jinja2 auto-escaping must be enabled for HTML templates
from jinja2 import Environment, select_autoescape
env = Environment(autoescape=select_autoescape(['html', 'htm']))
# Never use | safe filter on user-controlled content
```

---

### FE-8080-02 — Email Lab SSE stream not rate-limited
**File:** [src/app/routers/email_security.py](src/app/routers/email_security.py)

**Problem:** The "Agents" SSE simulation endpoint streams results indefinitely. Without rate limiting, a single client can hold many SSE connections open, exhausting server file descriptors.

**Fix:**
```python
@router.get("/api/v1/email_security/agents/stream")
async def agent_stream(request: Request, _=Depends(rate_limit_dep(per_minute=10))):
    # Also enforce max concurrent SSE connections per API key
    async def event_generator():
        for i, event in enumerate(simulation_events):
            if await request.is_disconnected():
                break
            if i > 50:  # max events per stream
                break
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

## Production Deployment Checklist (Frontend)

Before going live with any customer traffic:

- [ ] CSP enforced (not report-only) with nonce-based script allowlist
- [ ] HSTS header with `max-age=31536000; includeSubDomains; preload`
- [ ] All cookies: `httpOnly`, `Secure`, `SameSite=Strict`
- [ ] CSRF double-submit token on all state-changing requests
- [ ] Admin dashboard behind 2FA (TOTP via `admin_mfa.py`)
- [ ] Session idle timeout: 15 minutes for admin, 60 minutes for storefront
- [ ] File upload: server-side magic byte validation, 10MB limit
- [ ] No `localStorage` for session tokens — `sessionStorage` at minimum, `httpOnly` cookies preferred
- [ ] `dangerouslySetInnerHTML` only with DOMPurify sanitization
- [ ] SRI on any external script tags
- [ ] Error boundaries on all sensitive components (no stack traces to end users in prod)
- [ ] Vite build output: content-hashed filenames, source maps NOT deployed to production CDN
- [ ] Dependency audit: `npm audit --audit-level=high` passes in CI
- [ ] `robots.txt` disallows `/merchant/`, `/api/`, `/admin/` paths

---

*Back to: [COMPLIANCE-MASTER-ACTION-PLAN.md](COMPLIANCE-MASTER-ACTION-PLAN.md)*
