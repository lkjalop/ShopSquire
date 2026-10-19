"""Tenant- and session-scoped conversation memory.

Every key is namespaced by tenant, subject, and session epoch.  The subject is
normally the authenticated user (or bounded guest capability) and the epoch is
the conversation/session generation.  Callers that have not yet adopted an
explicit epoch remain compatible: their uid is used as both subject and epoch,
which preserves the old per-uid behaviour without restoring UID-only keys.

Keys are registered in a per-subject index so privacy erasure can remove every
known session epoch without relying on a broad Redis scan.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Optional

from redis import Redis

from src.app.platform.tenant_context import current_tenant_id


MEMORY_CONTRACT_VERSION = "2"
# Deprecated v1 templates remain only so erasure/export can clean up data
# written before the v2 scoped-key cutover. New writes never use these keys.
SUMMARY_KEY = "session:{uid}:summary"
KV_KEY = "session:{uid}:kv_state"
RETRIEVAL_KEY = "session:{uid}:recent_retrieval"
AGENT_STEPS_KEY = "session:{uid}:agent_steps"
STRUCTURED_STATE_KEY = "session:{uid}:structured_state"
PRODUCT_MEMORY_BANK_KEY = "session:{uid}:product_memory_bank"
OBSERVATION_LOG_KEY = "session:{uid}:observation_log"
OBSERVATION_SUMMARY_KEY = "session:{uid}:observation_summary"
_FAMILIES = (
    "summary",
    "kv_state",
    "recent_retrieval",
    "agent_steps",
    "structured_state",
    "product_memory_bank",
    "observation_log",
    "observation_summary",
    "pending_clarification",
)

# Register before writing: Redis scripts are atomic with respect to other
# clients, but do not roll back earlier commands after a command error. A
# failed index operation must therefore never leave a readable orphan value.
_WRITE_INDEXED = """
redis.call('SADD', KEYS[1], KEYS[2])
local remaining = redis.call('TTL', KEYS[1])
if remaining < tonumber(ARGV[1]) then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return redis.call('SETEX', KEYS[2], ARGV[2], ARGV[3])
"""
_ERASE_SUBJECT = """
local members = redis.call('SMEMBERS', KEYS[1])
for _, key in ipairs(members) do redis.call('DEL', key) end
redis.call('DEL', KEYS[1])
return members
"""
_ERASE_KEYS = """
for i = 2, #KEYS do
    redis.call('DEL', KEYS[i])
    redis.call('SREM', KEYS[1], KEYS[i])
end
if redis.call('SCARD', KEYS[1]) == 0 then redis.call('DEL', KEYS[1]) end
return 1
"""


def _identity_digest(value: str) -> str:
    """Return a deterministic, non-PII key segment."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _clean(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


@dataclass(frozen=True)
class MemoryScope:
    tenant_id: str
    subject_id: str
    session_epoch: str
    contract_version: str = MEMORY_CONTRACT_VERSION

    @classmethod
    def resolve(
        cls,
        uid: str,
        *,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        session_epoch: str | None = None,
    ) -> "MemoryScope":
        subject = _clean(subject_id, _clean(uid, "anonymous"))
        # Compatibility default: a uid remains its own conversation epoch.
        epoch = _clean(session_epoch, _clean(uid, "current"))
        return cls(
            tenant_id=_clean(tenant_id, current_tenant_id()),
            subject_id=subject,
            session_epoch=epoch,
        )

    @property
    def tenant_segment(self) -> str:
        return _identity_digest(self.tenant_id)

    @property
    def subject_segment(self) -> str:
        return _identity_digest(self.subject_id)

    @property
    def epoch_segment(self) -> str:
        return _identity_digest(self.session_epoch)

    def key(self, family: str) -> str:
        if family not in _FAMILIES and not family.startswith("episodic_"):
            raise ValueError(f"unsupported_memory_family:{family}")
        return (
            f"memory:v{self.contract_version}:{self.tenant_segment}:"
            f"{self.subject_segment}:{self.epoch_segment}:{family}"
        )

    @property
    def subject_index_key(self) -> str:
        return (
            f"memory:v{self.contract_version}:index:"
            f"{self.tenant_segment}:{self.subject_segment}"
        )


