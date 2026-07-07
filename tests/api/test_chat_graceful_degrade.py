"""N7 — a failed internal recommend hop must NEVER surface to the buyer as a raw HTTP 502.
Under TestClient the loopback host is unreachable (ConnectError), which is exactly the failure the
buyer would hit on a real hiccup — so this asserts the graceful-degrade contract directly."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_recommend_hop_failure_degrades_to_200_not_502():
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tempfile.mkdtemp()}/degrade.sqlite"
    client = TestClient(create_app())
    r = client.post("/api/v1/chat/query", json={"uid": "degrade-user", "query": "laptop under 1000"},
                    headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 200, f"buyer must never see a 5xx: got {r.status_code}"
    body = r.json()
    assert body.get("degraded") is True
    assert body.get("decision_trace_id")                    # still traceable for the operator
    assert "hiccup" in (body.get("assistant_message") or "").lower()
    assert body.get("products") == []
    # the recoverable prompt gives the buyer a way forward
    goals = {q.get("goal") for q in body.get("next_questions") or []}
    assert "retry_search" in goals
