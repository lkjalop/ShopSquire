import json
import time
import requests


def _read_sse_events(url: str, headers: dict, timeout: float = 12.0):
    events = []
    deadline = time.time() + timeout
    # Use a longer read timeout to allow the server to poll and emit events
    with requests.get(url, headers=headers, stream=True, timeout=(3.0, timeout)) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if time.time() > deadline:
                break
            if not line:
                continue
            if line.startswith(b"data:"):
                payload = line.replace(b"data:", b"", 1).strip()
                if not payload:
                    continue
                try:
                    data = json.loads(payload.decode("utf-8"))
                except Exception:
                    continue
                events.append(data)
                if len(events) >= 1:
                    break
    return events


def test_trace_id_and_sse_events(test_server, page):
    base = test_server["base_url"]
    headers = {"x-api-key": "local-merchant-key"}
    resp = page.request.get(
        base + "/api/v1/recommend/suggest?uid=pw-user&query=show%20laptops%20under%202000",
        headers=headers,
    )
    assert resp.status == 200
    data = resp.json()
    trace_id = data.get("trace_id") or data.get("decision_id")
    assert trace_id

    sse_events = _read_sse_events(
        base + f"/api/v1/decisions/{trace_id}/events/stream",
        headers=headers,
    )
    assert sse_events, "Expected SSE events for trace"
    flat = sse_events[0]
    assert isinstance(flat, list) and len(flat) > 0


def test_policy_gate_logged_and_visible(test_server, page):
    base = test_server["base_url"]
    headers = {"x-api-key": "local-merchant-key"}
    trace_id = f"trace-{int(time.time())}"
    payload = {
        "tool": "refund.issue",
        "params": {"card_number": "4111111111111111"},
        "uid": "pw-user",
        "trace_id": trace_id,
    }
    resp = requests.post(base + "/api/v1/tools/run", headers=headers, json=payload, timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("blocked", "review_required")

    events = _read_sse_events(
        base + f"/api/v1/decisions/{trace_id}/events/stream",
        headers=headers,
    )
    assert events, "Expected SSE events for policy gate"
    event_list = events[0]
    found = any(ev.get("event_type") == "policy_gate" for ev in event_list if isinstance(ev, dict))
    assert found, "Expected policy_gate event in trace stream"
