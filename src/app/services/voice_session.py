from __future__ import annotations

import json
import time
from typing import Dict, Optional


class VoiceSessionManager:
    """Manage voice session state (transcript, context) backed by Redis when available."""

    def __init__(self, redis_client=None, ttl_seconds: int = 900):
        self.redis = redis_client
        self.ttl = int(ttl_seconds)

    def _key(self, session_id: str) -> str:
        return f"voice_session:{session_id}"

    def get(self, session_id: str) -> Dict:
        if not self.redis:
            return {"transcript": "", "updated_at": int(time.time())}
        raw = self.redis.get(self._key(session_id))
        if not raw:
            return {"transcript": "", "updated_at": int(time.time())}
        try:
            return json.loads(raw)
        except Exception:
            return {"transcript": "", "updated_at": int(time.time())}

    def append_transcript(self, session_id: str, text: str) -> Dict:
        state = self.get(session_id)
        prev = state.get("transcript") or ""
        new = f"{prev} {text}".strip()
        state["transcript"] = new
        state["updated_at"] = int(time.time())
        if self.redis:
            try:
                self.redis.setex(self._key(session_id), self.ttl, json.dumps(state))
            except Exception:
                pass
        return state
