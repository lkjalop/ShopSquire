import json
import os
import time
from threading import RLock
from typing import Any, Dict, Optional

from redis import Redis


SUMMARY_KEY = "session:{uid}:summary"
KV_KEY = "session:{uid}:kv_state"
RETRIEVAL_KEY = "session:{uid}:recent_retrieval"
AGENT_STEPS_KEY = "session:{uid}:agent_steps"


class Memory:
    _LOCAL_LOCK = RLock()
    _LOCAL_STORE: Dict[str, Dict[str, Any]] = {}

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        try:
            self.summary_ttl = int(os.getenv("CHAT_ACTIVE_TTL_SECONDS", os.getenv("CHAT_TTL_SECONDS", "86400")))
        except Exception:
            self.summary_ttl = 86400
        try:
            self.kv_ttl = int(os.getenv("CHAT_ACTIVE_TTL_SECONDS", os.getenv("CHAT_TTL_SECONDS", "86400")))
        except Exception:
            self.kv_ttl = 86400
        try:
            self.retrieval_ttl = int(os.getenv("RAG_CACHE_TTL_SECONDS", "600"))
        except Exception:
            self.retrieval_ttl = 600

    def _local_get(self, key: str) -> Optional[str]:
        try:
            with self._LOCAL_LOCK:
                row = self._LOCAL_STORE.get(key)
                if not row:
                    return None
                exp = row.get("exp")
                if exp is not None and float(exp) < time.time():
                    self._LOCAL_STORE.pop(key, None)
                    return None
                return row.get("value")
        except Exception:
            return None

    def _local_setex(self, key: str, ttl: int, value: str) -> None:
        try:
            exp = time.time() + max(1, int(ttl))
            with self._LOCAL_LOCK:
                self._LOCAL_STORE[key] = {"value": value, "exp": exp}
        except Exception:
            pass

    def get_context(self, uid: str) -> Dict[str, Any]:
        summary = kv = retrieval = None
        try:
            summary = self.redis.get(SUMMARY_KEY.format(uid=uid))
            kv = self.redis.get(KV_KEY.format(uid=uid))
            retrieval = self.redis.get(RETRIEVAL_KEY.format(uid=uid))
        except Exception:
            pass
        if not summary:
            summary = self._local_get(SUMMARY_KEY.format(uid=uid))
        if not kv:
            kv = self._local_get(KV_KEY.format(uid=uid))
        if not retrieval:
            retrieval = self._local_get(RETRIEVAL_KEY.format(uid=uid))
        return {
            "summary": json.loads(summary) if summary else None,
            "kv": json.loads(kv) if kv else None,
            "recent_retrieval": json.loads(retrieval) if retrieval else None,
        }

    def touch_session(self, uid: str, ttl_seconds: int | None = None) -> None:
        ttl = self.kv_ttl if ttl_seconds is None else max(1, int(ttl_seconds))
        keys = [
            SUMMARY_KEY.format(uid=uid),
            KV_KEY.format(uid=uid),
            RETRIEVAL_KEY.format(uid=uid),
            AGENT_STEPS_KEY.format(uid=uid),
        ]
        try:
            for key in keys:
                try:
                    self.redis.expire(key, ttl)
                except Exception:
                    continue
        except Exception:
            pass

    def set_summary(self, uid: str, summary: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            ttl = self.summary_ttl if ttl_seconds is None else ttl_seconds
            payload = json.dumps(summary)
            self.redis.setex(SUMMARY_KEY.format(uid=uid), ttl, payload)
        except Exception:
            payload = json.dumps(summary)
            ttl = self.summary_ttl if ttl_seconds is None else ttl_seconds
            self._local_setex(SUMMARY_KEY.format(uid=uid), ttl, payload)
        else:
            self._local_setex(SUMMARY_KEY.format(uid=uid), ttl, payload)

    def set_kv(self, uid: str, kv: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            ttl = self.kv_ttl if ttl_seconds is None else ttl_seconds
            payload = json.dumps(kv)
            self.redis.setex(KV_KEY.format(uid=uid), ttl, payload)
        except Exception:
            payload = json.dumps(kv)
            ttl = self.kv_ttl if ttl_seconds is None else ttl_seconds
            self._local_setex(KV_KEY.format(uid=uid), ttl, payload)
        else:
            self._local_setex(KV_KEY.format(uid=uid), ttl, payload)

    def get_kv(self, uid: str) -> Dict[str, Any]:
        try:
            raw = self.redis.get(KV_KEY.format(uid=uid))
            if raw:
                try:
                    self.redis.expire(KV_KEY.format(uid=uid), self.kv_ttl)
                except Exception:
                    pass
                return json.loads(raw)
        except Exception:
            pass
        raw = self._local_get(KV_KEY.format(uid=uid))
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def set_recent_retrieval(self, uid: str, facts: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            ttl = self.retrieval_ttl if ttl_seconds is None else ttl_seconds
            payload = json.dumps(facts)
            self.redis.setex(RETRIEVAL_KEY.format(uid=uid), ttl, payload)
        except Exception:
            payload = json.dumps(facts)
            ttl = self.retrieval_ttl if ttl_seconds is None else ttl_seconds
            self._local_setex(RETRIEVAL_KEY.format(uid=uid), ttl, payload)
        else:
            self._local_setex(RETRIEVAL_KEY.format(uid=uid), ttl, payload)

    def append_agent_step(self, uid: str, step: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            # read existing list
            key = AGENT_STEPS_KEY.format(uid=uid)
            raw = self.redis.get(key)
            data = json.loads(raw) if raw else []
            data.append(step)
            ttl = self.kv_ttl if ttl_seconds is None else ttl_seconds
            payload = json.dumps(data)
            self.redis.setex(key, ttl, payload)
        except Exception:
            try:
                key = AGENT_STEPS_KEY.format(uid=uid)
                raw = self._local_get(key)
                data = json.loads(raw) if raw else []
                data.append(step)
                ttl = self.kv_ttl if ttl_seconds is None else ttl_seconds
                self._local_setex(key, ttl, json.dumps(data))
            except Exception:
                pass
        else:
            self._local_setex(key, ttl, payload)

    def get_agent_steps(self, uid: str) -> Optional[list]:
        try:
            key = AGENT_STEPS_KEY.format(uid=uid)
            raw = self.redis.get(key)
            if raw:
                return json.loads(raw)
            raw_local = self._local_get(key)
            return json.loads(raw_local) if raw_local else []
        except Exception:
            try:
                key = AGENT_STEPS_KEY.format(uid=uid)
                raw_local = self._local_get(key)
                return json.loads(raw_local) if raw_local else []
            except Exception:
                return []
