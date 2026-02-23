from __future__ import annotations

import json
import os
from typing import Any, Dict

import redis


def _redis_client():
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    return redis.from_url(url, decode_responses=True)


def set_job(job_id: str, payload: Dict[str, Any]) -> None:
    r = _redis_client()
    r.set(f"sc_swarm:{job_id}", json.dumps(payload))


def get_job(job_id: str) -> Dict[str, Any] | None:
    r = _redis_client()
    v = r.get(f"sc_swarm:{job_id}")
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def delete_job(job_id: str) -> None:
    r = _redis_client()
    r.delete(f"sc_swarm:{job_id}")
