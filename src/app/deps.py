import json
import unicodedata
import re
from typing import Dict, Generator

import redis
from fastapi import Depends

from src.app.config import get_settings, load_feature_flags


_settings = get_settings()


class DummyRedis:
    def get(self, *_args, **_kwargs):
        return None

    def setex(self, *_args, **_kwargs):
        return None


_lazy_redis: redis.Redis | None = None


def _create_redis_client() -> redis.Redis | None:
    try:
        cli = redis.from_url(
            _settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.01,
            socket_timeout=0.01,
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
    else:
        _lazy_redis = cli
    return _lazy_redis


def get_flags() -> Dict:
    return load_feature_flags(_settings.feature_flags_path)


def unicode_normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


PII_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PII_PHONE = re.compile(r"\b(\+?\d[\d\-\s]{7,}\d)\b")
JAILBREAK_PAT = re.compile(r"(?i)(ignore\s+previous|disregard\s+rules|do\s+anything\s+now)")


def scrub_pii(text: str) -> str:
    text = PII_EMAIL.sub("[REDACTED_EMAIL]", text)
    text = PII_PHONE.sub("[REDACTED_PHONE]", text)
    return text


def security_sanitize(payload: Dict) -> Dict:
    s = json.dumps(payload, ensure_ascii=False)
    s = unicode_normalize(s)
    s = scrub_pii(s)
    return json.loads(s)


def get_security_context(payload: Dict = Depends(lambda: {})) -> Dict:
    # Minimal observer context holder for routes
    sanitized = security_sanitize(payload if payload else {})
    verdict = {
        "risk": "info" if not JAILBREAK_PAT.search(json.dumps(sanitized)) else "high",
        "details": {"flags": ["JAILBREAK_PATTERN"] if JAILBREAK_PAT.search(json.dumps(sanitized)) else []},
    }
    return {"sanitized": sanitized, "verdict": verdict}
