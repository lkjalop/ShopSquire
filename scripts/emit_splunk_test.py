import os
import time
import sys
import json

def main():
    try:
        import requests
    except Exception:
        print("requests library not available in venv; cannot send HEC event")
        sys.exit(2)

    url = os.getenv("SPLUNK_HEC_URL")
    token = os.getenv("SPLUNK_HEC_TOKEN")
    if not url or not token:
        print("SPLUNK envs not set; skipping")
        return

    body = {
        "time": int(time.time()),
        "sourcetype": "shopsquire:security",
        "source": "manual-test",
        "event": {"message": "test-event", "component": "telemetry_emit", "severity": "info"},
    }
    headers = {"Authorization": f"Splunk {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        try:
            txt = resp.text
        except Exception:
            txt = str(resp.content)
        print("Splunk HEC response status:", resp.status_code)
        print(txt)
    except Exception as e:
        print("HEC send failed:", str(e))
        sys.exit(1)

if __name__ == '__main__':
    main()
#!/usr/bin/env python
import os
import json
import time
import sys
import requests


def main():
    hec_url = os.getenv("SPLUNK_HEC_URL")
    hec_token = os.getenv("SPLUNK_HEC_TOKEN")
    if not hec_url or not hec_token:
        print("SPLUNK_HEC_URL/SPLUNK_HEC_TOKEN not set; skipping")
        sys.exit(0)
    event = {
        "type": "telemetry_emit",
        "component": "hec_test",
        "message": "test-event",
        "severity": "info",
        "ts": int(time.time()),
    }
    body = {"time": int(time.time()), "sourcetype": "shopsquire:security", "event": {"severity": "info", "payload": event}}
    headers = {"Authorization": f"Splunk {hec_token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(hec_url, headers=headers, data=json.dumps(body), timeout=5)
        print(f"Splunk HEC response: {getattr(resp, 'text', '')}")
    except Exception as exc:
        print(f"HEC send failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
