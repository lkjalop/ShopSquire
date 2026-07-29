"""Redis-backed semantic cache with in-process fallback.

This provides a minimal interface used by `TierRouter` and other services:
- `get(key)` -> parsed value or None
- `set(key, value, ex=None)` -> store value (JSON-serializable)

If `REDIS_URL` is present in the environment and `redis` is installed, it will
use Redis; otherwise a process-local dict is used.
"""
from __future__ import annotations
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from src.app.platform.tenant_context import current_tenant_id

_has_redis = False
try:
    import redis
    _has_redis = True
except Exception:
    redis = None


_LOCAL_CACHE_MAXSIZE = 500
CACHE_CONTRACT_VERSION = "2"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_citation_id(
    *,
    source_id: str,
    document_id: str,
    revision: str,
    locator: str = "",
    content_hash: str = "",
) -> str:
    """Stable citation identity across Python processes and deployments."""
    canonical = _canonical_json(
        {
            "source_id": str(source_id or "unknown"),
            "document_id": str(document_id or "unknown"),
            "revision": str(revision or "unversioned"),
            "locator": str(locator or ""),
            "content_hash": str(content_hash or ""),
        }
    )
    return f"cite:v1:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]}"


@dataclass(frozen=True)
class CacheContract:
    """Authority context that makes a cache entry safe to reuse."""

    tenant_id: str
    corpus_version: str
    policy_version: str
    model_version: str
    evidence_cutoff: str
    subject_id: str = ""
    session_epoch: str = ""
    schema_version: str = CACHE_CONTRACT_VERSION

    @classmethod
    def resolve(
        cls,
        *,
        tenant_id: str | None = None,
        corpus_version: str,
        policy_version: str,
        model_version: str,
        evidence_cutoff: str,
        subject_id: str = "",
        session_epoch: str = "",
    ) -> "CacheContract":
        tenant = str(tenant_id or current_tenant_id()).strip() or "default"
        if not str(evidence_cutoff or "").strip():
            raise ValueError("evidence_cutoff_required")
        return cls(
            tenant_id=tenant,
            corpus_version=str(corpus_version or "unversioned"),
            policy_version=str(policy_version or "unversioned"),
            model_version=str(model_version or "unversioned"),
            evidence_cutoff=str(evidence_cutoff),
            subject_id=str(subject_id or ""),
            session_epoch=str(session_epoch or ""),
        )

    def cache_key(self, namespace: str, request: Any) -> str:
        request_digest = hashlib.sha256(_canonical_json(request).encode("utf-8")).hexdigest()
        scope_digest = hashlib.sha256(_canonical_json(asdict(self)).encode("utf-8")).hexdigest()
        return f"cache:v{self.schema_version}:{namespace}:{scope_digest[:32]}:{request_digest}"

    @property
    def erasure_index_key(self) -> str:
        identity = _canonical_json(
            {"tenant_id": self.tenant_id, "subject_id": self.subject_id or "_shared"}
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return f"cache:v{self.schema_version}:index:{digest}"


class SemanticCache:
    def __init__(
        self,
        redis_url: Optional[str] = None,
        default_ttl: int = 3600,
        maxsize: int = _LOCAL_CACHE_MAXSIZE,
        redis_client: Any = None,
    ):
        self.default_ttl = default_ttl
        self._maxsize = maxsize
        self._local: dict[str, Any] = {}
        self._local_expiry: dict[str, float] = {}
        self._local_scope_index: dict[str, set[str]] = {}
        self._redis = redis_client
        if self._redis is None and redis_url and _has_redis:
            try:
                from src.app.services.redis_factory import create_redis_client
                self._redis = create_redis_client(url=redis_url, decode_responses=True)
            except Exception:
                self._redis = None

    def get(self, key: str) -> Optional[Any]:
        if not key:
            return None
        # Try Redis first
        try:
            if self._redis:
                v = self._redis.get(key)
                if v is None:
                    return None
                try:
                    return json.loads(v)
                except Exception:
                    return v
        except Exception:
            pass

        # Fallback to local dict
        exp = self._local_expiry.get(key)
        if exp is not None and exp < time.time():
            self._local.pop(key, None)
            self._local_expiry.pop(key, None)
            return None
        v = self._local.get(key)
        return v

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        if not key:
            return
        ex = ex or self.default_ttl
        try:
            if self._redis:
                payload = json.dumps(value, ensure_ascii=False)
                try:
                    # redis-py expects seconds
                    self._redis.set(name=key, value=payload, ex=int(ex))
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # Local store fallback
        try:
            # Evict expired entries first; if still over maxsize, drop oldest by expiry.
            if len(self._local) >= self._maxsize:
                now = time.time()
                expired_keys = [k for k, exp in list(self._local_expiry.items()) if exp < now]
                for k in expired_keys:
                    self._local.pop(k, None)
                    self._local_expiry.pop(k, None)
            if len(self._local) >= self._maxsize:
                oldest = sorted(self._local_expiry.items(), key=lambda x: x[1])[:max(1, self._maxsize // 10)]
                for k, _ in oldest:
                    self._local.pop(k, None)
                    self._local_expiry.pop(k, None)
            self._local[key] = value
            self._local_expiry[key] = time.time() + max(1, int(ex))
        except Exception:
            pass

    def delete(self, key: str) -> None:
        if not key:
            return
        try:
            if self._redis:
                self._redis.delete(key)
        except Exception:
            pass
        self._local.pop(key, None)
        self._local_expiry.pop(key, None)

    def set_safe(self, key: str, value: Any, *, source_id: str, trust_score: float, ex: Optional[int] = None) -> None:
        ts = int(time.time())
        wrapped = {
            "_meta": {
                "source_id": str(source_id or "unknown"),
                "trust_score": float(max(0.0, min(1.0, trust_score))),
                "created_at": ts,
                "quarantined": False,
                "poison_reason": None,
            },
            "value": value,
        }
        self.set(key, wrapped, ex=ex)

    def quarantine(self, key: str, reason: str = "suspected_poison") -> None:
        cur = self.get(key)
        if not isinstance(cur, dict):
            return
        meta = cur.get("_meta") if isinstance(cur.get("_meta"), dict) else {}
        meta["quarantined"] = True
        meta["poison_reason"] = str(reason or "suspected_poison")
        cur["_meta"] = meta
        self.set(key, cur, ex=self.default_ttl)

    def get_safe(self, key: str, *, min_trust: float = 0.3) -> Optional[Any]:
        cur = self.get(key)
        if not isinstance(cur, dict):
            return cur
        meta = cur.get("_meta") if isinstance(cur.get("_meta"), dict) else {}
        if bool(meta.get("quarantined")):
            return None
        trust = float(meta.get("trust_score") or 0.0)
        if trust < float(min_trust):
            return None
        return cur.get("value")

    def set_versioned(
        self,
        *,
        namespace: str,
        request: Any,
        contract: CacheContract,
        value: Any,
        source_id: str,
        trust_score: float,
        ex: Optional[int] = None,
    ) -> str:
        """Store a value only under its complete authority/version scope."""
        key = contract.cache_key(namespace, request)
        ttl = max(1, int(ex or self.default_ttl))
        now = int(time.time())
        wrapped = {
            "_meta": {
                "cache_contract": asdict(contract),
                "source_id": str(source_id or "unknown"),
                "trust_score": float(max(0.0, min(1.0, trust_score))),
                "created_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                "expires_at": datetime.fromtimestamp(now + ttl, timezone.utc).isoformat(),
                "quarantined": False,
                "poison_reason": None,
            },
            "value": value,
        }
        self.set(key, wrapped, ex=ttl)
        index_key = contract.erasure_index_key
        self._local_scope_index.setdefault(index_key, set()).add(key)
        try:
            if self._redis:
                self._redis.sadd(index_key, key)
                # Keep the erasure index at least as long as any supported
                # cache entry; later short writes must not orphan older keys.
                self._redis.expire(index_key, max(ttl, 90 * 86400))
        except Exception:
            pass
        return key

    def get_versioned(
        self,
        *,
        namespace: str,
        request: Any,
        contract: CacheContract,
        min_trust: float = 0.3,
    ) -> Optional[Any]:
        key = contract.cache_key(namespace, request)
        wrapped = self.get(key)
        if not isinstance(wrapped, dict):
            return None
        meta = wrapped.get("_meta") if isinstance(wrapped.get("_meta"), dict) else {}
        if meta.get("cache_contract") != asdict(contract):
            return None
        if bool(meta.get("quarantined")):
            return None
        if float(meta.get("trust_score") or 0.0) < float(min_trust):
            return None
        return wrapped.get("value")

    def erase_scope(self, contract: CacheContract) -> int:
        """Erase cached material for one tenant/subject privacy scope."""
        index_key = contract.erasure_index_key
        keys = set(self._local_scope_index.get(index_key, set()))
        try:
            if self._redis:
                raw = self._redis.smembers(index_key) or set()
                keys.update(
                    item.decode("utf-8") if isinstance(item, bytes) else str(item)
                    for item in raw
                )
        except Exception:
            pass
        for key in keys:
            self.delete(key)
        try:
            if self._redis:
                self._redis.delete(index_key)
        except Exception:
            pass
        self._local_scope_index.pop(index_key, None)
        return len(keys)
