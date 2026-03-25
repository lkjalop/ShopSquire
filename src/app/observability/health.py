from __future__ import annotations

import os
import time
from typing import Any, Dict
from sqlalchemy import text

from src.app.deps import get_redis
from src.app.models.db import db_session


_CACHE: Dict[str, Any] = {"ts": 0, "payload": None}
_CACHE_TTL_SECONDS = 30


def _check_db() -> Dict[str, Any]:
    start = time.time()
    try:
        with db_session() as db:
            db.execute(text("SELECT 1"))
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms, "last_ok": int(time.time())}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc), "last_ok": None, "latency_ms": None}


def _check_redis() -> Dict[str, Any]:
    start = time.time()
    try:
        redis_client = get_redis()
        if hasattr(redis_client, "ping"):
            redis_client.ping()
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms, "last_ok": int(time.time())}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc), "last_ok": None, "latency_ms": None}


def _check_ollama() -> Dict[str, Any]:
    """Probe Ollama /api/tags endpoint (lightweight, no model load)."""
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    start = time.time()
    try:
        import httpx
        r = httpx.get(f"{url}/api/tags", timeout=3.0)
        latency_ms = int((time.time() - start) * 1000)
        if r.status_code == 200:
            models = [m.get("name") for m in (r.json().get("models") or [])]
            return {"status": "healthy", "latency_ms": latency_ms, "models": models[:5], "last_ok": int(time.time())}
        return {"status": "degraded", "http_status": r.status_code, "latency_ms": latency_ms, "last_ok": None}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)[:120], "latency_ms": None, "last_ok": None}


def _check_pgvector() -> Dict[str, Any]:
    """Confirm pgvector extension is installed and product_embeddings table accessible."""
    start = time.time()
    try:
        with db_session() as db:
            row = db.execute(text("SELECT COUNT(*) FROM product_embeddings LIMIT 1")).fetchone()
            count = int(row[0]) if row else 0
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms, "indexed_vectors": count, "last_ok": int(time.time())}
    except Exception as exc:
        err = str(exc)
        if "does not exist" in err or "no such table" in err:
            return {
                "status": "not_migrated",
                "error": "product_embeddings table missing — run alembic upgrade",
                "latency_ms": None,
                "last_ok": None,
            }
        return {"status": "unhealthy", "error": err[:120], "latency_ms": None, "last_ok": None}


def _check_cv_provider() -> Dict[str, Any]:
    """Report which CV provider is configured (instantaneous config check, no live call)."""
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    google_key = os.getenv("GOOGLE_AI_API_KEY", "").strip()
    ollama_vision = os.getenv("OLLAMA_VISION_MODEL", "").strip()
    if openai_key:
        return {"status": "healthy", "provider": "openai", "model": os.getenv("OPENAI_VISION_MODEL", "gpt-4o")}
    if google_key:
        return {"status": "healthy", "provider": "google", "model": "gemini-pro-vision"}
    if ollama_vision:
        return {"status": "healthy", "provider": "ollama", "model": ollama_vision}
    return {"status": "not_configured", "provider": None, "note": "Set OPENAI_API_KEY or OLLAMA_VISION_MODEL"}


def dependency_health_snapshot(force: bool = False) -> Dict[str, Any]:
    now = int(time.time())
    if not force and _CACHE.get("payload") and (now - int(_CACHE.get("ts", 0))) < _CACHE_TTL_SECONDS:
        return _CACHE["payload"]

    db_status = _check_db()
    redis_status = _check_redis()
    ollama_status = _check_ollama()
    pgvector_status = _check_pgvector()
    cv_status = _check_cv_provider()

    deps: Dict[str, Any] = {
        "db": db_status,
        "redis": redis_status,
        "ollama": ollama_status,
        "pgvector": pgvector_status,
        "cv_provider": cv_status,
    }
    critical_ok = all(deps[k].get("status") == "healthy" for k in ("db", "redis"))
    overall = "healthy" if critical_ok else "degraded"

    payload: Dict[str, Any] = {
        "timestamp": now,
        "overall": overall,
        "dependencies": deps,
    }
    _CACHE["ts"] = now
    _CACHE["payload"] = payload
    return payload
