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

        # Ensure the dedup table exists (schema shared with payments._idempotent).
        try:
            with db_session() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS idempotency_keys "
                    "(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response_status INT, "
                    "response_body TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                )
                db.commit()
        except Exception:
            pass

        # ATOMIC RESERVE-OR-REPLAY (P0-1a): one INSERT ... ON CONFLICT DO NOTHING is the lock, so two
        # concurrent duplicates can't both proceed (the old SELECT-then-process was check-then-act —
        # both missed the SELECT, both ran the side effect). rowcount==1 → we own the key. rowcount==0
        # → someone else holds it. DB error → we can't dedup; fall through and process WITHOUT dedup
        # (this is defense-in-depth — money endpoints carry their own atomic guard — so availability
        # wins over a hard block when the store is down).
        reserve = "error"
        try:
            with db_session() as db:
                res = db.execute(
                    "INSERT INTO idempotency_keys (key, fingerprint, response_status, response_body) "
                    "VALUES (:k, :fp, NULL, NULL) ON CONFLICT (key) DO NOTHING",
                    {"k": key, "fp": fingerprint},
                )
                db.commit()
                reserve = "won" if int(getattr(res, "rowcount", 0) or 0) == 1 else "exists"
        except Exception:
            reserve = "error"

        if reserve == "exists":
            # another request already holds this key — replay its completed response, else reject the
            # in-flight duplicate (fail-CLOSED: never run the side effect twice).
            row = None
            try:
                with db_session() as db:
                    row = db.execute(
                        "SELECT response_status, response_body FROM idempotency_keys WHERE key = :k",
                        {"k": key},
                    ).fetchone()
            except Exception:
                row = None
            if row is not None and row[0] is not None:
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
            return ORJSONResponse({"detail": "duplicate request in progress"}, status_code=409)

        if reserve == "error":
            # store unavailable → cannot dedup; process without the guard (see note above)
            return await call_next(request)

        # reserve == "won": process EXACTLY once. On failure, RELEASE the reservation so the client
        # can retry — a burned in-flight row would otherwise 409 forever (there is no DB TTL sweep).
        try:
            response = await call_next(request)
        except Exception:
            try:
                with db_session() as db:
                    db.execute(
                        "DELETE FROM idempotency_keys WHERE key = :k AND response_status IS NULL",
                        {"k": key},
                    )
                    db.commit()
            except Exception:
                pass
            raise
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

        # Complete the reserved row with the real response (UPDATE, not INSERT — we already own it).
        try:
            with db_session() as db:
                db.execute(
                    "UPDATE idempotency_keys SET fingerprint = :fp, response_status = :st, "
                    "response_body = :rb WHERE key = :k",
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
