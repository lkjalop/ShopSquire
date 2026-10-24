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
from threading import RLock
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

# Register before publishing: Redis script errors do not roll back commands.
# Retaining a harmless index member is safe; retaining an unindexed value is not.
_WRITE_VERSIONED = """
local remaining = redis.call('TTL', KEYS[2])
redis.call('SADD', KEYS[2], KEYS[1])
if remaining == -2 or (remaining >= 0 and remaining < tonumber(ARGV[3])) then
    redis.call('EXPIRE', KEYS[2], ARGV[3])
end
return redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
"""
_ERASE_VERSIONED = """
local members = redis.call('SMEMBERS', KEYS[1])
for _, member in ipairs(members) do
    redis.call('DEL', member)
end
redis.call('DEL', KEYS[1])
return #members
"""
_READ_VERSIONED = """
if redis.call('SISMEMBER', KEYS[2], KEYS[1]) == 0 then return false end
return redis.call('GET', KEYS[1])
"""


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
        self._local_key_scope: dict[str, str] = {}
        self._scope_lock = RLock()
        self._redis = redis_client
        if self._redis is None and redis_url and _has_redis:
            try:
                from src.app.services.redis_factory import create_redis_client
                self._redis = create_redis_client(url=redis_url, decode_responses=True)
            except Exception:
                self._redis = None

    def get(self, key: str, *, allow_local_fallback: bool = True) -> Optional[Any]:
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
            if not allow_local_fallback:
                return None

        # Fallback to local dict
        exp = self._local_expiry.get(key)
        if exp is not None and exp < time.time():
            self._drop_local(key)
            return None
        v = self._local.get(key)
        return v

    @property
    def is_shared_backend(self) -> bool:
        """Whether writes are visible across API and worker processes."""
        return self._redis is not None

    def _drop_local(self, key: str) -> None:
        self._local.pop(key, None)
        self._local_expiry.pop(key, None)
        index = self._local_key_scope.pop(key, None)
        if index is not None:
            members = self._local_scope_index.get(index)
            if members is not None:
                members.discard(key)
                if not members:
                    self._local_scope_index.pop(index, None)

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
                    self._drop_local(k)
            if len(self._local) >= self._maxsize:
                oldest = sorted(self._local_expiry.items(), key=lambda x: x[1])[:max(1, self._maxsize // 10)]
                for k, _ in oldest:
                    self._drop_local(k)
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
        self._drop_local(key)

    def delete_strict(self, key: str) -> None:
        """Delete an entry without concealing shared-cache failures.

        The compatibility ``delete`` method remains best-effort for callers
        that do not own an authority transition.  Temporal invalidation uses
        this strict variant so a Redis outage becomes durable retry work
        instead of an apparent successful eviction.
        """
        if not key:
            return
        if self._redis is not None:
            self._redis.delete(key)
        self._drop_local(key)

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
        index_key = contract.erasure_index_key
        if self._redis is not None:
            try:
                # Shared versioned publication requires the atomic protocol.
                # An unavailable/unsupported backend is a cache miss, never a
                # process-local copy that a replacement worker cannot erase.
                self._redis.eval(_WRITE_VERSIONED, 2, key, index_key,
                                 json.dumps(wrapped, ensure_ascii=False), ttl,
                                 ttl + 1)
            except Exception:
                return key
        else:
            with self._scope_lock:
                self.set(key, wrapped, ex=ttl)
                if key in self._local:
                    self._local_scope_index.setdefault(index_key, set()).add(key)
                    self._local_key_scope[key] = index_key
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
        # A disconnected shared-cache client cannot establish whether another
        # worker revoked or erased this scope. Never resurrect its local copy.
        # Explicitly local-only caches continue using their local storage.
        if self._redis is not None:
            try:
                raw = self._redis.eval(_READ_VERSIONED, 2, key, contract.erasure_index_key)
                wrapped = json.loads(raw) if raw else None
            except Exception:
                return None
        else:
            wrapped = self.get(key, allow_local_fallback=False)
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
        with self._scope_lock:
            return self._erase_scope(contract)

    def _erase_scope(self, contract: CacheContract) -> int:
        index_key = contract.erasure_index_key
        try:
            atomic_backend = self._redis is not None and callable(getattr(self._redis, 'eval', None))
        except Exception as exc:
            raise RuntimeError('cache_erasure_incomplete:index_unavailable') from exc
        if atomic_backend:
            try:
                # Serialize discovery and deletion against shared publication.
                return int(self._redis.eval(_ERASE_VERSIONED, 1, index_key))
            except Exception as exc:
                raise RuntimeError('cache_erasure_incomplete:atomic_delete_failed') from exc
        keys = set(self._local_scope_index.get(index_key, set()))
        try:
            if self._redis:
                raw = self._redis.smembers(index_key) or set()
                keys.update(
                    item.decode("utf-8") if isinstance(item, bytes) else str(item)
                    for item in raw
                )
        except Exception as exc:
            raise RuntimeError('cache_erasure_incomplete:index_unavailable') from exc
        failed = False
        for key in keys:
            self._local.pop(key, None)
            self._local_expiry.pop(key, None)
            try:
                self.delete_strict(key)
            except Exception:
                failed = True
        if failed:
            # Retain the subject index so the caller can retry incomplete work.
            raise RuntimeError('cache_erasure_incomplete:delete_failed')
        try:
            if self._redis is not None:
                self._redis.delete(index_key)
        except Exception as exc:
            raise RuntimeError('cache_erasure_incomplete:index_delete_failed') from exc
        self._local_scope_index.pop(index_key, None)
        return len(keys)
