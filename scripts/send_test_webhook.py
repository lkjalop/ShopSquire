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
