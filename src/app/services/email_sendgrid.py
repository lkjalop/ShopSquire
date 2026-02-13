from __future__ import annotations

import os
from typing import Dict
import httpx


class SendGridClient:
    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY")
        self.base_url = "https://api.sendgrid.com/v3"

    def send_email(self, to_email: str, subject: str, content_text: str, from_email: str | None = None) -> Dict[str, any]:
        if not self.api_key:
            return {"ok": False, "error": "missing_api_key"}
        from_email = from_email or os.getenv("SENDGRID_FROM_EMAIL") or "noreply@shopsquire.local"
        payload = {
            "personalizations": [{"to": [{"email": to_email}], "subject": subject}],
            "from": {"email": from_email},
            "content": [{"type": "text/plain", "value": content_text}],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(f"{self.base_url}/mail/send", json=payload, headers=headers)
                if r.status_code >= 300:
                    return {"ok": False, "error": f"sendgrid_error:{r.status_code}", "text": r.text}
                return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}