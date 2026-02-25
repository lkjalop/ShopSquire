import json
import unicodedata
import re
import hashlib
import os
from typing import Dict, Generator, Any

import redis
import logging
from fastapi import Depends

from src.app.config import get_settings, load_feature_flags


class DummyRedis:
    def get(self, *_args, **_kwargs):
        return None

    def setex(self, *_args, **_kwargs):
        return None

    def delete(self, *_args, **_kwargs):
        return 0

    def incrby(self, *_args, **_kwargs):
        return 0

    def incrbyfloat(self, *_args, **_kwargs):
        return 0.0

    def expire(self, *_args, **_kwargs):
        return False


_lazy_redis: redis.Redis | None = None
_redis_warned = False


def _create_redis_client() -> redis.Redis | None:
    try:
        settings = get_settings()
        redis_url = settings.redis_url
        acl_user = str(os.getenv("REDIS_ACL_USERNAME", "") or "").strip()
        acl_pass = str(os.getenv("REDIS_ACL_PASSWORD", "") or "").strip()
        kwargs = {
            "decode_responses": True,
            "socket_connect_timeout": 0.01,
            "socket_timeout": 0.01,
        }
        if acl_user:
            kwargs["username"] = acl_user
        if acl_pass:
            kwargs["password"] = acl_pass
        cli = redis.from_url(
            redis_url,
            **kwargs,
        )
        # quick health-check; may raise quickly if unreachable
        try:
            cli.ping()
        except Exception:
            return None
        return cli
    except Exception:
        return None


def get_redis() -> redis.Redis:
    global _lazy_redis
    if _lazy_redis is not None:
        return _lazy_redis
    cli = _create_redis_client()
    if cli is None:
        _lazy_redis = DummyRedis()
        global _redis_warned
        if not _redis_warned:
            try:
                settings = get_settings()
                url = getattr(settings, 'redis_url', None)
            except Exception:
                url = None
            logging.getLogger("shopsquire.startup").warning("Redis not available%s; using DummyRedis", (f' at {url}' if url else ''))
            _redis_warned = True
    else:
        _lazy_redis = cli
    return _lazy_redis


def get_flags() -> Dict:
    return load_feature_flags((get_settings().feature_flags_path))


def unicode_normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


PII_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone-like digit strings, but avoid short numeric ranges like "900-1300".
# Require at least 10 digits total (E.164 / typical national numbers).
PII_PHONE = re.compile(r"\b(?=(?:\D*\d){10,})(\+?\d[\d\-\s]{7,}\d)\b")
PII_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PII_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
API_KEY_PAT = re.compile(r"(?i)\b(sk|rk|pk)_(live|test)?_[a-z0-9]{12,}\b")
JAILBREAK_PAT = re.compile(
    r"(?i)(ignore\s+previous|disregard\s+rules|do\s+anything\s+now|system\s+prompt|developer\s+message|bypass|jailbreak|reveal\s+prompt|override\s+policy|act\s+as\s+system|role\s*play|simulate|prompt\s*injection|instruction\s*hierarchy)"
)


def scrub_pii(text: str) -> str:
    if not text:
        return text
    protected = {}

    def _protect(m: re.Match) -> str:
        key = f"__PROTECT_{len(protected)}__"
        protected[key] = m.group(0)
        return key

    # Preserve known system IDs that can look like phone numbers.
    text = re.sub(r"\b(?:TKT|INC|CASE|ORD|ORDER|REQ|DEC|TRACE|EVT|EVENT)-\d{6,}\b", _protect, text, flags=re.I)
    text = PII_EMAIL.sub("[REDACTED_EMAIL]", text)
    text = PII_PHONE.sub("[REDACTED_PHONE]", text)
    text = PII_SSN.sub("[REDACTED_SSN]", text)
    text = PII_IP.sub("[REDACTED_IP]", text)
    text = API_KEY_PAT.sub("[REDACTED_API_KEY]", text)
    for key, val in protected.items():
        text = text.replace(key, val)
    return text


def hash_uid(uid: str) -> str:
    return hashlib.sha256((uid or "").encode("utf-8")).hexdigest()[:16]


def hash_value(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def security_sanitize(payload: Dict) -> Dict:
    # Recursively sanitize Python objects to avoid JSON serialization edge-cases
    def _sanitize_value(v):
        if isinstance(v, str):
            v2 = unicode_normalize(v)
            v2 = scrub_pii(v2)
            return v2
        if isinstance(v, dict):
            return {k: _sanitize_value(vv) for k, vv in v.items()}
        if isinstance(v, list):
            return [_sanitize_value(x) for x in v]
        return v

    try:
        return _sanitize_value(payload if payload else {})
    except Exception:
        # Fallback to original JSON approach if unexpected types encountered
        s = json.dumps(payload, ensure_ascii=False)
        s = unicode_normalize(s)
        s = scrub_pii(s)
        try:
            return json.loads(s)
        except Exception:
            return {}


def _looks_like_base64(value: str) -> bool:
    if not value:
        return False
    if len(value) < 200:
        return False
    # Heuristic: base64-like chars only and length multiple of 4 (often).
    if len(value) % 4 != 0:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/=]+", value))


def redact_for_trace(payload: Any) -> Any:
    """Redact sensitive or bulky payloads for trace persistence."""
    def _redact(v):
        if isinstance(v, str):
            v2 = unicode_normalize(v)
            v2 = scrub_pii(v2)
            if _looks_like_base64(v2):
                return "[REDACTED_BASE64]"
            if len(v2) > 512:
                return f"[REDACTED_LEN:{len(v2)}]"
            return v2
        if isinstance(v, dict):
            out = {}
            for k, vv in v.items():
                key = str(k).lower()
                if any(tok in key for tok in ("image", "photo", "file", "bytes", "blob", "data_url", "base64", "attachment")):
                    out[k] = "[REDACTED_BLOB]"
                else:
                    out[k] = _redact(vv)
            return out
        if isinstance(v, list):
            return [_redact(x) for x in v]
        return v

    try:
        return _redact(payload)
    except Exception:
        return {}


def get_security_context(payload: Dict = Depends(lambda: {})) -> Dict:
    # Minimal observer context holder for routes
    sanitized = security_sanitize(payload if payload else {})
    verdict = {
        "risk": "info" if not JAILBREAK_PAT.search(json.dumps(sanitized)) else "high",
        "details": {"flags": ["JAILBREAK_PATTERN"] if JAILBREAK_PAT.search(json.dumps(sanitized)) else []},
    }
    return {"sanitized": sanitized, "verdict": verdict}
