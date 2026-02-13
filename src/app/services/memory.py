import json
import os
from typing import Any, Dict, Optional

from redis import Redis


SUMMARY_KEY = "session:{uid}:summary"
KV_KEY = "session:{uid}:kv_state"
RETRIEVAL_KEY = "session:{uid}:recent_retrieval"
AGENT_STEPS_KEY = "session:{uid}:agent_steps"


class Memory:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        try:
            self.summary_ttl = int(os.getenv("CHAT_TTL_SECONDS", "7200"))
        except Exception:
            self.summary_ttl = 7200
        try:
            self.kv_ttl = int(os.getenv("CHAT_TTL_SECONDS", "7200"))
        except Exception:
            self.kv_ttl = 7200
        try:
            self.retrieval_ttl = int(os.getenv("RAG_CACHE_TTL_SECONDS", "600"))
        except Exception:
            self.retrieval_ttl = 600

    def get_context(self, uid: str) -> Dict[str, Any]:
        try:
            summary = self.redis.get(SUMMARY_KEY.format(uid=uid))
            kv = self.redis.get(KV_KEY.format(uid=uid))
            retrieval = self.redis.get(RETRIEVAL_KEY.format(uid=uid))
        except Exception:
            summary = kv = retrieval = None
        return {
            "summary": json.loads(summary) if summary else None,
            "kv": json.loads(kv) if kv else None,
            "recent_retrieval": json.loads(retrieval) if retrieval else None,
        }

    def set_summary(self, uid: str, summary: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            ttl = self.summary_ttl if ttl_seconds is None else ttl_seconds
            self.redis.setex(SUMMARY_KEY.format(uid=uid), ttl, json.dumps(summary))
        except Exception:
            pass

    def set_kv(self, uid: str, kv: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            ttl = self.kv_ttl if ttl_seconds is None else ttl_seconds
            self.redis.setex(KV_KEY.format(uid=uid), ttl, json.dumps(kv))
        except Exception:
            pass

    def set_recent_retrieval(self, uid: str, facts: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            ttl = self.retrieval_ttl if ttl_seconds is None else ttl_seconds
            self.redis.setex(RETRIEVAL_KEY.format(uid=uid), ttl, json.dumps(facts))
        except Exception:
            pass

    def append_agent_step(self, uid: str, step: Dict[str, Any], ttl_seconds: int | None = None) -> None:
        try:
            # read existing list
            key = AGENT_STEPS_KEY.format(uid=uid)
            raw = self.redis.get(key)
            data = json.loads(raw) if raw else []
            data.append(step)
            ttl = self.kv_ttl if ttl_seconds is None else ttl_seconds
            self.redis.setex(key, ttl, json.dumps(data))
        except Exception:
            pass

    def get_agent_steps(self, uid: str) -> Optional[list]:
        try:
            key = AGENT_STEPS_KEY.format(uid=uid)
            raw = self.redis.get(key)
            return json.loads(raw) if raw else []
        except Exception:
            return []
