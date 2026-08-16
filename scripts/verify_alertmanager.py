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
        resp = requests.post(f"{alertmanager_url}/api/v2/alerts", json=payload, timeout=5)
        if resp.status_code >= 300:
            print(f"AlertManager responded with {resp.status_code}: {resp.text}")
            return 1
        # Allow a short delay for routing and then prove the receiver retained it.
        time.sleep(1)
        observed = requests.get(f"{alertmanager_url}/api/v2/alerts", timeout=5)
        observed.raise_for_status()
        names = {
            item.get("labels", {}).get("alertname")
            for item in observed.json()
            if isinstance(item, dict)
        }
        if "ShopsquireAlertmanagerTest" not in names:
            print("AlertManager accepted the request but the test alert was not observable")
            return 1
        print(f"AlertManager accepted and retained test alert at {alertmanager_url}")
        return 0
    except Exception as exc:
        print(f"Failed to send test alert: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
