import os
import time
import hmac
import hashlib
import requests


def sign_payload(secret: str, payload: bytes, ts: int) -> str:
    signed = f"{ts}.".encode("utf-8") + payload
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def main():
    url = os.getenv("TEST_WEBHOOK_URL", "http://localhost:8080/api/v1/admin/connectors/test")
    secret = os.getenv("WEBHOOK_SECRET", "demo-secret")
    ts = int(time.time())
    body = {"event": "demo.test", "message": "hello"}
    import json
    payload = json.dumps(body).encode("utf-8")
    sig = sign_payload(secret, payload, ts)
    headers = {
        "x-webhook-timestamp": str(ts),
        "x-webhook-signature": f"sha256={sig}",
        "content-type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=body)
    print("status:", resp.status_code)
    print("body:", resp.text)


if __name__ == "__main__":
    main()
import os
import json
import urllib.request

from pathlib import Path


def load_senders():
    senders = []
    env = os.getenv("DECISION_WEBHOOK_URLS")
    if env:
        for u in env.split(","):
            if u.strip():
                senders.append(u.strip())
    try:
        text = Path("config/webhooks.yml").read_text()
        try:
            import yaml

            cfg = yaml.safe_load(text)
        except Exception:
            try:
                cfg = json.loads(text)
            except Exception:
                cfg = {}
        s = cfg.get("webhooks", {}).get("decision_events", []) or []
        for u in s:
            if u and u not in senders:
                senders.append(u)
    except Exception:
        pass
    return senders


def send(payload: dict):
    senders = load_senders()
    if not senders:
        print("No webhook senders configured. Set DECISION_WEBHOOK_URLS or edit config/webhooks.yml")
        return
    data = json.dumps(payload).encode("utf-8")
    for url in senders:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                print(url, r.status, r.read().decode("utf-8", errors="ignore")[:200])
        except Exception as e:
            print(url, "error", e)


if __name__ == "__main__":
    sample = {"event": "decision.test", "decision_id": "test-123", "actor": "tester", "meta": {"reason": "manual-test"}}
    send(sample)
