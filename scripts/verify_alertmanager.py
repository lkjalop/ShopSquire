import json
import os
import time
from datetime import datetime, timezone

import requests


def main() -> int:
    alertmanager_url = os.getenv("ALERTMANAGER_URL", "http://localhost:9093").rstrip("/")
    now = datetime.now(timezone.utc).isoformat()
    payload = [
        {
            "labels": {
                "alertname": "ShopsquireAlertmanagerTest",
                "severity": "warning",
                "service": "shopsquire-api",
            },
            "annotations": {
                "summary": f"AlertManager verification fired at {now}",
                "description": "Synthetic alert to validate routing and receivers.",
            },
            "startsAt": now,
        }
    ]
    try:
        resp = requests.post(f"{alertmanager_url}/api/v1/alerts", json=payload, timeout=5)
        if resp.status_code >= 300:
            print(f"AlertManager responded with {resp.status_code}: {resp.text}")
            return 1
        # Allow a short delay for routing and UI visibility.
        time.sleep(1)
        print(f"AlertManager accepted test alert at {alertmanager_url}")
        return 0
    except Exception as exc:
        print(f"Failed to send test alert: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
