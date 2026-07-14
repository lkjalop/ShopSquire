from __future__ import annotations

import hashlib
import json
import logging
import os
import time

from fastapi import Request
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.app.models.db import db_session

_log = logging.getLogger("shopsquire.idempotency")

# Paths where a duplicate side effect is a MONEY/safety event — there the middleware fails CLOSED
# (503) if the idempotency store is unavailable. Everywhere else it degrades to process-WITHOUT-dedup
# so a flaky store can't take down every idempotent write (P1 review: availability coupling). The
# money endpoints additionally carry their own atomic `_idempotent` guard, so this is defence in depth.
_CRITICAL_PREFIXES = tuple(
    p.strip() for p in os.getenv(
        "IDEMPOTENCY_CRITICAL_PREFIXES",
        "/api/v1/payments,/api/v1/orders,/api/v1/refunds,/api/v1/checkout,/api/v1/fulfillment",
    ).split(",") if p.strip()
)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.cache = {}
        try:
            self.ttl = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
        except Exception:
            self.ttl = 86400
        try:
            self.cache_max = max(64, int(os.getenv("IDEMPOTENCY_CACHE_MAX", "2048")))
        except Exception:
            self.cache_max = 2048

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        if method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)
        key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
        if not key:
            return await call_next(request)

        path = request.url.path
        critical = any(path.startswith(p) for p in _CRITICAL_PREFIXES)

        try:
            body = await request.body()
        except Exception:
            body = b""
        # PRINCIPAL NAMESPACING (GPT-5.6 review-11b #1): the key was scoped by (method,path,key)
        # only, so two DIFFERENT callers reusing the same Idempotency-Key on the same route
        # cross-replayed each other's response (reproduced: tenant B got tenant A's payment intent).
        # Namespace the storage key by a stable caller identity derived from the auth headers the
        # middleware CAN see (it runs before the endpoint's role dependency), so a key is private to
        # its caller. And the fingerprint now includes the QUERY STRING — /payments/intent takes
        # amount_cents as a QUERY param, so a body-only fingerprint was identical for amount=100 and
        # amount=200 and replayed the wrong charge.
        principal = (request.headers.get("x-api-key") or request.headers.get("authorization")
                     or request.headers.get("x-tenant-id") or request.headers.get("x-tenant") or "anon")
        principal_id = hashlib.sha256(str(principal).encode("utf-8")).hexdigest()[:16]
        query = request.url.query or ""
        fp_source = f"{method}|{path}|{query}|{hashlib.sha256(body).hexdigest()}"
        fingerprint = hashlib.sha256(fp_source.encode("utf-8")).hexdigest()
        storage_key = f"http:{principal_id}:{method}:{path}:{key}"
        now = time.time()

        # in-memory fast path (fingerprint-checked)
        try:
            entry = self.cache.get(storage_key)
            if entry and (now - float(entry.get("ts", 0))) < self.ttl:
                if entry.get("fingerprint") != fingerprint:
                    return self._conflict()
                return ORJSONResponse(entry.get("body") or {}, status_code=int(entry.get("status") or 200))
        except Exception:
            pass

        # ── store availability: fail CLOSED on money paths, degrade (no dedup) elsewhere ──
        try:
            with db_session() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS idempotency_keys "
                    "(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response_status INT, "
                    "response_body TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                )
                db.commit()
        except Exception as exc:
            _log.error("idempotency_table_unavailable", exc_info=exc)
            return self._unavailable() if critical else await call_next(request)

        try:
            with db_session() as db:
                result = db.execute(
                    "INSERT INTO idempotency_keys (key, fingerprint, response_status, response_body) "
                    "VALUES (:key, :fingerprint, NULL, NULL) ON CONFLICT (key) DO NOTHING",
                    {"key": storage_key, "fingerprint": fingerprint},
                )
                db.commit()
                reserve_won = int(getattr(result, "rowcount", 0) or 0) == 1
        except Exception as exc:
            _log.error("idempotency_reservation_failed", exc_info=exc)
            return self._unavailable() if critical else await call_next(request)

        if not reserve_won:
            try:
                with db_session() as db:
                    row = db.execute(
                        "SELECT fingerprint, response_status, response_body "
                        "FROM idempotency_keys WHERE key = :key",
                        {"key": storage_key},
                    ).fetchone()
            except Exception as exc:
                _log.error("idempotency_replay_read_failed", exc_info=exc)
                return self._unavailable() if critical else await call_next(request)
            if row is not None and str(row[0] or "") != fingerprint:
                return self._conflict()
            if row is not None and row[1] is not None:
                replay_body = self._decode_body(row[2])
                status = int(row[1] or 200)
                self._cache_put(storage_key, {
                    "fingerprint": fingerprint, "body": replay_body, "status": status, "ts": now,
                })
                return ORJSONResponse(replay_body, status_code=status)
            return ORJSONResponse({"detail": "duplicate request in progress"}, status_code=409)

        # ── we own the key: execute EXACTLY once ──
        try:
            response = await call_next(request)
        except Exception:
            # the side effect did NOT complete (call_next raised) → release so a retry can proceed.
            self._release(storage_key)
            raise

        # From here the side effect HAS completed. Invariant: NEVER release (a retry must never
        # re-execute) and ALWAYS return the real response to this client — persisting it is
        # best-effort. (P1 review: fixes capture-fail→re-execute and commit-fail→client-503.)
        status = int(getattr(response, "status_code", 200))
        try:
            if getattr(response, "body", None) is not None:
                raw_body = bytes(response.body)
            else:
                raw_body = b"".join([chunk async for chunk in response.body_iterator])
        except Exception as exc:
            _log.error("idempotency_response_capture_failed", exc_info=exc)
            raw_body = b""
        try:
            parsed = json.loads(raw_body.decode("utf-8")) if raw_body else None
        except Exception:
            parsed = None
        # store JSON when we have it; else a sentinel so a cross-process replay is deterministic
        # (the side effect already ran) rather than a re-execution.
        replay_body = parsed if parsed is not None else {"detail": "request already processed"}

        try:
            with db_session() as db:
                db.execute(
                    "UPDATE idempotency_keys SET response_status = :status, response_body = :body "
                    "WHERE key = :key AND fingerprint = :fingerprint",
                    {
                        "key": storage_key,
                        "fingerprint": fingerprint,
                        "status": status,
                        "body": json.dumps(replay_body, ensure_ascii=False),
                    },
                )
                db.commit()
        except Exception as exc:
            # persist failed but the side effect happened: do NOT release, do NOT 503 — return the
            # real response. Cross-process retries during the outage get 409-in-progress until the
            # store recovers (safe: no double execution).
            _log.error("idempotency_response_commit_failed", exc_info=exc)

        self._cache_put(storage_key, {
            "fingerprint": fingerprint, "body": replay_body, "status": status, "ts": now,
        })
        if not raw_body:
            return ORJSONResponse(replay_body, status_code=status)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=raw_body,
            status_code=status,
            headers=headers,
            media_type=getattr(response, "media_type", None),
            background=getattr(response, "background", None),
        )

    def _cache_put(self, storage_key: str, entry: dict) -> None:
        """Bounded in-memory cache (P1 review: was unbounded). Evicts the oldest ~10% by ts when full."""
        cache = self.cache
        cache[storage_key] = entry
        if len(cache) > self.cache_max:
            try:
                for stale in sorted(cache, key=lambda k: cache[k].get("ts", 0))[: max(1, self.cache_max // 10)]:
                    cache.pop(stale, None)
            except Exception:
                cache.clear()

    @staticmethod
    def _decode_body(value):
        try:
            return json.loads(value) if isinstance(value, str) else (value or {})
        except Exception:
            return value or {}

    @staticmethod
    def _conflict() -> ORJSONResponse:
        return ORJSONResponse(
            {"detail": "idempotency key reused with a different request"}, status_code=409
        )

    @staticmethod
    def _unavailable() -> ORJSONResponse:
        return ORJSONResponse({"detail": "idempotency store unavailable"}, status_code=503)

    @staticmethod
    def _release(storage_key: str) -> None:
        try:
            with db_session() as db:
                db.execute(
                    "DELETE FROM idempotency_keys WHERE key = :key AND response_status IS NULL",
                    {"key": storage_key},
                )
                db.commit()
        except Exception as exc:
            _log.error("idempotency_reservation_release_failed", exc_info=exc)
