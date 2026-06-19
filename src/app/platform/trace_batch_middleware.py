"""Pure-ASGI middleware that batches durable trace-event writes for the recommend hot path.

The recommend route emits tens of durable `log_trace_event` calls per request, each a sync DB
INSERT. This middleware opens a trace batch on entry and flushes ONE bulk insert after the response
is sent — moving the audit-write cost off the request's critical path while preserving every event.

Pure-ASGI (not BaseHTTPMiddleware) so the batch ContextVar set here reaches the (threadpool-run)
sync route — the same propagation requirement as the StoreProfile selector. Scoped to the recommend
path so the blast radius is bounded; all other routes keep per-event writes.
"""
from __future__ import annotations

from src.app.services.decision_log import begin_trace_batch, flush_trace_batch

_BATCH_PATH_PREFIXES = ("/api/v1/recommend",)


class TraceBatchMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if not any(path.startswith(p) for p in _BATCH_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return
        token = begin_trace_batch()
        try:
            await self.app(scope, receive, send)
        finally:
            # Flush AFTER the response is sent — the buyer gets the recommendation first; the
            # audit rows persist in one write just after. Never raises (flush is best-effort).
            try:
                flush_trace_batch(token)
            except Exception:
                pass
