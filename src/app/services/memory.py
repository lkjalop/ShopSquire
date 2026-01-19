import json
from typing import Any, Dict, Optional

from redis import Redis


SUMMARY_KEY = "session:{uid}:summary"
KV_KEY = "session:{uid}:kv_state"
RETRIEVAL_KEY = "session:{uid}:recent_retrieval"


class Memory:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

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

    def set_summary(self, uid: str, summary: Dict[str, Any], ttl_seconds: int = 10800) -> None:
        try:
            self.redis.setex(SUMMARY_KEY.format(uid=uid), ttl_seconds, json.dumps(summary))
        except Exception:
            pass

    def set_kv(self, uid: str, kv: Dict[str, Any], ttl_seconds: int = 10800) -> None:
        try:
            self.redis.setex(KV_KEY.format(uid=uid), ttl_seconds, json.dumps(kv))
        except Exception:
            pass

    def set_recent_retrieval(self, uid: str, facts: Dict[str, Any], ttl_seconds: int = 600) -> None:
        try:
            self.redis.setex(RETRIEVAL_KEY.format(uid=uid), ttl_seconds, json.dumps(facts))
        except Exception:
            pass
