from __future__ import annotations

import os
from typing import Any, Dict, Optional


class JanuSecClient:
    """Minimal client to forward triage context for correlation.

    Env:
      JANUSEC_API_URL, JANUSEC_API_KEY
    """

    def __init__(self) -> None:
        self.base = os.getenv("JANUSEC_API_URL")
        self.key = os.getenv("JANUSEC_API_KEY")

    def enabled(self) -> bool:
        return bool(self.base and self.key)

    def send_triage(self, payload: Dict[str, Any]) -> bool:
        if not self.enabled():
            return False
        try:
            import httpx

            headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
            with httpx.Client(timeout=3.0) as client:
                r = client.post(f"{self.base.rstrip('/')}/api/v1/triage", json=payload, headers=headers)
                return r.status_code // 100 == 2
        except Exception:
            return False
