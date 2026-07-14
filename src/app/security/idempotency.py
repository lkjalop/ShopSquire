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


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.cache = {}
        try:
            self.ttl = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
        except Exception:
            self.ttl = 86400

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        if method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)
        key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
        if not key:
            return await call_next(request)

        try:
            body = await request.body()
        except Exception:
            body = b""
        fp_source = f"{method}|{request.url.path}|{hashlib.sha256(body).hexdigest()}"
        fingerprint = hashlib.sha256(fp_source.encode("utf-8")).hexdigest()
        storage_key = f"http:{method}:{request.url.path}:{key}"

        now = time.time()
        cache = self.cache
        try:
            entry = cache.get(storage_key)
            if entry and (now - float(entry.get("ts", 0))) < self.ttl:
                if entry.get("fingerprint") != fingerprint:
                    return self._conflict()
                return ORJSONResponse(entry.get("body") or {}, status_code=int(entry.get("status") or 200))
        except Exception:
            pass

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
            return self._unavailable()

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
            return self._unavailable()

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
                return self._unavailable()
            if row is not None and str(row[0] or "") != fingerprint:
                return self._conflict()
            if row is not None and row[1] is not None:
                try:
                    replay_body = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
                except Exception:
                    replay_body = row[2] or {}
                status = int(row[1] or 200)
                cache[storage_key] = {
                    "fingerprint": fingerprint,
                    "body": replay_body,
                    "status": status,
                    "ts": now,
                }
                return ORJSONResponse(replay_body, status_code=status)
            return ORJSONResponse({"detail": "duplicate request in progress"}, status_code=409)

        try:
            response = await call_next(request)
        except Exception:
            self._release(storage_key)
            raise

        status = int(getattr(response, "status_code", 200))
        try:
            if getattr(response, "body", None) is not None:
                raw_body = bytes(response.body)
            else:
                raw_body = b"".join([chunk async for chunk in response.body_iterator])
            response_body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as exc:
            self._release(storage_key)
            _log.error("idempotency_response_capture_failed", exc_info=exc)
            return ORJSONResponse({"detail": "idempotent response could not be recorded"}, status_code=503)

        try:
            with db_session() as db:
                db.execute(
                    "UPDATE idempotency_keys SET response_status = :status, response_body = :body "
                    "WHERE key = :key AND fingerprint = :fingerprint",
                    {
                        "key": storage_key,
                        "fingerprint": fingerprint,
                        "status": status,
                        "body": json.dumps(response_body, ensure_ascii=False),
                    },
                )
                db.commit()
        except Exception as exc:
            _log.error("idempotency_response_commit_failed", exc_info=exc)
            return ORJSONResponse({"detail": "idempotent response could not be committed"}, status_code=503)

        cache[storage_key] = {
            "fingerprint": fingerprint,
            "body": response_body,
            "status": status,
            "ts": now,
        }
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=raw_body,
            status_code=status,
            headers=headers,
            media_type=getattr(response, "media_type", None),
            background=getattr(response, "background", None),
        )

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
