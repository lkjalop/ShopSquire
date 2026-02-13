from __future__ import annotations

import hashlib
import json
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.app.models.db import db_session


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        # lightweight cache for recent keys
        try:
            if not hasattr(self.app.state, "idempotency_cache"):
                self.app.state.idempotency_cache = {}
        except Exception:
            pass
        # TTL in seconds
        try:
            self.ttl = int(__import__("os").getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
        except Exception:
            self.ttl = 86400

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        if method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)
        # Only enforce when header present
        key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
        if not key:
            return await call_next(request)
        # Compute fingerprint: method + path + body hash
        try:
            body = await request.body()
        except Exception:
            body = b""
        fp_src = f"{method}|{request.url.path}|" + hashlib.sha256(body or b"").hexdigest()
        fingerprint = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()

        # Check in-memory cache first
        now = time.time()
        try:
            cache = getattr(self.app.state, "idempotency_cache", {})
            entry = cache.get(key)
            if entry and entry.get("fingerprint") == fingerprint and (now - float(entry.get("ts", 0))) < self.ttl:
                return ORJSONResponse(entry.get("body") or {}, status_code=int(entry.get("status") or 200))
        except Exception:
            pass

        # Check DB table next
        try:
            with db_session() as db:
                row = db.execute(
                    "SELECT response_status, response_body, created_at FROM idempotency_keys WHERE key = :k AND fingerprint = :fp",
                    {"k": key, "fp": fingerprint},
                ).fetchone()
                if row:
                    try:
                        resp_body = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
                    except Exception:
                        resp_body = row[1] or {}
                    status = int(row[0] or 200)
                    try:
                        cache[key] = {"fingerprint": fingerprint, "body": resp_body, "status": status, "ts": now}
                    except Exception:
                        pass
                    return ORJSONResponse(resp_body, status_code=status)
        except Exception:
            pass

        # Process request and store response
        response = await call_next(request)
        try:
            status = int(getattr(response, "status_code", 200))
        except Exception:
            status = 200
        # Extract body from ORJSONResponse or fallback
        resp_payload: Optional[dict] = None
        try:
            if hasattr(response, "body") and response.body:
                resp_payload = json.loads(response.body.decode("utf-8"))
        except Exception:
            resp_payload = None
        if resp_payload is None:
            resp_payload = {"status": status}

        # Persist best-effort
        try:
            with db_session() as db:
                db.execute(
                    "INSERT OR REPLACE INTO idempotency_keys (key, fingerprint, response_status, response_body) VALUES (:k, :fp, :st, :rb)",
                    {"k": key, "fp": fingerprint, "st": status, "rb": json.dumps(resp_payload, ensure_ascii=False)},
                )
                try:
                    db.commit()
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            getattr(self.app.state, "idempotency_cache", {})[key] = {
                "fingerprint": fingerprint,
                "body": resp_payload,
                "status": status,
                "ts": now,
            }
        except Exception:
            pass
        return response