class Memory:
    _LOCAL_LOCK = RLock()
    _LAST_WRITE_NS = 0
    _LOCAL_STORE: Dict[str, Dict[str, Any]] = {}
    _LOCAL_INDEX: Dict[str, set[str]] = {}

    def __init__(
        self,
        redis_client: Redis | None,
        *,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        session_epoch: str | None = None,
    ):
        # A declared local-only adapter is not an authoritative shared store.
        self.redis = None if getattr(redis_client,'is_shared_backend',True) is False else redis_client
        self._tenant_id = tenant_id
        self._subject_id = subject_id
        self._session_epoch = session_epoch
        self.summary_ttl = self._env_ttl("CHAT_ACTIVE_TTL_SECONDS", "CHAT_TTL_SECONDS", 86400)
        self.kv_ttl = self._env_ttl("CHAT_ACTIVE_TTL_SECONDS", "CHAT_TTL_SECONDS", 86400)
        self.retrieval_ttl = self._env_ttl("RAG_CACHE_TTL_SECONDS", default=600)

    @staticmethod
    def _env_ttl(primary: str, secondary: str | None = None, default: int = 86400) -> int:
        try:
            raw = os.getenv(primary, os.getenv(secondary, str(default)) if secondary else str(default))
            return max(1, int(raw))
        except (TypeError, ValueError):
            return default

    def scope(
        self,
        uid: str,
        *,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        session_epoch: str | None = None,
    ) -> MemoryScope:
        return MemoryScope.resolve(
            uid,
            tenant_id=tenant_id if tenant_id is not None else self._tenant_id,
            subject_id=subject_id if subject_id is not None else self._subject_id,
            session_epoch=session_epoch if session_epoch is not None else self._session_epoch,
        )

    def scoped_key(
        self,
        family: str,
        uid: str,
        *,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        session_epoch: str | None = None,
    ) -> str:
        return self.scope(
            uid,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_epoch=session_epoch,
        ).key(family)

    def _register_key(self, scope: MemoryScope, key: str, ttl: int) -> None:
        index_key = scope.subject_index_key
        if self.redis is not None:
            # Compatibility for explicit in-memory adapters without scripting.
            # Failure propagates to _set_json, which must not write the value.
            self.redis.sadd(index_key, key)
            self.redis.expire(index_key, max(ttl, self.kv_ttl, 90 * 86400))

    def _prune_local(self) -> None:
        """Reclaim idle subjects and cap retained payloads; caller holds lock."""
        now = time.time()
        for key, row in list(self._LOCAL_STORE.items()):
            if float(row.get('exp', 0)) <= now:
                self._LOCAL_STORE.pop(key, None)
        max_keys = self._env_ttl('MEMORY_LOCAL_MAX_KEYS', default=1024)
        max_bytes = self._env_ttl('MEMORY_LOCAL_MAX_BYTES', default=64 * 1024 * 1024)
        size = sum(row.get('size', len(row['value'].encode('utf-8')))
                   for row in self._LOCAL_STORE.values())
        while self._LOCAL_STORE and (len(self._LOCAL_STORE) > max_keys or size > max_bytes):
            key = next(iter(self._LOCAL_STORE))
            row = self._LOCAL_STORE.pop(key)
            size -= row.get('size', len(row['value'].encode('utf-8')))
        live = self._LOCAL_STORE.keys()
        for index, members in list(self._LOCAL_INDEX.items()):
            members.intersection_update(live)
            if not members:
                self._LOCAL_INDEX.pop(index, None)

    def _local_get(self, key: str) -> Optional[str]:
        with self._LOCAL_LOCK:
            self._prune_local()
            row = self._LOCAL_STORE.get(key)
            if not row:
                return None
            exp = row.get("exp")
            if exp is not None and float(exp) <= time.time():
                self._LOCAL_STORE.pop(key, None)
                return None
            return row.get("value")

    def _local_setex(self, key: str, ttl: int, value: str, index_key: str | None = None) -> None:
        with self._LOCAL_LOCK:
            # Reinsert updates at the end so eviction retains recent writes.
            self._LOCAL_STORE.pop(key, None)
            self._LOCAL_STORE[key] = {
                "value": value,
                "exp": time.time() + max(1, int(ttl)),
                "size": len(value.encode('utf-8')),
            }
            if index_key:
                self._LOCAL_INDEX.setdefault(index_key, set()).add(key)
            self._prune_local()

    def _set_json(self, scope: MemoryScope, family: str, value: Any, ttl: int) -> None:
        key = scope.key(family)
        # Cache transport metadata is separate from the caller's facts. Accepted
        # case revisions remain database-owned; this orders cache copies only.
        with self._LOCAL_LOCK:
            Memory._LAST_WRITE_NS=max(time.time_ns(),Memory._LAST_WRITE_NS+1)
            written_at=Memory._LAST_WRITE_NS
        payload = json.dumps({'_memory_storage_version':1,'written_at_ns':written_at,'value':value})
        try:
            if self.redis is None:
                raise RuntimeError("redis_unavailable")
            if callable(getattr(self.redis, 'eval', None)):
                self.redis.eval(_WRITE_INDEXED, 2, scope.subject_index_key, key,
                                max(ttl, self.kv_ttl, 90 * 86400), max(1, int(ttl)), payload)
            else:
                self._register_key(scope, key, ttl)
                self.redis.setex(key, max(1, int(ttl)), payload)
        except Exception:
            self._local_setex(key, ttl, payload, scope.subject_index_key)
        else:
            self._local_setex(key, ttl, payload, scope.subject_index_key)

    def _get_json(self, scope: MemoryScope, family: str, default: Any) -> Any:
        key = scope.key(family)
        raw = None
        try:
            if self.redis is not None:
                raw = self.redis.get(key)
        except Exception:
            # This worker cannot know whether another worker erased the scope.
            # Durable accepted case facts are restored separately from SQL.
            return default
        if self.redis is not None and raw is None:
            # An authoritative shared miss must not resurrect a local copy.
            # Local-only deployments (redis=None) retain their bounded fallback.
            with self._LOCAL_LOCK:
                self._LOCAL_STORE.pop(key,None)
                self._prune_local()
            return default
        candidates=[]
        for value in (raw,self._local_get(key)):
            try:
                decoded=json.loads(value) if value else None
                if decoded is None:continue
                if (isinstance(decoded,dict) and decoded.get('_memory_storage_version')==1
                        and type(decoded.get('written_at_ns')) is int and 'value' in decoded):
                    candidates.append((decoded['written_at_ns'],decoded['value']))
                else:
                    candidates.append((0,decoded))  # compatible legacy cache
            except (TypeError,ValueError,json.JSONDecodeError):
                continue
        return max(candidates,key=lambda item:item[0])[1] if candidates else default

    def get_context(self, uid: str, **scope_args: Any) -> Dict[str, Any]:
        scope = self.scope(uid, **scope_args)
        return {
            "summary": self._get_json(scope, "summary", None),
            "kv": self._get_json(scope, "kv_state", None),
            "recent_retrieval": self._get_json(scope, "recent_retrieval", None),
            "structured_state": self._get_json(scope, "structured_state", None),
            "product_memory_bank": self._get_json(scope, "product_memory_bank", None),
        }

    def touch_session(self, uid: str, ttl_seconds: int | None = None, **scope_args: Any) -> None:
        ttl = self.kv_ttl if ttl_seconds is None else max(1, int(ttl_seconds))
        scope = self.scope(uid, **scope_args)
        for family in _FAMILIES:
            key = scope.key(family)
            try:
                if self.redis is not None:
                    # Extending a value's lifetime must also extend its erasure
                    # index, including sessions first written many days ago.
                    self._register_key(scope, key, ttl)
                    self.redis.expire(key, ttl)
            except Exception:
                continue
        # Deliberately do not refresh local fallback TTLs on read/touch: expiry
        # remains a bounded retention promise, not a sliding indefinite history.

    def clear_session(self, uid: str, **scope_args: Any) -> None:
        scope = self.scope(uid, **scope_args)
        keys = [scope.key(family) for family in _FAMILIES]
        self._erase_keys(scope, keys)

    def _tombstone_keys(self, scope: MemoryScope, keys) -> None:
        # Suppress stale backend copies during a failed delete. These local
        # tombstones are continuity protection, not proof of durable erasure.
        with self._LOCAL_LOCK:
            Memory._LAST_WRITE_NS=max(time.time_ns(),Memory._LAST_WRITE_NS+1)
            payload=json.dumps({'_memory_storage_version':1,'written_at_ns':Memory._LAST_WRITE_NS,'value':None})
            for key in keys:
                self._local_setex(key,max(self.kv_ttl,90*86400),payload,scope.subject_index_key)

    def _erase_keys(self, scope: MemoryScope, keys: list[str]) -> None:
        self._tombstone_keys(scope, keys)
        try:
            if self.redis is not None:
                if callable(getattr(self.redis, 'eval', None)):
                    self.redis.eval(_ERASE_KEYS, 1 + len(keys), scope.subject_index_key, *keys)
                else:
                    self.redis.delete(*keys)
                    self.redis.srem(scope.subject_index_key, *keys)
        except Exception as exc:
            # Keep the index for a retry; callers must not report completion.
            raise RuntimeError('memory_erasure_incomplete') from exc
        with self._LOCAL_LOCK:
            for key in keys:
                self._LOCAL_STORE.pop(key, None)
            indexed = self._LOCAL_INDEX.get(scope.subject_index_key)
            if indexed is not None:
                indexed.difference_update(keys)
                if not indexed:
                    self._LOCAL_INDEX.pop(scope.subject_index_key, None)

    def erase_subject(
        self,
        subject_id: str,
        *,
        tenant_id: str | None = None,
    ) -> Dict[str, Any]:
        """Erase all indexed conversation epochs for one tenant-bound subject."""
        scope = self.scope(
            subject_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_epoch="erasure-index",
        )
        index_key = scope.subject_index_key
        if self.redis is not None and callable(getattr(self.redis, 'eval', None)):
            with self._LOCAL_LOCK:
                self._tombstone_keys(scope, tuple(self._LOCAL_INDEX.get(index_key, ())))
            try:
                # Snapshot and deletion share one Redis serialization point.
                # A concurrent write is either erased or registered afterwards.
                raw_keys = self.redis.eval(_ERASE_SUBJECT, 1, index_key) or []
            except Exception as exc:
                raise RuntimeError('memory_erasure_incomplete') from exc
            with self._LOCAL_LOCK:
                keys = set(self._LOCAL_INDEX.pop(index_key, set()))
                keys.update(item.decode() if isinstance(item, bytes) else str(item) for item in raw_keys)
                for key in keys:
                    self._LOCAL_STORE.pop(key, None)
            return {'tenant_id': scope.tenant_id, 'subject_id': subject_id,
                    'erased_keys': len(keys), 'contract_version': MEMORY_CONTRACT_VERSION}
        keys: set[str] = set()
        index_failed = False
        try:
            if self.redis is not None:
                raw_keys = self.redis.smembers(index_key) or set()
                keys.update(
                    item.decode("utf-8") if isinstance(item, bytes) else str(item)
                    for item in raw_keys
                )
        except Exception:
            index_failed = True
        with self._LOCAL_LOCK:
            keys.update(self._LOCAL_INDEX.get(index_key, set()))
        if keys:
            self._erase_keys(scope, sorted(keys))
        if index_failed:
            raise RuntimeError('memory_erasure_incomplete:index_unavailable')
        try:
            if self.redis is not None:self.redis.delete(index_key)
        except Exception as exc:
            raise RuntimeError('memory_erasure_incomplete') from exc
        with self._LOCAL_LOCK:
            for key in keys:
                self._LOCAL_STORE.pop(key, None)
            self._LOCAL_INDEX.pop(index_key, None)
        return {
            "tenant_id": scope.tenant_id,
            "subject_id": subject_id,
            "erased_keys": len(keys),
            "contract_version": MEMORY_CONTRACT_VERSION,
        }

    def set_pending_clarification(
        self,
        uid: str,
        pending: Dict[str, Any],
        *,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        session_epoch: str | None = None,
        ttl_seconds: int = 900,
    ) -> None:
        ttl = max(30, min(int(ttl_seconds), 3600))
        scope = self.scope(
            uid,
            tenant_id=tenant_id,
            subject_id=subject_id,
            session_epoch=session_epoch,
        )
        self._set_json(scope, "pending_clarification", pending if isinstance(pending, dict) else {}, ttl)

    def get_pending_clarification(self, uid: str, **scope_args: Any) -> Dict[str, Any]:
        value = self._get_json(self.scope(uid, **scope_args), "pending_clarification", {})
        return value if isinstance(value, dict) else {}

    def clear_pending_clarification(self, uid: str, **scope_args: Any) -> None:
        scope = self.scope(uid, **scope_args)
        key = scope.key("pending_clarification")
        self._erase_keys(scope, [key])

    def set_summary(self, uid: str, summary: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        self._set_json(self.scope(uid, **scope_args), "summary", summary, ttl_seconds or self.summary_ttl)

    def set_kv(self, uid: str, kv: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        self._set_json(self.scope(uid, **scope_args), "kv_state", kv, ttl_seconds or self.kv_ttl)

    def get_kv(self, uid: str, **scope_args: Any) -> Dict[str, Any]:
        value = self._get_json(self.scope(uid, **scope_args), "kv_state", {})
        return value if isinstance(value, dict) else {}

    def set_recent_retrieval(self, uid: str, facts: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        self._set_json(self.scope(uid, **scope_args), "recent_retrieval", facts, ttl_seconds or self.retrieval_ttl)

    def set_structured_state(self, uid: str, state: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        self._set_json(self.scope(uid, **scope_args), "structured_state", state, ttl_seconds or self.kv_ttl)

    def get_structured_state(self, uid: str, **scope_args: Any) -> Dict[str, Any]:
        value = self._get_json(self.scope(uid, **scope_args), "structured_state", {})
        return value if isinstance(value, dict) else {}

    def set_product_memory_bank(self, uid: str, bank: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        self._set_json(self.scope(uid, **scope_args), "product_memory_bank", bank, ttl_seconds or self.kv_ttl)

    def get_product_memory_bank(self, uid: str, **scope_args: Any) -> Dict[str, Any]:
        value = self._get_json(self.scope(uid, **scope_args), "product_memory_bank", {})
        return value if isinstance(value, dict) else {}

    def append_agent_step(self, uid: str, step: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        scope = self.scope(uid, **scope_args)
        data = self._get_json(scope, "agent_steps", [])
        if not isinstance(data, list):
            data = []
        data.append(step)
        self._set_json(scope, "agent_steps", data, ttl_seconds or self.kv_ttl)

    def get_agent_steps(self, uid: str, **scope_args: Any) -> list:
        value = self._get_json(self.scope(uid, **scope_args), "agent_steps", [])
        return value if isinstance(value, list) else []

    def append_observation(self, uid: str, observation: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        scope = self.scope(uid, **scope_args)
        log = self._get_json(scope, "observation_log", [])
        if not isinstance(log, list):
            log = []
        item = dict(observation or {})
        item["ts"] = item.get("ts") or time.time()
        log.append(item)
        self._set_json(scope, "observation_log", log[-500:], ttl_seconds or self.kv_ttl)

    def get_observation_log(self, uid: str, **scope_args: Any) -> list:
        value = self._get_json(self.scope(uid, **scope_args), "observation_log", [])
        return value if isinstance(value, list) else []

    def set_observation_summary(self, uid: str, summary: Dict[str, Any], ttl_seconds: int | None = None, **scope_args: Any) -> None:
        self._set_json(self.scope(uid, **scope_args), "observation_summary", summary, ttl_seconds or self.kv_ttl)

    def get_observation_summary(self, uid: str, **scope_args: Any) -> Dict[str, Any]:
        value = self._get_json(self.scope(uid, **scope_args), "observation_summary", {})
        return value if isinstance(value, dict) else {}
