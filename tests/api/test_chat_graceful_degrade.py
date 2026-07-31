"""N7 — failed recommendation dispatch must never surface as a buyer-facing 5xx.

Chat now calls the V2 compatibility boundary in process. Inject the failure at that
owned seam instead of relying on the obsolete TestClient-loopback failure.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_recommend_hop_failure_degrades_to_200_not_502(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'degrade.sqlite'}",
    )

    calls = []

    async def fail_v2_dispatch(request, params, *, redis, db, role):
        calls.append({
            "query": params.get("query"),
            "uid": params.get("uid"),
            "role": role,
        })
        raise ConnectionError("injected V2 compatibility boundary failure")

    monkeypatch.setattr(
        "src.app.routers.chat._call_recommend_in_process",
        fail_v2_dispatch,
    )
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/chat/query",
        json={"uid": "degrade-user", "query": "laptop under 1000"},
        headers={"x-api-key": "local-merchant-key"},
    )

    assert calls == [{
        "query": "laptop under 1000",
        "uid": "degrade-user",
        "role": "merchant",
    }]
    assert response.status_code == 200, (
        f"buyer must never see a 5xx: got {response.status_code}"
    )
    body = response.json()
    assert body.get("degraded") is True
    assert body.get("degraded_reason") == "recommend_error"
    assert body.get("blocked") is False
    assert body.get("security_route") == "allow"
    assert body.get("decision_trace_id")  # still traceable for the operator
    assert "hiccup" in (body.get("assistant_message") or "").lower()
    assert body.get("products") == []
    goals = {q.get("goal") for q in body.get("next_questions") or []}
    assert "retry_search" in goals
